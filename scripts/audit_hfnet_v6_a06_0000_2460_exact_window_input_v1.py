#!/usr/bin/env python3
"""Independently audit the prepared A06 0000..2460 HFNet input tree.

The auditor does not import the A06 materializer.  It re-hashes every output,
validates every PNG container and decoded scanline envelope, checks the exact
camera/IMU reader brackets, and streams the pinned raw archive independently
to prove byte preservation.  It never starts HFNet, ROS, VINS, or an evaluator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys
import tarfile
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple
import zlib


ROOT = Path(__file__).resolve().parents[1]
INPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_v6_a06_exact_window_v1/"
    "aqualoc_archaeology_a06_0000_2460"
)
SOURCE_ARCHIVE = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences/archaeo_sequence_6_raw_data.tar.gz"
)
CONFIG = ROOT / "configs/published_baselines/hfnet_slam_aqualoc_a06_0000_2460_exact_window_v1.yaml"
SELECTOR = ROOT / "papers/hfnet_v6_a06_0000_2460_exact_window_selector_freeze_v1.json"
IMAGE_PREFIX = "raw_data/images_sequence_6/"

SCHEMA_VERSION = "aqua-fe-hfnet-v6-a06-0000-2460-independent-input-audit-v1"
SOURCE_SIZE = 758_010_849
SOURCE_SHA256 = "02795e92984321d61cbf7ee5555cf2b4ee344e2263bb7dcf37ffd94cb2472bd9"
SELECTOR_SIZE = 8_273
SELECTOR_SHA256 = "1d0937320c087cb73911db7a5c55d8cde40d0bf0c800c4cf42aba68342b72b15"
CONFIG_SIZE = 2_037
CONFIG_SHA256 = "37ec8f0f274818b3a8f952a535d9be87dae0f8d0436ce05503381791ace69db6"

CAMERA_FIRST_NS = 1_542_883_311_780_022_336
CAMERA_LAST_NS = 1_542_883_434_765_650_624
CAMERA_COUNT = 2_461
IMU_COUNT = 24_581
IMU_ENDPOINTS = (
    1_542_883_311_777_960_896,
    1_542_883_311_783_094_496,
    1_542_883_434_762_137_952,
    1_542_883_434_767_231_456,
)
IMU_HEADER = (
    "#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],"
    "w_RS_S_z [rad s^-1],a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],"
    "a_RS_S_z [m s^-2]"
)
EXPECTED_GENERATED = {
    "cam0_times.txt": (49_220, "7b81913749fe5b296aae4280531e6e26cda3349791e7331befdb72eb6de7f861", "ab59a657"),
    "mav0/cam0/data.csv": (108_309, "91ccea67a551f15090e6136dd754fa6cae00eeece798b3b025c0c1209928eb23", "f5fd3504"),
    "mav0/imu0/data.csv": (2_749_671, "2e5d9a78192d86d6de55a46f9c29a1f639536e114702b5f9b0480c070d0a9388", "40a84fd6"),
}
EXPECTED_IMAGE_BYTES = 544_207_164
EXPECTED_IMAGE_INVENTORY_SHA256 = "1dee6b53ef749584f218316701f40fbddbcf4be3fd17e24cae1f1f3a12073193"
EXPECTED_IMAGE_INVENTORY_CRC32 = "03c2d990"
EXPECTED_PAYLOAD_SHA256 = "a03a119b98ec4c3a862905692325133310acae6d268cabaf7369262803b36673"
EXPECTED_PAYLOAD_CRC32 = "489e46af"


class AuditError(RuntimeError):
    pass


def hash_file(path: Path, relative: str) -> Dict[str, Any]:
    digest = hashlib.sha256()
    crc = 0
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
            crc = zlib.crc32(block, crc)
            size += len(block)
    return {"path": relative, "size_bytes": size, "sha256": digest.hexdigest(), "crc32": f"{crc & 0xffffffff:08x}"}


def aggregate(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    digest = hashlib.sha256()
    crc = 0
    for row in sorted(rows, key=lambda value: str(value["path"])):
        encoded = f"{row['path']}\0{row['size_bytes']}\0{row['sha256']}\0{row['crc32']}\n".encode()
        digest.update(encoded)
        crc = zlib.crc32(encoded, crc)
    return {"sha256": digest.hexdigest(), "crc32": f"{crc & 0xffffffff:08x}"}


def require_identity(path: Path, size: int, digest: str, label: str) -> Dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise AuditError(f"{label}_MISSING_OR_NOT_REGULAR")
    observed = hash_file(path, str(path.resolve()))
    if observed["size_bytes"] != size or observed["sha256"] != digest:
        raise AuditError(f"{label}_IDENTITY_MISMATCH")
    return observed


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
            raise AuditError("PNG_CHUNK_CRC_MISMATCH")
        chunk_count += 1
        if kind == b"IHDR":
            schema = struct.unpack(">IIBBBBB", data)
        elif kind == b"IDAT":
            idat.append(data)
        elif kind == b"IEND":
            position = end
            ended = True
            break
        position = end
    if not ended or position != len(payload):
        raise AuditError("PNG_END_MISMATCH")
    if schema != (968, 608, 8, 0, 0, 0, 0):
        raise AuditError(f"PNG_SCHEMA_MISMATCH:{schema}")
    try:
        decoded = zlib.decompress(b"".join(idat))
    except zlib.error as error:
        raise AuditError("PNG_IDAT_DECODE_FAILED") from error
    if len(decoded) != 608 * 969:
        raise AuditError("PNG_SCANLINE_SIZE_MISMATCH")
    if any(decoded[row * 969] > 4 for row in range(608)):
        raise AuditError("PNG_FILTER_INVALID")
    return {"chunk_count": chunk_count, "chunk_crc_valid": True, "idat_decoded": True}


def parse_camera(root: Path) -> Tuple[List[int], List[Dict[str, Any]], Dict[str, int]]:
    payload = (root / "cam0_times.txt").read_bytes()
    if not payload.endswith(b"\n"):
        raise AuditError("CAM0_TIMES_FINAL_NEWLINE_MISSING")
    try:
        stamps = [int(line) for line in payload.decode("ascii").splitlines()]
    except ValueError as error:
        raise AuditError("CAM0_TIMES_INVALID") from error
    if len(stamps) != CAMERA_COUNT or stamps[0] != CAMERA_FIRST_NS or stamps[-1] != CAMERA_LAST_NS:
        raise AuditError("CAM0_TIMES_ENDPOINT_OR_COUNT_MISMATCH")
    if any(current <= previous for previous, current in zip(stamps, stamps[1:])):
        raise AuditError("CAM0_TIMES_NON_MONOTONIC")
    lines = (root / "mav0/cam0/data.csv").read_text(encoding="ascii").splitlines()
    if not lines or lines[0] != "#timestamp [ns],filename":
        raise AuditError("CAM0_DATA_CSV_HEADER_MISMATCH")
    if lines[1:] != [f"{stamp},{stamp}.png" for stamp in stamps]:
        raise AuditError("CAM0_DATA_CSV_MAPPING_MISMATCH")
    rows: List[Dict[str, Any]] = []
    histogram: Dict[str, int] = {}
    for stamp in stamps:
        relative = f"mav0/cam0/data/{stamp}.png"
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise AuditError(f"IMAGE_MISSING_OR_NOT_REGULAR:{stamp}")
        image = path.read_bytes()
        png = validate_png(image)
        key = str(png["chunk_count"])
        histogram[key] = histogram.get(key, 0) + 1
        rows.append({"path": relative, "size_bytes": len(image), "sha256": hashlib.sha256(image).hexdigest(), "crc32": f"{zlib.crc32(image) & 0xffffffff:08x}"})
    return stamps, rows, histogram


def parse_imu(root: Path, camera_stamps: Sequence[int]) -> Dict[str, Any]:
    payload = (root / "mav0/imu0/data.csv").read_bytes()
    if payload.endswith(b"\n"):
        raise AuditError("IMU_FINAL_NEWLINE_PRESENT")
    lines = payload.decode("utf-8").splitlines()
    if not lines or lines[0] != IMU_HEADER:
        raise AuditError("IMU_HEADER_MISMATCH")
    stamps: List[int] = []
    for index, line in enumerate(lines[1:]):
        fields = line.split(",")
        if len(fields) != 7:
            raise AuditError(f"IMU_COLUMN_COUNT:{index}")
        try:
            stamps.append(int(fields[0]))
            values = [float(value) for value in fields[1:]]
        except ValueError as error:
            raise AuditError(f"IMU_NUMERIC_INVALID:{index}") from error
        if not all(math.isfinite(value) for value in values):
            raise AuditError(f"IMU_NONFINITE:{index}")
    if len(stamps) != IMU_COUNT or any(current <= previous for previous, current in zip(stamps, stamps[1:])):
        raise AuditError("IMU_COUNT_OR_ORDER_MISMATCH")
    endpoints = (stamps[0], stamps[1], stamps[-2], stamps[-1])
    if endpoints != IMU_ENDPOINTS:
        raise AuditError("IMU_ENDPOINT_MISMATCH")
    if not (stamps[0] <= camera_stamps[0] < stamps[1] and stamps[-2] <= camera_stamps[-1] < stamps[-1]):
        raise AuditError("IMU_CAMERA_READER_BRACKET_MISMATCH")
    return {"count": len(stamps), "strictly_monotonic": True, "endpoints_ns": list(endpoints), "reader_bracket_valid": True, "final_newline": False}


def check_generated(root: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for relative, expected in EXPECTED_GENERATED.items():
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise AuditError(f"GENERATED_MISSING:{relative}")
        observed = hash_file(path, relative)
        if (observed["size_bytes"], observed["sha256"], observed["crc32"]) != expected:
            raise AuditError(f"GENERATED_IDENTITY_MISMATCH:{relative}")
        rows.append(observed)
    return rows


def compare_to_source(source: Path, output_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    expected = {f"frame{index:06d}.png": output_rows[index] for index in range(CAMERA_COUNT)}
    seen: Set[str] = set()
    try:
        with tarfile.open(str(source), "r|gz") as tar:
            for member in tar:
                if not member.name.startswith(IMAGE_PREFIX):
                    continue
                name = member.name[len(IMAGE_PREFIX) :]
                output = expected.get(name)
                if output is None:
                    continue
                if name in seen or not member.isreg() or member.issym() or member.islnk():
                    raise AuditError(f"SOURCE_IMAGE_MEMBER_INVALID:{name}")
                extracted = tar.extractfile(member)
                if extracted is None:
                    raise AuditError(f"SOURCE_IMAGE_UNREADABLE:{name}")
                payload = extracted.read()
                observed = (len(payload), hashlib.sha256(payload).hexdigest(), f"{zlib.crc32(payload) & 0xffffffff:08x}")
                expected_identity = (output["size_bytes"], output["sha256"], output["crc32"])
                if observed != expected_identity:
                    raise AuditError(f"SOURCE_OUTPUT_BYTES_DIFFER:{name}")
                seen.add(name)
    except (tarfile.TarError, EOFError, OSError, zlib.error) as error:
        raise AuditError(f"SOURCE_STREAM_INTEGRITY_ERROR:{type(error).__name__}") from error
    if seen != set(expected):
        raise AuditError(f"SOURCE_IMAGE_SET_MISMATCH:{len(seen)}")
    return {"source_members_compared": len(seen), "all_output_png_bytes_identical_to_canonical_source_members": True, "source_gzip_stream_fully_consumed_and_crc_checked": True}


def audit(root: Path, source: Path, config: Path, selector: Path) -> Dict[str, Any]:
    root, source, config, selector = map(Path, (root, source, config, selector))
    if root.is_symlink() or not root.is_dir():
        raise AuditError("INPUT_ROOT_MISSING_OR_NOT_DIRECTORY")
    source_identity = require_identity(source, SOURCE_SIZE, SOURCE_SHA256, "SOURCE")
    selector_identity = require_identity(selector, SELECTOR_SIZE, SELECTOR_SHA256, "SELECTOR")
    config_identity = require_identity(config, CONFIG_SIZE, CONFIG_SHA256, "CONFIG")
    stamps, image_rows, histogram = parse_camera(root)
    generated_rows = check_generated(root)
    imu = parse_imu(root, stamps)
    image_identity = aggregate(image_rows)
    if sum(int(row["size_bytes"]) for row in image_rows) != EXPECTED_IMAGE_BYTES:
        raise AuditError("IMAGE_TOTAL_BYTES_MISMATCH")
    if image_identity != {"sha256": EXPECTED_IMAGE_INVENTORY_SHA256, "crc32": EXPECTED_IMAGE_INVENTORY_CRC32}:
        raise AuditError("IMAGE_INVENTORY_IDENTITY_MISMATCH")
    payload_identity = aggregate(list(image_rows) + generated_rows)
    if payload_identity != {"sha256": EXPECTED_PAYLOAD_SHA256, "crc32": EXPECTED_PAYLOAD_CRC32}:
        raise AuditError("PAYLOAD_IDENTITY_MISMATCH")
    expected_paths = {str(row["path"]) for row in image_rows + generated_rows}
    expected_paths.add("materialization_manifest.json")
    observed_paths: Set[str] = set()
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if path.is_symlink() or not path.is_file():
            raise AuditError(f"OUTPUT_NONREGULAR:{path}")
        observed_paths.add(path.relative_to(root).as_posix())
    if observed_paths != expected_paths:
        raise AuditError("OUTPUT_FILE_SET_MISMATCH")
    source_comparison = compare_to_source(source, image_rows)
    manifest_path = root / "materialization_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "PASS_PREPARATION_ONLY" or manifest.get("schema_version") != "aqua-fe-hfnet-v6-a06-0000-2460-input-materialization-v1":
        raise AuditError("MANIFEST_STATUS_OR_SCHEMA_MISMATCH")
    if manifest.get("payload_identity_excluding_manifest") != {"algorithm": "sorted UTF-8 path\\0size\\0sha256\\0crc32\\n", "sha256": EXPECTED_PAYLOAD_SHA256, "crc32": EXPECTED_PAYLOAD_CRC32}:
        raise AuditError("MANIFEST_PAYLOAD_PIN_MISMATCH")
    if any(value is not False for value in manifest.get("claims", {}).values()):
        raise AuditError("MANIFEST_FORBIDDEN_CLAIM")
    selection = manifest.get("selection", {})
    if selection.get("camera_indices_inclusive") != [0, 2460] or selection.get("score_camera_indices_inclusive") != [2210, 2460] or selection.get("development_result_conditioned_selection") is not True:
        raise AuditError("MANIFEST_SELECTION_BOUNDARY_MISMATCH")
    config_text = config.read_text(encoding="utf-8")
    for required in ('Camera.type: "PinHole"', "Camera.width: 968", "Camera.height: 608", "IMU.NoiseGyro: 0.003", "IMU.NoiseAcc: 0.05", "IMU.GyroWalk: 0.0001", "IMU.AccWalk: 0.0015", "IMU.Frequency: 200.0", "Extractor.nFeatures: 675", "Extractor.threshold: 0.01", "loopClosing: 1"):
        if required not in config_text:
            raise AuditError(f"CONFIG_REQUIRED_PIN_MISSING:{required}")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_PREPARATION_ONLY_INDEPENDENT_AUDIT",
        "input_root": str(root.resolve()),
        "source": source_identity,
        "selector_freeze": selector_identity,
        "config": config_identity,
        "file_count_including_manifest": len(observed_paths),
        "payload_file_count_excluding_manifest": len(image_rows) + len(generated_rows),
        "camera": {"count": len(image_rows), "header_ns_inclusive": [stamps[0], stamps[-1]], "score_camera_indices_inclusive": [2210, 2460], "total_png_bytes": EXPECTED_IMAGE_BYTES, "schema": "968x608 8-bit grayscale non-interlaced PNG", "all_png_chunk_crc_valid": True, "all_png_idat_decoded": True, "chunk_count_histogram": histogram, "inventory_identity": image_identity, **source_comparison},
        "imu": imu,
        "generated_files": generated_rows,
        "payload_identity_excluding_manifest": payload_identity,
        "manifest": hash_file(manifest_path, "materialization_manifest.json"),
        "reporting_boundary": "development-only input preparation; no trajectory, accuracy, or comparison",
        "claims": {"runner_created": False, "start_claim_created": False, "hfnet_started": False, "vins_started": False, "detector_started": False, "evaluator_started": False, "trajectory_produced": False, "accuracy_measured": False, "scientific_comparison_produced": False},
    }


def canonical_json(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def write_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=INPUT_ROOT)
    parser.add_argument("--source-archive", type=Path, default=SOURCE_ARCHIVE)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--selector-freeze", type=Path, default=SELECTOR)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        result = audit(args.input_root, args.source_archive, args.config, args.selector_freeze)
        return_code = 0
    except Exception as error:
        result = {"schema_version": SCHEMA_VERSION, "status": "INTEGRITY_ERROR", "errors": [f"{type(error).__name__}:{error}"], "claims": {"hfnet_started": False, "trajectory_produced": False}}
        return_code = 2
    payload = canonical_json(result)
    if args.report is not None:
        write_exclusive(args.report, payload)
    sys.stdout.buffer.write(payload)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
