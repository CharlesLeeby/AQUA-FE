#!/usr/bin/env python3
"""Independently audit a prepared NTNU HFNet exact-window EuRoC tree.

This auditor does not import the materializer.  It independently reselects the
source camera messages by closed bag record time, applies the frozen IMU shift,
reconstructs the official-reader bracket, decodes every output PNG, and checks
the manifest-last/no-extra-file payload contract.  It starts no scientific
process and computes no trajectory or accuracy metric.
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
import zlib


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "aqua-fe-hfnet-v6-ntnu-positive-independent-input-audit-v1"
MATERIALIZATION_SCHEMA = "aqua-fe-hfnet-v6-ntnu-positive-input-materialization-v1"
SELECTOR_SCHEMA = "aqua-fe-hfnet-v6-ntnu-historical-positive-exact-window-selector-v1"
SELECTOR = ROOT / "papers/hfnet_v6_ntnu_historical_positive_exact_window_selector_v1.json"
SELECTOR_SIZE = 7_480
SELECTOR_SHA256 = "ee6759123c50ed1e9ebbffecc205e75d5730d27afa5ee77e3fe1188ff9a04344"
CONFIG = ROOT / "configs/published_baselines/hfnet_slam_ntnu_cam0_mono_inertial_v1.yaml"
CONFIG_SIZE = 2_228
CONFIG_SHA256 = "5b8b8d7ed6c010f25d4cf8d80ca24692b06de4cd17f4d19ae2a0cb9cc91a54dd"

CAMERA_TOPIC = "/alphasense_driver_ros/cam0"
IMU_TOPIC = "/alphasense_driver_ros/imu"
IMU_SHIFT_NS = -1_765_624
READER_MARGIN_NS = 500_000_000
IMU_CSV_HEADER = (
    "#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],"
    "w_RS_S_z [rad s^-1],a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],"
    "a_RS_S_z [m s^-2]"
)
PRODUCTION_CAMERA_SCHEMA = {
    "width": 720,
    "height": 540,
    "encoding": "mono8",
    "step": 720,
    "is_bigendian": 0,
    "frame_id": "cam0_sensor_frame",
}


class AuditError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuditSpec:
    window_id: str
    sequence_id: str
    source_bag: Path
    source_size_bytes: int
    source_sha256: Optional[str]
    start_offset_ns: int
    end_offset_ns: int
    output_root: Path


@dataclass(frozen=True)
class RawCamera:
    record_ns: int
    header_ns: int
    mono8_sha256: str


@dataclass(frozen=True)
class RawImu:
    record_ns: int
    raw_header_ns: int
    shifted_header_ns: int
    values: Tuple[float, float, float, float, float, float]


def canonical_json(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def file_identity(path: Path, relative: str) -> Dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise AuditError(f"FILE_MISSING_OR_NOT_REGULAR:{relative}")
    digest = hashlib.sha256()
    crc = 0
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
            crc = zlib.crc32(block, crc)
            size += len(block)
    return {
        "path": relative,
        "size_bytes": size,
        "sha256": digest.hexdigest(),
        "crc32": f"{crc & 0xffffffff:08x}",
    }


def require_pin(path: Path, size: int, digest: str, label: str) -> Dict[str, Any]:
    value = file_identity(path, str(path.resolve()))
    if value["size_bytes"] != size or value["sha256"] != digest:
        raise AuditError(f"{label}_IDENTITY_MISMATCH")
    return value


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


def exact_ns(value: Any) -> int:
    secs = getattr(value, "secs", None)
    nsecs = getattr(value, "nsecs", None)
    if not isinstance(secs, int) or not isinstance(nsecs, int):
        raise AuditError("ROS_TIME_NOT_EXACT_INTEGER_FIELDS")
    return secs * 1_000_000_000 + nsecs


def ros_time(stamp_ns: int) -> Any:
    try:
        import genpy
    except ImportError as error:  # pragma: no cover
        raise AuditError("GENPY_UNAVAILABLE") from error
    return genpy.Time(stamp_ns // 1_000_000_000, stamp_ns % 1_000_000_000)


def bag_begin_ns(bag: Any) -> int:
    try:
        entry = next(bag._get_entries())
    except Exception as error:
        raise AuditError("CANNOT_READ_EXACT_BAG_BEGIN") from error
    return exact_ns(entry.time)


def deserialize(raw: Any, topic: str) -> Any:
    if not isinstance(raw, tuple) or len(raw) not in (4, 5):
        raise AuditError(f"RAW_MESSAGE_TUPLE_INVALID:{topic}")
    serialized = raw[1]
    pytype = raw[4] if len(raw) == 5 else raw[3]
    if not isinstance(serialized, (bytes, bytearray)) or pytype is None:
        raise AuditError(f"RAW_MESSAGE_NOT_DESERIALIZABLE:{topic}")
    message = pytype()
    message.deserialize(serialized)
    return message


def message_header_ns(message: Any, topic: str) -> int:
    try:
        return exact_ns(message.header.stamp)
    except Exception as error:
        raise AuditError(f"HEADER_STAMP_MISSING:{topic}") from error


def schema_of(message: Any) -> Dict[str, Any]:
    return {
        "width": int(message.width),
        "height": int(message.height),
        "encoding": str(message.encoding).lower(),
        "step": int(message.step),
        "is_bigendian": int(message.is_bigendian),
        "frame_id": str(message.header.frame_id),
    }


def imu_values(message: Any) -> Tuple[float, float, float, float, float, float]:
    values = (
        float(message.angular_velocity.x),
        float(message.angular_velocity.y),
        float(message.angular_velocity.z),
        float(message.linear_acceleration.x),
        float(message.linear_acceleration.y),
        float(message.linear_acceleration.z),
    )
    if not all(math.isfinite(value) for value in values):
        raise AuditError("IMU_NONFINITE")
    return values


def scan_source(
    spec: AuditSpec, camera_schema: Mapping[str, Any]
) -> Tuple[int, Tuple[int, int], List[RawCamera], List[RawImu]]:
    try:
        info = spec.source_bag.lstat()
    except FileNotFoundError as error:
        raise AuditError("SOURCE_BAG_MISSING") from error
    if spec.source_bag.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise AuditError("SOURCE_BAG_NOT_REGULAR_OR_IS_SYMLINK")
    if info.st_size != spec.source_size_bytes:
        raise AuditError("SOURCE_BAG_SIZE_MISMATCH")
    try:
        import rosbag
    except ImportError as error:  # pragma: no cover
        raise AuditError("ROSBAG_PYTHON_UNAVAILABLE") from error

    cameras: List[RawCamera] = []
    margin_imus: List[RawImu] = []
    with rosbag.Bag(str(spec.source_bag), "r") as bag:
        begin = bag_begin_ns(bag)
        lower = begin + spec.start_offset_ns
        upper = begin + spec.end_offset_ns
        previous_record = {CAMERA_TOPIC: -1, IMU_TOPIC: -1}
        previous_header = {CAMERA_TOPIC: -1, IMU_TOPIC: -1}
        for item in bag.read_messages(
            topics=[CAMERA_TOPIC, IMU_TOPIC],
            start_time=ros_time(max(begin, lower - READER_MARGIN_NS)),
            end_time=ros_time(upper + READER_MARGIN_NS),
            raw=True,
            return_connection_header=True,
        ):
            topic = str(item.topic)
            record = exact_ns(item.timestamp)
            if record <= previous_record[topic]:
                raise AuditError(f"RECORD_NOT_STRICT:{topic}")
            previous_record[topic] = record
            message = deserialize(item.message, topic)
            header = message_header_ns(message, topic)
            if header <= previous_header[topic]:
                raise AuditError(f"HEADER_NOT_STRICT:{topic}")
            previous_header[topic] = header
            if topic == CAMERA_TOPIC:
                if not lower <= record <= upper:
                    continue
                if getattr(message, "_type", "") != "sensor_msgs/Image":
                    raise AuditError("CAMERA_TYPE_MISMATCH")
                if schema_of(message) != dict(camera_schema):
                    raise AuditError("CAMERA_SCHEMA_MISMATCH")
                payload = bytes(message.data)
                cameras.append(RawCamera(record, header, hashlib.sha256(payload).hexdigest()))
            else:
                if getattr(message, "_type", "") != "sensor_msgs/Imu":
                    raise AuditError("IMU_TYPE_MISMATCH")
                margin_imus.append(
                    RawImu(record, header, header + IMU_SHIFT_NS, imu_values(message))
                )
    if not cameras:
        raise AuditError("NO_CAMERAS")
    shifted = [sample.shifted_header_ns for sample in margin_imus]
    first = bisect.bisect_right(shifted, cameras[0].header_ns) - 1
    last = bisect.bisect_right(shifted, cameras[-1].header_ns)
    if first < 0 or last >= len(margin_imus):
        raise AuditError("IMU_BRACKET_MISSING")
    imus = margin_imus[first : last + 1]
    if not (
        imus[0].shifted_header_ns <= cameras[0].header_ns < imus[1].shifted_header_ns
        and imus[-2].shifted_header_ns <= cameras[-1].header_ns < imus[-1].shifted_header_ns
    ):
        raise AuditError("IMU_BRACKET_INVALID")
    return begin, (lower, upper), cameras, imus


def expected_summary(
    begin: int, bounds: Tuple[int, int], cameras: Sequence[RawCamera], imus: Sequence[RawImu]
) -> Dict[str, Any]:
    deltas = [sample.header_ns - sample.record_ns for sample in cameras]
    return {
        "source_bag_first_record_ns": begin,
        "absolute_record_bounds_ns_closed": list(bounds),
        "camera": {
            "count": len(cameras),
            "record_ns_inclusive": [cameras[0].record_ns, cameras[-1].record_ns],
            "header_ns_inclusive": [cameras[0].header_ns, cameras[-1].header_ns],
            "header_minus_record_ns_range": [min(deltas), max(deltas)],
        },
        "imu": {
            "count": len(imus),
            "record_ns_inclusive": [imus[0].record_ns, imus[-1].record_ns],
            "raw_header_ns_inclusive": [imus[0].raw_header_ns, imus[-1].raw_header_ns],
            "shifted_header_ns_inclusive": [imus[0].shifted_header_ns, imus[-1].shifted_header_ns],
        },
    }


def enforce_frozen(summary: Mapping[str, Any], frozen: Mapping[str, Any]) -> None:
    checks = (
        (summary["source_bag_first_record_ns"], frozen["source_bag_first_record_ns"], "BAG_BEGIN"),
        (summary["absolute_record_bounds_ns_closed"], frozen["absolute_record_bounds_ns_closed"], "RECORD_BOUNDS"),
        (summary["camera"]["count"], frozen["camera"]["count"], "CAMERA_COUNT"),
        (summary["camera"]["record_ns_inclusive"], frozen["camera"]["record_ns_inclusive"], "CAMERA_RECORD"),
        (summary["camera"]["header_ns_inclusive"], frozen["camera"]["header_ns_inclusive"], "CAMERA_HEADER"),
        (summary["camera"]["header_minus_record_ns_range"], frozen["camera"]["header_minus_record_ns_range"], "CAMERA_DELTA"),
        (summary["imu"]["count"], frozen["imu"]["count"], "IMU_COUNT"),
        (summary["imu"]["record_ns_inclusive"], frozen["imu"]["record_ns_inclusive"], "IMU_RECORD"),
        (summary["imu"]["raw_header_ns_inclusive"], frozen["imu"]["raw_header_ns_inclusive"], "IMU_RAW_HEADER"),
        (summary["imu"]["shifted_header_ns_inclusive"], frozen["imu"]["shifted_header_ns_inclusive"], "IMU_SHIFTED_HEADER"),
    )
    for observed, expected, label in checks:
        if observed != expected:
            raise AuditError(f"FROZEN_{label}_MISMATCH")


def parse_output_camera(root: Path) -> Tuple[List[int], List[Dict[str, Any]]]:
    times_path = root / "cam0_times.txt"
    payload = times_path.read_bytes()
    if not payload.endswith(b"\n"):
        raise AuditError("CAM0_TIMES_FINAL_NEWLINE_MISSING")
    try:
        stamps = [int(line) for line in payload.decode("ascii").splitlines()]
    except ValueError as error:
        raise AuditError("CAM0_TIMES_INVALID") from error
    if not stamps or any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise AuditError("CAM0_TIMES_EMPTY_OR_NONMONOTONIC")
    csv_lines = (root / "mav0/cam0/data.csv").read_text(encoding="ascii").splitlines()
    expected = ["#timestamp [ns],filename"] + [f"{stamp},{stamp}.png" for stamp in stamps]
    if csv_lines != expected:
        raise AuditError("CAM0_DATA_CSV_MAPPING_MISMATCH")
    identities = [
        file_identity(root / f"mav0/cam0/data/{stamp}.png", f"mav0/cam0/data/{stamp}.png")
        for stamp in stamps
    ]
    return stamps, identities


def validate_png_pixels(
    root: Path, stamps: Sequence[int], source: Sequence[RawCamera], camera_schema: Mapping[str, Any]
) -> None:
    if len(stamps) != len(source):
        raise AuditError("OUTPUT_SOURCE_CAMERA_COUNT_MISMATCH")
    if list(stamps) != [sample.header_ns for sample in source]:
        raise AuditError("OUTPUT_SOURCE_CAMERA_HEADER_MISMATCH")
    try:
        import cv2
        import numpy as np
    except ImportError as error:  # pragma: no cover
        raise AuditError("CV2_OR_NUMPY_UNAVAILABLE") from error
    expected_shape = (int(camera_schema["height"]), int(camera_schema["width"]))
    for stamp, sample in zip(stamps, source):
        image = cv2.imread(str(root / f"mav0/cam0/data/{stamp}.png"), cv2.IMREAD_UNCHANGED)
        if image is None or image.shape != expected_shape or image.dtype != np.uint8:
            raise AuditError(f"PNG_SCHEMA_OR_DECODE_MISMATCH:{stamp}")
        if hashlib.sha256(image.tobytes()).hexdigest() != sample.mono8_sha256:
            raise AuditError(f"PNG_SOURCE_PIXEL_BYTES_MISMATCH:{stamp}")


def parse_and_compare_imu(root: Path, source: Sequence[RawImu]) -> Dict[str, Any]:
    payload = (root / "mav0/imu0/data.csv").read_bytes()
    if payload.endswith(b"\n"):
        raise AuditError("IMU_FINAL_NEWLINE_PRESENT")
    lines = payload.decode("ascii").splitlines()
    expected = [IMU_CSV_HEADER]
    for sample in source:
        values = ",".join(format(value, ".17g") for value in sample.values)
        expected.append(f"{sample.shifted_header_ns},{values}")
    if lines != expected:
        raise AuditError("IMU_CSV_DIFFERS_FROM_SOURCE_SELECTION")
    return {
        "count": len(source),
        "shifted_header_ns_inclusive": [source[0].shifted_header_ns, source[-1].shifted_header_ns],
        "reader_brackets_camera": True,
        "measurement_values_preserved": True,
        "synthetic_or_extrapolated_samples": False,
    }


def validate_config(path: Path) -> Dict[str, Any]:
    identity = require_pin(path, CONFIG_SIZE, CONFIG_SHA256, "CONFIG")
    text = path.read_text(encoding="utf-8")
    required = (
        'Camera.type: "KannalaBrandt8"',
        "Camera.width: 720",
        "Camera.height: 540",
        "IMU.NoiseGyro: 0.000587",
        "IMU.NoiseAcc: 0.0186",
        'Extractor.modelPath: "/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT/"',
        "0.0057458859421451467",
        "0.048394787222036377",
        "-0.0097706618631980095",
    )
    if any(token not in text for token in required):
        raise AuditError("CONFIG_REQUIRED_TOKEN_MISSING")
    if "-0.04828147993677678" in text:
        raise AuditError("CONFIG_WRONG_EXTRINSIC_DIRECTION")
    return identity


def audit_one(
    spec: AuditSpec,
    frozen: Mapping[str, Any],
    *,
    camera_schema: Mapping[str, Any] = PRODUCTION_CAMERA_SCHEMA,
    config_identity: Optional[Mapping[str, Any]] = None,
    selector_identity: Optional[Mapping[str, Any]] = None,
    verify_source_sha256: bool = False,
) -> Dict[str, Any]:
    root = spec.output_root
    if root.is_symlink() or not root.is_dir():
        raise AuditError("INPUT_ROOT_MISSING_OR_NOT_DIRECTORY")
    if verify_source_sha256:
        if spec.source_sha256 is None:
            raise AuditError("SOURCE_SHA256_NOT_FROZEN")
        observed = file_identity(spec.source_bag, str(spec.source_bag.resolve()))
        if observed["sha256"] != spec.source_sha256:
            raise AuditError("SOURCE_SHA256_MISMATCH")

    begin, bounds, source_cameras, source_imus = scan_source(spec, camera_schema)
    summary = expected_summary(begin, bounds, source_cameras, source_imus)
    enforce_frozen(summary, frozen)
    stamps, image_rows = parse_output_camera(root)
    validate_png_pixels(root, stamps, source_cameras, camera_schema)
    imu = parse_and_compare_imu(root, source_imus)

    generated_rows = [
        file_identity(root / "cam0_times.txt", "cam0_times.txt"),
        file_identity(root / "mav0/cam0/data.csv", "mav0/cam0/data.csv"),
        file_identity(root / "mav0/imu0/data.csv", "mav0/imu0/data.csv"),
    ]
    payload_identity = aggregate(list(image_rows) + generated_rows)
    expected_paths = {str(row["path"]) for row in image_rows + generated_rows}
    expected_paths.add("materialization_manifest.json")
    observed_paths = set()
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        relative = path.relative_to(root).as_posix()
        if path.is_symlink() or not path.is_file():
            raise AuditError(f"OUTPUT_NONREGULAR:{relative}")
        observed_paths.add(relative)
    if observed_paths != expected_paths:
        raise AuditError("OUTPUT_FILE_SET_MISMATCH")

    manifest_path = root / "materialization_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != MATERIALIZATION_SCHEMA:
        raise AuditError("MANIFEST_SCHEMA_MISMATCH")
    if manifest.get("status") != "PASS_EXACT_WINDOW_PREPARATION_ONLY":
        raise AuditError("MANIFEST_STATUS_MISMATCH")
    if manifest.get("window_id") != spec.window_id:
        raise AuditError("MANIFEST_WINDOW_MISMATCH")
    if manifest.get("payload_identity_excluding_manifest") != payload_identity:
        raise AuditError("MANIFEST_PAYLOAD_IDENTITY_MISMATCH")
    if manifest.get("payload_file_count_excluding_manifest") != len(image_rows) + 3:
        raise AuditError("MANIFEST_PAYLOAD_COUNT_MISMATCH")
    if any(value is not False for value in manifest.get("claims", {}).values()):
        raise AuditError("MANIFEST_FORBIDDEN_CLAIM")
    manifest_files = manifest.get("camera", {}).get("files", [])
    if [row.get("source_record_ns") for row in manifest_files] != [sample.record_ns for sample in source_cameras]:
        raise AuditError("MANIFEST_CAMERA_RECORD_TRANSCRIPT_MISMATCH")
    if [row.get("source_mono8_sha256") for row in manifest_files] != [sample.mono8_sha256 for sample in source_cameras]:
        raise AuditError("MANIFEST_CAMERA_SOURCE_HASH_TRANSCRIPT_MISMATCH")

    binding_config = dict(config_identity) if config_identity is not None else validate_config(CONFIG)
    manifest_absolute = file_identity(manifest_path, str(manifest_path.resolve()))
    runner_binding = {
        "schema_version": "aqua-fe-hfnet-v6-samehistory-input-audit-binding-v1",
        "case_id": spec.window_id,
        "input_root": str(root.resolve()),
        "input_manifest": {
            "path": str(manifest_path.resolve()),
            "size_bytes": manifest_absolute["size_bytes"],
            "sha256": manifest_absolute["sha256"],
        },
        "base_config": {
            "path": str(Path(str(binding_config["path"])).resolve()),
            "size_bytes": int(binding_config["size_bytes"]),
            "sha256": str(binding_config["sha256"]),
        },
        "camera_count": len(source_cameras),
        "camera_header_ns_inclusive": [source_cameras[0].header_ns, source_cameras[-1].header_ns],
        "score_relative_indices_inclusive": [0, len(source_cameras) - 1],
        "history": "EXACT_WINDOW_COLD_START_NO_PRIOR_CAMERA_HISTORY",
        "times_relative_path": "cam0_times.txt",
        "images_relative_path": "mav0/cam0/data",
        "image_extension": ".png",
        "imu_relative_path": "mav0/imu0/data.csv",
        "imu_reader_bracket_valid": True,
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_PREPARATION_ONLY_INDEPENDENT_AUDIT",
        "window_id": spec.window_id,
        "input_root": str(root.resolve()),
        "selector_freeze": selector_identity,
        "hfnet_config": config_identity,
        "source_sha256_recomputed": verify_source_sha256,
        "selection": summary,
        "camera": {
            "count": len(source_cameras),
            "all_pngs_decode_as_frozen_mono8_schema": True,
            "all_png_pixels_byte_identical_to_selected_source_messages": True,
            "selected_by_closed_bag_record_time": True,
            "output_named_by_original_header_time": True,
        },
        "imu": imu,
        "runner_binding": runner_binding,
        "payload_file_count_excluding_manifest": len(image_rows) + 3,
        "payload_identity_excluding_manifest": payload_identity,
        "manifest": file_identity(manifest_path, "materialization_manifest.json"),
        "reporting_boundary": "input preparation only; no trajectory, accuracy, or comparison",
        "claims": {
            "hfnet_started": False,
            "vins_started": False,
            "trajectory_produced": False,
            "accuracy_measured": False,
            "scientific_comparison_produced": False,
        },
    }


def selector_and_specs(path: Path = SELECTOR) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, AuditSpec]]:
    identity = require_pin(path, SELECTOR_SIZE, SELECTOR_SHA256, "SELECTOR")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != SELECTOR_SCHEMA:
        raise AuditError("SELECTOR_SCHEMA_MISMATCH")
    specs = {}
    for window_id, row in value["windows"].items():
        source = row["source_bag"]
        specs[window_id] = AuditSpec(
            window_id=window_id,
            sequence_id=row["sequence_id"],
            source_bag=Path(source["path"]),
            source_size_bytes=int(source["size_bytes"]),
            source_sha256=source.get("local_full_file_sha256"),
            start_offset_ns=int(row["offsets_ns_closed"][0]),
            end_offset_ns=int(row["offsets_ns_closed"][1]),
            output_root=Path(row["output_root"]),
        )
    return value, identity, specs


def write_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--window",
        choices=("fjord1_s83_d10", "mclab1_s60_d15", "mclab2_s110_d10"),
        required=True,
    )
    parser.add_argument("--selector-freeze", type=Path, default=SELECTOR)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--verify-source-sha256", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        selector, selector_identity, specs = selector_and_specs(args.selector_freeze)
        config_identity = validate_config(args.config)
        result = audit_one(
            specs[args.window],
            selector["windows"][args.window],
            camera_schema=selector["shared_inputs"]["camera_schema"],
            config_identity=config_identity,
            selector_identity=selector_identity,
            verify_source_sha256=args.verify_source_sha256,
        )
        return_code = 0
    except Exception as error:
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "INTEGRITY_ERROR",
            "errors": [f"{type(error).__name__}:{error}"],
            "claims": {"hfnet_started": False, "trajectory_produced": False, "accuracy_measured": False},
        }
        return_code = 2
    payload = canonical_json(result)
    if args.report is not None:
        try:
            write_exclusive(args.report, payload)
        except Exception as error:
            sys.stderr.write(f"report publication failed: {type(error).__name__}:{error}\n")
            return 3
    sys.stdout.buffer.write(payload)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
