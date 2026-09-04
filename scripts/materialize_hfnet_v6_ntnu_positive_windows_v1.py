#!/usr/bin/env python3
"""Prepare frozen NTNU historical-positive HFNet EuRoC inputs, and nothing else.

The formal path is the outcome-selected exact-window cold-start protocol in
``papers/hfnet_v6_ntnu_historical_positive_exact_window_selector_v1.json``.
Camera messages are selected by *bag record time* using the same closed-window
rule as the historical frontend exporter, while EuRoC filenames use the
original camera Header.stamp.  Real IMU timestamps are shifted by the frozen
cam0/IMU calibration and trimmed only to the reader bracket required by the
official monocular-inertial entry.

Publication is manifest-last, atomic, and no-clobber.  This module contains no
HFNet/ROS/VINS/detector/evaluator process launch.  A natural-history mode is
available for read-only secondary preflight only; materializing it requires a
separate future selector freeze.
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
import stat
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import materialize_hfnet_v6_phase_f_h03_1800_3600_v1 as atomic_core
from scripts import p07_ntnu_window_fanout_v1 as record_core
from scripts import prepare_orbslam3_euroc_segment as euroc_core


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "aqua-fe-hfnet-v6-ntnu-positive-input-materialization-v1"
PREFLIGHT_SCHEMA_VERSION = "aqua-fe-hfnet-v6-ntnu-positive-input-preflight-v1"
SELECTOR_SCHEMA = "aqua-fe-hfnet-v6-ntnu-historical-positive-exact-window-selector-v1"

DEFAULT_SELECTOR = ROOT / "papers/hfnet_v6_ntnu_historical_positive_exact_window_selector_v1.json"
SELECTOR_SIZE = 7_480
SELECTOR_SHA256 = "ee6759123c50ed1e9ebbffecc205e75d5730d27afa5ee77e3fe1188ff9a04344"

DEFAULT_CONFIG = ROOT / "configs/published_baselines/hfnet_slam_ntnu_cam0_mono_inertial_v1.yaml"
CONFIG_SIZE = 2_228
CONFIG_SHA256 = "5b8b8d7ed6c010f25d4cf8d80ca24692b06de4cd17f4d19ae2a0cb9cc91a54dd"

REUSED_CODE = {
    ROOT / "scripts/materialize_hfnet_v6_phase_f_h03_1800_3600_v1.py": (
        38_774,
        "9146602be29e6faee2d13c91e25b01d2bc4081c11bbf419787128822275e584d",
    ),
    ROOT / "scripts/p07_ntnu_window_fanout_v1.py": (
        62_457,
        "6f2c557ff66a2a22222fc4665b0f202de5fc2d269cfc1160ca6b06c5d240d1e3",
    ),
    ROOT / "scripts/prepare_orbslam3_euroc_segment.py": (
        10_028,
        "fc396725c4e7e1245a6cc165bf1a10ee508b0a9b9cea87cd1a0860ab19709cb6",
    ),
}

CAMERA_TOPIC = "/alphasense_driver_ros/cam0"
IMU_TOPIC = "/alphasense_driver_ros/imu"
IMU_SHIFT_NS = -1_765_624
READER_MARGIN_NS = 500_000_000
MAX_HEADER_RECORD_DELTA_NS = 250_000_000
CAMERA_SCHEMA = {
    "width": 720,
    "height": 540,
    "encoding": "mono8",
    "step": 720,
    "is_bigendian": 0,
    "frame_id": "cam0_sensor_frame",
}
IMU_CSV_HEADER = (
    "#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],"
    "w_RS_S_z [rad s^-1],a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],"
    "a_RS_S_z [m s^-2]"
)


class ContractError(RuntimeError):
    """A source, frozen selector, synchronization, or no-clobber rule failed."""


@dataclass(frozen=True)
class WindowSpec:
    window_id: str
    sequence_id: str
    source_bag: Path
    source_size_bytes: int
    official_xet_cas_key: str
    local_full_file_sha256: str
    start_offset_ns: int
    end_offset_ns: int
    output_root: Path


@dataclass
class CameraSample:
    record_ns: int
    header_ns: int
    raw_payload_sha256: str
    message: Optional[Any] = None


@dataclass
class ImuSample:
    record_ns: int
    raw_header_ns: int
    shifted_header_ns: int
    values: Tuple[float, float, float, float, float, float]


@dataclass
class WindowScan:
    spec: WindowSpec
    mode: str
    source_begin_ns: int
    requested_record_bounds_ns: Tuple[int, int]
    camera_samples: List[CameraSample]
    imu_samples: List[ImuSample]
    dropped_leading_cameras_without_predecessor: int
    source_identity: Dict[str, Any]


def canonical_json(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def hash_file(path: Path, *, label: str) -> Dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"{label}_MISSING_OR_NOT_REGULAR")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return {"path": str(path.resolve()), "size_bytes": size, "sha256": digest.hexdigest()}


def require_file_pin(path: Path, size: int, digest: str, label: str) -> Dict[str, Any]:
    value = hash_file(path, label=label)
    if value["size_bytes"] != size or value["sha256"] != digest:
        raise ContractError(f"{label}_IDENTITY_MISMATCH")
    return value


def validate_reused_code() -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for path, (size, digest) in REUSED_CODE.items():
        result[path.name] = require_file_pin(path, size, digest, f"REUSED_{path.stem.upper()}")
    return result


def validate_config(path: Path = DEFAULT_CONFIG) -> Dict[str, Any]:
    identity = require_file_pin(path, CONFIG_SIZE, CONFIG_SHA256, "HFNET_CONFIG")
    text = path.read_text(encoding="utf-8")
    required = (
        'Camera.type: "KannalaBrandt8"',
        "Camera.width: 720",
        "Camera.height: 540",
        "Camera.fps: 20",
        "IMU.NoiseGyro: 0.000587",
        "IMU.NoiseAcc: 0.0186",
        "IMU.GyroWalk: 0.002866",
        "IMU.AccWalk: 0.00433",
        "IMU.Frequency: 200.0",
        'Extractor.type: "HFNetRT"',
        'Extractor.modelPath: "/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT/"',
        "Extractor.nFeatures: 675",
        "Extractor.threshold: 0.01",
        "loopClosing: 1",
        "0.0057458859421451467",
        "0.048394787222036377",
        "-0.0097706618631980095",
    )
    for token in required:
        if token not in text:
            raise ContractError(f"HFNET_CONFIG_REQUIRED_TOKEN_MISSING:{token}")
    if "-0.04828147993677678" in text:
        raise ContractError("HFNET_CONFIG_CONTAINS_WRONG_DIRECTION_T_CAM_IMU")
    return identity


def validate_selector(path: Path = DEFAULT_SELECTOR) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    identity = require_file_pin(path, SELECTOR_SIZE, SELECTOR_SHA256, "SELECTOR_FREEZE")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != SELECTOR_SCHEMA:
        raise ContractError("SELECTOR_SCHEMA_MISMATCH")
    if value.get("status") != "FROZEN_AFTER_READ_ONLY_SOURCE_PREFLIGHT_BEFORE_MATERIALIZATION_OR_HFNET_START":
        raise ContractError("SELECTOR_STATUS_MISMATCH")
    semantics = value.get("selection_semantics", {})
    required_semantics = {
        "camera_selection": "closed bag record-time interval [T0+start_offset_ns,T0+end_offset_ns]",
        "output_camera_timestamp": "original sensor_msgs/Image Header.stamp",
        "imu_time_transform": "output_ns=raw_imu_header_ns-1765624",
        "synthetic_or_extrapolated_imu_permitted": False,
        "camera_downsampling": False,
        "cold_start": True,
        "natural_history": False,
        "score_window_equals_feed_window": True,
    }
    for key, expected in required_semantics.items():
        if semantics.get(key) != expected:
            raise ContractError(f"SELECTOR_SEMANTICS_MISMATCH:{key}")
    if value.get("shared_inputs", {}).get("camera_schema") != CAMERA_SCHEMA:
        raise ContractError("SELECTOR_CAMERA_SCHEMA_MISMATCH")
    config = value.get("shared_inputs", {}).get("hfnet_config", {})
    if config.get("size_bytes") != CONFIG_SIZE or config.get("sha256") != CONFIG_SHA256:
        raise ContractError("SELECTOR_CONFIG_PIN_MISMATCH")
    windows = value.get("windows")
    if not isinstance(windows, dict) or set(windows) != {
        "fjord1_s83_d10",
        "mclab1_s60_d15",
        "mclab2_s110_d10",
    }:
        raise ContractError("SELECTOR_WINDOW_ROSTER_MISMATCH")
    if any(item is not False for item in value.get("claims", {}).values()):
        raise ContractError("SELECTOR_FORBIDDEN_CLAIM")
    for window_id, row in windows.items():
        source = row.get("source_bag", {})
        local_digest = source.get("local_full_file_sha256")
        xet_key = source.get("official_xet_cas_key")
        if not isinstance(local_digest, str) or len(local_digest) != 64:
            raise ContractError(f"SELECTOR_LOCAL_SOURCE_SHA256_INVALID:{window_id}")
        if not isinstance(xet_key, str) or len(xet_key) != 64:
            raise ContractError(f"SELECTOR_XET_CAS_KEY_INVALID:{window_id}")
        if local_digest == xet_key:
            raise ContractError(f"SELECTOR_LOCAL_SHA256_MISLABELLED_AS_XET_KEY:{window_id}")
    return value, identity


def production_specs(selector: Mapping[str, Any]) -> Dict[str, WindowSpec]:
    result: Dict[str, WindowSpec] = {}
    for window_id, row in selector["windows"].items():
        source = row["source_bag"]
        offsets = row["offsets_ns_closed"]
        result[window_id] = WindowSpec(
            window_id=window_id,
            sequence_id=str(row["sequence_id"]),
            source_bag=Path(source["path"]),
            source_size_bytes=int(source["size_bytes"]),
            official_xet_cas_key=str(source["official_xet_cas_key"]),
            local_full_file_sha256=str(source["local_full_file_sha256"]),
            start_offset_ns=int(offsets[0]),
            end_offset_ns=int(offsets[1]),
            output_root=Path(row["output_root"]),
        )
    return result


def _source_stat(path: Path, expected_size: int) -> Tuple[os.stat_result, Dict[str, Any]]:
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise ContractError("SOURCE_BAG_MISSING") from error
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise ContractError("SOURCE_BAG_NOT_REGULAR_OR_IS_SYMLINK")
    if info.st_size != expected_size:
        raise ContractError(f"SOURCE_BAG_SIZE_MISMATCH:{info.st_size}")
    identity = {
        "path": str(path.resolve()),
        "size_bytes": info.st_size,
        "device": info.st_dev,
        "inode": info.st_ino,
        "mtime_ns": info.st_mtime_ns,
        "content_pin_kind": "frozen local full-file SHA-256 plus exact size; SHA-256 recorded from a prior complete local read and not recomputed by this scan",
    }
    return info, identity


def verify_source_full_file_sha256(spec: WindowSpec) -> Dict[str, Any]:
    """Re-read the complete local bag before a materialization action."""

    observed = hash_file(spec.source_bag, label="SOURCE_BAG_FULL_FILE")
    if observed["size_bytes"] != spec.source_size_bytes:
        raise ContractError("SOURCE_BAG_FULL_FILE_SIZE_MISMATCH")
    if observed["sha256"] != spec.local_full_file_sha256:
        raise ContractError("SOURCE_BAG_FULL_FILE_SHA256_MISMATCH")
    return observed


def _deserialize_raw(raw: Any, *, topic: str) -> Any:
    if not isinstance(raw, tuple) or len(raw) not in (4, 5):
        raise ContractError(f"RAW_MESSAGE_TUPLE_INVALID:{topic}")
    serialized = raw[1]
    pytype = raw[4] if len(raw) == 5 else raw[3]
    if not isinstance(serialized, (bytes, bytearray)) or pytype is None:
        raise ContractError(f"RAW_MESSAGE_NOT_DESERIALIZABLE:{topic}")
    try:
        message = pytype()
        message.deserialize(serialized)
    except Exception as error:
        raise ContractError(f"RAW_MESSAGE_DESERIALIZATION_FAILED:{topic}") from error
    return message


def _header_ns(message: Any, *, topic: str) -> int:
    header = getattr(message, "header", None)
    stamp = getattr(header, "stamp", None)
    if stamp is None:
        raise ContractError(f"MESSAGE_HEADER_STAMP_MISSING:{topic}")
    return record_core._exact_time_ns(stamp, label=f"Header.stamp on {topic}")


def _camera_schema(message: Any) -> Dict[str, Any]:
    return {
        "width": int(message.width),
        "height": int(message.height),
        "encoding": str(message.encoding).lower(),
        "step": int(message.step),
        "is_bigendian": int(message.is_bigendian),
        "frame_id": str(message.header.frame_id),
    }


def _imu_values(message: Any) -> Tuple[float, float, float, float, float, float]:
    values = (
        float(message.angular_velocity.x),
        float(message.angular_velocity.y),
        float(message.angular_velocity.z),
        float(message.linear_acceleration.x),
        float(message.linear_acceleration.y),
        float(message.linear_acceleration.z),
    )
    if not all(math.isfinite(value) for value in values):
        raise ContractError("IMU_NONFINITE_VALUE")
    return values


def _mode_bounds(spec: WindowSpec, source_begin_ns: int, mode: str) -> Tuple[int, int]:
    if mode == "exact-window":
        lower = source_begin_ns + spec.start_offset_ns
    elif mode == "natural-history":
        lower = source_begin_ns
    else:
        raise ContractError(f"UNKNOWN_MODE:{mode}")
    upper = source_begin_ns + spec.end_offset_ns
    if upper <= lower:
        raise ContractError("INVALID_RECORD_BOUNDS")
    return lower, upper


def _assert_strict(values: Sequence[int], label: str) -> None:
    if any(right <= left for left, right in zip(values, values[1:])):
        raise ContractError(f"{label}_NOT_STRICTLY_INCREASING")


def scan_window(
    spec: WindowSpec,
    *,
    mode: str = "exact-window",
    retain_camera_messages: bool = False,
) -> WindowScan:
    """Read one source window without writing any artifact or starting a process."""

    before, source_identity = _source_stat(spec.source_bag, spec.source_size_bytes)
    source_identity["official_xet_cas_key"] = spec.official_xet_cas_key
    source_identity["local_full_file_sha256"] = spec.local_full_file_sha256
    source_identity["local_full_file_sha256_recomputed_this_action"] = False
    try:
        import rosbag
    except ImportError as error:  # pragma: no cover - environment gate
        raise ContractError("ROSBAG_PYTHON_UNAVAILABLE") from error

    cameras: List[CameraSample] = []
    margin_imus: List[ImuSample] = []
    with rosbag.Bag(str(spec.source_bag), "r") as bag:
        source_begin_ns = record_core._bag_begin_ns(bag)
        lower, upper = _mode_bounds(spec, source_begin_ns, mode)
        read_lower = max(source_begin_ns, lower - READER_MARGIN_NS)
        read_upper = upper + READER_MARGIN_NS
        previous_record = {CAMERA_TOPIC: -1, IMU_TOPIC: -1}
        previous_header = {CAMERA_TOPIC: -1, IMU_TOPIC: -1}
        messages = bag.read_messages(
            topics=[CAMERA_TOPIC, IMU_TOPIC],
            start_time=record_core._time_from_ns(read_lower),
            end_time=record_core._time_from_ns(read_upper),
            raw=True,
            return_connection_header=True,
        )
        for item in messages:
            topic = str(item.topic)
            if topic not in previous_record:
                raise ContractError(f"UNREQUESTED_TOPIC:{topic}")
            record_ns = record_core._exact_time_ns(item.timestamp, label="bag record stamp")
            if not read_lower <= record_ns <= read_upper:
                raise ContractError("ROSBAG_READER_BOUND_VIOLATION")
            if record_ns <= previous_record[topic]:
                raise ContractError(f"RECORD_TIME_NOT_STRICT:{topic}")
            previous_record[topic] = record_ns
            message = _deserialize_raw(item.message, topic=topic)
            header_ns = _header_ns(message, topic=topic)
            if header_ns <= previous_header[topic]:
                raise ContractError(f"HEADER_TIME_NOT_STRICT:{topic}")
            previous_header[topic] = header_ns

            if topic == CAMERA_TOPIC:
                if getattr(message, "_type", "") != "sensor_msgs/Image":
                    raise ContractError("CAMERA_MESSAGE_TYPE_MISMATCH")
                if not lower <= record_ns <= upper:
                    continue
                schema = _camera_schema(message)
                if schema != CAMERA_SCHEMA:
                    raise ContractError(f"CAMERA_SCHEMA_MISMATCH:{schema}")
                if abs(header_ns - record_ns) > MAX_HEADER_RECORD_DELTA_NS:
                    raise ContractError("CAMERA_HEADER_RECORD_DELTA_TOO_LARGE")
                raw_payload = bytes(message.data)
                if len(raw_payload) != CAMERA_SCHEMA["width"] * CAMERA_SCHEMA["height"]:
                    raise ContractError("CAMERA_PAYLOAD_SIZE_MISMATCH")
                cameras.append(
                    CameraSample(
                        record_ns=record_ns,
                        header_ns=header_ns,
                        raw_payload_sha256=hashlib.sha256(raw_payload).hexdigest(),
                        message=message if retain_camera_messages else None,
                    )
                )
            else:
                if getattr(message, "_type", "") != "sensor_msgs/Imu":
                    raise ContractError("IMU_MESSAGE_TYPE_MISMATCH")
                margin_imus.append(
                    ImuSample(
                        record_ns=record_ns,
                        raw_header_ns=header_ns,
                        shifted_header_ns=header_ns + IMU_SHIFT_NS,
                        values=_imu_values(message),
                    )
                )

    after = spec.source_bag.lstat()
    stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
        raise ContractError("SOURCE_BAG_IDENTITY_CHANGED_DURING_SCAN")
    if not cameras:
        raise ContractError("NO_CAMERA_MESSAGES_SELECTED")
    _assert_strict([sample.record_ns for sample in cameras], "CAMERA_RECORD")
    _assert_strict([sample.header_ns for sample in cameras], "CAMERA_HEADER")
    _assert_strict([sample.shifted_header_ns for sample in margin_imus], "SHIFTED_IMU_HEADER")

    shifted = [sample.shifted_header_ns for sample in margin_imus]
    dropped = 0
    while cameras and bisect.bisect_right(shifted, cameras[0].header_ns) == 0:
        cameras.pop(0)
        dropped += 1
    if not cameras:
        raise ContractError("NO_CAMERA_WITH_REAL_SHIFTED_IMU_PREDECESSOR")
    first_imu = bisect.bisect_right(shifted, cameras[0].header_ns) - 1
    last_imu = bisect.bisect_right(shifted, cameras[-1].header_ns)
    if first_imu < 0:
        raise ContractError("FIRST_CAMERA_LACKS_SHIFTED_IMU_PREDECESSOR")
    if last_imu >= len(margin_imus):
        raise ContractError("LAST_CAMERA_LACKS_SHIFTED_IMU_SUCCESSOR")
    imus = margin_imus[first_imu : last_imu + 1]
    if len(imus) < 2:
        raise ContractError("TOO_FEW_IMU_SAMPLES")
    if not (
        imus[0].shifted_header_ns <= cameras[0].header_ns < imus[1].shifted_header_ns
        and imus[-2].shifted_header_ns <= cameras[-1].header_ns < imus[-1].shifted_header_ns
    ):
        raise ContractError("IMU_READER_BRACKET_INVALID")
    imu_span = (imus[-1].shifted_header_ns - imus[0].shifted_header_ns) / 1e9
    imu_rate = (len(imus) - 1) / imu_span
    if not 150.0 <= imu_rate <= 250.0:
        raise ContractError(f"IMU_RATE_OUT_OF_RANGE:{imu_rate}")

    return WindowScan(
        spec=spec,
        mode=mode,
        source_begin_ns=source_begin_ns,
        requested_record_bounds_ns=(lower, upper),
        camera_samples=cameras,
        imu_samples=imus,
        dropped_leading_cameras_without_predecessor=dropped,
        source_identity=source_identity,
    )


def _range(values: Sequence[int]) -> List[int]:
    return [min(values), max(values)]


def scan_summary(scan: WindowScan) -> Dict[str, Any]:
    cameras = scan.camera_samples
    imus = scan.imu_samples
    deltas = [sample.header_ns - sample.record_ns for sample in cameras]
    imu_rate = (len(imus) - 1) / ((imus[-1].shifted_header_ns - imus[0].shifted_header_ns) / 1e9)
    return {
        "window_id": scan.spec.window_id,
        "sequence_id": scan.spec.sequence_id,
        "mode": scan.mode,
        "source": scan.source_identity,
        "source_bag_first_record_ns": scan.source_begin_ns,
        "requested_record_bounds_ns_closed": list(scan.requested_record_bounds_ns),
        "camera": {
            "count": len(cameras),
            "record_ns_inclusive": [cameras[0].record_ns, cameras[-1].record_ns],
            "header_ns_inclusive": [cameras[0].header_ns, cameras[-1].header_ns],
            "header_minus_record_ns_range": _range(deltas),
            "schema": CAMERA_SCHEMA,
            "record_timestamps_strictly_increasing": True,
            "header_timestamps_strictly_increasing": True,
            "selected_by_record_time": True,
            "output_named_by_header_time": True,
            "dropped_leading_without_real_shifted_imu_predecessor": scan.dropped_leading_cameras_without_predecessor,
        },
        "imu": {
            "count": len(imus),
            "record_ns_inclusive": [imus[0].record_ns, imus[-1].record_ns],
            "raw_header_ns_inclusive": [imus[0].raw_header_ns, imus[-1].raw_header_ns],
            "shifted_header_ns_inclusive": [imus[0].shifted_header_ns, imus[-1].shifted_header_ns],
            "time_transform": "output_ns=raw_imu_header_ns-1765624",
            "shift_ns": IMU_SHIFT_NS,
            "observed_rate_hz": imu_rate,
            "timestamps_strictly_increasing": True,
            "reader_brackets_first_and_last_camera": True,
            "synthetic_or_extrapolated_samples": False,
        },
    }


def enforce_exact_selector(scan: WindowScan, frozen: Mapping[str, Any]) -> None:
    if scan.mode != "exact-window":
        raise ContractError("EXACT_SELECTOR_CANNOT_VALIDATE_NATURAL_HISTORY")
    summary = scan_summary(scan)
    checks = {
        "source_bag_first_record_ns": (summary["source_bag_first_record_ns"], frozen["source_bag_first_record_ns"]),
        "absolute_record_bounds_ns_closed": (summary["requested_record_bounds_ns_closed"], frozen["absolute_record_bounds_ns_closed"]),
        "camera.count": (summary["camera"]["count"], frozen["camera"]["count"]),
        "camera.record_ns_inclusive": (summary["camera"]["record_ns_inclusive"], frozen["camera"]["record_ns_inclusive"]),
        "camera.header_ns_inclusive": (summary["camera"]["header_ns_inclusive"], frozen["camera"]["header_ns_inclusive"]),
        "camera.header_minus_record_ns_range": (summary["camera"]["header_minus_record_ns_range"], frozen["camera"]["header_minus_record_ns_range"]),
        "imu.count": (summary["imu"]["count"], frozen["imu"]["count"]),
        "imu.record_ns_inclusive": (summary["imu"]["record_ns_inclusive"], frozen["imu"]["record_ns_inclusive"]),
        "imu.raw_header_ns_inclusive": (summary["imu"]["raw_header_ns_inclusive"], frozen["imu"]["raw_header_ns_inclusive"]),
        "imu.shifted_header_ns_inclusive": (summary["imu"]["shifted_header_ns_inclusive"], frozen["imu"]["shifted_header_ns_inclusive"]),
    }
    for label, (observed, expected) in checks.items():
        if observed != expected:
            raise ContractError(f"FROZEN_BOUNDARY_MISMATCH:{label}:{observed!r}")
    if scan.dropped_leading_cameras_without_predecessor != 0:
        raise ContractError("EXACT_WINDOW_UNEXPECTED_CAMERA_DROP")


def _times_payload(samples: Sequence[CameraSample]) -> bytes:
    return "".join(f"{sample.header_ns}\n" for sample in samples).encode("ascii")


def _camera_csv_payload(samples: Sequence[CameraSample]) -> bytes:
    lines = ["#timestamp [ns],filename"]
    lines.extend(f"{sample.header_ns},{sample.header_ns}.png" for sample in samples)
    return ("\n".join(lines) + "\n").encode("ascii")


def _imu_csv_payload(samples: Sequence[ImuSample]) -> bytes:
    lines = [IMU_CSV_HEADER]
    for sample in samples:
        values = ",".join(format(value, ".17g") for value in sample.values)
        lines.append(f"{sample.shifted_header_ns},{values}")
    return "\n".join(lines).encode("ascii")


def preflight_one(
    spec: WindowSpec,
    frozen: Mapping[str, Any],
    *,
    selector_identity: Mapping[str, Any],
    config_identity: Mapping[str, Any],
    reused_code: Mapping[str, Any],
    mode: str = "exact-window",
) -> Dict[str, Any]:
    if spec.output_root.exists() or spec.output_root.is_symlink():
        raise ContractError(f"NO_CLOBBER_OUTPUT_EXISTS:{spec.output_root}")
    scan = scan_window(spec, mode=mode, retain_camera_messages=False)
    if mode == "exact-window":
        enforce_exact_selector(scan, frozen)
        status = "PREFLIGHT_READY_EXACT_WINDOW_PREPARATION_ONLY"
    else:
        status = "PREFLIGHT_SECONDARY_NATURAL_HISTORY_UNFROZEN_NOT_MATERIALIZABLE"
    return {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "status": status,
        "selector_freeze": selector_identity,
        "hfnet_config": config_identity,
        "reused_code": reused_code,
        "output_root": str(spec.output_root.resolve(strict=False)),
        "scan": scan_summary(scan),
        "reporting_boundary": "input preparation only; no trajectory, accuracy, or comparison",
        "claims": {
            "output_created": False,
            "hfnet_started": False,
            "vins_started": False,
            "trajectory_produced": False,
            "accuracy_measured": False,
        },
    }


def materialize_one(
    spec: WindowSpec,
    frozen: Mapping[str, Any],
    *,
    selector_identity: Mapping[str, Any],
    config_identity: Mapping[str, Any],
    reused_code: Mapping[str, Any],
    mode: str = "exact-window",
) -> Dict[str, Any]:
    if mode != "exact-window":
        raise ContractError("NATURAL_HISTORY_REQUIRES_SEPARATE_SELECTOR_FREEZE")
    if spec.output_root.exists() or spec.output_root.is_symlink():
        raise ContractError(f"NO_CLOBBER_OUTPUT_EXISTS:{spec.output_root}")
    source_full_identity = verify_source_full_file_sha256(spec)
    scan = scan_window(spec, mode=mode, retain_camera_messages=True)
    scan.source_identity["local_full_file_sha256"] = source_full_identity["sha256"]
    scan.source_identity["local_full_file_sha256_recomputed_this_action"] = True
    enforce_exact_selector(scan, frozen)

    try:
        import cv2
        from cv_bridge import CvBridge
    except ImportError as error:  # pragma: no cover - environment gate
        raise ContractError("CV2_OR_CV_BRIDGE_UNAVAILABLE") from error

    times_payload = _times_payload(scan.camera_samples)
    camera_csv_payload = _camera_csv_payload(scan.camera_samples)
    imu_csv_payload = _imu_csv_payload(scan.imu_samples)
    generated = {
        "cam0_times": atomic_core.identity_bytes("cam0_times.txt", times_payload),
        "cam0_data_csv": atomic_core.identity_bytes("mav0/cam0/data.csv", camera_csv_payload),
        "imu0_data_csv": atomic_core.identity_bytes("mav0/imu0/data.csv", imu_csv_payload),
    }

    bridge = CvBridge()
    with atomic_core.atomic_directory(spec.output_root) as staging:
        image_rows: List[Dict[str, Any]] = []
        for sample in scan.camera_samples:
            if sample.message is None:
                raise ContractError("RETAINED_CAMERA_MESSAGE_MISSING")
            image = euroc_core.to_mono8(bridge, sample.message)
            if hashlib.sha256(image.tobytes()).hexdigest() != sample.raw_payload_sha256:
                raise ContractError("GENERIC_EUROC_MONO8_BYTES_DIFFER_FROM_SOURCE")
            ok, encoded = cv2.imencode(".png", image)
            if not ok:
                raise ContractError("PNG_ENCODING_FAILED")
            payload = bytes(encoded)
            relative = f"mav0/cam0/data/{sample.header_ns}.png"
            atomic_core.write_exclusive_bytes(staging / relative, payload)
            image_rows.append(
                {
                    **atomic_core.identity_bytes(relative, payload),
                    "source_record_ns": sample.record_ns,
                    "source_header_ns": sample.header_ns,
                    "source_mono8_sha256": sample.raw_payload_sha256,
                }
            )

        atomic_core.write_exclusive_bytes(staging / "cam0_times.txt", times_payload)
        atomic_core.write_exclusive_bytes(staging / "mav0/cam0/data.csv", camera_csv_payload)
        atomic_core.write_exclusive_bytes(staging / "mav0/imu0/data.csv", imu_csv_payload)
        payload_rows: List[Mapping[str, Any]] = list(image_rows)
        payload_rows.extend(generated.values())
        payload_identity = atomic_core.aggregate_identities(payload_rows)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_EXACT_WINDOW_PREPARATION_ONLY",
            "window_id": spec.window_id,
            "sequence_id": spec.sequence_id,
            "output_root": str(spec.output_root.resolve(strict=False)),
            "selector_freeze": selector_identity,
            "hfnet_config": config_identity,
            "reused_code": reused_code,
            "scan": scan_summary(scan),
            "camera": {
                "copy_policy": "generic bag-to-EuRoC mono8 conversion followed by lossless PNG encoding",
                "selection_clock": "bag record time",
                "output_timestamp_clock": "original camera Header.stamp",
                "files": image_rows,
            },
            "generated_files": generated,
            "imu": {
                "csv_header": IMU_CSV_HEADER,
                "measurement_values_preserved": True,
                "axis_transform": "none",
                "timestamp_shift_ns": IMU_SHIFT_NS,
                "synthetic_or_extrapolated_samples": False,
                "final_newline": False,
            },
            "payload_file_count_excluding_manifest": len(image_rows) + 3,
            "payload_identity_excluding_manifest": payload_identity,
            "reporting_boundary": "outcome-selected exact-window input preparation only; no trajectory, accuracy, or comparison",
            "claims": {
                "runner_created": False,
                "start_claim_created": False,
                "hfnet_started": False,
                "vins_started": False,
                "detector_started": False,
                "evaluator_started": False,
                "trajectory_produced": False,
                "accuracy_measured": False,
                "scientific_comparison_produced": False,
            },
        }
        atomic_core.write_exclusive_bytes(
            staging / "materialization_manifest.json", canonical_json(manifest)
        )
        for directory in (
            staging / "mav0/cam0/data",
            staging / "mav0/cam0",
            staging / "mav0/imu0",
            staging / "mav0",
            staging,
        ):
            atomic_core.fsync_directory(directory)
    return manifest


def _run(argv: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("preflight", "materialize"), default="preflight")
    parser.add_argument(
        "--window",
        choices=("all", "fjord1_s83_d10", "mclab1_s60_d15", "mclab2_s110_d10"),
        default="all",
    )
    parser.add_argument("--mode", choices=("exact-window", "natural-history"), default="exact-window")
    parser.add_argument("--selector-freeze", type=Path, default=DEFAULT_SELECTOR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)

    selector, selector_identity = validate_selector(args.selector_freeze)
    config_identity = validate_config(args.config)
    reused_code = validate_reused_code()
    specs = production_specs(selector)
    if args.action == "materialize" and args.window == "all":
        raise ContractError("MATERIALIZE_REQUIRES_ONE_EXPLICIT_WINDOW")
    selected = list(specs) if args.window == "all" else [args.window]
    results = []
    for window_id in selected:
        spec = specs[window_id]
        frozen = selector["windows"][window_id]
        if args.action == "materialize":
            value = materialize_one(
                spec,
                frozen,
                selector_identity=selector_identity,
                config_identity=config_identity,
                reused_code=reused_code,
                mode=args.mode,
            )
        else:
            value = preflight_one(
                spec,
                frozen,
                selector_identity=selector_identity,
                config_identity=config_identity,
                reused_code=reused_code,
                mode=args.mode,
            )
        results.append(value)
    return {
        "schema_version": PREFLIGHT_SCHEMA_VERSION if args.action == "preflight" else SCHEMA_VERSION,
        "status": "PASS_PREPARATION_PREFLIGHT" if args.action == "preflight" else "PASS_MATERIALIZATION",
        "action": args.action,
        "mode": args.mode,
        "results": results,
        "claims": {"hfnet_started": False, "trajectory_produced": False, "accuracy_measured": False},
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        result = _run(argv)
        return_code = 0
    except Exception as error:
        result = {
            "schema_version": PREFLIGHT_SCHEMA_VERSION,
            "status": "INTEGRITY_ERROR",
            "errors": [f"{type(error).__name__}:{error}"],
            "claims": {"hfnet_started": False, "trajectory_produced": False, "accuracy_measured": False},
        }
        return_code = 2
    sys.stdout.buffer.write(canonical_json(result))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
