#!/usr/bin/env python3
"""Independently audit a prepared CIRS HFNet v6 cold-start input tree.

This module imports no materializer.  It independently hashes the source bag,
selector, configuration, and every output; compares every decoded output PNG
to the source ``mono8`` raster; rebuilds camera/IMU text payloads; validates
the official HFNet reader's IMU bracket; recomputes the published-body
extrinsic; and closes the output namespace.  It never starts HFNet or another
scientific process.
"""

from __future__ import annotations

import argparse
import bisect
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple
import zlib

import cv2
import numpy as np
import rosbag


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "aqua-fe-hfnet-v6-cirs-exact-window-coldstart-independent-input-audit-v1"
RUNNER_BINDING_SCHEMA = "aqua-fe-hfnet-v6-samehistory-input-audit-binding-v1"
MATERIALIZATION_SCHEMA = "aqua-fe-hfnet-v6-cirs-exact-window-coldstart-materialization-v1"
CONFIG = ROOT / "configs/published_baselines/hfnet_slam_cirs_cala_viuda_exact_window_coldstart_v1.yaml"
CONFIG_SIZE = 2391
CONFIG_SHA256 = "b6e93daf3ca06e3e29433fffa7eb037119b97261888395fe1d51fa2d7a218204"
DEFAULT_INPUT_PARENT = Path("/mnt/data/AQUA-FE_WS/datasets/hfnet_v6_cirs_exact_window_coldstart_v1")

IMAGE_TOPIC = "/cirs/camera/image_mono"
IMU_TOPIC = "/cirs/imu_xsens"
PROXY_TOPIC = "/cirs/odometry_gt"
EXPECTED_TOPICS = {IMAGE_TOPIC, IMU_TOPIC, PROXY_TOPIC}
CAMERA_CSV_HEADER = "#timestamp [ns],filename"
IMU_HEADER = (
    "#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],"
    "w_RS_S_z [rad s^-1],a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],"
    "a_RS_S_z [m s^-2]"
)

T_BODY_IMU_TRANSLATION = (0.1, 0.0, -0.16)
T_BODY_IMU_QUATERNION_XYZW = (
    0.7071067811865476,
    -0.7071067811865475,
    -4.329780281177466e-17,
    4.329780281177467e-17,
)
T_BODY_CAMERA_TRANSLATION = (0.26, 0.0, -0.02)
T_BODY_CAMERA_QUATERNION_XYZW = (0.0, 0.0, 0.7071067811865475, 0.7071067811865476)
EXPECTED_T_IMU_CAMERA = np.array(
    [
        [-1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, -0.16],
        [0.0, 0.0, -1.0, -0.14],
        [0.0, 0.0, 0.0, 1.0],
    ],
    dtype=np.float64,
)

CONFIG_TOKENS = (
    'Camera.type: "PinHole"',
    "Camera1.fx: 405.6384738851233",
    "Camera1.fy: 405.5883353782040",
    "Camera1.cx: 189.9054317917407",
    "Camera1.cy: 139.9149578253755",
    "Camera1.k1: 0.0",
    "Camera1.k2: 0.0",
    "Camera1.p1: 0.0",
    "Camera1.p2: 0.0",
    "Camera.width: 384",
    "Camera.height: 288",
    "Camera.fps: 5.0",
    "Camera.RGB: 0",
    "IMU.NoiseGyro: 0.004",
    "IMU.NoiseAcc: 0.08",
    "IMU.GyroWalk: 0.0004",
    "IMU.AccWalk: 0.004",
    "IMU.Frequency: 10.0",
    "ASSUMED_NOT_DATASET_CALIBRATED",
    'Extractor.type: "HFNetRT"',
    "Extractor.scaleFactor: 1.2",
    "Extractor.nLevels: 4",
    "Extractor.nFeatures: 675",
    "Extractor.threshold: 0.01",
    "loopClosing: 1",
)


class AuditError(RuntimeError):
    """An independently checked input invariant failed."""


@dataclass(frozen=True)
class AuditContract:
    window_id: str
    selector_schema: str
    selector: Path
    selector_size: int
    selector_sha256: str
    source_bag: Path
    source_size: int
    source_sha256: str
    input_root: Path
    source_indices: Tuple[int, int]
    camera_count: int
    camera_endpoints: Tuple[int, int]
    imu_count: int
    imu_endpoints: Tuple[int, int, int, int]
    proxy_count: int
    proxy_endpoints: Tuple[int, int]
    generated: Mapping[str, Tuple[int, str, str]]
    image_total: int
    image_sha256: str
    image_crc32: str
    payload_sha256: str
    payload_crc32: str


CONTRACTS: Dict[str, AuditContract] = {
    "cirs_s575_d30": AuditContract(
        "cirs_s575_d30",
        "aqua-fe-hfnet-v6-cirs-s575-d30-exact-window-selector-freeze-v1",
        ROOT / "papers/hfnet_v6_cirs_s575_d30_exact_window_selector_freeze_v1.json",
        1688,
        "f381428e8b49a384bb010a3fe3c05b7ce46c6385d8383f0fff0ba1c6ed28a045",
        Path("/mnt/data/AQUA-FE_WS/logs/cirs_caves_vins/external_klt_every1_jul14frozen3way_cirs_s575_d30_klt/raw_segment.bag"),
        17_017_751,
        "8370b0b842142bd9b5fc24cec4dc3d8cba8f37e6859bf868abe6bcf427f7a5a0",
        DEFAULT_INPUT_PARENT / "cirs_s575_d30",
        (2874, 3023),
        150,
        (1372687783674637079, 1372687813476711988),
        310,
        (1372687783174521923, 1372687783275060653, 1372687813974821805, 1372687814077413558),
        344,
        (1372687783130550622, 1372687814062464237),
        {
            "cam0_times.txt": (3000, "1a7a68d3b149a9b9e0f9c0b7cbd578142d91930cdbf6b9abe748c26d1aed600b", "8df5b670"),
            "mav0/cam0/data.csv": (6625, "0b4ec696f5aa0754586cbf3880fa142c0fae7ed2e99cbeeb3f0ac5770564dd46", "140b8494"),
            "mav0/imu0/data.csv": (43084, "12c755f9628c47a12102222842075b2d3bc3cf9f74f19ee26d0937fed893d919", "d2b9ab2c"),
        },
        8_714_010,
        "c2a403e6aa70ff3e73dd726fbdb10ccde92c940623be1548f381930de86f7eda",
        "5cf56ea5",
        "70b79250ac8525f25fb78190328b3031adff1903dab2e3e6d48de0acc94fc89d",
        "b6fec768",
    ),
    "cirs_s900_d30": AuditContract(
        "cirs_s900_d30",
        "aqua-fe-hfnet-v6-cirs-s900-d30-exact-window-selector-freeze-v1",
        ROOT / "papers/hfnet_v6_cirs_s900_d30_exact_window_selector_freeze_v1.json",
        1688,
        "20cb70adc30ce8d80bf4bc972bf80cbfe2dbc744765cdea7f6978acc5b0f147d",
        Path("/mnt/data/AQUA-FE_WS/logs/cirs_caves_vins/external_klt_every1_jul14frozen3way_cirs_s900_d30_klt/raw_segment.bag"),
        17_020_851,
        "0ebcc2ece9733499ee74b47033812115b813e6b1e918c27217a16db7da694919",
        DEFAULT_INPUT_PARENT / "cirs_s900_d30",
        (4499, 4648),
        150,
        (1372688108674326896, 1372688138475372076),
        310,
        (1372688108174928426, 1372688108275302886, 1372688138974294900, 1372688139076464176),
        348,
        (1372688108210351467, 1372688139038984775),
        {
            "cam0_times.txt": (3000, "e3e9d25cae17efdbeab3c3c734a20cd139fbf7e0147445fa9955a0462ecf1629", "366c8ec4"),
            "mav0/cam0/data.csv": (6625, "5c47b4f93f2c8d56b1c1a9f95172f94bf956297951d4c493478559fb91f3f285", "68829764"),
            "mav0/imu0/data.csv": (43212, "12d026dc1c5b36eb05fbf4044b746a404f2265ff39fe0ec9af7b4b2fce25966c", "2c55377a"),
        },
        8_930_970,
        "36a01ee33dceb24eb822343ac5296a1e9ebfea243b5c8c22a3f0b847706b6bd9",
        "fbf7f9eb",
        "544eaaaec76611f5b0138746f444ae4df5365b1027abcf144de2b3395d50a4ea",
        "82f8bc2c",
    ),
}


CLAIMS = {
    "runner_created": False,
    "start_claim_created": False,
    "hfnet_started": False,
    "ros_started": False,
    "vins_started": False,
    "detector_started": False,
    "evaluator_started": False,
    "trajectory_produced": False,
    "accuracy_measured": False,
    "scientific_comparison_produced": False,
}


def canonical_json(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _open_regular(path: Path, label: str) -> int:
    if path.is_symlink():
        raise AuditError(f"{label}_SYMLINK")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(path), flags)
    except OSError as error:
        raise AuditError(f"{label}_OPEN_FAILED:{type(error).__name__}") from error
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise AuditError(f"{label}_NOT_REGULAR")
    return descriptor


def read_regular(path: Path, label: str) -> bytes:
    descriptor = _open_regular(path, label)
    try:
        blocks: List[bytes] = []
        while True:
            block = os.read(descriptor, 4 * 1024 * 1024)
            if not block:
                return b"".join(blocks)
            blocks.append(block)
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
    return {"path": relative, "size_bytes": size, "sha256": digest.hexdigest(), "crc32": f"{crc & 0xffffffff:08x}"}


def require_file(path: Path, size: int, digest: str, label: str) -> Dict[str, Any]:
    observed = identity_file(path, str(path.resolve()), label)
    if observed["size_bytes"] != size or observed["sha256"] != digest:
        raise AuditError(f"{label}_IDENTITY_MISMATCH")
    return observed


def require_tuple(observed: Mapping[str, Any], expected: Tuple[int, str, str], label: str) -> None:
    actual = (observed["size_bytes"], observed["sha256"], observed["crc32"])
    if actual != expected:
        raise AuditError(f"{label}_IDENTITY_MISMATCH:{actual}")


def aggregate(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    digest = hashlib.sha256()
    crc = 0
    for row in sorted(rows, key=lambda item: str(item["path"])):
        payload = f"{row['path']}\0{row['size_bytes']}\0{row['sha256']}\0{row['crc32']}\n".encode("utf-8")
        digest.update(payload)
        crc = zlib.crc32(payload, crc)
    return {"algorithm": "sorted UTF-8 path\\0size\\0sha256\\0crc32\\n", "sha256": digest.hexdigest(), "crc32": f"{crc & 0xffffffff:08x}"}


def quaternion_matrix(xyzw: Sequence[float], translation: Sequence[float]) -> np.ndarray:
    q = np.asarray(xyzw, dtype=np.float64)
    q = q / np.linalg.norm(q)
    x, y, z, w = q
    rotation = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )
    transform = np.eye(4)
    transform[:3, :3] = rotation
    transform[:3, 3] = translation
    return transform


def derive_extrinsic() -> Dict[str, Any]:
    body_imu = quaternion_matrix(T_BODY_IMU_QUATERNION_XYZW, T_BODY_IMU_TRANSLATION)
    body_camera = quaternion_matrix(T_BODY_CAMERA_QUATERNION_XYZW, T_BODY_CAMERA_TRANSLATION)
    imu_body = np.eye(4)
    imu_body[:3, :3] = body_imu[:3, :3].T
    imu_body[:3, 3] = -body_imu[:3, :3].T @ body_imu[:3, 3]
    result = imu_body @ body_camera
    determinant = float(np.linalg.det(result[:3, :3]))
    orthogonality = float(np.max(np.abs(result[:3, :3].T @ result[:3, :3] - np.eye(3))))
    canonical_error = float(np.max(np.abs(result - EXPECTED_T_IMU_CAMERA)))
    if abs(determinant - 1.0) > 1e-12 or orthogonality > 1e-12 or canonical_error > 1e-12:
        raise AuditError("EXTRINSIC_DERIVATION_INVALID")
    return {"T_imu_camera": result.tolist(), "rotation_determinant": determinant, "orthogonality_max_abs_error": orthogonality, "canonical_matrix_max_abs_error": canonical_error, "published_body_identity_assumption": "sparus == sparus2 DVL body"}


def audit_config(path: Path) -> Dict[str, Any]:
    observed = require_file(path, CONFIG_SIZE, CONFIG_SHA256, "CONFIG")
    text = path.read_text(encoding="utf-8")
    for token in CONFIG_TOKENS:
        if token not in text:
            raise AuditError(f"CONFIG_REQUIRED_TOKEN_MISSING:{token}")
    match = re.search(r"IMU\.T_b_c1:.*?data:\s*\[([^\]]+)\]", text, re.DOTALL)
    if match is None:
        raise AuditError("CONFIG_EXTRINSIC_MISSING")
    try:
        values = [float(item.strip()) for item in match.group(1).split(",")]
    except ValueError as error:
        raise AuditError("CONFIG_EXTRINSIC_INVALID") from error
    derived = np.asarray(derive_extrinsic()["T_imu_camera"])
    if len(values) != 16 or float(np.max(np.abs(np.asarray(values).reshape(4, 4) - derived))) > 1e-12:
        raise AuditError("CONFIG_EXTRINSIC_MISMATCH")
    return observed


def audit_selector(path: Path, contract: AuditContract) -> Dict[str, Any]:
    observed = require_file(path, contract.selector_size, contract.selector_sha256, "SELECTOR")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise AuditError("SELECTOR_JSON_INVALID") from error
    selection = value.get("selection", {})
    if value.get("schema_version") != contract.selector_schema or selection.get("window_id") != contract.window_id:
        raise AuditError("SELECTOR_SCHEMA_OR_WINDOW_MISMATCH")
    if selection.get("cold_start") is not True or selection.get("camera_source_indices_inclusive_zero_based") != list(contract.source_indices):
        raise AuditError("SELECTOR_COLDSTART_OR_INDICES_MISMATCH")
    if selection.get("feed_camera_source_indices_inclusive") != list(contract.source_indices) or selection.get("score_camera_source_indices_inclusive") != list(contract.source_indices):
        raise AuditError("SELECTOR_FEED_SCORE_MISMATCH")
    if not value.get("claims") or any(item is not False for item in value["claims"].values()):
        raise AuditError("SELECTOR_FORBIDDEN_CLAIM")
    return observed


def source_raster(message: Any) -> np.ndarray:
    if message.encoding != "mono8" or message.width != 384 or message.height != 288 or message.step < message.width:
        raise AuditError("SOURCE_IMAGE_SCHEMA_MISMATCH")
    if len(message.data) != message.step * message.height:
        raise AuditError("SOURCE_IMAGE_SIZE_MISMATCH")
    return np.ascontiguousarray(np.frombuffer(message.data, dtype=np.uint8).reshape(message.height, message.step)[:, : message.width])


def read_source(path: Path, contract: AuditContract) -> Dict[str, Any]:
    source = require_file(path, contract.source_size, contract.source_sha256, "SOURCE_BAG")
    images: List[Tuple[int, int, np.ndarray]] = []
    imu: List[Tuple[int, Tuple[float, ...]]] = []
    proxy: List[int] = []
    with rosbag.Bag(str(path), "r") as bag:
        if set(bag.get_type_and_topic_info().topics) != EXPECTED_TOPICS:
            raise AuditError("SOURCE_TOPIC_SET_MISMATCH")
        for topic, message, _ in bag.read_messages(topics=sorted(EXPECTED_TOPICS)):
            stamp = int(message.header.stamp.to_nsec())
            if topic == IMAGE_TOPIC:
                images.append((int(message.header.seq), stamp, source_raster(message)))
            elif topic == IMU_TOPIC:
                values = (float(message.angular_velocity.x), float(message.angular_velocity.y), float(message.angular_velocity.z), float(message.linear_acceleration.x), float(message.linear_acceleration.y), float(message.linear_acceleration.z))
                if not all(math.isfinite(value) for value in values):
                    raise AuditError("SOURCE_IMU_NONFINITE")
                imu.append((stamp, values))
            else:
                proxy.append(stamp)
    camera_stamps = [row[1] for row in images]
    camera_sequences = [row[0] for row in images]
    imu_stamps = [row[0] for row in imu]
    if camera_sequences != list(range(contract.source_indices[0], contract.source_indices[1] + 1)):
        raise AuditError("SOURCE_CAMERA_SEQUENCE_MISMATCH")
    if len(images) != contract.camera_count or (camera_stamps[0], camera_stamps[-1]) != contract.camera_endpoints:
        raise AuditError("SOURCE_CAMERA_COUNT_OR_ENDPOINT_MISMATCH")
    if len(imu) != contract.imu_count or (imu_stamps[0], imu_stamps[1], imu_stamps[-2], imu_stamps[-1]) != contract.imu_endpoints:
        raise AuditError("SOURCE_IMU_COUNT_OR_ENDPOINT_MISMATCH")
    if len(proxy) != contract.proxy_count or (proxy[0], proxy[-1]) != contract.proxy_endpoints:
        raise AuditError("SOURCE_PROXY_COUNT_OR_ENDPOINT_MISMATCH")
    for values, label in ((camera_stamps, "CAMERA"), (imu_stamps, "IMU"), (proxy, "PROXY")):
        if any(right <= left for left, right in zip(values, values[1:])):
            raise AuditError(f"SOURCE_{label}_NON_MONOTONIC")
    left = bisect.bisect_right(imu_stamps, camera_stamps[0])
    right = bisect.bisect_right(imu_stamps, camera_stamps[-1])
    if left == 0 or left >= len(imu) or right == 0 or right >= len(imu):
        raise AuditError("SOURCE_IMU_READER_BRACKET_MISSING")
    return {
        "identity": source,
        "images": images,
        "imu": imu,
        "camera_stamps": camera_stamps,
        "bracket": {
            "first_camera_predecessor_imu_ns": imu_stamps[left - 1],
            "first_camera_successor_imu_ns": imu_stamps[left],
            "last_camera_predecessor_imu_ns": imu_stamps[right - 1],
            "last_camera_successor_imu_ns": imu_stamps[right],
            "valid": True,
        },
    }


def validate_png(payload: bytes) -> Dict[str, Any]:
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AuditError("PNG_SIGNATURE_MISMATCH")
    position = 8
    schema: Optional[Tuple[int, int, int, int, int, int, int]] = None
    ended = False
    chunks = 0
    while position < len(payload):
        if position + 12 > len(payload):
            raise AuditError("PNG_TRUNCATED")
        length = struct.unpack(">I", payload[position : position + 4])[0]
        end = position + 12 + length
        if end > len(payload):
            raise AuditError("PNG_CHUNK_LENGTH_INVALID")
        kind = payload[position + 4 : position + 8]
        data = payload[position + 8 : position + 8 + length]
        expected_crc = struct.unpack(">I", payload[position + 8 + length : end])[0]
        if zlib.crc32(kind + data) & 0xffffffff != expected_crc:
            raise AuditError("PNG_CHUNK_CRC_MISMATCH")
        chunks += 1
        if kind == b"IHDR":
            schema = struct.unpack(">IIBBBBB", data)
        if kind == b"IEND":
            if length != 0:
                raise AuditError("PNG_IEND_INVALID")
            position = end
            ended = True
            break
        position = end
    if not ended or position != len(payload) or schema != (384, 288, 8, 0, 0, 0, 0):
        raise AuditError(f"PNG_SCHEMA_OR_END_MISMATCH:{schema}")
    decoded = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if decoded is None or decoded.shape != (288, 384) or decoded.dtype != np.uint8:
        raise AuditError("PNG_DECODE_SCHEMA_MISMATCH")
    return {"raster": decoded, "chunk_count": chunks, "chunk_crc_all_valid": True}


def audit_tree(root: Path, contract: AuditContract, source: Mapping[str, Any]) -> Dict[str, Any]:
    if root.is_symlink() or not root.is_dir():
        raise AuditError("INPUT_ROOT_MISSING_OR_NOT_DIRECTORY")
    camera_stamps = source["camera_stamps"]
    times_expected = "".join(f"{stamp}\n" for stamp in camera_stamps).encode("ascii")
    camera_csv_expected = (CAMERA_CSV_HEADER + "\n" + "".join(f"{stamp},{stamp}.png\n" for stamp in camera_stamps)).encode("ascii")
    imu_lines = [IMU_HEADER]
    imu_lines.extend(f"{stamp}," + ",".join(format(value, ".17g") for value in values) for stamp, values in source["imu"])
    imu_expected = "\n".join(imu_lines).encode("ascii")
    generated_rows: List[Mapping[str, Any]] = []
    for relative, expected_payload in (("cam0_times.txt", times_expected), ("mav0/cam0/data.csv", camera_csv_expected), ("mav0/imu0/data.csv", imu_expected)):
        observed_payload = read_regular(root / relative, relative)
        if observed_payload != expected_payload:
            raise AuditError(f"GENERATED_SOURCE_REBUILD_MISMATCH:{relative}")
        observed = identity_file(root / relative, relative, relative)
        require_tuple(observed, contract.generated[relative], relative)
        generated_rows.append(observed)
    image_rows: List[Mapping[str, Any]] = []
    chunk_histogram: Dict[str, int] = {}
    for (sequence, stamp, source_image) in source["images"]:
        relative = f"mav0/cam0/data/{stamp}.png"
        payload = read_regular(root / relative, relative)
        png = validate_png(payload)
        if not np.array_equal(png["raster"], source_image):
            raise AuditError(f"OUTPUT_SOURCE_RASTER_MISMATCH:{stamp}")
        observed = identity_file(root / relative, relative, relative)
        image_rows.append({**observed, "source_seq": sequence, "stamp_ns": stamp})
        key = str(png["chunk_count"])
        chunk_histogram[key] = chunk_histogram.get(key, 0) + 1
    image_inventory = aggregate(image_rows)
    if sum(int(row["size_bytes"]) for row in image_rows) != contract.image_total:
        raise AuditError("OUTPUT_IMAGE_TOTAL_MISMATCH")
    if image_inventory["sha256"] != contract.image_sha256 or image_inventory["crc32"] != contract.image_crc32:
        raise AuditError("OUTPUT_IMAGE_INVENTORY_MISMATCH")
    payload_inventory = aggregate(image_rows + generated_rows)
    if payload_inventory["sha256"] != contract.payload_sha256 or payload_inventory["crc32"] != contract.payload_crc32:
        raise AuditError("OUTPUT_PAYLOAD_INVENTORY_MISMATCH")
    expected_files = {row["path"] for row in image_rows + generated_rows}
    expected_files.add("materialization_manifest.json")
    observed_files: Set[str] = set()
    observed_directories: Set[str] = {""}
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise AuditError(f"OUTPUT_SYMLINK:{relative}")
        if path.is_dir():
            observed_directories.add(relative)
        elif path.is_file():
            observed_files.add(relative)
        else:
            raise AuditError(f"OUTPUT_NONREGULAR:{relative}")
    if observed_files != expected_files:
        raise AuditError("OUTPUT_FILE_SET_MISMATCH")
    if observed_directories != {"", "mav0", "mav0/cam0", "mav0/cam0/data", "mav0/imu0"}:
        raise AuditError("OUTPUT_DIRECTORY_SET_MISMATCH")
    return {"image_rows": image_rows, "generated_rows": generated_rows, "image_inventory": image_inventory, "payload_inventory": payload_inventory, "chunk_histogram": chunk_histogram}


def audit_manifest(root: Path, contract: AuditContract, tree: Mapping[str, Any], source: Mapping[str, Any]) -> Dict[str, Any]:
    payload = read_regular(root / "materialization_manifest.json", "MANIFEST")
    try:
        manifest = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AuditError("MANIFEST_JSON_INVALID") from error
    if manifest.get("schema_version") != MATERIALIZATION_SCHEMA or manifest.get("status") != "PASS_PREPARATION_ONLY":
        raise AuditError("MANIFEST_SCHEMA_OR_STATUS_MISMATCH")
    selection = manifest.get("selection", {})
    if selection.get("window_id") != contract.window_id or selection.get("cold_start") is not True or selection.get("feed_equals_score_window") is not True:
        raise AuditError("MANIFEST_SELECTION_MISMATCH")
    if selection.get("source_indices_inclusive_zero_based") != list(contract.source_indices):
        raise AuditError("MANIFEST_SOURCE_INDICES_MISMATCH")
    if manifest.get("claims") != CLAIMS:
        raise AuditError("MANIFEST_CLAIMS_MISMATCH")
    if manifest.get("payload_identity_excluding_manifest") != tree["payload_inventory"]:
        raise AuditError("MANIFEST_PAYLOAD_IDENTITY_MISMATCH")
    if manifest.get("camera", {}).get("files") != tree["image_rows"]:
        raise AuditError("MANIFEST_IMAGE_ROWS_MISMATCH")
    if manifest.get("imu", {}).get("reader_bracket", {}).get("official_reader_bracket_valid") is not True:
        raise AuditError("MANIFEST_IMU_BRACKET_MISMATCH")
    reference = manifest.get("odometry_reference", {})
    if reference.get("independent_ground_truth") is not False or "non-independent" not in reference.get("role", ""):
        raise AuditError("MANIFEST_REFERENCE_ROLE_MISMATCH")
    extrinsic = np.asarray(manifest.get("extrinsic", {}).get("T_imu_camera", []), dtype=float)
    if extrinsic.shape != (4, 4) or float(np.max(np.abs(extrinsic - np.asarray(derive_extrinsic()["T_imu_camera"])))) > 1e-12:
        raise AuditError("MANIFEST_EXTRINSIC_MISMATCH")
    if manifest.get("source", {}).get("sha256") != source["identity"]["sha256"]:
        raise AuditError("MANIFEST_SOURCE_IDENTITY_MISMATCH")
    return {"identity": identity_file(root / "materialization_manifest.json", "materialization_manifest.json", "MANIFEST"), "valid": True}


def audit(contract: AuditContract, input_root: Path, source_bag: Path, selector: Path, config: Path) -> Dict[str, Any]:
    source = read_source(source_bag, contract)
    selector_identity = audit_selector(selector, contract)
    config_identity = audit_config(config)
    extrinsic = derive_extrinsic()
    tree = audit_tree(input_root, contract, source)
    manifest = audit_manifest(input_root, contract, tree, source)
    manifest_identity = {
        "path": str((input_root / "materialization_manifest.json").resolve()),
        "size_bytes": manifest["identity"]["size_bytes"],
        "sha256": manifest["identity"]["sha256"],
    }
    binding_config_identity = {
        "path": str(config.resolve()),
        "size_bytes": config_identity["size_bytes"],
        "sha256": config_identity["sha256"],
    }
    runner_binding = {
        "schema_version": RUNNER_BINDING_SCHEMA,
        "case_id": contract.window_id,
        "input_root": str(input_root.resolve()),
        "input_manifest": manifest_identity,
        "base_config": binding_config_identity,
        "camera_count": contract.camera_count,
        "camera_header_ns_inclusive": [
            source["camera_stamps"][0],
            source["camera_stamps"][-1],
        ],
        "score_relative_indices_inclusive": [0, contract.camera_count - 1],
        "history": "EXACT_WINDOW_COLD_START_NO_PRIOR_CAMERA_HISTORY",
        "times_relative_path": "cam0_times.txt",
        "images_relative_path": "mav0/cam0/data",
        "image_extension": ".png",
        "imu_relative_path": "mav0/imu0/data.csv",
        "imu_reader_bracket_valid": source["bracket"]["valid"],
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_PREPARATION_ONLY_INDEPENDENT_AUDIT",
        "window_id": contract.window_id,
        "input_root": str(input_root.resolve()),
        "source": source["identity"],
        "selector_freeze": selector_identity,
        "config": config_identity,
        "camera": {"count": contract.camera_count, "all_output_rasters_equal_source": True, "all_png_crc_valid": True, "chunk_count_histogram": tree["chunk_histogram"], "inventory_identity": tree["image_inventory"]},
        "imu": {"count": contract.imu_count, "frequency_setting_hz": 10.0, "reader_bracket": source["bracket"], "stochastic_parameters": "ASSUMED_NOT_DATASET_CALIBRATED"},
        "extrinsic": extrinsic,
        "odometry_reference": {"count": contract.proxy_count, "role": "official CIRS odometry trajectory proxy; non-independent", "independent_ground_truth": False},
        "payload_identity_excluding_manifest": tree["payload_inventory"],
        "manifest": manifest,
        "runner_binding": runner_binding,
        "reporting_boundary": "input preparation audit only; no process start, trajectory, accuracy, or comparison",
        "claims": dict(CLAIMS),
    }


def write_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", choices=sorted(CONTRACTS), required=True)
    parser.add_argument("--input-root", type=Path)
    parser.add_argument("--source-bag", type=Path)
    parser.add_argument("--selector-freeze", type=Path)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    contract = CONTRACTS[args.window]
    try:
        result = audit(contract, args.input_root or contract.input_root, args.source_bag or contract.source_bag, args.selector_freeze or contract.selector, args.config)
        return_code = 0
    except Exception as error:
        result = {"schema_version": SCHEMA_VERSION, "status": "INTEGRITY_ERROR", "window_id": contract.window_id, "errors": [f"{type(error).__name__}:{error}"], "claims": dict(CLAIMS)}
        return_code = 2
    payload = canonical_json(result)
    if args.report is not None:
        write_exclusive(args.report, payload)
    os.write(1, payload)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
