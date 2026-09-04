#!/usr/bin/env python3
"""Prepare the two frozen CIRS positive windows for HFNet v6, without running it.

The source of each window is the byte-identical ``raw_segment.bag`` shared by
the historical learned+KLT and pure-KLT arms.  Images are exported as
timestamp-named, lossless PNGs and IMU samples as the exact seven-column CSV
consumed by HFNet-SLAM's official EuRoC mono-inertial entry point.

Publication is atomic and no-clobber.  This module has no launcher and never
starts HFNet, ROS master, VINS, a detector, or an evaluator.
"""

from __future__ import annotations

import argparse
import bisect
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple
import zlib

import cv2
import numpy as np
import rosbag


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "aqua-fe-hfnet-v6-cirs-exact-window-coldstart-materialization-v1"
CONFIG = (
    ROOT
    / "configs/published_baselines/"
    "hfnet_slam_cirs_cala_viuda_exact_window_coldstart_v1.yaml"
)
CONFIG_PIN = (2391, "b6e93daf3ca06e3e29433fffa7eb037119b97261888395fe1d51fa2d7a218204")
DEFAULT_OUTPUT_PARENT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_v6_cirs_exact_window_coldstart_v1"
)

IMAGE_TOPIC = "/cirs/camera/image_mono"
IMU_TOPIC = "/cirs/imu_xsens"
ODOMETRY_PROXY_TOPIC = "/cirs/odometry_gt"
EXPECTED_TOPICS = {IMAGE_TOPIC, IMU_TOPIC, ODOMETRY_PROXY_TOPIC}
IMU_HEADER = (
    "#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],"
    "w_RS_S_z [rad s^-1],a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],"
    "a_RS_S_z [m s^-2]"
)
CAMERA_CSV_HEADER = "#timestamp [ns],filename"

# Recorded CIRS TF values.  The dataset paper (DOI
# 10.1177/0278364917732838, Sec. 2.3/Table 2) gives both offsets relative to
# the DVL body, which is the authority for identifying sparus and sparus2 here.
T_BODY_IMU_TRANSLATION = (0.1, 0.0, -0.16)
T_BODY_IMU_QUATERNION_XYZW = (
    0.7071067811865476,
    -0.7071067811865475,
    -4.329780281177466e-17,
    4.329780281177467e-17,
)
T_BODY_CAMERA_TRANSLATION = (0.26, 0.0, -0.02)
T_BODY_CAMERA_QUATERNION_XYZW = (
    0.0,
    0.0,
    0.7071067811865475,
    0.7071067811865476,
)
EXPECTED_T_IMU_CAMERA = np.array(
    [
        [-1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, -0.16],
        [0.0, 0.0, -1.0, -0.14],
        [0.0, 0.0, 0.0, 1.0],
    ],
    dtype=np.float64,
)

CONFIG_REQUIRED_TOKENS = (
    'Camera.type: "PinHole"',
    "Camera1.fx: 405.6384738851233",
    "Camera1.fy: 405.5883353782040",
    "Camera1.cx: 189.9054317917407",
    "Camera1.cy: 139.9149578253755",
    "Camera1.k1: 0.0",
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
    "Extractor.nFeatures: 675",
    "Extractor.threshold: 0.01",
    "loopClosing: 1",
)


class ContractError(RuntimeError):
    """A frozen source, selection, calibration, or output invariant failed."""


@dataclass(frozen=True)
class FilePin:
    size_bytes: Optional[int] = None
    sha256: Optional[str] = None
    crc32: Optional[str] = None


@dataclass(frozen=True)
class WindowContract:
    window_id: str
    selector_schema: str
    selector: Path
    selector_pin: FilePin
    source_bag: Path
    source_pin: FilePin
    output_root: Path
    start_offset_seconds: float
    duration_seconds: float
    source_indices_inclusive: Tuple[int, int]
    camera_count: int
    camera_endpoints_ns: Tuple[int, int]
    imu_count: int
    imu_endpoints_ns: Tuple[int, int, int, int]
    odometry_proxy_count: int
    odometry_proxy_endpoints_ns: Tuple[int, int]
    times_pin: FilePin
    camera_csv_pin: FilePin
    imu_csv_pin: FilePin
    image_total_bytes: int
    image_inventory_sha256: str
    image_inventory_crc32: str
    payload_sha256: str
    payload_crc32: str


WINDOWS: Dict[str, WindowContract] = {
    "cirs_s575_d30": WindowContract(
        window_id="cirs_s575_d30",
        selector_schema="aqua-fe-hfnet-v6-cirs-s575-d30-exact-window-selector-freeze-v1",
        selector=ROOT / "papers/hfnet_v6_cirs_s575_d30_exact_window_selector_freeze_v1.json",
        selector_pin=FilePin(1688, "f381428e8b49a384bb010a3fe3c05b7ce46c6385d8383f0fff0ba1c6ed28a045"),
        source_bag=Path(
            "/mnt/data/AQUA-FE_WS/logs/cirs_caves_vins/"
            "external_klt_every1_jul14frozen3way_cirs_s575_d30_klt/raw_segment.bag"
        ),
        source_pin=FilePin(17_017_751, "8370b0b842142bd9b5fc24cec4dc3d8cba8f37e6859bf868abe6bcf427f7a5a0"),
        output_root=DEFAULT_OUTPUT_PARENT / "cirs_s575_d30",
        start_offset_seconds=575.0,
        duration_seconds=30.0,
        source_indices_inclusive=(2874, 3023),
        camera_count=150,
        camera_endpoints_ns=(1372687783674637079, 1372687813476711988),
        imu_count=310,
        imu_endpoints_ns=(1372687783174521923, 1372687783275060653, 1372687813974821805, 1372687814077413558),
        odometry_proxy_count=344,
        odometry_proxy_endpoints_ns=(1372687783130550622, 1372687814062464237),
        times_pin=FilePin(3000, "1a7a68d3b149a9b9e0f9c0b7cbd578142d91930cdbf6b9abe748c26d1aed600b", "8df5b670"),
        camera_csv_pin=FilePin(6625, "0b4ec696f5aa0754586cbf3880fa142c0fae7ed2e99cbeeb3f0ac5770564dd46", "140b8494"),
        imu_csv_pin=FilePin(43084, "12c755f9628c47a12102222842075b2d3bc3cf9f74f19ee26d0937fed893d919", "d2b9ab2c"),
        image_total_bytes=8_714_010,
        image_inventory_sha256="c2a403e6aa70ff3e73dd726fbdb10ccde92c940623be1548f381930de86f7eda",
        image_inventory_crc32="5cf56ea5",
        payload_sha256="70b79250ac8525f25fb78190328b3031adff1903dab2e3e6d48de0acc94fc89d",
        payload_crc32="b6fec768",
    ),
    "cirs_s900_d30": WindowContract(
        window_id="cirs_s900_d30",
        selector_schema="aqua-fe-hfnet-v6-cirs-s900-d30-exact-window-selector-freeze-v1",
        selector=ROOT / "papers/hfnet_v6_cirs_s900_d30_exact_window_selector_freeze_v1.json",
        selector_pin=FilePin(1688, "20cb70adc30ce8d80bf4bc972bf80cbfe2dbc744765cdea7f6978acc5b0f147d"),
        source_bag=Path(
            "/mnt/data/AQUA-FE_WS/logs/cirs_caves_vins/"
            "external_klt_every1_jul14frozen3way_cirs_s900_d30_klt/raw_segment.bag"
        ),
        source_pin=FilePin(17_020_851, "0ebcc2ece9733499ee74b47033812115b813e6b1e918c27217a16db7da694919"),
        output_root=DEFAULT_OUTPUT_PARENT / "cirs_s900_d30",
        start_offset_seconds=900.0,
        duration_seconds=30.0,
        source_indices_inclusive=(4499, 4648),
        camera_count=150,
        camera_endpoints_ns=(1372688108674326896, 1372688138475372076),
        imu_count=310,
        imu_endpoints_ns=(1372688108174928426, 1372688108275302886, 1372688138974294900, 1372688139076464176),
        odometry_proxy_count=348,
        odometry_proxy_endpoints_ns=(1372688108210351467, 1372688139038984775),
        times_pin=FilePin(3000, "e3e9d25cae17efdbeab3c3c734a20cd139fbf7e0147445fa9955a0462ecf1629", "366c8ec4"),
        camera_csv_pin=FilePin(6625, "5c47b4f93f2c8d56b1c1a9f95172f94bf956297951d4c493478559fb91f3f285", "68829764"),
        imu_csv_pin=FilePin(43212, "12d026dc1c5b36eb05fbf4044b746a404f2265ff39fe0ec9af7b4b2fce25966c", "2c55377a"),
        image_total_bytes=8_930_970,
        image_inventory_sha256="36a01ee33dceb24eb822343ac5296a1e9ebfea243b5c8c22a3f0b847706b6bd9",
        image_inventory_crc32="fbf7f9eb",
        payload_sha256="544eaaaec76611f5b0138746f444ae4df5365b1027abcf144de2b3395d50a4ea",
        payload_crc32="82f8bc2c",
    ),
}


def canonical_json(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def identity_bytes(path: str, payload: bytes) -> Dict[str, Any]:
    return {
        "path": path,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "crc32": f"{zlib.crc32(payload) & 0xffffffff:08x}",
    }


def identity_file(path: Path, relative: Optional[str] = None) -> Dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"NOT_REGULAR_NONSYMLINK_FILE:{path}")
    digest = hashlib.sha256()
    crc = 0
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
            crc = zlib.crc32(block, crc)
            size += len(block)
    return {
        "path": relative or str(path.resolve()),
        "size_bytes": size,
        "sha256": digest.hexdigest(),
        "crc32": f"{crc & 0xffffffff:08x}",
    }


def require_pin(observed: Mapping[str, Any], pin: FilePin, label: str) -> None:
    for key in ("size_bytes", "sha256", "crc32"):
        expected = getattr(pin, key)
        if expected is not None and observed.get(key) != expected:
            raise ContractError(f"{label}_{key.upper()}_MISMATCH:{observed.get(key)}")


def aggregate(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
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
        "crc32": f"{crc & 0xffffffff:08x}",
    }


def quaternion_matrix(xyzw: Sequence[float], translation: Sequence[float]) -> np.ndarray:
    q = np.asarray(xyzw, dtype=np.float64)
    norm = float(np.linalg.norm(q))
    if not math.isfinite(norm) or norm <= 0.0:
        raise ContractError("EXTRINSIC_QUATERNION_INVALID")
    x, y, z, w = q / norm
    rotation = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )
    transform = np.eye(4, dtype=np.float64)
    transform[:3, :3] = rotation
    transform[:3, 3] = np.asarray(translation, dtype=np.float64)
    return transform


def extrinsic_audit() -> Dict[str, Any]:
    body_imu = quaternion_matrix(T_BODY_IMU_QUATERNION_XYZW, T_BODY_IMU_TRANSLATION)
    body_camera = quaternion_matrix(T_BODY_CAMERA_QUATERNION_XYZW, T_BODY_CAMERA_TRANSLATION)
    imu_body = np.eye(4, dtype=np.float64)
    imu_body[:3, :3] = body_imu[:3, :3].T
    imu_body[:3, 3] = -body_imu[:3, :3].T @ body_imu[:3, 3]
    imu_camera = imu_body @ body_camera
    rotation = imu_camera[:3, :3]
    determinant = float(np.linalg.det(rotation))
    orthogonality_error = float(np.max(np.abs(rotation.T @ rotation - np.eye(3))))
    expected_error = float(np.max(np.abs(imu_camera - EXPECTED_T_IMU_CAMERA)))
    if abs(determinant - 1.0) > 1e-12:
        raise ContractError(f"EXTRINSIC_ROTATION_DETERMINANT:{determinant}")
    if orthogonality_error > 1e-12:
        raise ContractError(f"EXTRINSIC_ROTATION_NOT_ORTHONORMAL:{orthogonality_error}")
    if expected_error > 1e-12:
        raise ContractError(f"EXTRINSIC_DERIVATION_MISMATCH:{expected_error}")
    return {
        "authority": "DOI 10.1177/0278364917732838 Sec.2.3/Table2 plus recorded TF values",
        "body_frame_identity_assumption": "sparus and sparus2 are the same published DVL body",
        "recorded_T_body_imu": {"translation": list(T_BODY_IMU_TRANSLATION), "quaternion_xyzw": list(T_BODY_IMU_QUATERNION_XYZW)},
        "recorded_T_body_camera": {"translation": list(T_BODY_CAMERA_TRANSLATION), "quaternion_xyzw": list(T_BODY_CAMERA_QUATERNION_XYZW)},
        "formula": "T_imu_camera=inv(T_body_imu)@T_body_camera",
        "T_imu_camera": imu_camera.tolist(),
        "rotation_determinant": determinant,
        "orthogonality_max_abs_error": orthogonality_error,
        "canonical_matrix_max_abs_error": expected_error,
    }


def validate_config(path: Path) -> Dict[str, Any]:
    observed = identity_file(path)
    require_pin(observed, FilePin(*CONFIG_PIN), "CONFIG")
    text = path.read_text(encoding="utf-8")
    missing = [token for token in CONFIG_REQUIRED_TOKENS if token not in text]
    if missing:
        raise ContractError(f"CONFIG_REQUIRED_TOKEN_MISSING:{missing[0]}")
    match = re.search(r"IMU\.T_b_c1:.*?data:\s*\[([^\]]+)\]", text, re.DOTALL)
    if match is None:
        raise ContractError("CONFIG_EXTRINSIC_MATRIX_MISSING")
    try:
        values = [float(value.strip()) for value in match.group(1).split(",")]
    except ValueError as error:
        raise ContractError("CONFIG_EXTRINSIC_MATRIX_INVALID") from error
    if len(values) != 16:
        raise ContractError("CONFIG_EXTRINSIC_MATRIX_SIZE")
    derived = np.asarray(extrinsic_audit()["T_imu_camera"], dtype=np.float64)
    error = float(np.max(np.abs(np.asarray(values).reshape(4, 4) - derived)))
    if error > 1e-12:
        raise ContractError(f"CONFIG_EXTRINSIC_DERIVATION_MISMATCH:{error}")
    return {**observed, "semantic_tokens_valid": True, "extrinsic_max_abs_error": error}


def validate_selector(path: Path, contract: WindowContract) -> Dict[str, Any]:
    observed = identity_file(path)
    require_pin(observed, contract.selector_pin, "SELECTOR")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ContractError("SELECTOR_JSON_INVALID") from error
    selection = value.get("selection", {})
    if value.get("schema_version") != contract.selector_schema:
        raise ContractError("SELECTOR_SCHEMA_MISMATCH")
    if selection.get("window_id") != contract.window_id:
        raise ContractError("SELECTOR_WINDOW_MISMATCH")
    if selection.get("cold_start") is not True:
        raise ContractError("SELECTOR_NOT_COLD_START")
    if selection.get("camera_source_indices_inclusive_zero_based") != list(contract.source_indices_inclusive):
        raise ContractError("SELECTOR_CAMERA_INDICES_MISMATCH")
    if selection.get("feed_camera_source_indices_inclusive") != list(contract.source_indices_inclusive):
        raise ContractError("SELECTOR_FEED_INDICES_MISMATCH")
    if selection.get("score_camera_source_indices_inclusive") != list(contract.source_indices_inclusive):
        raise ContractError("SELECTOR_SCORE_INDICES_MISMATCH")
    if selection.get("camera_count") != contract.camera_count:
        raise ContractError("SELECTOR_CAMERA_COUNT_MISMATCH")
    if selection.get("camera_header_ns_inclusive") != list(contract.camera_endpoints_ns):
        raise ContractError("SELECTOR_CAMERA_ENDPOINT_MISMATCH")
    claims = value.get("claims", {})
    if not claims or any(item is not False for item in claims.values()):
        raise ContractError("SELECTOR_FORBIDDEN_CLAIM")
    return observed


def image_raster(message: Any) -> np.ndarray:
    if message.encoding != "mono8" or message.width != 384 or message.height != 288:
        raise ContractError(f"IMAGE_SCHEMA_MISMATCH:{message.encoding}:{message.width}x{message.height}")
    if int(message.step) < int(message.width):
        raise ContractError("IMAGE_STEP_TOO_SMALL")
    expected = int(message.step) * int(message.height)
    if len(message.data) != expected:
        raise ContractError(f"IMAGE_DATA_SIZE_MISMATCH:{len(message.data)}:{expected}")
    rows = np.frombuffer(message.data, dtype=np.uint8).reshape(message.height, message.step)
    return np.ascontiguousarray(rows[:, : message.width])


def encode_png(raster: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", raster, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    if not ok:
        raise ContractError("PNG_ENCODING_FAILED")
    payload = encoded.tobytes()
    decoded = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if decoded is None or not np.array_equal(decoded, raster):
        raise ContractError("PNG_RASTER_ROUNDTRIP_MISMATCH")
    return payload


def _strict(values: Sequence[int], label: str) -> None:
    if any(right <= left for left, right in zip(values, values[1:])):
        raise ContractError(f"{label}_TIMESTAMPS_NOT_STRICT")


def prepare_payloads(source_bag: Path, contract: WindowContract) -> Dict[str, Any]:
    source = identity_file(source_bag)
    require_pin(source, contract.source_pin, "SOURCE_BAG")
    images: List[Dict[str, Any]] = []
    image_stamps: List[int] = []
    image_sequences: List[int] = []
    imu_rows: List[Tuple[int, Tuple[float, ...]]] = []
    proxy_stamps: List[int] = []
    with rosbag.Bag(str(source_bag), "r") as bag:
        topic_info = bag.get_type_and_topic_info().topics
        if set(topic_info) != EXPECTED_TOPICS:
            raise ContractError(f"SOURCE_TOPIC_SET_MISMATCH:{sorted(topic_info)}")
        for topic, message, _ in bag.read_messages(topics=sorted(EXPECTED_TOPICS)):
            stamp = int(message.header.stamp.to_nsec())
            if topic == IMAGE_TOPIC:
                raster = image_raster(message)
                payload = encode_png(raster)
                relative = f"mav0/cam0/data/{stamp}.png"
                images.append({"identity": identity_bytes(relative, payload), "payload": payload, "source_seq": int(message.header.seq), "stamp_ns": stamp})
                image_stamps.append(stamp)
                image_sequences.append(int(message.header.seq))
            elif topic == IMU_TOPIC:
                values = (
                    float(message.angular_velocity.x), float(message.angular_velocity.y), float(message.angular_velocity.z),
                    float(message.linear_acceleration.x), float(message.linear_acceleration.y), float(message.linear_acceleration.z),
                )
                if not all(math.isfinite(value) for value in values):
                    raise ContractError("IMU_NONFINITE")
                imu_rows.append((stamp, values))
            else:
                pose = message.pose.pose
                values = (pose.position.x, pose.position.y, pose.position.z, pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w)
                if not all(math.isfinite(float(value)) for value in values):
                    raise ContractError("ODOMETRY_PROXY_NONFINITE")
                proxy_stamps.append(stamp)

    imu_stamps = [row[0] for row in imu_rows]
    _strict(image_stamps, "CAMERA")
    _strict(imu_stamps, "IMU")
    _strict(proxy_stamps, "ODOMETRY_PROXY")
    if len(images) != contract.camera_count or tuple((image_stamps[0], image_stamps[-1])) != contract.camera_endpoints_ns:
        raise ContractError("CAMERA_COUNT_OR_ENDPOINT_MISMATCH")
    expected_sequences = list(range(contract.source_indices_inclusive[0], contract.source_indices_inclusive[1] + 1))
    if image_sequences != expected_sequences:
        raise ContractError("CAMERA_SOURCE_SEQUENCE_MISMATCH")
    observed_imu_endpoints = (imu_stamps[0], imu_stamps[1], imu_stamps[-2], imu_stamps[-1])
    if len(imu_rows) != contract.imu_count or observed_imu_endpoints != contract.imu_endpoints_ns:
        raise ContractError("IMU_COUNT_OR_ENDPOINT_MISMATCH")
    if len(proxy_stamps) != contract.odometry_proxy_count or (proxy_stamps[0], proxy_stamps[-1]) != contract.odometry_proxy_endpoints_ns:
        raise ContractError("ODOMETRY_PROXY_COUNT_OR_ENDPOINT_MISMATCH")

    first_right = bisect.bisect_right(imu_stamps, image_stamps[0])
    last_right = bisect.bisect_right(imu_stamps, image_stamps[-1])
    if first_right == 0 or first_right >= len(imu_stamps) or last_right == 0 or last_right >= len(imu_stamps):
        raise ContractError("IMU_CAMERA_READER_BRACKET_MISSING")
    bracket = {
        "first_camera_ns": image_stamps[0],
        "first_camera_predecessor_imu_ns": imu_stamps[first_right - 1],
        "first_camera_successor_imu_ns": imu_stamps[first_right],
        "last_camera_ns": image_stamps[-1],
        "last_camera_predecessor_imu_ns": imu_stamps[last_right - 1],
        "last_camera_successor_imu_ns": imu_stamps[last_right],
        "official_reader_bracket_valid": True,
    }

    times_payload = "".join(f"{stamp}\n" for stamp in image_stamps).encode("ascii")
    camera_csv_payload = (CAMERA_CSV_HEADER + "\n" + "".join(f"{stamp},{stamp}.png\n" for stamp in image_stamps)).encode("ascii")
    imu_lines = [IMU_HEADER]
    imu_lines.extend(f"{stamp}," + ",".join(format(value, ".17g") for value in values) for stamp, values in imu_rows)
    imu_payload = "\n".join(imu_lines).encode("ascii")
    generated = {
        "cam0_times": identity_bytes("cam0_times.txt", times_payload),
        "cam0_data_csv": identity_bytes("mav0/cam0/data.csv", camera_csv_payload),
        "imu0_data_csv": identity_bytes("mav0/imu0/data.csv", imu_payload),
    }
    require_pin(generated["cam0_times"], contract.times_pin, "CAM0_TIMES")
    require_pin(generated["cam0_data_csv"], contract.camera_csv_pin, "CAM0_DATA_CSV")
    require_pin(generated["imu0_data_csv"], contract.imu_csv_pin, "IMU0_DATA_CSV")
    image_identities = [item["identity"] for item in images]
    image_inventory = aggregate(image_identities)
    if sum(int(row["size_bytes"]) for row in image_identities) != contract.image_total_bytes:
        raise ContractError("IMAGE_TOTAL_BYTES_MISMATCH")
    if image_inventory["sha256"] != contract.image_inventory_sha256 or image_inventory["crc32"] != contract.image_inventory_crc32:
        raise ContractError("IMAGE_INVENTORY_IDENTITY_MISMATCH")
    payload_inventory = aggregate(image_identities + list(generated.values()))
    if payload_inventory["sha256"] != contract.payload_sha256 or payload_inventory["crc32"] != contract.payload_crc32:
        raise ContractError("PAYLOAD_INVENTORY_IDENTITY_MISMATCH")
    return {
        "source": source,
        "images": images,
        "times_payload": times_payload,
        "camera_csv_payload": camera_csv_payload,
        "imu_payload": imu_payload,
        "generated": generated,
        "image_inventory": image_inventory,
        "payload_inventory": payload_inventory,
        "bracket": bracket,
    }


def fsync_directory(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
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


def build_manifest(contract: WindowContract, output_root: Path, metadata: Mapping[str, Any], selector: Mapping[str, Any], config: Mapping[str, Any]) -> Dict[str, Any]:
    image_rows = [{**item["identity"], "source_seq": item["source_seq"], "stamp_ns": item["stamp_ns"]} for item in metadata["images"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_PREPARATION_ONLY",
        "output_root": str(output_root.resolve(strict=False)),
        "selection": {
            "window_id": contract.window_id,
            "dataset_family": "CIRS_Cala_Viuda",
            "cold_start": True,
            "feed_history": "none_before_exact_window",
            "feed_equals_score_window": True,
            "start_offset_seconds": contract.start_offset_seconds,
            "duration_seconds": contract.duration_seconds,
            "source_indices_inclusive_zero_based": list(contract.source_indices_inclusive),
            "camera_count": contract.camera_count,
            "camera_header_ns_inclusive": list(contract.camera_endpoints_ns),
            "development_result_conditioned_selection": True,
            "held_out_confirmatory_claim_permitted": False,
        },
        "source": {
            **metadata["source"],
            "selector_freeze": selector,
            "topics": {"camera": IMAGE_TOPIC, "imu": IMU_TOPIC, "odometry_proxy": ODOMETRY_PROXY_TOPIC},
            "historical_full_and_klt_raw_segment_bytes_identical": True,
        },
        "configuration": {
            **config,
            "camera_calibration": "constant CameraInfo K/P on undistorted 384x288 images; zero distortion",
            "imu_rate_hz": 10.0,
            "imu_stochastic_parameters": "ASSUMED_NOT_DATASET_CALIBRATED; inherited from existing CIRS VINS protocol",
        },
        "extrinsic": extrinsic_audit(),
        "camera": {
            "count": contract.camera_count,
            "source_encoding": "mono8",
            "output_schema": "384x288 8-bit grayscale PNG",
            "png_encoder": f"OpenCV {cv2.__version__}; IMWRITE_PNG_COMPRESSION=3",
            "raster_roundtrip_all_exact": True,
            "total_png_bytes": contract.image_total_bytes,
            "inventory_identity": metadata["image_inventory"],
            "files": image_rows,
        },
        "imu": {
            "count": contract.imu_count,
            "frequency_setting_hz": 10.0,
            "measurement_axis_transform": "none; ROS Imu angular_velocity and linear_acceleration copied in sensor axes",
            "timestamp_transform": "none",
            "final_newline": False,
            "reader_bracket": metadata["bracket"],
        },
        "odometry_reference": {
            "topic": ODOMETRY_PROXY_TOPIC,
            "count": contract.odometry_proxy_count,
            "header_ns_inclusive": list(contract.odometry_proxy_endpoints_ns),
            "role": "official CIRS odometry trajectory proxy; non-independent; not copied into HFNet feed",
            "independent_ground_truth": False,
        },
        "generated_files": metadata["generated"],
        "payload_identity_excluding_manifest": metadata["payload_inventory"],
        "payload_file_count_excluding_manifest": contract.camera_count + 3,
        "reporting_boundary": "development-only input preparation; no process start, trajectory, accuracy, or comparison",
        "claims": dict(CLAIMS),
    }


def _require_output_absent(output_root: Path) -> None:
    if output_root.exists() or output_root.is_symlink():
        raise ContractError(f"NO_CLOBBER_OUTPUT_EXISTS:{output_root}")


def preflight(contract: WindowContract, source_bag: Path, selector_path: Path, config_path: Path, output_root: Path) -> Dict[str, Any]:
    _require_output_absent(output_root)
    selector = validate_selector(selector_path, contract)
    config = validate_config(config_path)
    metadata = prepare_payloads(source_bag, contract)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PREFLIGHT_READY_PREPARATION_ONLY",
        "window_id": contract.window_id,
        "output_root": str(output_root.resolve(strict=False)),
        "source": metadata["source"],
        "selector_freeze": selector,
        "config": config,
        "camera_count": contract.camera_count,
        "imu_count": contract.imu_count,
        "odometry_proxy_count": contract.odometry_proxy_count,
        "imu_reader_bracket": metadata["bracket"],
        "extrinsic": extrinsic_audit(),
        "payload_identity": metadata["payload_inventory"],
        "claims": {"output_created": False, **CLAIMS},
    }


def materialize(contract: WindowContract, source_bag: Path, selector_path: Path, config_path: Path, output_root: Path) -> Dict[str, Any]:
    _require_output_absent(output_root)
    selector = validate_selector(selector_path, contract)
    config = validate_config(config_path)
    metadata = prepare_payloads(source_bag, contract)
    manifest = build_manifest(contract, output_root, metadata, selector, config)
    with atomic_directory(output_root) as staging:
        for item in metadata["images"]:
            write_exclusive(staging / item["identity"]["path"], item["payload"])
        write_exclusive(staging / "cam0_times.txt", metadata["times_payload"])
        write_exclusive(staging / "mav0/cam0/data.csv", metadata["camera_csv_payload"])
        write_exclusive(staging / "mav0/imu0/data.csv", metadata["imu_payload"])
        write_exclusive(staging / "materialization_manifest.json", canonical_json(manifest))
        for directory in (staging / "mav0/cam0/data", staging / "mav0/cam0", staging / "mav0/imu0", staging / "mav0", staging):
            fsync_directory(directory)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", choices=sorted(WINDOWS), required=True)
    parser.add_argument("--action", choices=("preflight", "materialize"), default="preflight")
    parser.add_argument("--source-bag", type=Path)
    parser.add_argument("--selector-freeze", type=Path)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--output-root", type=Path)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    contract = WINDOWS[args.window]
    source_bag = args.source_bag or contract.source_bag
    selector = args.selector_freeze or contract.selector
    output_root = args.output_root or contract.output_root
    try:
        if args.action == "materialize":
            result = materialize(contract, source_bag, selector, args.config, output_root)
        else:
            result = preflight(contract, source_bag, selector, args.config, output_root)
        return_code = 0
    except Exception as error:
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "INTEGRITY_ERROR",
            "window_id": contract.window_id,
            "errors": [f"{type(error).__name__}:{error}"],
            "claims": dict(CLAIMS),
        }
        return_code = 2
    os.write(1, canonical_json(result))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
