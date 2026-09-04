#!/usr/bin/env python3
"""Independently audit the prepared H03 Phase-F input tree.

This auditor intentionally does not import the materializer.  It re-hashes all
payloads, validates every PNG chunk CRC and decoded scanline envelope, checks
camera/IMU timestamps and reader brackets, and streams the canonical raw tar a
second time to prove that all 1,801 PNG outputs preserve source member bytes.
It never starts HFNet, VINS, a detector, or an evaluator.
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
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_v6_phase_f_fresh_underwater_v1/"
    "aqualoc_harbor_h03_1800_3600"
)
SOURCE_ARCHIVE = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/Harbor_sites_sequences/"
    "harbor_sequence_03_raw_data.tar.gz"
)
IMAGE_PREFIX = "raw_data/harbor_images_sequence_03/"
CONFIG = ROOT / "configs/published_baselines/hfnet_slam_aqualoc_h03_1800_3600_phase_f_v1.yaml"
SELECTOR = ROOT / "papers/hfnet_v6_phase_f_h03_1800_3600_selector_freeze_v1.json"

SCHEMA_VERSION = "aqua-fe-hfnet-v6-phase-f-h03-independent-input-audit-v1"
SOURCE_SIZE = 905_738_013
SOURCE_SHA256 = "6a4062a61498a108ade031ecff1cdf0818390212ff84882e922cc162ee5e54f1"
SELECTOR_SIZE = 12_536
SELECTOR_SHA256 = "ab7557db88d884e565d71a31a562e3e88c70eba6d8e643f22ca5b2bdd2d18269"
CONFIG_SIZE = 2_257
CONFIG_SHA256 = "3ed0e32354049edfaf7c42edaeed3baf7a25e994ec29fab3135b5edef053f5ab"

CAMERA_FIRST_NS = 1_523_966_922_643_979_137
CAMERA_LAST_NS = 1_523_967_012_680_410_986
CAMERA_COUNT = 1_801
IMU_COUNT = 17_999
IMU_ENDPOINTS = (
    1_523_966_922_642_896_766,
    1_523_966_922_647_928_935,
    1_523_967_012_677_636_392,
    1_523_967_012_682_667_184,
)
IMU_HEADER = (
    "#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],"
    "w_RS_S_z [rad s^-1],a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],"
    "a_RS_S_z [m s^-2]"
)
EXPECTED_GENERATED = {
    "cam0_times.txt": (36_020, "5732e74d12a720cbf7aa3b68cbf5ab189e3493bec7954271017bde7d54f5d92e", "8f95d70e"),
    "mav0/cam0/data.csv": (79_269, "02ddfd4c66ce1d05956a16790140f29abb43c47222ae5ea1faf47b66205bca6f", "420d7c09"),
    "mav0/imu0/data.csv": (2_058_198, "45edd79a4073f646813cc53d710ab5fd6a26a4b3acb927dfa18292dc6c377193", "a3016b12"),
}
EXPECTED_IMAGE_BYTES = 327_959_010
EXPECTED_IMAGE_INVENTORY_SHA256 = "bb1cf0238839c5899f4907845c3aac1c9e659ff0b1c1d65b6cfbad015238614a"
EXPECTED_IMAGE_INVENTORY_CRC32 = "8a0dd9e5"
EXPECTED_PAYLOAD_SHA256 = "afdfec7e12f9e80b3008f7e82ecbb25f9b16ff0716b9b0c4878a3af06b2061b4"
EXPECTED_PAYLOAD_CRC32 = "69365ded"


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
    return {
        "path": relative,
        "size_bytes": size,
        "sha256": digest.hexdigest(),
        "crc32": f"{crc & 0xFFFFFFFF:08x}",
    }


def aggregate(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    digest = hashlib.sha256()
    crc = 0
    for row in sorted(rows, key=lambda item: str(item["path"])):
        encoded = (
            f"{row['path']}\0{row['size_bytes']}\0{row['sha256']}\0{row['crc32']}\n"
        ).encode("utf-8")
        digest.update(encoded)
        crc = zlib.crc32(encoded, crc)
    return {"sha256": digest.hexdigest(), "crc32": f"{crc & 0xFFFFFFFF:08x}"}


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
        if (zlib.crc32(kind + data) & 0xFFFFFFFF) != expected_crc:
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
    if schema != (640, 512, 8, 0, 0, 0, 0):
        raise AuditError(f"PNG_SCHEMA_MISMATCH:{schema}")
    try:
        decoded = zlib.decompress(b"".join(idat))
    except zlib.error as error:
        raise AuditError("PNG_IDAT_DECODE_FAILED") from error
    if len(decoded) != 512 * 641:
        raise AuditError("PNG_SCANLINE_SIZE_MISMATCH")
    if any(decoded[row * 641] > 4 for row in range(512)):
        raise AuditError("PNG_FILTER_INVALID")
    return {"chunk_count": chunk_count, "chunk_crc_valid": True, "idat_decoded": True}


def parse_camera(root: Path) -> Tuple[List[int], List[Dict[str, Any]], Dict[str, int]]:
    times_path = root / "cam0_times.txt"
    times_payload = times_path.read_bytes()
    if not times_payload.endswith(b"\n"):
        raise AuditError("CAM0_TIMES_FINAL_NEWLINE_MISSING")
    try:
        stamps = [int(line) for line in times_payload.decode("ascii").splitlines()]
    except ValueError as error:
        raise AuditError("CAM0_TIMES_INVALID") from error
    if len(stamps) != CAMERA_COUNT or stamps[0] != CAMERA_FIRST_NS or stamps[-1] != CAMERA_LAST_NS:
        raise AuditError("CAM0_TIMES_ENDPOINT_OR_COUNT_MISMATCH")
    if any(current <= previous for previous, current in zip(stamps, stamps[1:])):
        raise AuditError("CAM0_TIMES_NON_MONOTONIC")

    csv_lines = (root / "mav0/cam0/data.csv").read_text(encoding="ascii").splitlines()
    if not csv_lines or csv_lines[0] != "#timestamp [ns],filename":
        raise AuditError("CAM0_DATA_CSV_HEADER_MISMATCH")
    expected_rows = [f"{stamp},{stamp}.png" for stamp in stamps]
    if csv_lines[1:] != expected_rows:
        raise AuditError("CAM0_DATA_CSV_MAPPING_MISMATCH")

    image_rows: List[Dict[str, Any]] = []
    histogram: Dict[str, int] = {}
    for stamp in stamps:
        relative = f"mav0/cam0/data/{stamp}.png"
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise AuditError(f"IMAGE_MISSING_OR_NOT_REGULAR:{stamp}")
        payload = path.read_bytes()
        png = validate_png(payload)
        key = str(png["chunk_count"])
        histogram[key] = histogram.get(key, 0) + 1
        image_rows.append(
            {
                "path": relative,
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "crc32": f"{zlib.crc32(payload) & 0xFFFFFFFF:08x}",
            }
        )
    return stamps, image_rows, histogram


def parse_imu(root: Path, stamps: Sequence[int]) -> Dict[str, Any]:
    path = root / "mav0/imu0/data.csv"
    payload = path.read_bytes()
    if payload.endswith(b"\n"):
        raise AuditError("IMU_FINAL_NEWLINE_PRESENT")
    lines = payload.decode("utf-8").splitlines()
    if not lines or lines[0] != IMU_HEADER:
        raise AuditError("IMU_HEADER_MISMATCH")
    output_stamps: List[int] = []
    for index, line in enumerate(lines[1:]):
        fields = line.split(",")
        if len(fields) != 7:
            raise AuditError(f"IMU_COLUMN_COUNT:{index}")
        try:
            output_stamps.append(int(fields[0]))
            values = [float(field) for field in fields[1:]]
        except ValueError as error:
            raise AuditError(f"IMU_NUMERIC_INVALID:{index}") from error
        if not all(math.isfinite(value) for value in values):
            raise AuditError(f"IMU_NONFINITE:{index}")
    if len(output_stamps) != IMU_COUNT:
        raise AuditError("IMU_COUNT_MISMATCH")
    if any(current <= previous for previous, current in zip(output_stamps, output_stamps[1:])):
        raise AuditError("IMU_NON_MONOTONIC")
    endpoints = (
        output_stamps[0], output_stamps[1], output_stamps[-2], output_stamps[-1]
    )
    if endpoints != IMU_ENDPOINTS:
        raise AuditError("IMU_ENDPOINT_MISMATCH")
    if not (output_stamps[0] <= stamps[0] < output_stamps[1]):
        raise AuditError("IMU_FIRST_BRACKET_MISMATCH")
    if not (output_stamps[-2] <= stamps[-1] < output_stamps[-1]):
        raise AuditError("IMU_LAST_BRACKET_MISMATCH")
    return {
        "count": len(output_stamps),
        "strictly_monotonic": True,
        "endpoints_ns": list(endpoints),
        "reader_bracket_valid": True,
        "final_newline": False,
    }


def compare_to_source(
    source: Path, stamps: Sequence[int], output_rows: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    expected: Dict[str, Mapping[str, Any]] = {
        f"frame{1800 + offset:06d}.png": output_rows[offset]
        for offset in range(CAMERA_COUNT)
    }
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
                observed = {
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "crc32": f"{zlib.crc32(payload) & 0xFFFFFFFF:08x}",
                }
                for key in observed:
                    if observed[key] != output[key]:
                        raise AuditError(f"SOURCE_OUTPUT_BYTES_DIFFER:{name}:{key}")
                seen.add(name)
    except (tarfile.TarError, EOFError, OSError, zlib.error) as error:
        raise AuditError(f"SOURCE_STREAM_INTEGRITY_ERROR:{type(error).__name__}") from error
    if seen != set(expected):
        raise AuditError(f"SOURCE_IMAGE_SET_MISMATCH:{len(seen)}")
    return {
        "source_members_compared": len(seen),
        "all_output_png_bytes_identical_to_canonical_source_members": True,
        "source_gzip_stream_fully_consumed_and_crc_checked": True,
    }


def check_generated(root: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for relative, expected in EXPECTED_GENERATED.items():
        path = root / relative
        observed = hash_file(path, relative)
        if (observed["size_bytes"], observed["sha256"], observed["crc32"]) != expected:
            raise AuditError(f"GENERATED_IDENTITY_MISMATCH:{relative}")
        rows.append(observed)
    return rows


def audit(root: Path, source: Path, config: Path, selector: Path) -> Dict[str, Any]:
    if root.is_symlink() or not root.is_dir():
        raise AuditError("INPUT_ROOT_MISSING_OR_NOT_DIRECTORY")
    source_identity = require_identity(source, SOURCE_SIZE, SOURCE_SHA256, "SOURCE")
    selector_identity = require_identity(selector, SELECTOR_SIZE, SELECTOR_SHA256, "SELECTOR")
    config_identity = require_identity(config, CONFIG_SIZE, CONFIG_SHA256, "CONFIG")

    stamps, image_rows, chunk_histogram = parse_camera(root)
    generated_rows = check_generated(root)
    imu = parse_imu(root, stamps)
    image_identity = aggregate(image_rows)
    if sum(int(row["size_bytes"]) for row in image_rows) != EXPECTED_IMAGE_BYTES:
        raise AuditError("IMAGE_TOTAL_BYTES_MISMATCH")
    if image_identity != {
        "sha256": EXPECTED_IMAGE_INVENTORY_SHA256,
        "crc32": EXPECTED_IMAGE_INVENTORY_CRC32,
    }:
        raise AuditError("IMAGE_INVENTORY_IDENTITY_MISMATCH")
    payload_identity = aggregate(list(image_rows) + generated_rows)
    if payload_identity != {
        "sha256": EXPECTED_PAYLOAD_SHA256,
        "crc32": EXPECTED_PAYLOAD_CRC32,
    }:
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
        raise AuditError(
            f"OUTPUT_FILE_SET_MISMATCH:extra={sorted(observed_paths-expected_paths)[:3]}:"
            f"missing={sorted(expected_paths-observed_paths)[:3]}"
        )

    source_comparison = compare_to_source(source, stamps, image_rows)
    manifest_path = root / "materialization_manifest.json"
    manifest_identity = hash_file(manifest_path, "materialization_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "PASS_PREPARATION_ONLY":
        raise AuditError("MANIFEST_STATUS_MISMATCH")
    if manifest.get("payload_identity_excluding_manifest", {}).get("sha256") != EXPECTED_PAYLOAD_SHA256:
        raise AuditError("MANIFEST_PAYLOAD_PIN_MISMATCH")
    claims = manifest.get("claims", {})
    forbidden_true = [key for key, value in claims.items() if value is not False]
    if forbidden_true:
        raise AuditError(f"MANIFEST_CLAIM_NOT_FALSE:{forbidden_true}")

    config_text = config.read_text(encoding="utf-8")
    for required in (
        'Camera.type: "KannalaBrandt8"',
        "IMU.NoiseGyro: 0.001",
        "IMU.NoiseAcc: 0.02",
        "IMU.GyroWalk: 0.00005",
        "IMU.AccWalk: 0.001",
        "IMU.Frequency: 200.0",
        "Extractor.nFeatures: 675",
        "Extractor.threshold: 0.01",
        "loopClosing: 1",
    ):
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
        "camera": {
            "count": len(image_rows),
            "header_ns_inclusive": [stamps[0], stamps[-1]],
            "total_png_bytes": sum(int(row["size_bytes"]) for row in image_rows),
            "schema": "640x512 8-bit grayscale non-interlaced PNG",
            "all_png_chunk_crc_valid": True,
            "all_png_idat_decoded": True,
            "chunk_count_histogram": chunk_histogram,
            "inventory_identity": image_identity,
            **source_comparison,
        },
        "imu": imu,
        "generated_files": generated_rows,
        "payload_identity_excluding_manifest": payload_identity,
        "manifest": manifest_identity,
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


def write_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def canonical_json(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n"
    ).encode("utf-8")


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
    except AuditError as error:
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "INTEGRITY_ERROR",
            "errors": [str(error)],
            "claims": {"hfnet_started": False, "trajectory_produced": False},
        }
        return_code = 2
    payload = canonical_json(result)
    if args.report is not None:
        write_exclusive(args.report, payload)
    sys.stdout.buffer.write(payload)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
