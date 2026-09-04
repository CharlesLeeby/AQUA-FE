#!/usr/bin/env python3
"""Prepare the frozen H03 Phase-F monocular-inertial input, and nothing else.

The production action selectively streams 1,801 canonical PNG members from the
H03 raw tarball, copies their bytes unchanged under EuRoC timestamp names, and
writes the exact camera and shifted-IMU CSV inputs consumed by the frozen
HFNet-SLAM monocular-inertial entry.  Publication is atomic and no-clobber.

This module deliberately contains no runner, process-start claim, detector,
VINS, HFNet, trajectory, or evaluator invocation.
"""

from __future__ import annotations

import argparse
import bisect
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import sys
import tarfile
import tempfile
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Set, Tuple
import zlib


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "aqua-fe-hfnet-v6-phase-f-h03-input-materialization-v1"
SELECTOR_SCHEMA = "aqua-fe-hfnet-v6-phase-f-underwater-selector-freeze-v1"

DEFAULT_SELECTOR_FREEZE = (
    ROOT / "papers/hfnet_v6_phase_f_h03_1800_3600_selector_freeze_v1.json"
)
SELECTOR_FREEZE_SIZE = 12_536
SELECTOR_FREEZE_SHA256 = (
    "ab7557db88d884e565d71a31a562e3e88c70eba6d8e643f22ca5b2bdd2d18269"
)

DEFAULT_SOURCE_ARCHIVE = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Harbor_sites_sequences/harbor_sequence_03_raw_data.tar.gz"
)
DEFAULT_OUTPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_v6_phase_f_fresh_underwater_v1/"
    "aqualoc_harbor_h03_1800_3600"
)

IMAGE_CSV_HEADER = "#timestamp [ns], frame_id"
CAMERA_OUTPUT_CSV_HEADER = "#timestamp [ns],filename"
IMU_CSV_HEADER = (
    "#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],"
    "w_RS_S_z [rad s^-1],a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],"
    "a_RS_S_z [m s^-2]"
)


class ContractError(RuntimeError):
    """A frozen source, selection, payload, or no-clobber invariant failed."""


@dataclass(frozen=True)
class FilePin:
    size_bytes: Optional[int] = None
    sha256: Optional[str] = None
    crc32: Optional[str] = None


@dataclass(frozen=True)
class MaterializationContract:
    source_archive: Path
    source_pin: FilePin
    source_gzip_crc32: Optional[str]
    source_gzip_isize: Optional[int]
    image_csv_member: str
    image_csv_pin: FilePin
    imu_csv_member: str
    imu_csv_pin: FilePin
    image_member_prefix: str
    source_camera_count: int
    source_imu_count: int
    camera_start_index: int
    camera_end_index: int
    camera_first_ns: int
    camera_last_ns: int
    width: int
    height: int
    png_bit_depth: int
    png_color_type: int
    imu_shift_ns: int
    imu_first_index: int
    imu_last_index: int
    imu_first_raw_ns: int
    imu_last_raw_ns: int
    imu_first_output_ns: int
    imu_second_output_ns: int
    imu_penultimate_output_ns: int
    imu_last_output_ns: int
    expected_image_total_bytes: Optional[int]
    expected_source_image_inventory_sha256: Optional[str]
    expected_source_image_inventory_crc32: Optional[str]
    expected_renamed_image_inventory_sha256: Optional[str]
    expected_renamed_image_inventory_crc32: Optional[str]
    times_pin: FilePin
    camera_csv_pin: FilePin
    imu_output_pin: FilePin
    expected_payload_sha256: Optional[str]
    expected_payload_crc32: Optional[str]

    @property
    def camera_count(self) -> int:
        return self.camera_end_index - self.camera_start_index + 1

    @property
    def imu_count(self) -> int:
        return self.imu_last_index - self.imu_first_index + 1


PRODUCTION_CONTRACT = MaterializationContract(
    source_archive=DEFAULT_SOURCE_ARCHIVE,
    source_pin=FilePin(
        size_bytes=905_738_013,
        sha256="6a4062a61498a108ade031ecff1cdf0818390212ff84882e922cc162ee5e54f1",
    ),
    source_gzip_crc32="f6d45bb2",
    source_gzip_isize=915_148_800,
    image_csv_member="raw_data/harbor_img_sequence_03.csv",
    image_csv_pin=FilePin(
        size_bytes=185_462,
        sha256="39d7a847cbd80a2cd1ebeeab5d167e0629ea133dc61b6c18488232c13cff6c6c",
    ),
    imu_csv_member="raw_data/harbor_imu_sequence_03.csv",
    imu_csv_pin=FilePin(
        size_bytes=5_907_091,
        sha256="c883cf2620bb2765b140f1717d12b65b52b8335e8a2fd66edafcffa48d6edac1",
    ),
    image_member_prefix="raw_data/harbor_images_sequence_03/",
    source_camera_count=5_151,
    source_imu_count=51_507,
    camera_start_index=1_800,
    camera_end_index=3_600,
    camera_first_ns=1_523_966_922_643_979_137,
    camera_last_ns=1_523_967_012_680_410_986,
    width=640,
    height=512,
    png_bit_depth=8,
    png_color_type=0,
    imu_shift_ns=40_380_655,
    imu_first_index=18_003,
    imu_last_index=36_001,
    imu_first_raw_ns=1_523_966_922_602_516_111,
    imu_last_raw_ns=1_523_967_012_642_286_529,
    imu_first_output_ns=1_523_966_922_642_896_766,
    imu_second_output_ns=1_523_966_922_647_928_935,
    imu_penultimate_output_ns=1_523_967_012_677_636_392,
    imu_last_output_ns=1_523_967_012_682_667_184,
    expected_image_total_bytes=327_959_010,
    expected_source_image_inventory_sha256=(
        "e06c6107e00479d84a9bcd0b398f643e3cbd0fbdd3567e0eb5dad5a75f8a3cb7"
    ),
    expected_source_image_inventory_crc32="672dd515",
    expected_renamed_image_inventory_sha256=(
        "bb1cf0238839c5899f4907845c3aac1c9e659ff0b1c1d65b6cfbad015238614a"
    ),
    expected_renamed_image_inventory_crc32="8a0dd9e5",
    times_pin=FilePin(
        size_bytes=36_020,
        sha256="5732e74d12a720cbf7aa3b68cbf5ab189e3493bec7954271017bde7d54f5d92e",
        crc32="8f95d70e",
    ),
    camera_csv_pin=FilePin(
        size_bytes=79_269,
        sha256="02ddfd4c66ce1d05956a16790140f29abb43c47222ae5ea1faf47b66205bca6f",
        crc32="420d7c09",
    ),
    imu_output_pin=FilePin(
        size_bytes=2_058_198,
        sha256="45edd79a4073f646813cc53d710ab5fd6a26a4b3acb927dfa18292dc6c377193",
        crc32="a3016b12",
    ),
    expected_payload_sha256=(
        "afdfec7e12f9e80b3008f7e82ecbb25f9b16ff0716b9b0c4878a3af06b2061b4"
    ),
    expected_payload_crc32="69365ded",
)


def canonical_json(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def crc32_bytes(payload: bytes) -> str:
    return f"{zlib.crc32(payload) & 0xFFFFFFFF:08x}"


def identity_bytes(path: str, payload: bytes) -> Dict[str, Any]:
    return {
        "path": path,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "crc32": crc32_bytes(payload),
    }


def identity_file(path: Path, relative: str) -> Dict[str, Any]:
    digest = hashlib.sha256()
    crc = 0
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            size += len(block)
            digest.update(block)
            crc = zlib.crc32(block, crc)
    return {
        "path": relative,
        "size_bytes": size,
        "sha256": digest.hexdigest(),
        "crc32": f"{crc & 0xFFFFFFFF:08x}",
    }


def require_pin(observed: Mapping[str, Any], expected: FilePin, label: str) -> None:
    if expected.size_bytes is not None and observed["size_bytes"] != expected.size_bytes:
        raise ContractError(f"{label}_SIZE_MISMATCH:{observed['size_bytes']}")
    if expected.sha256 is not None and observed["sha256"] != expected.sha256:
        raise ContractError(f"{label}_SHA256_MISMATCH:{observed['sha256']}")
    if expected.crc32 is not None and observed["crc32"] != expected.crc32:
        raise ContractError(f"{label}_CRC32_MISMATCH:{observed['crc32']}")


def aggregate_identities(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    digest = hashlib.sha256()
    crc = 0
    for row in sorted(rows, key=lambda item: str(item["path"])):
        encoded = (
            f"{row['path']}\0{row['size_bytes']}\0{row['sha256']}\0{row['crc32']}\n"
        ).encode("utf-8")
        digest.update(encoded)
        crc = zlib.crc32(encoded, crc)
    return {
        "algorithm": "sorted UTF-8 path\\0size\\0sha256\\0crc32\\n",
        "sha256": digest.hexdigest(),
        "crc32": f"{crc & 0xFFFFFFFF:08x}",
    }


def fsync_directory(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_exclusive_bytes(
    path: Path, payload: bytes, mode: int = 0o444, durable: bool = True
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        if durable:
            os.fsync(stream.fileno())


@contextmanager
def atomic_directory(target: Path) -> Iterator[Path]:
    target = target.expanduser().resolve(strict=False)
    if target.exists() or target.is_symlink():
        raise ContractError(f"NO_CLOBBER_OUTPUT_EXISTS:{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.tmp-", dir=str(target.parent)))
    published = False
    try:
        yield staging
        if target.exists() or target.is_symlink():
            raise ContractError(f"NO_CLOBBER_OUTPUT_APPEARED:{target}")
        os.rename(str(staging), str(target))
        fsync_directory(target.parent)
        published = True
    finally:
        if not published:
            shutil.rmtree(str(staging), ignore_errors=True)


def validate_selector(path: Path) -> Dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ContractError("SELECTOR_FREEZE_MISSING_OR_NOT_REGULAR")
    observed = {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if observed["size_bytes"] != SELECTOR_FREEZE_SIZE:
        raise ContractError("SELECTOR_FREEZE_SIZE_MISMATCH")
    if observed["sha256"] != SELECTOR_FREEZE_SHA256:
        raise ContractError("SELECTOR_FREEZE_SHA256_MISMATCH")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != SELECTOR_SCHEMA:
        raise ContractError("SELECTOR_FREEZE_SCHEMA_MISMATCH")
    selection = value.get("selection", {})
    if selection.get("sequence_id") != "H03":
        raise ContractError("SELECTOR_SEQUENCE_MISMATCH")
    if selection.get("camera_indices_inclusive_for_feed") != [1800, 3600]:
        raise ContractError("SELECTOR_CAMERA_RANGE_MISMATCH")
    if value.get("claims", {}).get("hfnet_started") is not False:
        raise ContractError("SELECTOR_HFNET_START_CLAIM_INVALID")
    return observed


def validate_source_archive(path: Path, contract: MaterializationContract) -> Dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ContractError("SOURCE_ARCHIVE_MISSING_OR_NOT_REGULAR")
    size = path.stat().st_size
    digest = sha256_file(path)
    observed: Dict[str, Any] = {
        "path": str(path.resolve()),
        "size_bytes": size,
        "sha256": digest,
    }
    require_pin({**observed, "crc32": None}, contract.source_pin, "SOURCE_ARCHIVE")
    with path.open("rb") as stream:
        stream.seek(-8, os.SEEK_END)
        footer = stream.read(8)
    if len(footer) != 8:
        raise ContractError("SOURCE_GZIP_FOOTER_MISSING")
    footer_crc, footer_isize = struct.unpack("<II", footer)
    observed["gzip_footer_crc32"] = f"{footer_crc:08x}"
    observed["gzip_footer_isize_mod_2_32"] = footer_isize
    if (
        contract.source_gzip_crc32 is not None
        and observed["gzip_footer_crc32"] != contract.source_gzip_crc32
    ):
        raise ContractError("SOURCE_GZIP_FOOTER_CRC_MISMATCH")
    if contract.source_gzip_isize is not None and footer_isize != contract.source_gzip_isize:
        raise ContractError("SOURCE_GZIP_FOOTER_ISIZE_MISMATCH")
    return observed


def read_pinned_member(
    archive: Path, member_name: str, pin: FilePin, label: str
) -> Tuple[bytes, Dict[str, Any]]:
    with tarfile.open(str(archive), "r:gz") as tar:
        try:
            member = tar.getmember(member_name)
        except KeyError as error:
            raise ContractError(f"{label}_MEMBER_MISSING") from error
        if not member.isreg() or member.issym() or member.islnk():
            raise ContractError(f"{label}_MEMBER_NOT_REGULAR")
        extracted = tar.extractfile(member)
        if extracted is None:
            raise ContractError(f"{label}_MEMBER_UNREADABLE")
        payload = extracted.read()
    observed = identity_bytes(member_name, payload)
    if member.size != observed["size_bytes"]:
        raise ContractError(f"{label}_TAR_SIZE_MISMATCH")
    require_pin(observed, pin, label)
    return payload, observed


def parse_camera_rows(
    payload: bytes, contract: MaterializationContract
) -> Tuple[List[Tuple[int, str]], List[Tuple[int, str]]]:
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ContractError("IMAGE_CSV_NOT_UTF8") from error
    if not lines or lines[0] != IMAGE_CSV_HEADER:
        raise ContractError("IMAGE_CSV_HEADER_MISMATCH")
    rows: List[Tuple[int, str]] = []
    previous: Optional[int] = None
    for index, line in enumerate(lines[1:]):
        fields = line.split(",")
        if len(fields) != 2:
            raise ContractError(f"IMAGE_CSV_COLUMN_COUNT:{index}")
        try:
            stamp = int(fields[0])
        except ValueError as error:
            raise ContractError(f"IMAGE_CSV_TIMESTAMP_INVALID:{index}") from error
        expected_name = f"frame{index:06d}.png"
        if fields[1] != expected_name:
            raise ContractError(f"IMAGE_CSV_FRAME_NAME_MISMATCH:{index}")
        if previous is not None and stamp <= previous:
            raise ContractError(f"IMAGE_CSV_NON_MONOTONIC:{index}")
        rows.append((stamp, fields[1]))
        previous = stamp
    if len(rows) != contract.source_camera_count:
        raise ContractError(f"IMAGE_CSV_SOURCE_COUNT_MISMATCH:{len(rows)}")
    selected = rows[contract.camera_start_index : contract.camera_end_index + 1]
    if len(selected) != contract.camera_count:
        raise ContractError("IMAGE_CSV_SELECTION_COUNT_MISMATCH")
    if selected[0][0] != contract.camera_first_ns:
        raise ContractError("CAMERA_FIRST_TIMESTAMP_MISMATCH")
    if selected[-1][0] != contract.camera_last_ns:
        raise ContractError("CAMERA_LAST_TIMESTAMP_MISMATCH")
    return rows, selected


def parse_imu_rows(
    payload: bytes,
    selected_camera: Sequence[Tuple[int, str]],
    contract: MaterializationContract,
) -> Tuple[List[Tuple[int, Tuple[str, ...]]], List[Tuple[int, Tuple[str, ...]]]]:
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ContractError("IMU_CSV_NOT_UTF8") from error
    if not lines or lines[0] != IMU_CSV_HEADER:
        raise ContractError("IMU_CSV_HEADER_MISMATCH")
    rows: List[Tuple[int, Tuple[str, ...]]] = []
    previous: Optional[int] = None
    for index, line in enumerate(lines[1:]):
        fields = line.split(",")
        if len(fields) != 7:
            raise ContractError(f"IMU_CSV_COLUMN_COUNT:{index}")
        try:
            stamp = int(fields[0])
            numeric = [float(field) for field in fields[1:]]
        except ValueError as error:
            raise ContractError(f"IMU_CSV_NUMERIC_INVALID:{index}") from error
        if not all(math.isfinite(value) for value in numeric):
            raise ContractError(f"IMU_CSV_NONFINITE:{index}")
        if previous is not None and stamp <= previous:
            raise ContractError(f"IMU_CSV_NON_MONOTONIC:{index}")
        rows.append((stamp, tuple(fields[1:])))
        previous = stamp
    if len(rows) != contract.source_imu_count:
        raise ContractError(f"IMU_CSV_SOURCE_COUNT_MISMATCH:{len(rows)}")

    raw_stamps = [row[0] for row in rows]
    first_cut = selected_camera[0][0] - contract.imu_shift_ns
    last_cut = selected_camera[-1][0] - contract.imu_shift_ns
    first_index = bisect.bisect_right(raw_stamps, first_cut) - 1
    last_index = bisect.bisect_left(raw_stamps, last_cut)
    if (first_index, last_index) != (contract.imu_first_index, contract.imu_last_index):
        raise ContractError(f"IMU_SELECTION_INDEX_MISMATCH:{first_index}:{last_index}")
    selected = rows[first_index : last_index + 1]
    if len(selected) != contract.imu_count:
        raise ContractError("IMU_SELECTION_COUNT_MISMATCH")
    if selected[0][0] != contract.imu_first_raw_ns:
        raise ContractError("IMU_FIRST_RAW_TIMESTAMP_MISMATCH")
    if selected[-1][0] != contract.imu_last_raw_ns:
        raise ContractError("IMU_LAST_RAW_TIMESTAMP_MISMATCH")
    return rows, selected


def camera_times_bytes(selected: Sequence[Tuple[int, str]]) -> bytes:
    return ("\n".join(str(stamp) for stamp, _ in selected) + "\n").encode("ascii")


def camera_csv_bytes(selected: Sequence[Tuple[int, str]]) -> bytes:
    lines = [CAMERA_OUTPUT_CSV_HEADER]
    lines.extend(f"{stamp},{stamp}.png" for stamp, _ in selected)
    return ("\n".join(lines) + "\n").encode("ascii")


def imu_csv_bytes(
    selected: Sequence[Tuple[int, Tuple[str, ...]]], shift_ns: int
) -> bytes:
    lines = [IMU_CSV_HEADER]
    lines.extend(
        str(raw_stamp + shift_ns) + "," + ",".join(measurements)
        for raw_stamp, measurements in selected
    )
    payload = "\n".join(lines).encode("utf-8")
    if payload.endswith(b"\n"):
        raise AssertionError("IMU output must not end in a newline")
    return payload


def validate_imu_bracket(
    imu_payload: bytes, camera_rows: Sequence[Tuple[int, str]], contract: MaterializationContract
) -> Dict[str, Any]:
    lines = imu_payload.decode("utf-8").splitlines()
    output_stamps = [int(line.split(",", 1)[0]) for line in lines[1:]]
    if len(output_stamps) != contract.imu_count:
        raise ContractError("OUTPUT_IMU_COUNT_MISMATCH")
    if any(current <= previous for previous, current in zip(output_stamps, output_stamps[1:])):
        raise ContractError("OUTPUT_IMU_NON_MONOTONIC")
    camera_first = camera_rows[0][0]
    camera_last = camera_rows[-1][0]
    if not (output_stamps[0] <= camera_first < output_stamps[1]):
        raise ContractError("OUTPUT_IMU_FIRST_READER_BRACKET_MISMATCH")
    if not (output_stamps[-2] <= camera_last < output_stamps[-1]):
        raise ContractError("OUTPUT_IMU_LAST_READER_BRACKET_MISMATCH")
    expected = (
        contract.imu_first_output_ns,
        contract.imu_second_output_ns,
        contract.imu_penultimate_output_ns,
        contract.imu_last_output_ns,
    )
    observed = (
        output_stamps[0],
        output_stamps[1],
        output_stamps[-2],
        output_stamps[-1],
    )
    if observed != expected:
        raise ContractError(f"OUTPUT_IMU_ENDPOINTS_MISMATCH:{observed}")
    return {
        "strictly_monotonic": True,
        "reader_bracket_rule": (
            "imu[0] <= cam[0] < imu[1] and imu[-2] <= cam[-1] < imu[-1]"
        ),
        "first_two_output_ns": list(observed[:2]),
        "last_two_output_ns": list(observed[2:]),
        "first_camera_ns": camera_first,
        "last_camera_ns": camera_last,
    }


def validate_png(payload: bytes, contract: MaterializationContract) -> Dict[str, Any]:
    signature = b"\x89PNG\r\n\x1a\n"
    if not payload.startswith(signature):
        raise ContractError("PNG_SIGNATURE_MISMATCH")
    position = len(signature)
    width = height = bit_depth = color_type = None
    compression = filtering = interlace = None
    chunks = 0
    idat: List[bytes] = []
    saw_iend = False
    while position < len(payload):
        if position + 12 > len(payload):
            raise ContractError("PNG_TRUNCATED_CHUNK")
        length = struct.unpack(">I", payload[position : position + 4])[0]
        end = position + 12 + length
        if end > len(payload):
            raise ContractError("PNG_CHUNK_LENGTH_OUT_OF_RANGE")
        chunk_type = payload[position + 4 : position + 8]
        chunk_data = payload[position + 8 : position + 8 + length]
        expected_crc = struct.unpack(">I", payload[position + 8 + length : end])[0]
        observed_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if observed_crc != expected_crc:
            raise ContractError(f"PNG_CHUNK_CRC_MISMATCH:{chunk_type!r}")
        chunks += 1
        if chunk_type == b"IHDR":
            if chunks != 1 or length != 13:
                raise ContractError("PNG_IHDR_POSITION_OR_SIZE_MISMATCH")
            (
                width,
                height,
                bit_depth,
                color_type,
                compression,
                filtering,
                interlace,
            ) = struct.unpack(">IIBBBBB", chunk_data)
        elif chunk_type == b"IDAT":
            idat.append(chunk_data)
        elif chunk_type == b"IEND":
            if length != 0:
                raise ContractError("PNG_IEND_SIZE_MISMATCH")
            saw_iend = True
            position = end
            break
        position = end
    if not saw_iend or position != len(payload):
        raise ContractError("PNG_IEND_OR_TRAILING_BYTES_MISMATCH")
    if (width, height) != (contract.width, contract.height):
        raise ContractError(f"PNG_DIMENSION_MISMATCH:{width}x{height}")
    if (bit_depth, color_type) != (contract.png_bit_depth, contract.png_color_type):
        raise ContractError(f"PNG_SCHEMA_MISMATCH:{bit_depth}:{color_type}")
    if (compression, filtering, interlace) != (0, 0, 0):
        raise ContractError("PNG_METHOD_OR_INTERLACE_MISMATCH")
    if not idat:
        raise ContractError("PNG_IDAT_MISSING")
    try:
        scanlines = zlib.decompress(b"".join(idat))
    except zlib.error as error:
        raise ContractError("PNG_IDAT_DECOMPRESSION_FAILED") from error
    expected_scanline_bytes = contract.height * (contract.width + 1)
    if len(scanlines) != expected_scanline_bytes:
        raise ContractError(f"PNG_SCANLINE_SIZE_MISMATCH:{len(scanlines)}")
    if any(scanlines[row * (contract.width + 1)] > 4 for row in range(contract.height)):
        raise ContractError("PNG_FILTER_TYPE_INVALID")
    return {
        "width": width,
        "height": height,
        "bit_depth": bit_depth,
        "color_type": color_type,
        "chunk_count": chunks,
        "chunk_crc_all_valid": True,
        "idat_decompressed": True,
    }


def stream_selected_images(
    archive: Path,
    selected_camera: Sequence[Tuple[int, str]],
    staging: Path,
    contract: MaterializationContract,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    by_name = {name: (index, stamp) for index, (stamp, name) in enumerate(selected_camera)}
    if len(by_name) != len(selected_camera):
        raise ContractError("SELECTED_CAMERA_FILENAME_DUPLICATE")
    seen: Set[str] = set()
    output_rows: List[Dict[str, Any]] = []
    source_rows: List[Dict[str, Any]] = []
    image_directory = staging / "mav0" / "cam0" / "data"
    image_directory.mkdir(parents=True, exist_ok=False)

    try:
        with tarfile.open(str(archive), "r|gz") as tar:
            for member in tar:
                if not member.name.startswith(contract.image_member_prefix):
                    continue
                filename = member.name[len(contract.image_member_prefix) :]
                selected = by_name.get(filename)
                if selected is None:
                    continue
                if filename in seen:
                    raise ContractError(f"SELECTED_IMAGE_MEMBER_DUPLICATE:{filename}")
                if not member.isreg() or member.issym() or member.islnk():
                    raise ContractError(f"SELECTED_IMAGE_MEMBER_NOT_REGULAR:{filename}")
                extracted = tar.extractfile(member)
                if extracted is None:
                    raise ContractError(f"SELECTED_IMAGE_MEMBER_UNREADABLE:{filename}")
                payload = extracted.read()
                if len(payload) != member.size:
                    raise ContractError(f"SELECTED_IMAGE_TAR_SIZE_MISMATCH:{filename}")
                png = validate_png(payload, contract)
                relative_index, stamp = selected
                output_relative = f"mav0/cam0/data/{stamp}.png"
                # Closing each image makes its complete bytes visible to the
                # subsequent independent audit.  Per-image fsync would issue
                # 1,801 synchronous flushes and is intentionally avoided;
                # generated indices/manifest and all directories are fsynced
                # before the one-shot directory publication.
                write_exclusive_bytes(staging / output_relative, payload, durable=False)
                file_row = identity_bytes(output_relative, payload)
                source_row = dict(file_row)
                source_row["path"] = member.name
                output_rows.append(
                    {
                        **file_row,
                        "source_index": contract.camera_start_index + relative_index,
                        "source_member": member.name,
                        "camera_timestamp_ns": stamp,
                        "png": png,
                        "canonical_member_bytes_preserved": True,
                    }
                )
                source_rows.append(source_row)
                seen.add(filename)
    except (tarfile.TarError, EOFError, OSError, zlib.error) as error:
        raise ContractError(f"SOURCE_TAR_STREAM_INTEGRITY_ERROR:{type(error).__name__}") from error

    missing = sorted(set(by_name) - seen)
    if missing:
        raise ContractError(f"SELECTED_IMAGE_MEMBERS_MISSING:{missing[:3]}:{len(missing)}")
    if len(output_rows) != contract.camera_count:
        raise ContractError("SELECTED_IMAGE_OUTPUT_COUNT_MISMATCH")
    output_rows.sort(key=lambda row: int(row["source_index"]))
    source_rows.sort(key=lambda row: str(row["path"]))
    return output_rows, source_rows


def enforce_expected_aggregate(
    observed: Mapping[str, Any], expected_sha: Optional[str], expected_crc: Optional[str], label: str
) -> None:
    if expected_sha is not None and observed["sha256"] != expected_sha:
        raise ContractError(f"{label}_SHA256_MISMATCH:{observed['sha256']}")
    if expected_crc is not None and observed["crc32"] != expected_crc:
        raise ContractError(f"{label}_CRC32_MISMATCH:{observed['crc32']}")


def prepare_metadata(
    selector_freeze: Path,
    source_archive: Path,
    contract: MaterializationContract,
) -> Dict[str, Any]:
    selector = validate_selector(selector_freeze)
    source = validate_source_archive(source_archive, contract)
    image_payload, image_member = read_pinned_member(
        source_archive, contract.image_csv_member, contract.image_csv_pin, "IMAGE_CSV"
    )
    imu_payload, imu_member = read_pinned_member(
        source_archive, contract.imu_csv_member, contract.imu_csv_pin, "IMU_CSV"
    )
    _, selected_camera = parse_camera_rows(image_payload, contract)
    _, selected_imu = parse_imu_rows(imu_payload, selected_camera, contract)
    times_payload = camera_times_bytes(selected_camera)
    camera_csv_payload = camera_csv_bytes(selected_camera)
    output_imu_payload = imu_csv_bytes(selected_imu, contract.imu_shift_ns)
    times_identity = identity_bytes("cam0_times.txt", times_payload)
    camera_csv_identity = identity_bytes("mav0/cam0/data.csv", camera_csv_payload)
    imu_identity = identity_bytes("mav0/imu0/data.csv", output_imu_payload)
    require_pin(times_identity, contract.times_pin, "CAM0_TIMES")
    require_pin(camera_csv_identity, contract.camera_csv_pin, "CAM0_DATA_CSV")
    require_pin(imu_identity, contract.imu_output_pin, "IMU0_DATA_CSV")
    bracket = validate_imu_bracket(output_imu_payload, selected_camera, contract)
    return {
        "selector": selector,
        "source": source,
        "source_members": {"camera_csv": image_member, "imu_csv": imu_member},
        "selected_camera": selected_camera,
        "selected_imu": selected_imu,
        "times_payload": times_payload,
        "camera_csv_payload": camera_csv_payload,
        "imu_payload": output_imu_payload,
        "generated_identities": {
            "cam0_times": times_identity,
            "cam0_data_csv": camera_csv_identity,
            "imu0_data_csv": imu_identity,
        },
        "imu_bracket": bracket,
    }


def build_manifest(
    metadata: Mapping[str, Any],
    image_rows: Sequence[Mapping[str, Any]],
    source_image_rows: Sequence[Mapping[str, Any]],
    payload_identity: Mapping[str, Any],
    source_image_identity: Mapping[str, Any],
    renamed_image_identity: Mapping[str, Any],
    output_root: Path,
    contract: MaterializationContract,
) -> Dict[str, Any]:
    chunk_histogram: Dict[str, int] = {}
    for row in image_rows:
        key = str(row["png"]["chunk_count"])
        chunk_histogram[key] = chunk_histogram.get(key, 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_PREPARATION_ONLY",
        "output_root": str(output_root.resolve(strict=False)),
        "selector_freeze": metadata["selector"],
        "source": {
            **metadata["source"],
            "members": metadata["source_members"],
            "gzip_stream_fully_consumed_and_crc_checked": True,
        },
        "selection": {
            "dataset_family": "aqualoc_harbor",
            "sequence_id": "H03",
            "camera_indices_inclusive": [
                contract.camera_start_index,
                contract.camera_end_index,
            ],
            "camera_count": contract.camera_count,
            "camera_header_ns_inclusive": [
                contract.camera_first_ns,
                contract.camera_last_ns,
            ],
            "preroll_camera_indices_half_open": [1800, 2700],
            "score_camera_indices_inclusive": [2700, 3600],
            "imu_source_indices_inclusive_zero_based": [
                contract.imu_first_index,
                contract.imu_last_index,
            ],
            "imu_count": contract.imu_count,
            "imu_shift_ns": contract.imu_shift_ns,
            "imu_time_transform": "output_ns=raw_ns+40380655",
        },
        "camera": {
            "copy_policy": "canonical tar member PNG bytes copied unchanged",
            "renamed_to": "mav0/cam0/data/<camera_timestamp_ns>.png",
            "count": len(image_rows),
            "total_bytes": sum(int(row["size_bytes"]) for row in image_rows),
            "width": contract.width,
            "height": contract.height,
            "bit_depth": contract.png_bit_depth,
            "color_type": contract.png_color_type,
            "png_chunk_crc_all_valid": True,
            "png_idat_all_decompressed": True,
            "png_chunk_count_histogram": chunk_histogram,
            "source_member_inventory_identity": source_image_identity,
            "renamed_output_inventory_identity": renamed_image_identity,
            "files": list(image_rows),
        },
        "generated_files": metadata["generated_identities"],
        "imu": {
            "source_header": IMU_CSV_HEADER,
            "column_order": [
                "timestamp_ns",
                "gyro_x_rad_s",
                "gyro_y_rad_s",
                "gyro_z_rad_s",
                "acc_x_m_s2",
                "acc_y_m_s2",
                "acc_z_m_s2",
            ],
            "measurement_tokens_preserved": True,
            "axis_transform": "none; H03/Harbor T_i_b is identity",
            "final_newline": False,
            "bracket_audit": metadata["imu_bracket"],
        },
        "payload_identity_excluding_manifest": payload_identity,
        "payload_file_count_excluding_manifest": len(image_rows) + 3,
        "claims": {
            "runner_created": False,
            "start_claim_created": False,
            "hfnet_started": False,
            "vins_started": False,
            "detector_started": False,
            "evaluator_started": False,
            "trajectory_produced": False,
            "scientific_comparison_produced": False,
        },
    }


def materialize(
    selector_freeze: Path,
    source_archive: Path,
    output_root: Path,
    contract: MaterializationContract = PRODUCTION_CONTRACT,
) -> Dict[str, Any]:
    metadata = prepare_metadata(selector_freeze, source_archive, contract)
    with atomic_directory(output_root) as staging:
        image_rows, source_image_rows = stream_selected_images(
            source_archive,
            metadata["selected_camera"],
            staging,
            contract,
        )
        image_total = sum(int(row["size_bytes"]) for row in image_rows)
        if (
            contract.expected_image_total_bytes is not None
            and image_total != contract.expected_image_total_bytes
        ):
            raise ContractError(f"SELECTED_IMAGE_TOTAL_SIZE_MISMATCH:{image_total}")

        source_image_identity = aggregate_identities(source_image_rows)
        renamed_image_identity = aggregate_identities(image_rows)
        enforce_expected_aggregate(
            source_image_identity,
            contract.expected_source_image_inventory_sha256,
            contract.expected_source_image_inventory_crc32,
            "SOURCE_IMAGE_INVENTORY",
        )
        enforce_expected_aggregate(
            renamed_image_identity,
            contract.expected_renamed_image_inventory_sha256,
            contract.expected_renamed_image_inventory_crc32,
            "RENAMED_IMAGE_INVENTORY",
        )

        generated = metadata["generated_identities"]
        write_exclusive_bytes(staging / "cam0_times.txt", metadata["times_payload"])
        write_exclusive_bytes(staging / "mav0/cam0/data.csv", metadata["camera_csv_payload"])
        write_exclusive_bytes(staging / "mav0/imu0/data.csv", metadata["imu_payload"])

        payload_rows: List[Mapping[str, Any]] = list(image_rows)
        payload_rows.extend(
            [generated["cam0_times"], generated["cam0_data_csv"], generated["imu0_data_csv"]]
        )
        payload_identity = aggregate_identities(payload_rows)
        enforce_expected_aggregate(
            payload_identity,
            contract.expected_payload_sha256,
            contract.expected_payload_crc32,
            "PAYLOAD_IDENTITY",
        )
        manifest = build_manifest(
            metadata,
            image_rows,
            source_image_rows,
            payload_identity,
            source_image_identity,
            renamed_image_identity,
            output_root,
            contract,
        )
        write_exclusive_bytes(
            staging / "materialization_manifest.json", canonical_json(manifest)
        )
        for directory in (
            staging / "mav0/cam0/data",
            staging / "mav0/cam0",
            staging / "mav0/imu0",
            staging / "mav0",
            staging,
        ):
            fsync_directory(directory)
    return manifest


def preflight_result(
    selector_freeze: Path,
    source_archive: Path,
    output_root: Path,
    contract: MaterializationContract = PRODUCTION_CONTRACT,
) -> Dict[str, Any]:
    if output_root.exists() or output_root.is_symlink():
        raise ContractError(f"NO_CLOBBER_OUTPUT_EXISTS:{output_root}")
    metadata = prepare_metadata(selector_freeze, source_archive, contract)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PREFLIGHT_READY_PREPARATION_ONLY",
        "selector_freeze": metadata["selector"],
        "source": metadata["source"],
        "output_root": str(output_root.resolve(strict=False)),
        "camera_count": contract.camera_count,
        "imu_count": contract.imu_count,
        "generated_identities": metadata["generated_identities"],
        "imu_bracket": metadata["imu_bracket"],
        "claims": {
            "output_created": False,
            "runner_created": False,
            "start_claim_created": False,
            "hfnet_started": False,
            "trajectory_produced": False,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("preflight", "materialize"), default="preflight")
    parser.add_argument("--selector-freeze", type=Path, default=DEFAULT_SELECTOR_FREEZE)
    parser.add_argument("--source-archive", type=Path, default=DEFAULT_SOURCE_ARCHIVE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.action == "materialize":
            result = materialize(
                args.selector_freeze,
                args.source_archive,
                args.output_root,
            )
        else:
            result = preflight_result(
                args.selector_freeze,
                args.source_archive,
                args.output_root,
            )
        return_code = 0
    except ContractError as error:
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "INTEGRITY_ERROR",
            "errors": [str(error)],
            "claims": {
                "runner_created": False,
                "start_claim_created": False,
                "hfnet_started": False,
                "vins_started": False,
                "detector_started": False,
                "evaluator_started": False,
                "trajectory_produced": False,
            },
        }
        return_code = 2
    except Exception as error:  # Fail closed while retaining the diagnostic class.
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "INTEGRITY_ERROR",
            "errors": [f"UNEXPECTED_{type(error).__name__}:{error}"],
            "claims": {
                "runner_created": False,
                "start_claim_created": False,
                "hfnet_started": False,
                "vins_started": False,
                "detector_started": False,
                "evaluator_started": False,
                "trajectory_produced": False,
            },
        }
        return_code = 2
    sys.stdout.buffer.write(canonical_json(result))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
