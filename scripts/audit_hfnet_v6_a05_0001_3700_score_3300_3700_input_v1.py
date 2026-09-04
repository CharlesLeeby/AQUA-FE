#!/usr/bin/env python3
"""Independently audit the frozen A05 HFNet input and write one receipt.

The auditor imports no materializer.  It hashes and decodes every prepared
PNG, streams the pinned canonical archive through EOF, proves source frames
1..3700 were copied byte-for-byte, independently rebuilds the camera and
shifted-IMU files from the canonical CSV members, checks every camera has an
IMU predecessor and successor, closes the output tree, and validates the
materialization manifest.  It never starts HFNet, ROS, VINS, or an evaluator.

The sole permitted write is an additive, O_EXCL audit receipt outside the
input tree.  Existing inputs and receipts are never overwritten.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import struct
import sys
import tarfile
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple
import zlib


ROOT = Path(__file__).resolve().parents[1]
INPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_old_frozen_positive_windows_v1/"
    "a05_0001_3700_score_3300_3700_warmstart"
)
SOURCE_ARCHIVE = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences/archaeo_sequence_5_raw_data.tar.gz"
)
SELECTOR = (
    ROOT
    / "papers/hfnet_v6_a05_0001_3700_score_3300_3700_"
    "selector_freeze_v1.json"
)
CONFIG = (
    ROOT
    / "configs/published_baselines/"
    "hfnet_slam_aqualoc_a06_0000_2460_exact_window_v1.yaml"
)
DEFAULT_REPORT = Path(str(INPUT_ROOT) + ".independent_audit_v1.json")

SCHEMA_VERSION = (
    "aqua-fe-hfnet-v6-a05-0001-3700-score-3300-3700-"
    "independent-input-audit-v1"
)
MATERIALIZATION_SCHEMA = (
    "aqua-fe-hfnet-v6-a05-0001-3700-score-3300-3700-"
    "input-materialization-v1"
)
SELECTOR_SCHEMA = (
    "aqua-fe-hfnet-v6-a05-0001-3700-score-3300-3700-"
    "selector-freeze-v1"
)

SOURCE_SIZE = 866_604_152
SOURCE_SHA256 = (
    "49fc60a27a2da30ab3e3a883badafd43b579406a1fad10de632e175ad18be52c"
)
SOURCE_GZIP_CRC32 = "94fd6d95"
SOURCE_GZIP_ISIZE = 879_257_600
SELECTOR_SIZE = 4_558
SELECTOR_SHA256 = (
    "5533e33720239188c27191ff9eb6bb1aab523b6092240343452f99131512e7f7"
)
CONFIG_SIZE = 2_037
CONFIG_SHA256 = (
    "37ec8f0f274818b3a8f952a535d9be87dae0f8d0436ce05503381791ace69db6"
)

IMAGE_CSV_MEMBER = "raw_data/img_sequence_5.csv"
IMAGE_CSV_SIZE = 143_414
IMAGE_CSV_SHA256 = (
    "a63ad0fd91cb268038e4dc9a6e478166d7b0c2f9bace636926e59ac1ed8a8980"
)
IMAGE_CSV_CRC32 = "79fa2f29"
IMU_CSV_MEMBER = "raw_data/imu_sequence_5.csv"
IMU_CSV_SIZE = 4_451_826
IMU_CSV_SHA256 = (
    "ff069b4df9d6fa4953c0f86fa85d32e767441d21904c19c20c2dc2bc4e8c2c01"
)
IMU_CSV_CRC32 = "ee1052d8"
IMAGE_PREFIX = "raw_data/images_sequence_5/"

SOURCE_CAMERA_COUNT = 3_983
SOURCE_CAMERA_FIRST = 1
SOURCE_CAMERA_LAST = 3_700
CAMERA_COUNT = 3_700
CAMERA_FIRST_NS = 1_455_214_178_615_853_120
CAMERA_LAST_NS = 1_455_214_363_536_846_272
SCORE_SOURCE = [3_300, 3_700]
SCORE_RELATIVE = [3_299, 3_699]

SOURCE_IMU_COUNT = 39_796
IMU_FIRST_INDEX = 7
IMU_LAST_INDEX = 36_964
IMU_COUNT = 36_958
IMU_SHIFT_NS = 53_694_112
IMU_FIRST_RAW_NS = 1_455_214_178_561_121_600
IMU_LAST_RAW_NS = 1_455_214_363_483_388_320
IMU_ENDPOINTS = (
    1_455_214_178_614_815_712,
    1_455_214_178_620_066_592,
    1_455_214_363_534_102_112,
    1_455_214_363_537_082_432,
)

IMAGE_CSV_HEADER = "#timestamp [ns], frame_id"
CAMERA_OUTPUT_CSV_HEADER = "#timestamp [ns],filename"
IMU_CSV_HEADER = (
    "#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],"
    "w_RS_S_z [rad s^-1],a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],"
    "a_RS_S_z [m s^-2]"
)

EXPECTED_GENERATED = {
    "cam0_times.txt": (
        74_000,
        "93c64e829cc26ff56c9dbff1b5b194c47bebf0a8b35b737bfe79dbb9d64f2468",
        "8f0834c5",
    ),
    "mav0/cam0/data.csv": (
        162_825,
        "0c15a52a9b9d5699a06288fb317de16626e68b0c6b56912fd893e5767a99f959",
        "aabb0577",
    ),
    "mav0/imu0/data.csv": (
        4_134_559,
        "0f7e80e1d3137e38bf6ef52a0c4b09282e9c11275583461dbfcfe5fb4454bb21",
        "c7a7a89c",
    ),
}

A06_ADAPTER = ROOT / "scripts/materialize_hfnet_v6_a06_0000_2460_exact_window_v1.py"
A06_ADAPTER_SIZE = 16_321
A06_ADAPTER_SHA256 = (
    "2ac7025c70a7aac48783b0ee37e9586aae43c00927a1183304a88ad05f796264"
)
SEALED_CORE = ROOT / "scripts/materialize_hfnet_v6_phase_f_h03_1800_3600_v1.py"
SEALED_CORE_SIZE = 38_774
SEALED_CORE_SHA256 = (
    "9146602be29e6faee2d13c91e25b01d2bc4081c11bbf419787128822275e584d"
)

EXPECTED_DIRECTORIES = {
    "",
    "mav0",
    "mav0/cam0",
    "mav0/cam0/data",
    "mav0/imu0",
}
CLAIMS = {
    "runner_created": False,
    "start_claim_created": False,
    "hfnet_started": False,
    "vins_started": False,
    "detector_started": False,
    "evaluator_started": False,
    "trajectory_produced": False,
    "accuracy_measured": False,
    "scientific_comparison_produced": False,
}


class AuditError(RuntimeError):
    """A pinned input, derived payload, tree, or manifest invariant failed."""


def canonical_json(value: Mapping[str, Any]) -> bytes:
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


def identity_bytes(relative: str, payload: bytes) -> Dict[str, Any]:
    return {
        "path": relative,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "crc32": f"{zlib.crc32(payload) & 0xffffffff:08x}",
    }


def _open_regular(path: Path, label: str) -> int:
    if path.is_symlink():
        raise AuditError(f"{label}_SYMLINK")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(os.fspath(path), flags)
    except OSError as error:
        raise AuditError(f"{label}_OPEN_FAILED:{type(error).__name__}") from error
    observed = os.fstat(descriptor)
    if not stat.S_ISREG(observed.st_mode):
        os.close(descriptor)
        raise AuditError(f"{label}_NOT_REGULAR")
    return descriptor


def read_regular(path: Path, label: str) -> bytes:
    descriptor = _open_regular(path, label)
    try:
        chunks: List[bytes] = []
        while True:
            block = os.read(descriptor, 4 * 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def identity_file(path: Path, relative: str, label: str) -> Dict[str, Any]:
    descriptor = _open_regular(path, label)
    digest = hashlib.sha256()
    crc = 0
    size = 0
    try:
        while True:
            block = os.read(descriptor, 8 * 1024 * 1024)
            if not block:
                break
            digest.update(block)
            crc = zlib.crc32(block, crc)
            size += len(block)
    finally:
        os.close(descriptor)
    return {
        "path": relative,
        "size_bytes": size,
        "sha256": digest.hexdigest(),
        "crc32": f"{crc & 0xffffffff:08x}",
    }


def require_identity(
    path: Path, size: int, sha256: str, label: str
) -> Dict[str, Any]:
    observed = identity_file(path, str(path.resolve()), label)
    if observed["size_bytes"] != size:
        raise AuditError(f"{label}_SIZE_MISMATCH:{observed['size_bytes']}")
    if observed["sha256"] != sha256:
        raise AuditError(f"{label}_SHA256_MISMATCH:{observed['sha256']}")
    return observed


def require_pin(
    observed: Mapping[str, Any], expected: Tuple[int, str, str], label: str
) -> None:
    actual = (
        observed.get("size_bytes"),
        observed.get("sha256"),
        observed.get("crc32"),
    )
    if actual != expected:
        raise AuditError(f"{label}_IDENTITY_MISMATCH:{actual}")


def aggregate(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    digest = hashlib.sha256()
    crc = 0
    for row in sorted(rows, key=lambda value: str(value["path"])):
        encoded = (
            f"{row['path']}\0{row['size_bytes']}\0{row['sha256']}\0"
            f"{row['crc32']}\n"
        ).encode("utf-8")
        digest.update(encoded)
        crc = zlib.crc32(encoded, crc)
    return {
        "algorithm": "sorted UTF-8 path\\0size\\0sha256\\0crc32\\n",
        "sha256": digest.hexdigest(),
        "crc32": f"{crc & 0xffffffff:08x}",
    }


def _reject_duplicate_keys(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AuditError(f"JSON_DUPLICATE_KEY:{key}")
        result[key] = value
    return result


def load_json_unique(payload: bytes, label: str) -> Dict[str, Any]:
    try:
        value = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AuditError(f"{label}_JSON_INVALID") from error
    if not isinstance(value, dict):
        raise AuditError(f"{label}_JSON_ROOT_NOT_OBJECT")
    return value


def validate_png(payload: bytes) -> Dict[str, Any]:
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AuditError("PNG_SIGNATURE_MISMATCH")
    position = 8
    schema: Optional[Tuple[int, int, int, int, int, int, int]] = None
    idat: List[bytes] = []
    chunk_count = 0
    ended = False
    while position < len(payload):
        if position + 12 > len(payload):
            raise AuditError("PNG_TRUNCATED")
        length = struct.unpack(">I", payload[position : position + 4])[0]
        end = position + 12 + length
        if end > len(payload):
            raise AuditError("PNG_LENGTH_INVALID")
        kind = payload[position + 4 : position + 8]
        data = payload[position + 8 : position + 8 + length]
        expected_crc = struct.unpack(">I", payload[position + 8 + length : end])[0]
        if (zlib.crc32(kind + data) & 0xffffffff) != expected_crc:
            raise AuditError(f"PNG_CHUNK_CRC_MISMATCH:{kind!r}")
        chunk_count += 1
        if kind == b"IHDR":
            if chunk_count != 1 or length != 13:
                raise AuditError("PNG_IHDR_POSITION_OR_SIZE_MISMATCH")
            schema = struct.unpack(">IIBBBBB", data)
        elif kind == b"IDAT":
            idat.append(data)
        elif kind == b"IEND":
            if length != 0:
                raise AuditError("PNG_IEND_SIZE_MISMATCH")
            position = end
            ended = True
            break
        position = end
    if not ended or position != len(payload):
        raise AuditError("PNG_IEND_OR_TRAILING_BYTES_MISMATCH")
    if schema != (968, 608, 8, 0, 0, 0, 0):
        raise AuditError(f"PNG_SCHEMA_MISMATCH:{schema}")
    if not idat:
        raise AuditError("PNG_IDAT_MISSING")
    try:
        decoded = zlib.decompress(b"".join(idat))
    except zlib.error as error:
        raise AuditError("PNG_IDAT_DECODE_FAILED") from error
    if len(decoded) != 608 * 969:
        raise AuditError("PNG_SCANLINE_SIZE_MISMATCH")
    if any(decoded[row * 969] > 4 for row in range(608)):
        raise AuditError("PNG_FILTER_INVALID")
    return {
        "width": 968,
        "height": 608,
        "bit_depth": 8,
        "color_type": 0,
        "chunk_count": chunk_count,
        "chunk_crc_all_valid": True,
        "idat_decompressed": True,
    }


def parse_camera_times(payload: bytes) -> List[int]:
    if not payload.endswith(b"\n"):
        raise AuditError("CAM0_TIMES_FINAL_NEWLINE_MISSING")
    try:
        stamps = [int(line) for line in payload.decode("ascii").splitlines()]
    except (UnicodeDecodeError, ValueError) as error:
        raise AuditError("CAM0_TIMES_INVALID") from error
    if (
        len(stamps) != CAMERA_COUNT
        or stamps[0] != CAMERA_FIRST_NS
        or stamps[-1] != CAMERA_LAST_NS
    ):
        raise AuditError("CAM0_TIMES_COUNT_OR_ENDPOINT_MISMATCH")
    if any(current <= previous for previous, current in zip(stamps, stamps[1:])):
        raise AuditError("CAM0_TIMES_NON_MONOTONIC")
    return stamps


def parse_source_camera(
    payload: bytes,
    source_count: int = SOURCE_CAMERA_COUNT,
    first: int = SOURCE_CAMERA_FIRST,
    last: int = SOURCE_CAMERA_LAST,
) -> Tuple[List[Tuple[int, str]], List[Tuple[int, str]]]:
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise AuditError("SOURCE_IMAGE_CSV_NOT_UTF8") from error
    if not lines or lines[0] != IMAGE_CSV_HEADER:
        raise AuditError("SOURCE_IMAGE_CSV_HEADER_MISMATCH")
    rows: List[Tuple[int, str]] = []
    previous: Optional[int] = None
    for index, line in enumerate(lines[1:]):
        fields = line.split(",")
        if len(fields) != 2:
            raise AuditError(f"SOURCE_IMAGE_CSV_COLUMN_COUNT:{index}")
        try:
            stamp = int(fields[0])
        except ValueError as error:
            raise AuditError(f"SOURCE_IMAGE_CSV_TIMESTAMP_INVALID:{index}") from error
        expected_name = f"frame{index:06d}.png"
        if fields[1] != expected_name:
            raise AuditError(f"SOURCE_IMAGE_CSV_FILENAME_MISMATCH:{index}")
        if previous is not None and stamp <= previous:
            raise AuditError(f"SOURCE_IMAGE_CSV_NON_MONOTONIC:{index}")
        rows.append((stamp, fields[1]))
        previous = stamp
    if len(rows) != source_count:
        raise AuditError(f"SOURCE_IMAGE_CSV_COUNT_MISMATCH:{len(rows)}")
    selected = rows[first : last + 1]
    if len(selected) != last - first + 1:
        raise AuditError("SOURCE_IMAGE_CSV_SELECTION_COUNT_MISMATCH")
    return rows, selected


def parse_source_imu(
    payload: bytes,
    selected_camera: Sequence[Tuple[int, str]],
    source_count: int = SOURCE_IMU_COUNT,
    first_index: int = IMU_FIRST_INDEX,
    last_index: int = IMU_LAST_INDEX,
    shift_ns: int = IMU_SHIFT_NS,
) -> Tuple[List[Tuple[int, Tuple[str, ...]]], List[Tuple[int, Tuple[str, ...]]]]:
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise AuditError("SOURCE_IMU_CSV_NOT_UTF8") from error
    if not lines or lines[0] != IMU_CSV_HEADER:
        raise AuditError("SOURCE_IMU_CSV_HEADER_MISMATCH")
    rows: List[Tuple[int, Tuple[str, ...]]] = []
    previous: Optional[int] = None
    for index, line in enumerate(lines[1:]):
        fields = line.split(",")
        if len(fields) != 7:
            raise AuditError(f"SOURCE_IMU_CSV_COLUMN_COUNT:{index}")
        try:
            stamp = int(fields[0])
            numeric = [float(field) for field in fields[1:]]
        except ValueError as error:
            raise AuditError(f"SOURCE_IMU_CSV_NUMERIC_INVALID:{index}") from error
        if not all(math.isfinite(value) for value in numeric):
            raise AuditError(f"SOURCE_IMU_CSV_NONFINITE:{index}")
        if previous is not None and stamp <= previous:
            raise AuditError(f"SOURCE_IMU_CSV_NON_MONOTONIC:{index}")
        rows.append((stamp, tuple(fields[1:])))
        previous = stamp
    if len(rows) != source_count:
        raise AuditError(f"SOURCE_IMU_CSV_COUNT_MISMATCH:{len(rows)}")
    raw_stamps = [row[0] for row in rows]
    derived_first = bisect.bisect_right(
        raw_stamps, selected_camera[0][0] - shift_ns
    ) - 1
    derived_last = bisect.bisect_left(
        raw_stamps, selected_camera[-1][0] - shift_ns
    )
    if (derived_first, derived_last) != (first_index, last_index):
        raise AuditError(
            f"SOURCE_IMU_SELECTION_INDEX_MISMATCH:{derived_first}:{derived_last}"
        )
    return rows, rows[first_index : last_index + 1]


def camera_times_bytes(selected: Sequence[Tuple[int, str]]) -> bytes:
    return ("\n".join(str(stamp) for stamp, _ in selected) + "\n").encode("ascii")


def camera_csv_bytes(selected: Sequence[Tuple[int, str]]) -> bytes:
    lines = [CAMERA_OUTPUT_CSV_HEADER]
    lines.extend(f"{stamp},{stamp}.png" for stamp, _ in selected)
    return ("\n".join(lines) + "\n").encode("ascii")


def imu_csv_bytes(
    selected: Sequence[Tuple[int, Tuple[str, ...]]], shift_ns: int = IMU_SHIFT_NS
) -> bytes:
    lines = [IMU_CSV_HEADER]
    lines.extend(
        f"{stamp + shift_ns}," + ",".join(measurements)
        for stamp, measurements in selected
    )
    return "\n".join(lines).encode("utf-8")


def validate_imu_brackets(
    imu_payload: bytes, camera_stamps: Sequence[int]
) -> Dict[str, Any]:
    try:
        lines = imu_payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise AuditError("OUTPUT_IMU_NOT_UTF8") from error
    if not lines or lines[0] != IMU_CSV_HEADER:
        raise AuditError("OUTPUT_IMU_HEADER_MISMATCH")
    stamps: List[int] = []
    for index, line in enumerate(lines[1:]):
        fields = line.split(",")
        if len(fields) != 7:
            raise AuditError(f"OUTPUT_IMU_COLUMN_COUNT:{index}")
        try:
            stamps.append(int(fields[0]))
            values = [float(field) for field in fields[1:]]
        except ValueError as error:
            raise AuditError(f"OUTPUT_IMU_NUMERIC_INVALID:{index}") from error
        if not all(math.isfinite(value) for value in values):
            raise AuditError(f"OUTPUT_IMU_NONFINITE:{index}")
    if len(stamps) != IMU_COUNT:
        raise AuditError(f"OUTPUT_IMU_COUNT_MISMATCH:{len(stamps)}")
    if any(current <= previous for previous, current in zip(stamps, stamps[1:])):
        raise AuditError("OUTPUT_IMU_NON_MONOTONIC")
    endpoints = (stamps[0], stamps[1], stamps[-2], stamps[-1])
    if endpoints != IMU_ENDPOINTS:
        raise AuditError(f"OUTPUT_IMU_ENDPOINT_MISMATCH:{endpoints}")
    predecessor_gaps: List[int] = []
    successor_gaps: List[int] = []
    for index, camera_stamp in enumerate(camera_stamps):
        successor = bisect.bisect_right(stamps, camera_stamp)
        if successor == 0 or successor == len(stamps):
            raise AuditError(f"OUTPUT_IMU_CAMERA_NOT_BRACKETED:{index}")
        predecessor_gaps.append(camera_stamp - stamps[successor - 1])
        successor_gaps.append(stamps[successor] - camera_stamp)
    if not (stamps[0] <= camera_stamps[0] < stamps[1]):
        raise AuditError("OUTPUT_IMU_FIRST_READER_BRACKET_MISMATCH")
    if not (stamps[-2] <= camera_stamps[-1] < stamps[-1]):
        raise AuditError("OUTPUT_IMU_LAST_READER_BRACKET_MISMATCH")
    return {
        "strictly_monotonic": True,
        "reader_bracket_rule": (
            "imu[0] <= cam[0] < imu[1] and imu[-2] <= cam[-1] < imu[-1]"
        ),
        "first_two_output_ns": list(endpoints[:2]),
        "last_two_output_ns": list(endpoints[2:]),
        "first_camera_ns": camera_stamps[0],
        "last_camera_ns": camera_stamps[-1],
        "all_camera_samples_have_predecessor_and_successor": True,
        "minimum_predecessor_gap_ns": min(predecessor_gaps),
        "maximum_predecessor_gap_ns": max(predecessor_gaps),
        "minimum_successor_gap_ns": min(successor_gaps),
        "maximum_successor_gap_ns": max(successor_gaps),
    }


def scan_tree(root: Path) -> Tuple[Set[str], Set[str], Dict[str, Tuple[int, ...]]]:
    if root.is_symlink() or not root.is_dir():
        raise AuditError("INPUT_ROOT_MISSING_SYMLINK_OR_NOT_DIRECTORY")
    files: Set[str] = set()
    directories: Set[str] = {""}
    snapshot: Dict[str, Tuple[int, ...]] = {}
    stack: List[Tuple[Path, str]] = [(root, "")]
    while stack:
        directory, relative_directory = stack.pop()
        observed_directory = os.stat(directory, follow_symlinks=False)
        snapshot[relative_directory + "/"] = (
            observed_directory.st_dev,
            observed_directory.st_ino,
            observed_directory.st_mode,
            observed_directory.st_size,
            observed_directory.st_mtime_ns,
            observed_directory.st_ctime_ns,
        )
        with os.scandir(directory) as entries:
            for entry in entries:
                relative = (
                    f"{relative_directory}/{entry.name}"
                    if relative_directory
                    else entry.name
                )
                observed = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(observed.st_mode):
                    raise AuditError(f"OUTPUT_SYMLINK:{relative}")
                fingerprint = (
                    observed.st_dev,
                    observed.st_ino,
                    observed.st_mode,
                    observed.st_size,
                    observed.st_mtime_ns,
                    observed.st_ctime_ns,
                )
                if stat.S_ISDIR(observed.st_mode):
                    directories.add(relative)
                    stack.append((Path(entry.path), relative))
                elif stat.S_ISREG(observed.st_mode):
                    files.add(relative)
                    snapshot[relative] = fingerprint
                else:
                    raise AuditError(f"OUTPUT_NONREGULAR:{relative}")
    return files, directories, snapshot


def require_tree_closure(
    root: Path, expected_files: Set[str]
) -> Dict[str, Tuple[int, ...]]:
    files, directories, snapshot = scan_tree(root)
    if files != expected_files:
        unexpected = sorted(files - expected_files)[:3]
        missing = sorted(expected_files - files)[:3]
        raise AuditError(f"OUTPUT_FILE_SET_MISMATCH:{unexpected}:{missing}")
    if directories != EXPECTED_DIRECTORIES:
        unexpected = sorted(directories - EXPECTED_DIRECTORIES)[:3]
        missing = sorted(EXPECTED_DIRECTORIES - directories)[:3]
        raise AuditError(f"OUTPUT_DIRECTORY_SET_MISMATCH:{unexpected}:{missing}")
    return snapshot


def validate_selector(payload: bytes) -> Dict[str, Any]:
    value = load_json_unique(payload, "SELECTOR")
    if value.get("schema_version") != SELECTOR_SCHEMA:
        raise AuditError("SELECTOR_SCHEMA_MISMATCH")
    if value.get("status") != (
        "FROZEN_BEFORE_A05_MATERIALIZATION_AND_HFNET_PROCESS_START"
    ):
        raise AuditError("SELECTOR_STATUS_MISMATCH")
    expected_selection = {
        "dataset_family": "aqualoc_archaeology",
        "sequence_id": "A05",
        "camera_indices_inclusive_for_feed": [1, 3700],
        "camera_count_for_feed": 3700,
        "camera_zero_excluded": True,
        "camera_zero_exclusion_reason": (
            "After the frozen +53694112 ns IMU-to-camera clock shift, source "
            "camera 0 has no shifted IMU predecessor; source camera 1 is the "
            "first legal feed frame."
        ),
        "preroll_camera_indices_inclusive": [1, 3299],
        "score_camera_indices_inclusive": [3300, 3700],
        "score_camera_count": 401,
        "score_history_policy": (
            "Feed frames 1..3700 continuously without estimator reset and "
            "score only source frames 3300..3700."
        ),
        "warm_start": True,
        "cold_start": False,
        "synthetic_or_extrapolated_imu_permitted": False,
    }
    if value.get("selection") != expected_selection:
        raise AuditError("SELECTOR_SELECTION_MISMATCH")
    boundary = value.get("knowledge_boundary", {})
    if (
        boundary.get("window_is_outcome_selected") is not True
        or boundary.get(
            "accuracy_requires_new_history_matched_controls_and_common_support"
        )
        is not True
        or boundary.get("natural_history_hfnet_must_not_be_ranked_against_cold_crop_metrics")
        is not True
    ):
        raise AuditError("SELECTOR_KNOWLEDGE_BOUNDARY_MISMATCH")
    if value.get("claims") != {
        "accuracy_evaluated": False,
        "confirmatory_evidence": False,
        "hfnet_runability_passed": False,
        "hfnet_started": False,
        "input_materialized": False,
        "superiority_supported": False,
        "system_ranking_supported": False,
        "trajectory_produced": False,
    }:
        raise AuditError("SELECTOR_CLAIMS_MISMATCH")
    return value


def validate_config(payload: bytes) -> None:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise AuditError("CONFIG_NOT_UTF8") from error
    for required in (
        '# c354c72588a97bb6f6a9c7c8317530795956ec80',
        'Camera.type: "PinHole"',
        "Camera.width: 968",
        "Camera.height: 608",
        "IMU.NoiseGyro: 0.003",
        "IMU.NoiseAcc: 0.05",
        "IMU.GyroWalk: 0.0001",
        "IMU.AccWalk: 0.0015",
        "IMU.Frequency: 200.0",
        "Extractor.nFeatures: 675",
        "Extractor.threshold: 0.01",
        "loopClosing: 1",
    ):
        if required not in text:
            raise AuditError(f"CONFIG_REQUIRED_PIN_MISSING:{required}")


def expected_manifest_selection() -> Dict[str, Any]:
    return {
        "dataset_family": "aqualoc_archaeology",
        "sequence_id": "A05",
        "camera_indices_inclusive": [1, 3700],
        "camera_count": 3700,
        "camera_header_ns_inclusive": [CAMERA_FIRST_NS, CAMERA_LAST_NS],
        "camera_zero_trimmed_for_missing_shifted_imu_predecessor": True,
        "first_legal_camera_source_index": 1,
        "preroll_source_camera_indices_inclusive": [1, 3299],
        "preroll_relative_indices_inclusive": [0, 3298],
        "score_source_camera_indices_inclusive": SCORE_SOURCE,
        "score_relative_indices_inclusive": SCORE_RELATIVE,
        "score_camera_count": 401,
        "warm_start": True,
        "cold_start": False,
        "development_result_conditioned_selection": True,
        "imu_source_indices_inclusive_zero_based": [7, 36964],
        "imu_count": IMU_COUNT,
        "imu_shift_ns": IMU_SHIFT_NS,
        "synthetic_imu_samples_added": False,
    }


def validate_manifest_selection(value: Any) -> None:
    if value != expected_manifest_selection():
        raise AuditError("MANIFEST_SELECTION_MISMATCH")


def stream_canonical_source(
    source: Path, output_rows: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    expected = {
        f"frame{source_index:06d}.png": output_rows[
            source_index - SOURCE_CAMERA_FIRST
        ]
        for source_index in range(SOURCE_CAMERA_FIRST, SOURCE_CAMERA_LAST + 1)
    }
    seen: Set[str] = set()
    captured: Dict[str, bytes] = {}
    source_rows: List[Dict[str, Any]] = []
    try:
        with tarfile.open(str(source), "r|gz") as archive:
            for member in archive:
                if member.name in (IMAGE_CSV_MEMBER, IMU_CSV_MEMBER):
                    if member.name in captured:
                        raise AuditError(f"SOURCE_MEMBER_DUPLICATE:{member.name}")
                    if not member.isreg() or member.issym() or member.islnk():
                        raise AuditError(f"SOURCE_MEMBER_NOT_REGULAR:{member.name}")
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise AuditError(f"SOURCE_MEMBER_UNREADABLE:{member.name}")
                    payload = extracted.read()
                    if len(payload) != member.size:
                        raise AuditError(f"SOURCE_MEMBER_SIZE_MISMATCH:{member.name}")
                    captured[member.name] = payload
                    continue
                if not member.name.startswith(IMAGE_PREFIX):
                    continue
                filename = member.name[len(IMAGE_PREFIX) :]
                output = expected.get(filename)
                if output is None:
                    continue
                if filename in seen:
                    raise AuditError(f"SOURCE_IMAGE_MEMBER_DUPLICATE:{filename}")
                if not member.isreg() or member.issym() or member.islnk():
                    raise AuditError(f"SOURCE_IMAGE_MEMBER_NOT_REGULAR:{filename}")
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise AuditError(f"SOURCE_IMAGE_MEMBER_UNREADABLE:{filename}")
                payload = extracted.read()
                if len(payload) != member.size:
                    raise AuditError(f"SOURCE_IMAGE_MEMBER_SIZE_MISMATCH:{filename}")
                observed = identity_bytes(member.name, payload)
                if (
                    observed["size_bytes"],
                    observed["sha256"],
                    observed["crc32"],
                ) != (
                    output["size_bytes"],
                    output["sha256"],
                    output["crc32"],
                ):
                    raise AuditError(f"SOURCE_OUTPUT_BYTES_DIFFER:{filename}")
                source_rows.append(observed)
                seen.add(filename)
    except AuditError:
        raise
    except (tarfile.TarError, EOFError, OSError, zlib.error) as error:
        raise AuditError(f"SOURCE_STREAM_INTEGRITY_ERROR:{type(error).__name__}") from error
    if seen != set(expected):
        raise AuditError(f"SOURCE_IMAGE_SET_MISMATCH:{len(seen)}")
    if set(captured) != {IMAGE_CSV_MEMBER, IMU_CSV_MEMBER}:
        raise AuditError("SOURCE_CSV_MEMBER_SET_MISMATCH")
    image_csv_identity = identity_bytes(IMAGE_CSV_MEMBER, captured[IMAGE_CSV_MEMBER])
    imu_csv_identity = identity_bytes(IMU_CSV_MEMBER, captured[IMU_CSV_MEMBER])
    require_pin(
        image_csv_identity,
        (IMAGE_CSV_SIZE, IMAGE_CSV_SHA256, IMAGE_CSV_CRC32),
        "SOURCE_IMAGE_CSV",
    )
    require_pin(
        imu_csv_identity,
        (IMU_CSV_SIZE, IMU_CSV_SHA256, IMU_CSV_CRC32),
        "SOURCE_IMU_CSV",
    )
    source_rows.sort(key=lambda row: str(row["path"]))
    return {
        "image_csv_payload": captured[IMAGE_CSV_MEMBER],
        "imu_csv_payload": captured[IMU_CSV_MEMBER],
        "image_csv_identity": image_csv_identity,
        "imu_csv_identity": imu_csv_identity,
        "source_image_rows": source_rows,
        "source_image_identity": aggregate(source_rows),
        "source_members_compared": len(seen),
        "source_gzip_stream_fully_consumed_and_crc_checked": True,
    }


def validate_manifest(
    manifest: Mapping[str, Any],
    root: Path,
    selector_identity: Mapping[str, Any],
    source_identity: Mapping[str, Any],
    source_members: Mapping[str, Any],
    reused_core: Mapping[str, Any],
    reused_adapter: Mapping[str, Any],
    image_rows: Sequence[Mapping[str, Any]],
    source_image_identity: Mapping[str, Any],
    image_identity: Mapping[str, Any],
    generated: Mapping[str, Mapping[str, Any]],
    payload_identity: Mapping[str, Any],
    bracket_for_manifest: Mapping[str, Any],
) -> None:
    expected_keys = {
        "schema_version",
        "status",
        "output_root",
        "reused_sealed_core",
        "reused_a06_adapter",
        "selector_freeze",
        "source",
        "selection",
        "camera",
        "generated_files",
        "imu",
        "payload_identity_excluding_manifest",
        "payload_file_count_excluding_manifest",
        "reporting_boundary",
        "claims",
    }
    if set(manifest) != expected_keys:
        raise AuditError("MANIFEST_TOP_LEVEL_KEY_SET_MISMATCH")
    if (
        manifest.get("schema_version") != MATERIALIZATION_SCHEMA
        or manifest.get("status") != "PASS_PREPARATION_ONLY"
        or manifest.get("output_root") != str(root.resolve())
    ):
        raise AuditError("MANIFEST_STATUS_SCHEMA_OR_ROOT_MISMATCH")
    if manifest.get("reused_sealed_core") != reused_core:
        raise AuditError("MANIFEST_REUSED_CORE_MISMATCH")
    if manifest.get("reused_a06_adapter") != reused_adapter:
        raise AuditError("MANIFEST_REUSED_ADAPTER_MISMATCH")
    if manifest.get("selector_freeze") != selector_identity:
        raise AuditError("MANIFEST_SELECTOR_IDENTITY_MISMATCH")
    expected_source = {
        **source_identity,
        "members": source_members,
        "gzip_stream_fully_consumed_and_crc_checked": True,
    }
    if manifest.get("source") != expected_source:
        raise AuditError("MANIFEST_SOURCE_IDENTITY_MISMATCH")
    validate_manifest_selection(manifest.get("selection"))
    histogram: Dict[str, int] = {}
    for row in image_rows:
        key = str(row["png"]["chunk_count"])
        histogram[key] = histogram.get(key, 0) + 1
    expected_camera = {
        "copy_policy": "canonical tar member PNG bytes copied unchanged",
        "renamed_to": "mav0/cam0/data/<camera_timestamp_ns>.png",
        "count": CAMERA_COUNT,
        "total_bytes": sum(int(row["size_bytes"]) for row in image_rows),
        "schema": "968x608 8-bit grayscale non-interlaced PNG",
        "png_chunk_crc_all_valid": True,
        "png_idat_all_decompressed": True,
        "png_chunk_count_histogram": histogram,
        "source_member_inventory_identity": source_image_identity,
        "renamed_output_inventory_identity": image_identity,
        "files": list(image_rows),
    }
    if manifest.get("camera") != expected_camera:
        raise AuditError("MANIFEST_CAMERA_INVENTORY_MISMATCH")
    if manifest.get("generated_files") != generated:
        raise AuditError("MANIFEST_GENERATED_FILE_IDENTITY_MISMATCH")
    expected_imu = {
        "source_header": IMU_CSV_HEADER,
        "measurement_tokens_preserved": True,
        "axis_transform": "none; A06 Archaeology T_i_b is identity",
        "final_newline": False,
        "bracket_audit": bracket_for_manifest,
    }
    if manifest.get("imu") != expected_imu:
        raise AuditError("MANIFEST_IMU_MISMATCH")
    if manifest.get("payload_identity_excluding_manifest") != payload_identity:
        raise AuditError("MANIFEST_PAYLOAD_IDENTITY_MISMATCH")
    if manifest.get("payload_file_count_excluding_manifest") != CAMERA_COUNT + 3:
        raise AuditError("MANIFEST_PAYLOAD_FILE_COUNT_MISMATCH")
    if manifest.get("reporting_boundary") != (
        "development-only A05 natural-history input preparation; historical "
        "cold-crop learned/KLT metrics are provenance only; no HFNet process, "
        "trajectory, accuracy, or ranking"
    ):
        raise AuditError("MANIFEST_REPORTING_BOUNDARY_MISMATCH")
    if manifest.get("claims") != CLAIMS:
        raise AuditError("MANIFEST_CLAIMS_MISMATCH")


def audit(
    root: Path = INPUT_ROOT,
    source: Path = SOURCE_ARCHIVE,
    selector: Path = SELECTOR,
    config: Path = CONFIG,
) -> Dict[str, Any]:
    root, source, selector, config = map(Path, (root, source, selector, config))
    source_identity = require_identity(source, SOURCE_SIZE, SOURCE_SHA256, "SOURCE")
    source_descriptor = _open_regular(source, "SOURCE_FOOTER")
    try:
        os.lseek(source_descriptor, -8, os.SEEK_END)
        footer = os.read(source_descriptor, 8)
    finally:
        os.close(source_descriptor)
    if len(footer) != 8:
        raise AuditError("SOURCE_GZIP_FOOTER_MISSING")
    footer_crc, footer_isize = struct.unpack("<II", footer)
    if f"{footer_crc:08x}" != SOURCE_GZIP_CRC32 or footer_isize != SOURCE_GZIP_ISIZE:
        raise AuditError("SOURCE_GZIP_FOOTER_MISMATCH")
    source_identity = {
        key: value for key, value in source_identity.items() if key != "crc32"
    }
    source_identity["gzip_footer_crc32"] = SOURCE_GZIP_CRC32
    source_identity["gzip_footer_isize_mod_2_32"] = SOURCE_GZIP_ISIZE

    selector_identity = require_identity(
        selector, SELECTOR_SIZE, SELECTOR_SHA256, "SELECTOR"
    )
    selector_payload = read_regular(selector, "SELECTOR")
    validate_selector(selector_payload)
    config_identity = require_identity(config, CONFIG_SIZE, CONFIG_SHA256, "CONFIG")
    validate_config(read_regular(config, "CONFIG"))
    reused_adapter = require_identity(
        A06_ADAPTER, A06_ADAPTER_SIZE, A06_ADAPTER_SHA256, "A06_ADAPTER"
    )
    reused_core = require_identity(
        SEALED_CORE, SEALED_CORE_SIZE, SEALED_CORE_SHA256, "SEALED_CORE"
    )
    auditor_identity = identity_file(
        Path(__file__).resolve(), str(Path(__file__).resolve()), "AUDITOR"
    )

    initial_files, initial_directories, _ = scan_tree(root)
    if initial_directories != EXPECTED_DIRECTORIES:
        raise AuditError("OUTPUT_DIRECTORY_SET_MISMATCH")
    manifest_path = root / "materialization_manifest.json"
    manifest_payload = read_regular(manifest_path, "MANIFEST")
    manifest = load_json_unique(manifest_payload, "MANIFEST")
    manifest_identity = identity_bytes("materialization_manifest.json", manifest_payload)

    generated_payloads = {
        relative: read_regular(root / relative, f"GENERATED:{relative}")
        for relative in EXPECTED_GENERATED
    }
    generated_rows: Dict[str, Dict[str, Any]] = {}
    generated_manifest = {
        "cam0_times": identity_bytes(
            "cam0_times.txt", generated_payloads["cam0_times.txt"]
        ),
        "cam0_data_csv": identity_bytes(
            "mav0/cam0/data.csv", generated_payloads["mav0/cam0/data.csv"]
        ),
        "imu0_data_csv": identity_bytes(
            "mav0/imu0/data.csv", generated_payloads["mav0/imu0/data.csv"]
        ),
    }
    for relative, payload in generated_payloads.items():
        row = identity_bytes(relative, payload)
        require_pin(row, EXPECTED_GENERATED[relative], f"GENERATED:{relative}")
        generated_rows[relative] = row
    camera_stamps = parse_camera_times(generated_payloads["cam0_times.txt"])
    expected_camera_csv = [CAMERA_OUTPUT_CSV_HEADER]
    expected_camera_csv.extend(f"{stamp},{stamp}.png" for stamp in camera_stamps)
    if generated_payloads["mav0/cam0/data.csv"] != (
        "\n".join(expected_camera_csv) + "\n"
    ).encode("ascii"):
        raise AuditError("OUTPUT_CAMERA_CSV_MAPPING_MISMATCH")
    bracket = validate_imu_brackets(
        generated_payloads["mav0/imu0/data.csv"], camera_stamps
    )

    image_rows: List[Dict[str, Any]] = []
    expected_image_paths: Set[str] = set()
    for relative_index, stamp in enumerate(camera_stamps):
        source_index = SOURCE_CAMERA_FIRST + relative_index
        source_member = f"{IMAGE_PREFIX}frame{source_index:06d}.png"
        relative = f"mav0/cam0/data/{stamp}.png"
        payload = read_regular(root / relative, f"IMAGE:{relative_index}")
        png = validate_png(payload)
        row = identity_bytes(relative, payload)
        row.update(
            {
                "source_index": source_index,
                "source_member": source_member,
                "camera_timestamp_ns": stamp,
                "png": png,
                "canonical_member_bytes_preserved": True,
            }
        )
        image_rows.append(row)
        expected_image_paths.add(relative)
    expected_files = expected_image_paths | set(EXPECTED_GENERATED) | {
        "materialization_manifest.json"
    }
    initial_snapshot = require_tree_closure(root, expected_files)
    if initial_files != expected_files:
        raise AuditError("OUTPUT_FILE_SET_CHANGED_DURING_INITIAL_SCAN")

    canonical = stream_canonical_source(source, image_rows)
    _, selected_camera = parse_source_camera(canonical["image_csv_payload"])
    if [stamp for stamp, _ in selected_camera] != camera_stamps:
        raise AuditError("CANONICAL_CAMERA_SELECTION_DIFFERS_FROM_OUTPUT")
    if selected_camera[0][0] != CAMERA_FIRST_NS or selected_camera[-1][0] != CAMERA_LAST_NS:
        raise AuditError("CANONICAL_CAMERA_ENDPOINT_MISMATCH")
    _, selected_imu = parse_source_imu(
        canonical["imu_csv_payload"], selected_camera
    )
    if (
        len(selected_imu) != IMU_COUNT
        or selected_imu[0][0] != IMU_FIRST_RAW_NS
        or selected_imu[-1][0] != IMU_LAST_RAW_NS
    ):
        raise AuditError("CANONICAL_IMU_SELECTION_MISMATCH")
    independently_derived = {
        "cam0_times.txt": camera_times_bytes(selected_camera),
        "mav0/cam0/data.csv": camera_csv_bytes(selected_camera),
        "mav0/imu0/data.csv": imu_csv_bytes(selected_imu),
    }
    for relative, expected_payload in independently_derived.items():
        if generated_payloads[relative] != expected_payload:
            raise AuditError(f"OUTPUT_DIFFERS_FROM_INDEPENDENT_DERIVATION:{relative}")

    image_identity = aggregate(image_rows)
    payload_rows: List[Mapping[str, Any]] = list(image_rows)
    payload_rows.extend(generated_rows.values())
    payload_identity = aggregate(payload_rows)
    source_members = {
        "camera_csv": canonical["image_csv_identity"],
        "imu_csv": canonical["imu_csv_identity"],
    }
    bracket_for_manifest = {
        key: bracket[key]
        for key in (
            "strictly_monotonic",
            "reader_bracket_rule",
            "first_two_output_ns",
            "last_two_output_ns",
            "first_camera_ns",
            "last_camera_ns",
        )
    }
    validate_manifest(
        manifest,
        root,
        selector_identity,
        source_identity,
        source_members,
        reused_core,
        reused_adapter,
        image_rows,
        canonical["source_image_identity"],
        image_identity,
        generated_manifest,
        payload_identity,
        bracket_for_manifest,
    )

    final_files, final_directories, final_snapshot = scan_tree(root)
    if (
        final_files != expected_files
        or final_directories != EXPECTED_DIRECTORIES
        or final_snapshot != initial_snapshot
    ):
        raise AuditError("OUTPUT_TREE_CHANGED_DURING_AUDIT")
    if read_regular(manifest_path, "MANIFEST_FINAL") != manifest_payload:
        raise AuditError("MANIFEST_CHANGED_DURING_AUDIT")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_PREPARATION_ONLY_INDEPENDENT_AUDIT",
        "input_root": str(root.resolve()),
        "auditor": auditor_identity,
        "source": {
            **source_identity,
            "members": source_members,
            "selected_png_members_compared": CAMERA_COUNT,
            "selected_png_bytes_equal": True,
            "gzip_stream_fully_consumed_and_crc_checked": True,
        },
        "selector_freeze": selector_identity,
        "configuration": config_identity,
        "tree_closure": {
            "file_count_including_manifest": len(expected_files),
            "payload_file_count_excluding_manifest": CAMERA_COUNT + 3,
            "directory_count_including_root": len(EXPECTED_DIRECTORIES),
            "exact_file_set": True,
            "exact_directory_set": True,
            "all_entries_regular_or_directories": True,
            "symlinks_present": False,
            "unchanged_during_audit": True,
        },
        "camera": {
            "source_indices_inclusive": [SOURCE_CAMERA_FIRST, SOURCE_CAMERA_LAST],
            "count": CAMERA_COUNT,
            "header_ns_inclusive": [camera_stamps[0], camera_stamps[-1]],
            "preroll_source_indices_inclusive": [1, 3299],
            "score_source_indices_inclusive": SCORE_SOURCE,
            "score_relative_indices_inclusive": SCORE_RELATIVE,
            "total_png_bytes": sum(int(row["size_bytes"]) for row in image_rows),
            "all_png_bytes_identical_to_canonical_source_members": True,
            "all_png_chunk_crc_valid": True,
            "all_png_idat_decoded": True,
            "renamed_output_inventory_identity": image_identity,
            "source_member_inventory_identity": canonical[
                "source_image_identity"
            ],
        },
        "imu": {
            "source_indices_inclusive_zero_based": [IMU_FIRST_INDEX, IMU_LAST_INDEX],
            "source_count": SOURCE_IMU_COUNT,
            "selected_count": IMU_COUNT,
            "time_transform": "output_ns=raw_ns+53694112",
            "measurement_tokens_preserved": True,
            "synthetic_samples_added": False,
            **bracket,
        },
        "generated_files": list(generated_rows.values()),
        "payload_identity_excluding_manifest": payload_identity,
        "materialization_manifest": manifest_identity,
        "manifest_selection_valid": True,
        "manifest_hash_computed_from_exact_bytes": True,
        "reporting_boundary": (
            "development-only A05 natural-history input preparation; no HFNet "
            "process, trajectory, runability result, accuracy, or ranking"
        ),
        "claims": CLAIMS,
    }


def write_exclusive(path: Path, payload: bytes) -> None:
    if os.path.lexists(os.fspath(path)):
        raise AuditError(f"NO_CLOBBER_REPORT_EXISTS:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(os.fspath(path), flags, 0o444)
    try:
        view = memoryview(payload)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise AuditError("AUDIT_REPORT_SHORT_WRITE")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--input-root", type=Path, default=INPUT_ROOT)
    value.add_argument("--source-archive", type=Path, default=SOURCE_ARCHIVE)
    value.add_argument("--selector-freeze", type=Path, default=SELECTOR)
    value.add_argument("--config", type=Path, default=CONFIG)
    value.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return value


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)
    try:
        if os.path.lexists(os.fspath(args.report)):
            raise AuditError(f"NO_CLOBBER_REPORT_EXISTS:{args.report}")
        result = audit(
            args.input_root,
            args.source_archive,
            args.selector_freeze,
            args.config,
        )
        payload = canonical_json(result)
        write_exclusive(args.report, payload)
        return_code = 0
    except Exception as error:
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "INTEGRITY_ERROR",
            "errors": [f"{type(error).__name__}:{error}"],
            "claims": {
                "hfnet_started": False,
                "trajectory_produced": False,
                "accuracy_measured": False,
            },
        }
        payload = canonical_json(result)
        return_code = 2
    sys.stdout.buffer.write(payload)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
