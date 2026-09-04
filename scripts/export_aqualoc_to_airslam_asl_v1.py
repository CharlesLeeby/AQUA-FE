#!/usr/bin/env python3
"""Fail-closed underwater-data adapter for stock, paper-era AirSLAM.

This adapter deliberately has two profiles:

* ``aqualoc-a02-0005`` is an incompatibility witness.  A02 has one camera,
  while stock AirSLAM requires two independent, timestamp-paired cameras.
  No export action is permitted for this profile.
* ``ntnu-fjord6-0001`` exports the frozen 45 s NTNU window as an ASL-style
  stereo/IMU directory.  It is a different-input whole-system baseline and
  must be reported separately from monocular A02 comparisons.

The program never edits AirSLAM.  It binds the conversion to the official
paper-era commit and source hashes, uses ROS header timestamps for sensor
time, shifts IMU stamps into the cam0 clock domain, and publishes a complete
directory only after every integrity check succeeds.

The default action is read-only preflight.  ``smoke-prefix`` creates a small,
explicitly non-evaluable input artifact.  ``export-window`` is the only action
that can materialize all 900 stereo pairs; callers should schedule it as a
separate, deliberate operation because the source bag is 26.6 GB.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


ADAPTER_VERSION = "airslam-asl-adapter-v1"
AIRSLAM_COMMIT = "2b825166b05b351fc708c70cee3fc8b5a5b380e9"
AIRSLAM_FILE_HASHES = {
    "src/camera.cc": "ead3c40931c9a243430eedcfd3e0cdac6766173eb210b56b2fabec03480c0e85",
    "src/dataset.cc": "e1e9faf602d6d80fd3ccfc080639139f411eafea2e9a8320866c69329948c7d4",
    "src/frame.cc": "0277d3b07c99ef6cc95dc1f7833cc456a00964f035cfe9774c10182dddf06545",
    "src/map_builder.cc": "0d252f40d3440ed58590feb21147a7d304dd37f84c336d3fa0931babd92cff69",
    "src/utils.cc": "e1e4bd322e5c00cde2a88b9556cea4211f345121a93ebfc233c305e9ec84843c",
    "configs/camera/euroc.yaml": "9389b5d73f436df8387217b34105f12b48687ae6ffbbd9fb02a701a65f7b0e35",
    "configs/visual_odometry/vo_euroc.yaml": "cd3903a45ed897987292a137dbe64d993d671e0ab04fd6802da519b300bfdb80",
}

READY = "READY_FOR_EXPORT_SCAN"
BLOCKED = "COMPATIBILITY_BLOCKED"
INTEGRITY_ERROR = "INTEGRITY_ERROR"
EXPORTED = "EXPORTED"

EXIT_READY = 0
EXIT_BLOCKED = 2
EXIT_INTEGRITY = 3

WORKSPACE_DEFAULT = Path(__file__).resolve().parents[1]
AIRSLAM_ROOT_DEFAULT = Path.home() / "SLAM" / "AirSLAM-paper-2025-r1"


class ContractError(RuntimeError):
    """An input violates a frozen adapter contract."""


@dataclass(frozen=True)
class Profile:
    name: str
    dataset_family: str
    sequence: str
    window_id: str
    bag_relpath: str
    expected_bag_size: int
    cam0_topic: str
    cam1_topic: str | None
    imu_topic: str
    camera_calib_relpath: str
    imucam_calib_relpath: str
    imu_calib_relpath: str
    record_start_ns: int | None
    record_end_ns: int | None
    expected_stereo_pairs: int | None
    expected_width: int
    expected_height: int
    reference_relpath: str | None
    reference_semantics: str
    reporting_class: str


PROFILES = {
    "aqualoc-a02-0005": Profile(
        name="aqualoc-a02-0005",
        dataset_family="aqualoc",
        sequence="archaeology_A02",
        window_id="aqualoc:archaeology_A02:0005",
        bag_relpath="datasets/aqualoc/rosbags/archaeo02_4500_5400.bag",
        expected_bag_size=222_477_260,
        cam0_topic="/camera/image_raw",
        cam1_topic=None,
        imu_topic="/rtimulib_node/imu",
        camera_calib_relpath=(
            "datasets/full_downloads/aqualoc/Archaeological_site_sequences/"
            "archaeo_calibration_files/archaeo_camera_calib.yaml"
        ),
        imucam_calib_relpath=(
            "datasets/full_downloads/aqualoc/Archaeological_site_sequences/"
            "archaeo_calibration_files/archaeo_imu_camera_calib.yaml"
        ),
        imu_calib_relpath=(
            "datasets/full_downloads/aqualoc/Archaeological_site_sequences/"
            "archaeo_calibration_files/archaeo_imu_noises.yaml"
        ),
        record_start_ns=None,
        record_end_ns=None,
        expected_stereo_pairs=None,
        expected_width=968,
        expected_height=608,
        reference_relpath=None,
        reference_semantics="/aqualoc/colmap_gt in the bag; monocular A02 comparison reference",
        reporting_class="A02_SAME_INPUT_INELIGIBLE",
    ),
    "ntnu-fjord6-0001": Profile(
        name="ntnu-fjord6-0001",
        dataset_family="ntnu",
        sequence="fjord_6",
        window_id="ntnu:fjord_6:0001",
        bag_relpath=(
            "datasets/full_downloads/ntnu_hf/subset-fjord/fjord_6/fjord_6.bag"
        ),
        expected_bag_size=26_567_323_609,
        cam0_topic="/alphasense_driver_ros/cam0",
        cam1_topic="/alphasense_driver_ros/cam1",
        imu_topic="/alphasense_driver_ros/imu",
        camera_calib_relpath=(
            "datasets/full_downloads/ntnu_hf/calibrations/cam0_cam1_stereo/"
            "intrinsics_water/camchain-stereo-intrinsics-underwater.yaml"
        ),
        imucam_calib_relpath=(
            "datasets/full_downloads/ntnu_hf/calibrations/cam0_cam1_stereo/"
            "extrinsics_air/camchain-imucam-stereo-extrinsics-air.yaml"
        ),
        imu_calib_relpath=(
            "datasets/full_downloads/ntnu_hf/calibrations/cam0_cam1_stereo/"
            "extrinsics_air/imu0_alphasense_noise.yaml"
        ),
        # Exact ROS bag record-time interval selected by --start 45 --duration 45.
        record_start_ns=1_700_603_752_886_577_184,
        record_end_ns=1_700_603_797_886_577_184,
        expected_stereo_pairs=900,
        expected_width=720,
        expected_height=540,
        reference_relpath=(
            "datasets/full_downloads/ntnu_hf/subset-fjord/fjord_6/"
            "fjord_6_baseline.tum"
        ),
        reference_semantics=(
            "ReAqROVIO four-camera+IMU world_T_cam0 reference proxy; "
            "not independent ground truth"
        ),
        reporting_class="SEPARATE_WHOLE_SYSTEM_STEREO_VI_DIFFERENT_INPUT",
    ),
}


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(data: Mapping[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n"


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.tmp-", dir=str(path.parent))
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


@contextmanager
def atomic_directory(target: Path) -> Iterator[Path]:
    """Yield a sibling staging directory and rename it only on success."""

    if target.exists() or target.is_symlink():
        raise ContractError(f"OUTPUT_ALREADY_EXISTS:{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.tmp-", dir=str(target.parent))
    )
    committed = False
    try:
        yield staging
        if target.exists() or target.is_symlink():
            raise ContractError(f"OUTPUT_APPEARED_DURING_EXPORT:{target}")
        os.rename(staging, target)
        committed = True
    finally:
        if not committed:
            shutil.rmtree(staging, ignore_errors=True)


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment gate
        raise ContractError("PYTHON_YAML_UNAVAILABLE") from exc
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"YAML_ROOT_NOT_MAPPING:{path}")
    return value


def dump_yaml(path: Path, value: Mapping[str, Any]) -> None:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment gate
        raise ContractError("PYTHON_YAML_UNAVAILABLE") from exc
    path.write_text(
        yaml.safe_dump(dict(value), sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def ros_time_to_ns(stamp: Any) -> int:
    if hasattr(stamp, "to_nsec"):
        return int(stamp.to_nsec())
    secs = getattr(stamp, "secs", getattr(stamp, "sec", None))
    nsecs = getattr(stamp, "nsecs", getattr(stamp, "nanosec", None))
    if secs is None or nsecs is None:
        raise ContractError("ROS_TIME_FIELDS_MISSING")
    return int(secs) * 1_000_000_000 + int(nsecs)


def ns_to_ros_time(stamp_ns: int) -> Any:
    try:
        import genpy
    except ImportError as exc:  # pragma: no cover - environment gate
        raise ContractError("GENPY_UNAVAILABLE") from exc
    return genpy.Time(stamp_ns // 1_000_000_000, stamp_ns % 1_000_000_000)


def shift_imu_timestamp_ns(raw_imu_header_ns: int, timeshift_cam_imu_s: float) -> int:
    """Put IMU data in cam0 time: t_out = t_imu_raw - td(cam0, imu)."""

    if not math.isfinite(timeshift_cam_imu_s):
        raise ContractError("NONFINITE_CAM_IMU_TIMESHIFT")
    return int(raw_imu_header_ns) - int(round(timeshift_cam_imu_s * 1e9))


def airslam_string_time_to_seconds(text: str) -> float:
    """Python model of AirSLAM's paper-era StringTimeToDouble parser."""

    compact = text.replace(".", "")
    return float(compact[:10]) + float("0." + compact[10:])


def audit_airslam_checkout(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    actual_hashes: dict[str, str | None] = {}
    if not root.is_dir():
        return {
            "root": str(root),
            "expected_commit": AIRSLAM_COMMIT,
            "actual_commit": None,
            "file_hashes": actual_hashes,
            "errors": ["AIRSLAM_ROOT_MISSING"],
        }
    process = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    actual_commit = process.stdout.strip() if process.returncode == 0 else None
    if actual_commit != AIRSLAM_COMMIT:
        errors.append("AIRSLAM_COMMIT_MISMATCH")
    for relative, expected in AIRSLAM_FILE_HASHES.items():
        path = root / relative
        actual = sha256_file(path) if path.is_file() else None
        actual_hashes[relative] = actual
        if actual != expected:
            errors.append(f"AIRSLAM_FILE_HASH_MISMATCH:{relative}")
    return {
        "root": str(root),
        "expected_commit": AIRSLAM_COMMIT,
        "actual_commit": actual_commit,
        "expected_file_hashes": AIRSLAM_FILE_HASHES,
        "actual_file_hashes": actual_hashes,
        "errors": errors,
    }


def _bag_header_fields(payload: bytes) -> dict[str, bytes]:
    """Decode the length-prefixed key/value fields used by ROS bag v2."""

    offset = 0
    result: dict[str, bytes] = {}
    while offset < len(payload):
        if offset + 4 > len(payload):
            raise ContractError("TRUNCATED_ROSBAG_HEADER_FIELD_LENGTH")
        field_length = struct.unpack_from("<I", payload, offset)[0]
        offset += 4
        end = offset + field_length
        if end > len(payload):
            raise ContractError("TRUNCATED_ROSBAG_HEADER_FIELD")
        field = payload[offset:end]
        offset = end
        if b"=" not in field:
            raise ContractError("INVALID_ROSBAG_HEADER_FIELD")
        key, value = field.split(b"=", 1)
        result[key.decode("ascii")] = value
    return result


def _unpack_bag_field(fields: Mapping[str, bytes], key: str, fmt: str) -> int:
    value = fields.get(key)
    if value is None or len(value) != struct.calcsize(fmt):
        raise ContractError(f"INVALID_ROSBAG_FIELD:{key}")
    return int(struct.unpack(fmt, value)[0])


def _read_bag_record(handle: Any) -> tuple[dict[str, bytes], bytes] | None:
    prefix = handle.read(4)
    if not prefix:
        return None
    if len(prefix) != 4:
        raise ContractError("TRUNCATED_ROSBAG_RECORD_HEADER_LENGTH")
    header_length = struct.unpack("<I", prefix)[0]
    header_payload = handle.read(header_length)
    if len(header_payload) != header_length:
        raise ContractError("TRUNCATED_ROSBAG_RECORD_HEADER")
    data_length_payload = handle.read(4)
    if len(data_length_payload) != 4:
        raise ContractError("TRUNCATED_ROSBAG_RECORD_DATA_LENGTH")
    data_length = struct.unpack("<I", data_length_payload)[0]
    data = handle.read(data_length)
    if len(data) != data_length:
        raise ContractError("TRUNCATED_ROSBAG_RECORD_DATA")
    return _bag_header_fields(header_payload), data


def inspect_bag_topics(path: Path) -> dict[str, dict[str, Any]]:
    """Read topic types/counts from the bag footer without decoding chunks.

    ``rosbag.Bag`` eagerly loads every per-message index entry.  That took tens
    of seconds and substantial memory for the 26.6 GB NTNU bag even though a
    preflight only needs the 16 connection records and 23,935 small chunk-info
    records.  ROS bag v2 stores both at ``index_pos``; reading that footer is
    exact, read-only, and completed in about 0.2 s on the frozen bag.
    """

    connections: dict[int, tuple[str, str]] = {}
    counts: dict[int, int] = {}
    with path.open("rb") as handle:
        if handle.readline() != b"#ROSBAG V2.0\n":
            raise ContractError("UNSUPPORTED_ROSBAG_MAGIC")
        file_header_record = _read_bag_record(handle)
        if file_header_record is None:
            raise ContractError("ROSBAG_FILE_HEADER_MISSING")
        file_header, _ = file_header_record
        if file_header.get("op") != b"\x03":
            raise ContractError("ROSBAG_FILE_HEADER_OP_MISMATCH")
        index_pos = _unpack_bag_field(file_header, "index_pos", "<Q")
        expected_connections = _unpack_bag_field(
            file_header, "conn_count", "<I"
        )
        expected_chunks = _unpack_bag_field(file_header, "chunk_count", "<I")
        handle.seek(index_pos)
        chunk_count = 0
        while True:
            record = _read_bag_record(handle)
            if record is None:
                break
            header, data = record
            op = header.get("op")
            if op == b"\x07":  # CONNECTION
                connection_id = _unpack_bag_field(header, "conn", "<I")
                topic_raw = header.get("topic")
                if topic_raw is None:
                    raise ContractError("ROSBAG_CONNECTION_TOPIC_MISSING")
                connection_data = _bag_header_fields(data)
                message_type = connection_data.get("type", b"").decode("utf-8")
                connections[connection_id] = (
                    topic_raw.decode("utf-8"),
                    message_type,
                )
            elif op == b"\x06":  # CHUNK_INFO
                chunk_count += 1
                entry_count = _unpack_bag_field(header, "count", "<I")
                if len(data) != entry_count * 8:
                    raise ContractError("ROSBAG_CHUNK_INFO_SIZE_MISMATCH")
                for index in range(entry_count):
                    connection_id, message_count = struct.unpack_from(
                        "<II", data, index * 8
                    )
                    counts[connection_id] = counts.get(connection_id, 0) + message_count
        if len(connections) != expected_connections:
            raise ContractError("ROSBAG_CONNECTION_COUNT_MISMATCH")
        if chunk_count != expected_chunks:
            raise ContractError("ROSBAG_CHUNK_COUNT_MISMATCH")

    result: dict[str, dict[str, Any]] = {}
    for connection_id, (topic, message_type) in connections.items():
        row = result.setdefault(
            topic, {"message_type": message_type, "message_count": 0}
        )
        if row["message_type"] != message_type:
            raise ContractError(f"MULTIPLE_MESSAGE_TYPES_FOR_TOPIC:{topic}")
        row["message_count"] += counts.get(connection_id, 0)
    return result


def modal_blockers(
    cam0_topic: str,
    cam1_topic: str | None,
    imu_topic: str,
    discovered_topics: Mapping[str, Any],
    calibrated_cameras: Sequence[str],
) -> list[str]:
    blockers: list[str] = []
    if not cam1_topic:
        blockers.append("AIRSLAM_REQUIRES_INDEPENDENT_CAM1_TOPIC")
    elif cam1_topic == cam0_topic:
        blockers.append("CAM0_CAM1_TOPIC_ALIAS_FORBIDDEN")
    if cam0_topic not in discovered_topics:
        blockers.append("CAM0_TOPIC_MISSING")
    if cam1_topic and cam1_topic not in discovered_topics:
        blockers.append("CAM1_TOPIC_MISSING")
    if imu_topic not in discovered_topics:
        blockers.append("IMU_TOPIC_MISSING")
    if "cam0" not in calibrated_cameras:
        blockers.append("CAM0_CALIBRATION_MISSING")
    if "cam1" not in calibrated_cameras:
        blockers.append("AIRSLAM_REQUIRES_CAM1_CALIBRATION")
    return blockers


def _require_camera_node(
    node: Mapping[str, Any], name: str, topic: str, width: int, height: int
) -> None:
    if node.get("rostopic") != topic:
        raise ContractError(f"CALIBRATION_TOPIC_MISMATCH:{name}")
    if node.get("camera_model") != "pinhole":
        raise ContractError(f"UNSUPPORTED_CAMERA_MODEL:{name}")
    if node.get("resolution") != [width, height]:
        raise ContractError(f"CALIBRATION_RESOLUTION_MISMATCH:{name}")
    intrinsics = node.get("intrinsics")
    distortion = node.get("distortion_coeffs")
    if not isinstance(intrinsics, list) or len(intrinsics) != 4:
        raise ContractError(f"INVALID_INTRINSICS:{name}")
    if not isinstance(distortion, list) or len(distortion) != 4:
        raise ContractError(f"INVALID_DISTORTION:{name}")
    if not all(math.isfinite(float(item)) for item in intrinsics + distortion):
        raise ContractError(f"NONFINITE_CAMERA_CALIBRATION:{name}")


def _matrix4(value: Any, label: str) -> Any:
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - environment gate
        raise ContractError("NUMPY_UNAVAILABLE") from exc
    matrix = np.asarray(value, dtype=float)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise ContractError(f"INVALID_TRANSFORM:{label}")
    if not np.allclose(matrix[3], [0.0, 0.0, 0.0, 1.0], atol=1e-9):
        raise ContractError(f"INVALID_HOMOGENEOUS_ROW:{label}")
    if not np.allclose(matrix[:3, :3].T @ matrix[:3, :3], np.eye(3), atol=1e-5):
        raise ContractError(f"NON_ORTHONORMAL_ROTATION:{label}")
    if not math.isclose(float(np.linalg.det(matrix[:3, :3])), 1.0, abs_tol=1e-5):
        raise ContractError(f"INVALID_ROTATION_DETERMINANT:{label}")
    return matrix


def validate_ntnu_calibrations(
    profile: Profile,
    camera_calib: Mapping[str, Any],
    imucam_calib: Mapping[str, Any],
    imu_calib: Mapping[str, Any],
) -> dict[str, Any]:
    if profile.cam1_topic is None:
        raise ContractError("NTNU_PROFILE_REQUIRES_CAM1")
    for name, topic in (("cam0", profile.cam0_topic), ("cam1", profile.cam1_topic)):
        camera_node = camera_calib.get(name)
        imucam_node = imucam_calib.get(name)
        if not isinstance(camera_node, dict) or not isinstance(imucam_node, dict):
            raise ContractError(f"CAMERA_CALIBRATION_MISSING:{name}")
        _require_camera_node(
            camera_node, name, topic, profile.expected_width, profile.expected_height
        )
        if camera_node.get("distortion_model") != "equidistant":
            raise ContractError(f"NTNU_WATER_EQUIDISTANT_CALIBRATION_REQUIRED:{name}")
        if imucam_node.get("rostopic") != topic:
            raise ContractError(f"IMUCAM_TOPIC_MISMATCH:{name}")
        _matrix4(imucam_node.get("T_cam_imu"), f"{name}.T_cam_imu")
        td = float(imucam_node.get("timeshift_cam_imu"))
        if not math.isfinite(td):
            raise ContractError(f"NONFINITE_CAM_IMU_TIMESHIFT:{name}")

    relative_water = _matrix4(
        camera_calib["cam1"].get("T_cn_cnm1"), "water.T_c1_c0"
    )
    baseline_m = float((relative_water[:3, 3] ** 2).sum() ** 0.5)
    if not 0.05 < baseline_m < 0.5:
        raise ContractError("IMPLAUSIBLE_STEREO_BASELINE")
    td0 = float(imucam_calib["cam0"]["timeshift_cam_imu"])
    td1 = float(imucam_calib["cam1"]["timeshift_cam_imu"])
    if abs(td1 - td0) > 1e-3:
        raise ContractError("CAMERA_TIMESHIFT_DISAGREEMENT")
    if imu_calib.get("rostopic") != profile.imu_topic:
        raise ContractError("IMU_CALIBRATION_TOPIC_MISMATCH")
    rate_hz = float(imu_calib.get("update_rate"))
    if not math.isclose(rate_hz, 200.0, rel_tol=0.01):
        raise ContractError("IMU_RATE_CALIBRATION_MISMATCH")
    for field in (
        "accelerometer_noise_density",
        "accelerometer_random_walk",
        "gyroscope_noise_density",
        "gyroscope_random_walk",
    ):
        value = float(imu_calib.get(field))
        if not math.isfinite(value) or value <= 0:
            raise ContractError(f"INVALID_IMU_NOISE:{field}")
    return {
        "cam0_timeshift_cam_imu_s": td0,
        "cam1_timeshift_cam_imu_s": td1,
        "timeshift_difference_s": td1 - td0,
        "underwater_stereo_baseline_m": baseline_m,
        "imu_rate_hz": rate_hz,
        "cam1_extrinsic_derivation": (
            "T_cam1_imu = T_cam1_cam0(intrinsics_water) @ "
            "T_cam0_imu(extrinsics_air)"
        ),
    }


def build_ntnu_airslam_camera_config(
    camera_calib: Mapping[str, Any],
    imucam_calib: Mapping[str, Any],
    imu_calib: Mapping[str, Any],
) -> dict[str, Any]:
    import numpy as np

    t_cam0_imu = _matrix4(imucam_calib["cam0"]["T_cam_imu"], "cam0.T_cam_imu")
    t_cam1_cam0 = _matrix4(
        camera_calib["cam1"]["T_cn_cnm1"], "water.T_cam1_cam0"
    )
    t_cam1_imu = t_cam1_cam0 @ t_cam0_imu

    def camera_node(name: str, transform: Any) -> dict[str, Any]:
        source = camera_calib[name]
        return {
            "intrinsics": [float(item) for item in source["intrinsics"]],
            "distortion_coeffs": [
                *[float(item) for item in source["distortion_coeffs"]],
                0.0,
            ],
            # AirSLAM T_type=1 consumes Kalibr T_cam_imu and inverts internally.
            "T_type": 1,
            "T": [[float(item) for item in row] for row in np.asarray(transform)],
        }

    return {
        "image_height": 540,
        "image_width": 720,
        "use_imu": 1,
        # Preserve the official EuRoC camera-config I/O/geometry thresholds.
        "depth_lower_thr": 0.1,
        "depth_upper_thr": 10.0,
        "max_y_diff": 1,
        "distortion_type": 2,
        "cam0": camera_node("cam0", t_cam0_imu),
        "cam1": camera_node("cam1", t_cam1_imu),
        "rate_hz": float(imu_calib["update_rate"]),
        "gyroscope_noise_density": float(imu_calib["gyroscope_noise_density"]),
        "gyroscope_random_walk": float(imu_calib["gyroscope_random_walk"]),
        "accelerometer_noise_density": float(
            imu_calib["accelerometer_noise_density"]
        ),
        "accelerometer_random_walk": float(imu_calib["accelerometer_random_walk"]),
        "g_value": 9.81,
    }


def build_ntnu_vo_io_config(official_vo_config: Mapping[str, Any]) -> dict[str, Any]:
    # A JSON round-trip gives a dependency-free deep copy of this scalar/list mapping.
    value = json.loads(json.dumps(official_vo_config))
    matcher = value.get("point_matcher")
    if not isinstance(matcher, dict):
        raise ContractError("OFFICIAL_VO_POINT_MATCHER_CONFIG_MISSING")
    matcher["image_width"] = 720
    matcher["image_height"] = 540
    return value


def _profile_paths(profile: Profile, workspace: Path) -> dict[str, Path | None]:
    return {
        "bag": workspace / profile.bag_relpath,
        "camera_calib": workspace / profile.camera_calib_relpath,
        "imucam_calib": workspace / profile.imucam_calib_relpath,
        "imu_calib": workspace / profile.imu_calib_relpath,
        "reference": workspace / profile.reference_relpath
        if profile.reference_relpath
        else None,
    }


def preflight(profile: Profile, workspace: Path, airslam_root: Path) -> dict[str, Any]:
    paths = _profile_paths(profile, workspace)
    upstream = audit_airslam_checkout(airslam_root)
    integrity_errors = list(upstream["errors"])
    file_audit: dict[str, Any] = {}
    for label, maybe_path in paths.items():
        if maybe_path is None:
            continue
        path = maybe_path
        present = path.is_file()
        size = path.stat().st_size if present else None
        file_audit[label] = {
            "path": str(path),
            "resolved_path": str(path.resolve(strict=False)),
            "present": present,
            "size_bytes": size,
        }
        if not present:
            integrity_errors.append(f"INPUT_FILE_MISSING:{label}")
    bag_path = paths["bag"]
    assert isinstance(bag_path, Path)
    if bag_path.is_file() and bag_path.stat().st_size != profile.expected_bag_size:
        integrity_errors.append("BAG_SIZE_MISMATCH")

    if integrity_errors:
        return {
            "adapter_version": ADAPTER_VERSION,
            "status": INTEGRITY_ERROR,
            "profile": profile.name,
            "window_id": profile.window_id,
            "integrity_errors": sorted(set(integrity_errors)),
            "blockers": [],
            "files": file_audit,
            "upstream": upstream,
        }

    camera_path = paths["camera_calib"]
    imucam_path = paths["imucam_calib"]
    imu_path = paths["imu_calib"]
    assert isinstance(camera_path, Path)
    assert isinstance(imucam_path, Path)
    assert isinstance(imu_path, Path)
    camera_calib = load_yaml(camera_path)
    imucam_calib = load_yaml(imucam_path)
    imu_calib = load_yaml(imu_path)
    topics = inspect_bag_topics(bag_path)
    calibrated_cameras = sorted(
        {key for key in camera_calib if key.startswith("cam")}
        & {key for key in imucam_calib if key.startswith("cam")}
    )
    blockers = modal_blockers(
        profile.cam0_topic,
        profile.cam1_topic,
        profile.imu_topic,
        topics,
        calibrated_cameras,
    )
    calibration_audit: dict[str, Any] = {
        "camera_calibrated_keys": calibrated_cameras,
        "file_sha256": {
            "camera": sha256_file(camera_path),
            "imucam": sha256_file(imucam_path),
            "imu": sha256_file(imu_path),
        },
    }
    if not blockers and profile.name == "ntnu-fjord6-0001":
        calibration_audit.update(
            validate_ntnu_calibrations(
                profile, camera_calib, imucam_calib, imu_calib
            )
        )

    status = BLOCKED if blockers else READY
    return {
        "adapter_version": ADAPTER_VERSION,
        "status": status,
        "profile": profile.name,
        "window_id": profile.window_id,
        "reporting_class": profile.reporting_class,
        "same_input_a02_comparison_eligible": False,
        "blockers": blockers,
        "integrity_errors": [],
        "files": file_audit,
        "upstream": upstream,
        "bag_topics": topics,
        "sensor_contract": {
            "cam0_topic": profile.cam0_topic,
            "cam1_topic": profile.cam1_topic,
            "imu_topic": profile.imu_topic,
            "record_time_interval_half_open_ns": [
                profile.record_start_ns,
                profile.record_end_ns,
            ],
            "expected_stereo_pairs": profile.expected_stereo_pairs,
            "image_filename_time": "ROS image header stamp, integer nanoseconds",
            "stereo_pairing": "exact equality of cam0/cam1 ROS header stamps",
            "imu_clock_transform": "t_imu_out_ns = t_imu_header_ns - round(cam0_td_s*1e9)",
        },
        "calibration": calibration_audit,
        "pending_export_checks": []
        if blockers
        else [
            "EXACT_STEREO_HEADER_TIMESTAMP_SETS",
            "STRICT_SENSOR_TIMESTAMP_MONOTONICITY",
            "720x540_MONO8_IMAGE_CONTRACT",
            "CAM0_CAM1_PAYLOADS_NOT_ALL_IDENTICAL",
            "SHIFTED_IMU_BRACKETS_IMAGE_TIMELINE",
            "FINITE_150_TO_250_HZ_IMU",
        ],
        "reference_contract": {
            "path": str(paths["reference"]) if paths["reference"] else None,
            "semantics": profile.reference_semantics,
            "trajectory_frame": "world_T_cam0",
            "airslam_output_frame": "world_T_cam0",
            "body_to_camera_transform_required": False,
            "alignment": "SE(3), no scale correction",
            "evaluation_grid_hz": 10.0,
            "max_reference_gap_s": 0.05,
            "max_estimate_gap_s": 0.375,
            "rpe_delta_s": 1.0,
            "nominal_window_s": [1700603752.8582888, 1700603797.8582888]
            if profile.dataset_family == "ntnu"
            else None,
            "support_rule": "evaluate only common valid overlap; fail closed on insufficient support",
        },
        "claims": {
            "adapter_preflight_only": True,
            "airslam_runtime_tested": False,
            "trajectory_produced": False,
            "full_window_converted": False,
        },
    }


@dataclass
class ImageRow:
    header_ns: int
    record_ns: int
    payload_sha256: str


def validate_stereo_rows(
    left: Sequence[ImageRow], right: Sequence[ImageRow], expected_count: int
) -> dict[str, Any]:
    blockers: list[str] = []
    if len(left) != expected_count:
        blockers.append(f"CAM0_COUNT_MISMATCH:{len(left)}!={expected_count}")
    if len(right) != expected_count:
        blockers.append(f"CAM1_COUNT_MISMATCH:{len(right)}!={expected_count}")
    left_stamps = [row.header_ns for row in left]
    right_stamps = [row.header_ns for row in right]
    if any(current <= previous for previous, current in zip(left_stamps, left_stamps[1:])):
        blockers.append("CAM0_HEADER_NOT_STRICTLY_MONOTONIC")
    if any(current <= previous for previous, current in zip(right_stamps, right_stamps[1:])):
        blockers.append("CAM1_HEADER_NOT_STRICTLY_MONOTONIC")
    if left_stamps != right_stamps:
        blockers.append("STEREO_HEADER_TIMESTAMP_SETS_DIFFER")
    identical_pairs = sum(
        row0.payload_sha256 == row1.payload_sha256 for row0, row1 in zip(left, right)
    )
    if expected_count > 0 and identical_pairs == expected_count:
        blockers.append("CAM0_DUPLICATED_AS_CAM1_FORBIDDEN")
    if blockers:
        raise ContractError(";".join(blockers))
    return {
        "pair_count": expected_count,
        "first_header_ns": left_stamps[0],
        "last_header_ns": left_stamps[-1],
        "identical_payload_pair_count": identical_pairs,
        "all_pairs_exact_header_match": True,
    }


def _encode_ros_mono8_png(msg: Any, expected_width: int, expected_height: int) -> bytes:
    if int(msg.width) != expected_width or int(msg.height) != expected_height:
        raise ContractError("IMAGE_DIMENSION_MISMATCH")
    if str(msg.encoding).lower() not in {"mono8", "8uc1"}:
        raise ContractError(f"IMAGE_ENCODING_NOT_MONO8:{msg.encoding}")
    if int(msg.step) != expected_width:
        raise ContractError("IMAGE_STEP_NOT_TIGHT_MONO8")
    payload = bytes(msg.data)
    if len(payload) != expected_width * expected_height:
        raise ContractError("IMAGE_PAYLOAD_SIZE_MISMATCH")
    try:
        import cv2
        import numpy as np
    except ImportError as exc:  # pragma: no cover - environment gate
        raise ContractError("CV2_OR_NUMPY_UNAVAILABLE") from exc
    image = np.frombuffer(payload, dtype=np.uint8).reshape(expected_height, expected_width)
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise ContractError("PNG_ENCODING_FAILED")
    return bytes(encoded)


def _scan_and_write_stereo(
    profile: Profile, bag_path: Path, staging: Path, limit: int | None
) -> tuple[list[ImageRow], list[ImageRow]]:
    if profile.cam1_topic is None:
        raise ContractError("CAM1_TOPIC_REQUIRED")
    try:
        import rosbag
    except ImportError as exc:  # pragma: no cover - environment gate
        raise ContractError("ROSBAG_PYTHON_UNAVAILABLE") from exc
    assert profile.record_start_ns is not None and profile.record_end_ns is not None
    (staging / "cam0" / "data").mkdir(parents=True)
    (staging / "cam1" / "data").mkdir(parents=True)
    rows: dict[str, list[ImageRow]] = {
        profile.cam0_topic: [],
        profile.cam1_topic: [],
    }
    directories = {
        profile.cam0_topic: staging / "cam0" / "data",
        profile.cam1_topic: staging / "cam1" / "data",
    }
    with rosbag.Bag(str(bag_path), "r") as bag:
        messages = bag.read_messages(
            topics=[profile.cam0_topic, profile.cam1_topic],
            start_time=ns_to_ros_time(profile.record_start_ns),
            end_time=ns_to_ros_time(profile.record_end_ns),
        )
        for topic, msg, record_stamp in messages:
            record_ns = ros_time_to_ns(record_stamp)
            if not profile.record_start_ns <= record_ns < profile.record_end_ns:
                continue
            if limit is not None and len(rows[topic]) >= limit:
                if all(len(value) >= limit for value in rows.values()):
                    break
                continue
            if getattr(msg, "_type", "") != "sensor_msgs/Image":
                raise ContractError(f"UNEXPECTED_IMAGE_MESSAGE_TYPE:{topic}")
            header_ns = ros_time_to_ns(msg.header.stamp)
            if rows[topic] and header_ns <= rows[topic][-1].header_ns:
                raise ContractError(f"NONMONOTONIC_IMAGE_HEADER:{topic}")
            raw_payload = bytes(msg.data)
            payload_hash = hashlib.sha256(raw_payload).hexdigest()
            filename = f"{header_ns:019d}.png"
            destination = directories[topic] / filename
            if destination.exists():
                raise ContractError(f"DUPLICATE_IMAGE_TIMESTAMP:{topic}:{header_ns}")
            destination.write_bytes(
                _encode_ros_mono8_png(
                    msg, profile.expected_width, profile.expected_height
                )
            )
            rows[topic].append(ImageRow(header_ns, record_ns, payload_hash))
            if limit is not None and all(len(value) >= limit for value in rows.values()):
                break
    return rows[profile.cam0_topic], rows[profile.cam1_topic]


@dataclass
class ImuRow:
    shifted_header_ns: int
    raw_header_ns: int
    record_ns: int
    values: tuple[float, float, float, float, float, float]


def _scan_imu(
    profile: Profile,
    bag_path: Path,
    td_s: float,
    scan_end_record_ns: int,
) -> list[ImuRow]:
    try:
        import rosbag
    except ImportError as exc:  # pragma: no cover - environment gate
        raise ContractError("ROSBAG_PYTHON_UNAVAILABLE") from exc
    assert profile.record_start_ns is not None
    margin_ns = 250_000_000
    start_ns = profile.record_start_ns - margin_ns
    end_ns = scan_end_record_ns + margin_ns
    result: list[ImuRow] = []
    with rosbag.Bag(str(bag_path), "r") as bag:
        messages = bag.read_messages(
            topics=[profile.imu_topic],
            start_time=ns_to_ros_time(start_ns),
            end_time=ns_to_ros_time(end_ns),
        )
        for topic, msg, record_stamp in messages:
            del topic
            record_ns = ros_time_to_ns(record_stamp)
            if not start_ns <= record_ns < end_ns:
                continue
            if getattr(msg, "_type", "") != "sensor_msgs/Imu":
                raise ContractError("UNEXPECTED_IMU_MESSAGE_TYPE")
            raw_header_ns = ros_time_to_ns(msg.header.stamp)
            shifted_ns = shift_imu_timestamp_ns(raw_header_ns, td_s)
            values = (
                float(msg.angular_velocity.x),
                float(msg.angular_velocity.y),
                float(msg.angular_velocity.z),
                float(msg.linear_acceleration.x),
                float(msg.linear_acceleration.y),
                float(msg.linear_acceleration.z),
            )
            if not all(math.isfinite(value) for value in values):
                raise ContractError("NONFINITE_IMU_SAMPLE")
            if result and shifted_ns <= result[-1].shifted_header_ns:
                raise ContractError("SHIFTED_IMU_TIMESTAMP_NOT_STRICTLY_MONOTONIC")
            result.append(ImuRow(shifted_ns, raw_header_ns, record_ns, values))
    return result


def validate_imu_rows(
    rows: Sequence[ImuRow], first_image_ns: int, last_image_ns: int
) -> dict[str, Any]:
    if len(rows) < 2:
        raise ContractError("TOO_FEW_IMU_SAMPLES")
    if rows[0].shifted_header_ns > first_image_ns:
        raise ContractError("IMU_DOES_NOT_BRACKET_FIRST_IMAGE")
    if rows[-1].shifted_header_ns < last_image_ns:
        raise ContractError("IMU_DOES_NOT_BRACKET_LAST_IMAGE")
    duration_s = (rows[-1].shifted_header_ns - rows[0].shifted_header_ns) / 1e9
    observed_rate_hz = (len(rows) - 1) / duration_s
    if not 150.0 <= observed_rate_hz <= 250.0:
        raise ContractError(f"IMU_RATE_OUT_OF_RANGE:{observed_rate_hz}")
    return {
        "sample_count": len(rows),
        "first_shifted_header_ns": rows[0].shifted_header_ns,
        "last_shifted_header_ns": rows[-1].shifted_header_ns,
        "observed_rate_hz": observed_rate_hz,
        "brackets_images": True,
    }


def write_imu_csv(path: Path, rows: Sequence[ImuRow]) -> None:
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        # Stock AirSLAM skips line 1 and consumes timestamp,gx,gy,gz,ax,ay,az.
        writer.writerow(["#timestamp [ns]", "w_x", "w_y", "w_z", "a_x", "a_y", "a_z"])
        for row in rows:
            writer.writerow(
                [str(row.shifted_header_ns)]
                + [format(value, ".17g") for value in row.values]
            )


def export_ntnu(
    profile: Profile,
    workspace: Path,
    airslam_root: Path,
    output_root: Path,
    prefix_pairs: int | None,
) -> dict[str, Any]:
    report = preflight(profile, workspace, airslam_root)
    if report["status"] != READY:
        raise ContractError(
            "PREFLIGHT_NOT_READY:" + ";".join(report.get("blockers", []))
        )
    if profile.name != "ntnu-fjord6-0001":
        raise ContractError("ONLY_NTNU_STEREO_PROFILE_IS_EXPORTABLE")
    if prefix_pairs is not None and not 1 <= prefix_pairs < int(profile.expected_stereo_pairs):
        raise ContractError("SMOKE_PREFIX_PAIRS_OUT_OF_RANGE")

    paths = _profile_paths(profile, workspace)
    bag_path = paths["bag"]
    camera_path = paths["camera_calib"]
    imucam_path = paths["imucam_calib"]
    imu_path = paths["imu_calib"]
    assert isinstance(bag_path, Path)
    assert isinstance(camera_path, Path)
    assert isinstance(imucam_path, Path)
    assert isinstance(imu_path, Path)
    camera_calib = load_yaml(camera_path)
    imucam_calib = load_yaml(imucam_path)
    imu_calib = load_yaml(imu_path)
    td_s = float(imucam_calib["cam0"]["timeshift_cam_imu"])
    expected_count = prefix_pairs or int(profile.expected_stereo_pairs)

    with atomic_directory(output_root) as staging:
        left, right = _scan_and_write_stereo(
            profile, bag_path, staging, prefix_pairs
        )
        stereo_audit = validate_stereo_rows(left, right, expected_count)
        scan_end_record_ns = (
            max(left[-1].record_ns, right[-1].record_ns)
            if prefix_pairs is not None
            else int(profile.record_end_ns)
        )
        imu_rows = _scan_imu(profile, bag_path, td_s, scan_end_record_ns)
        imu_audit = validate_imu_rows(
            imu_rows, left[0].header_ns, left[-1].header_ns
        )
        write_imu_csv(staging / "imu0" / "data.csv", imu_rows)

        camera_config = build_ntnu_airslam_camera_config(
            camera_calib, imucam_calib, imu_calib
        )
        camera_config_path = staging / "airslam_camera_ntnu_underwater.yaml"
        dump_yaml(camera_config_path, camera_config)
        official_vo_path = airslam_root / "configs/visual_odometry/vo_euroc.yaml"
        vo_config = build_ntnu_vo_io_config(load_yaml(official_vo_path))
        vo_config_path = staging / "airslam_vo_ntnu_io.yaml"
        dump_yaml(vo_config_path, vo_config)

        artifact_scope = "SMOKE_PREFIX_NOT_EVALUABLE" if prefix_pairs else "FROZEN_45S_WINDOW"
        manifest = {
            "adapter_version": ADAPTER_VERSION,
            "status": EXPORTED,
            "artifact_scope": artifact_scope,
            "evaluation_eligible_input": prefix_pairs is None,
            "profile": profile.name,
            "window_id": profile.window_id,
            "reporting_class": profile.reporting_class,
            "same_input_a02_comparison_eligible": False,
            "source_bag": {
                "path": str(bag_path),
                "resolved_path": str(bag_path.resolve()),
                "size_bytes": bag_path.stat().st_size,
                "record_time_interval_half_open_ns": [
                    profile.record_start_ns,
                    profile.record_end_ns,
                ],
            },
            "airslam_upstream": report["upstream"],
            "stereo": stereo_audit,
            "imu": {
                **imu_audit,
                "raw_to_output_timestamp": "t_out_ns=t_raw_header_ns-round(cam0_td_s*1e9)",
                "cam0_td_s": td_s,
            },
            "calibration": {
                **report["calibration"],
                "camera_config_sha256": sha256_file(camera_config_path),
                "vo_config_sha256": sha256_file(vo_config_path),
                "g_value_m_s2": 9.81,
                "g_value_source": "adapter-declared standard gravity",
                "vo_config_changes_from_official_euroc": {
                    "point_matcher.image_width": [752, 720],
                    "point_matcher.image_height": [480, 540],
                },
                "algorithm_threshold_changes": [],
            },
            "reference_contract": report["reference_contract"],
            "run_contract": {
                "not_executed_by_adapter": True,
                "executable": "rosrun air_slam visual_odometry",
                "parameters": {
                    "_config_path": "<artifact>/airslam_vo_ntnu_io.yaml",
                    "_model_dir": "<official-checkout>/output",
                    "_dataroot": "<artifact>",
                    "_camera_config_path": "<artifact>/airslam_camera_ntnu_underwater.yaml",
                    "_saving_dir": "<new-existing-run-output-dir>",
                },
                "expected_trajectory": "<saving_dir>/trajectory_v0.txt (TUM keyframes, world_T_cam0)",
            },
            "claims": {
                "airslam_started": False,
                "trajectory_produced": False,
                "runtime_compatibility_claimed": False,
                "full_window_converted": prefix_pairs is None,
            },
        }
        (staging / "conversion_manifest.json").write_text(
            canonical_json(manifest), encoding="utf-8"
        )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(PROFILES), required=True)
    parser.add_argument(
        "--action",
        choices=("preflight", "smoke-prefix", "export-window"),
        default="preflight",
    )
    parser.add_argument("--prefix-pairs", type=int, default=3)
    parser.add_argument("--workspace-root", type=Path, default=WORKSPACE_DEFAULT)
    parser.add_argument("--airslam-root", type=Path, default=AIRSLAM_ROOT_DEFAULT)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument(
        "--report-json",
        type=Path,
        help="optional atomic copy of the JSON result; stdout is always emitted",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    profile = PROFILES[args.profile]
    try:
        if args.action == "preflight":
            result = preflight(profile, args.workspace_root, args.airslam_root)
        else:
            if args.output_root is None:
                raise ContractError("OUTPUT_ROOT_REQUIRED_FOR_EXPORT")
            prefix = args.prefix_pairs if args.action == "smoke-prefix" else None
            result = export_ntnu(
                profile,
                args.workspace_root,
                args.airslam_root,
                args.output_root,
                prefix,
            )
    except ContractError as exc:
        result = {
            "adapter_version": ADAPTER_VERSION,
            "status": INTEGRITY_ERROR,
            "profile": profile.name,
            "window_id": profile.window_id,
            "integrity_errors": [str(exc)],
            "claims": {
                "airslam_started": False,
                "trajectory_produced": False,
            },
        }
    except Exception as exc:  # fail closed, but retain exception class for diagnosis
        result = {
            "adapter_version": ADAPTER_VERSION,
            "status": INTEGRITY_ERROR,
            "profile": profile.name,
            "window_id": profile.window_id,
            "integrity_errors": [f"UNEXPECTED_{type(exc).__name__}:{exc}"],
            "claims": {
                "airslam_started": False,
                "trajectory_produced": False,
            },
        }

    text = canonical_json(result)
    sys.stdout.write(text)
    if args.report_json:
        write_text_atomic(args.report_json, text)
    if result["status"] in {READY, EXPORTED}:
        return EXIT_READY
    if result["status"] == BLOCKED:
        return EXIT_BLOCKED
    return EXIT_INTEGRITY


if __name__ == "__main__":
    raise SystemExit(main())
