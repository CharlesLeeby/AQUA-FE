#!/usr/bin/env python3
"""Export the frozen A02 4500..6300 shared camera/HFNet input.

This is a high-level dataset adapter.  It does not start or modify HFNet-SLAM,
AnyFeature-VSLAM, AQUA-FE, or VINS-Fusion.  The default input is the one-pass
derived ROS bag produced once from the immutable canonical A02 raw archive.
Its adjacent provenance JSON must bind the bag to that archive, the frozen
converter, and the global source indices before any payload is accepted.  The
separately retained full ROS bag is only a cross-source catalogue; this script
does not falsely claim that the derived bag was byte-copied from it.

The output contains one canonical lossless PNG set, exact camera timestamps,
the score-window reference proxy, and a hard-linked EuRoC view for HFNet.  The
sealed first 901 PNGs are reused after per-frame timestamp/source-pixel/PNG hash
verification; only relative frames 901..1800 are encoded.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Iterator, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]

SCHEMA_VERSION = "aqua-fe-a02-shared-4500-6300-v1"
STATUS_EXPORTED = "EXPORTED_SHARED_INPUT_ONLY_NO_SLAM_STARTED"

FULL_BAG_SIZE_BYTES = 5_355_038_011
FULL_BAG_SHA256 = "ca43f4f7584baf3b4aac4f2b031c59d56afa999e06d73657fcdfc7496861ef55"
FULL_BAG_TOPIC_COUNTS = {
    "/barometer_node/depth": 27_254,
    "/barometer_node/pressure": 27_254,
    "/barometer_node/temperature": 27_254,
    "/camera/camera_info": 8_988,
    "/camera/image_raw": 8_987,
    "/camera/ueye_info": 8_988,
    "/rtimulib_node/imu": 89_795,
    "/rtimulib_node/mag": 89_801,
}
RAW_TAR_SIZE_BYTES = 2_195_786_266
RAW_TAR_SHA256 = "8f6203e0b46068a9d237f03e469acecb5f51eedbd6b7c1dc7c1f980ea6ea6d69"
RAW_CONVERTER_RELATIVE = "uw_frontend/datasets/aqualoc_raw_to_rosbag.py"
RAW_CONVERTER_SHA256 = "b0c4b7ce7f3e29dcb18cb1604190cc8690cae370fc222246c8dfeb4fc79ffbec"

CAMERA_TOPIC = "/camera/image_raw"
IMU_TOPIC = "/rtimulib_node/imu"
CAMERA_TYPE = "sensor_msgs/Image"
IMU_TYPE = "sensor_msgs/Imu"
CAMERA_WIDTH = 968
CAMERA_HEIGHT = 608
CAMERA_ENCODING = "mono8"

GLOBAL_CAMERA_FIRST = 4_500
GLOBAL_CAMERA_LAST = 6_300
CAMERA_COUNT = 1_801
PREROLL_GLOBAL_INDICES = (4_500, 5_399)
SCORE_GLOBAL_INDICES = (5_400, 6_300)
SCORE_REFERENCE_INDICES = tuple(range(5_400, 6_301, 20))
EXPECTED_FIRST_CAMERA_NS = 1_542_829_016_700_435_392
EXPECTED_BOUNDARY_CAMERA_NS = 1_542_829_061_692_686_528
EXPECTED_LAST_CAMERA_NS = 1_542_829_106_687_510_592

GLOBAL_IMU_FIRST = 44_954
GLOBAL_IMU_LAST = 62_940
IMU_COUNT = 17_987
IMU_SHIFT_NS = 53_694_112
EXPECTED_FIRST_IMU_RAW_NS = 1_542_829_016_645_312_000
EXPECTED_LAST_IMU_RAW_NS = 1_542_829_106_638_112_448

DEFAULT_WINDOW_BAG = ROOT / "datasets/aqualoc/rosbags/archaeo02_4500_6300.bag"
DEFAULT_PROVENANCE = ROOT / "datasets/aqualoc/rosbags/archaeo02_4500_6300.bag.manifest.json"
DEFAULT_PREFIX_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/anyfeature_adapter/aqualoc_a02_0005_full_r1"
)
DEFAULT_REFERENCE = (
    ROOT
    / "datasets/full_downloads/aqualoc/Archaeological_site_sequences/"
    "archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_02.txt"
)
REFERENCE_SIZE_BYTES = 64_318
REFERENCE_SHA256 = "1122b753372545966026df10f1899e751cdaa3359a6938be251cd8e22b6e4379"
PREFIX_MANIFEST_SHA256 = "2f08cc97e71d44e56d90720fbdd5bf925c1c7e5892096743f67265fc2df34afe"
PREFIX_CAMERA_COUNT = 901


class ContractError(RuntimeError):
    """A frozen input, data, or publication contract was violated."""


@dataclass(frozen=True)
class CameraSample:
    relative_index: int
    global_index: int
    header_ns: int
    record_ns: int
    width: int
    height: int
    encoding: str
    step: int
    pixels: bytes
    source_pixel_sha256: str


@dataclass(frozen=True)
class ImuSample:
    relative_index: int
    global_index: int
    raw_header_ns: int
    output_header_ns: int
    record_ns: int
    gyro_xyz: tuple[float, float, float]
    accel_xyz: tuple[float, float, float]


@dataclass(frozen=True)
class ReferencePose:
    global_camera_index: int
    header_ns: int
    position_xyz: tuple[float, float, float]
    quaternion_xyzw: tuple[float, float, float, float]


@dataclass(frozen=True)
class Selection:
    cameras: tuple[CameraSample, ...]
    imus: tuple[ImuSample, ...]
    references: tuple[ReferencePose, ...]
    topic_audit: Mapping[str, Mapping[str, object]]


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _regular_file(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ContractError(f"{label}_MUST_NOT_BE_SYMLINK")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ContractError(f"{label}_MISSING") from error
    if not resolved.is_file() or resolved.is_symlink():
        raise ContractError(f"{label}_NOT_REGULAR_FILE")
    return resolved


def _identity(path: Path) -> dict[str, object]:
    resolved = _regular_file(path, "IDENTITY_INPUT")
    return {
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }


def _dig(mapping: Mapping[str, object], paths: Sequence[Sequence[str]]) -> object:
    for keys in paths:
        value: object = mapping
        for key in keys:
            if not isinstance(value, Mapping) or key not in value:
                break
            value = value[key]
        else:
            return value
    raise ContractError("PROVENANCE_REQUIRED_FIELD_MISSING:" + "/".join(paths[0]))


def validate_provenance(path: Path, window_bag: Path) -> dict[str, object]:
    """Validate the canonical-raw window producer's frozen manifest."""

    resolved = _regular_file(path, "SOURCE_PROVENANCE")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError("SOURCE_PROVENANCE_INVALID_JSON") from error
    if not isinstance(value, Mapping):
        raise ContractError("SOURCE_PROVENANCE_NOT_OBJECT")

    if value.get("schema_version") != "aqua-fe-aqualoc-canonical-raw-window-bag-manifest-v1":
        raise ContractError("SOURCE_PROVENANCE_SCHEMA_MISMATCH")
    if value.get("status") != "PASS":
        raise ContractError("SOURCE_PROVENANCE_STATUS_NOT_PASS")
    raw = _dig(value, (("provenance", "raw_tar"),))
    converter = _dig(value, (("provenance", "converter"),))
    gt = _dig(value, (("provenance", "gt"),))
    if not isinstance(raw, Mapping) or (
        raw.get("size") != RAW_TAR_SIZE_BYTES
        and raw.get("size_bytes") != RAW_TAR_SIZE_BYTES
    ) or raw.get("sha") != RAW_TAR_SHA256 and raw.get("sha256") != RAW_TAR_SHA256:
        raise ContractError("CANONICAL_RAW_TAR_PROVENANCE_MISMATCH")
    if not isinstance(converter, Mapping) or (
        converter.get("sha") != RAW_CONVERTER_SHA256
        and converter.get("sha256") != RAW_CONVERTER_SHA256
    ):
        raise ContractError("RAW_CONVERTER_PROVENANCE_MISMATCH")
    converter_path = str(converter.get("path", ""))
    if not converter_path.endswith(RAW_CONVERTER_RELATIVE):
        raise ContractError("RAW_CONVERTER_PATH_MISMATCH")
    if not isinstance(gt, Mapping) or (
        gt.get("size") != REFERENCE_SIZE_BYTES
        and gt.get("size_bytes") != REFERENCE_SIZE_BYTES
    ) or (
        gt.get("sha") != REFERENCE_SHA256 and gt.get("sha256") != REFERENCE_SHA256
    ):
        raise ContractError("REFERENCE_PROVENANCE_MISMATCH")

    selection = _dig(value, (("selection",),))
    if not isinstance(selection, Mapping):
        raise ContractError("PROVENANCE_SELECTION_INVALID")
    if (
        selection.get("camera_global_start_index") != GLOBAL_CAMERA_FIRST
        or selection.get("camera_global_end_index_inclusive") != GLOBAL_CAMERA_LAST
        or selection.get("image_count_expected") != CAMERA_COUNT
        or selection.get("imu_margin_ns") != 250_000_000
        or "imu_rule_closed_interval" not in selection
    ):
        raise ContractError("PROVENANCE_CAMERA_RANGE_MISMATCH")

    semantics = _dig(value, (("semantics",),))
    if not isinstance(semantics, Mapping) or (
        semantics.get("header_stamp") != "raw_csv_integer_ns"
        or semantics.get("record_stamp_equals_header") is not True
        or semantics.get("no_time_shift") is not True
        or semantics.get("image_encoding") != CAMERA_ENCODING
        or semantics.get("gt_pose") != "world_T_camera"
    ):
        raise ContractError("PROVENANCE_SEMANTICS_MISMATCH")

    output_record = _dig(value, (("output",),))
    if not isinstance(output_record, Mapping):
        raise ContractError("PROVENANCE_OUTPUT_INVALID")
    if output_record.get("compression") != "bz2":
        raise ContractError("PROVENANCE_OUTPUT_COMPRESSION_MISMATCH")
    output_size = output_record.get("size_bytes", output_record.get("size"))
    output_hash = output_record.get("sha256", output_record.get("sha"))
    bag = _regular_file(window_bag, "DERIVED_WINDOW_BAG")
    if output_size != bag.stat().st_size or output_hash != sha256_file(bag):
        raise ContractError("DERIVED_WINDOW_BAG_IDENTITY_MISMATCH")
    derived_identity = {
        "path": str(bag),
        "size_bytes": bag.stat().st_size,
        "sha256": str(output_hash),
    }
    topic_counts = output_record.get("topic_counts")
    if not isinstance(topic_counts, Mapping):
        raise ContractError("PROVENANCE_OUTPUT_TOPIC_COUNTS_MISSING")
    if topic_counts.get(CAMERA_TOPIC) != CAMERA_COUNT:
        raise ContractError("PROVENANCE_OUTPUT_CAMERA_COUNT_MISMATCH")
    checks = value.get("checks")
    if not isinstance(checks, Mapping) or not checks or any(item is not True for item in checks.values()):
        raise ContractError("PROVENANCE_CHECKS_NOT_ALL_TRUE")
    return {
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
        "producer_record": value,
        "output_topic_counts": dict(topic_counts),
        "derived_window_bag": derived_identity,
    }


def _topic_info(bag: Any) -> dict[str, dict[str, object]]:
    info = bag.get_type_and_topic_info()
    rows: dict[str, dict[str, object]] = {}
    for connection in bag._connections.values():  # ROS1 has no public equivalent.
        topic = str(connection.topic)
        if topic in rows:
            continue
        topic_info = info.topics[topic]
        rows[topic] = {
            "message_type": str(topic_info.msg_type),
            "message_count": int(topic_info.message_count),
        }
    return rows


def _stamp_ns(stamp: object, label: str) -> int:
    try:
        value = stamp.to_nsec()  # type: ignore[attr-defined]
    except Exception as error:
        raise ContractError(f"{label}_STAMP_INVALID") from error
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractError(f"{label}_STAMP_INVALID")
    return value


def _finite_xyz(vector: object, label: str) -> tuple[float, float, float]:
    try:
        values = (float(vector.x), float(vector.y), float(vector.z))  # type: ignore[attr-defined]
    except Exception as error:
        raise ContractError(f"{label}_INVALID") from error
    if not all(math.isfinite(item) for item in values):
        raise ContractError(f"{label}_NONFINITE")
    return values


def read_window_bag(
    path: Path, expected_topic_counts: Mapping[str, object]
) -> tuple[tuple[CameraSample, ...], tuple[ImuSample, ...], dict[str, dict[str, object]]]:
    try:
        import rosbag
    except ImportError as error:
        raise ContractError("ROSBAG_IMPORT_FAILED") from error

    cameras: list[CameraSample] = []
    imus: list[ImuSample] = []
    with rosbag.Bag(str(path), "r") as bag:
        audit = _topic_info(bag)
        observed_counts = {
            topic: int(row["message_count"]) for topic, row in audit.items()
        }
        normalized_expected_counts = {
            str(topic): int(count) for topic, count in expected_topic_counts.items()
        }
        if observed_counts != normalized_expected_counts:
            raise ContractError("DERIVED_BAG_TOPIC_COUNTS_DIFFER_FROM_PROVENANCE")
        for topic, expected_type in (
            (CAMERA_TOPIC, CAMERA_TYPE),
            (IMU_TOPIC, IMU_TYPE),
        ):
            row = audit.get(topic)
            if row is None:
                raise ContractError(f"REQUIRED_TOPIC_MISSING:{topic}")
            if row["message_type"] != expected_type:
                raise ContractError(f"REQUIRED_TOPIC_TYPE_MISMATCH:{topic}")
        if audit[CAMERA_TOPIC]["message_count"] != CAMERA_COUNT:
            raise ContractError("REQUIRED_TOPIC_COUNT_MISMATCH:/camera/image_raw")
        if int(audit[IMU_TOPIC]["message_count"]) < IMU_COUNT:
            raise ContractError("DERIVED_BAG_IMU_MARGIN_TOO_SMALL")

        for topic, message, record_stamp in bag.read_messages(
            topics=[CAMERA_TOPIC, IMU_TOPIC]
        ):
            observed_type = getattr(message, "_type", None)
            if topic == CAMERA_TOPIC:
                relative = len(cameras)
                if observed_type != CAMERA_TYPE:
                    raise ContractError("CAMERA_MESSAGE_TYPE_MISMATCH")
                header_ns = _stamp_ns(message.header.stamp, "CAMERA_HEADER")
                record_ns = _stamp_ns(record_stamp, "CAMERA_RECORD")
                if header_ns != record_ns:
                    raise ContractError("CAMERA_HEADER_RECORD_MISMATCH")
                width, height = int(message.width), int(message.height)
                encoding, step = str(message.encoding), int(message.step)
                pixels = bytes(message.data)
                if (width, height, encoding, step) != (
                    CAMERA_WIDTH,
                    CAMERA_HEIGHT,
                    CAMERA_ENCODING,
                    CAMERA_WIDTH,
                ):
                    raise ContractError("CAMERA_SCHEMA_MISMATCH")
                if len(pixels) != width * height:
                    raise ContractError("CAMERA_PAYLOAD_SIZE_MISMATCH")
                cameras.append(
                    CameraSample(
                        relative_index=relative,
                        global_index=GLOBAL_CAMERA_FIRST + relative,
                        header_ns=header_ns,
                        record_ns=record_ns,
                        width=width,
                        height=height,
                        encoding=encoding,
                        step=step,
                        pixels=pixels,
                        source_pixel_sha256=sha256_bytes(pixels),
                    )
                )
            else:
                relative = len(imus)
                if observed_type != IMU_TYPE:
                    raise ContractError("IMU_MESSAGE_TYPE_MISMATCH")
                raw_ns = _stamp_ns(message.header.stamp, "IMU_HEADER")
                record_ns = _stamp_ns(record_stamp, "IMU_RECORD")
                if raw_ns != record_ns:
                    raise ContractError("IMU_HEADER_RECORD_MISMATCH")
                imus.append(
                    ImuSample(
                        relative_index=relative,
                        global_index=-1,
                        raw_header_ns=raw_ns,
                        output_header_ns=raw_ns + IMU_SHIFT_NS,
                        record_ns=record_ns,
                        gyro_xyz=_finite_xyz(message.angular_velocity, "IMU_GYRO"),
                        accel_xyz=_finite_xyz(message.linear_acceleration, "IMU_ACCEL"),
                    )
                )

    if len(cameras) != CAMERA_COUNT:
        raise ContractError("SELECTED_CAMERA_COUNT_MISMATCH")
    first_matches = [
        index for index, sample in enumerate(imus)
        if sample.raw_header_ns == EXPECTED_FIRST_IMU_RAW_NS
    ]
    last_matches = [
        index for index, sample in enumerate(imus)
        if sample.raw_header_ns == EXPECTED_LAST_IMU_RAW_NS
    ]
    if len(first_matches) != 1 or len(last_matches) != 1:
        raise ContractError("HFNET_IMU_ENDPOINT_NOT_UNIQUE_IN_MARGIN_BAG")
    first_imu, last_imu = first_matches[0], last_matches[0]
    if last_imu - first_imu + 1 != IMU_COUNT:
        raise ContractError("HFNET_IMU_SUBSEQUENCE_COUNT_MISMATCH")
    selected_imus = []
    for relative, sample in enumerate(imus[first_imu : last_imu + 1]):
        selected_imus.append(
            ImuSample(
                relative_index=relative,
                global_index=GLOBAL_IMU_FIRST + relative,
                raw_header_ns=sample.raw_header_ns,
                output_header_ns=sample.output_header_ns,
                record_ns=sample.record_ns,
                gyro_xyz=sample.gyro_xyz,
                accel_xyz=sample.accel_xyz,
            )
        )
    imus = selected_imus
    if [sample.relative_index for sample in cameras] != list(range(CAMERA_COUNT)):
        raise ContractError("CAMERA_RELATIVE_INDEX_MISMATCH")
    if [sample.relative_index for sample in imus] != list(range(IMU_COUNT)):
        raise ContractError("IMU_RELATIVE_INDEX_MISMATCH")
    if any(b.header_ns <= a.header_ns for a, b in zip(cameras, cameras[1:])):
        raise ContractError("CAMERA_TIMESTAMPS_NOT_STRICT")
    if any(b.raw_header_ns <= a.raw_header_ns for a, b in zip(imus, imus[1:])):
        raise ContractError("IMU_TIMESTAMPS_NOT_STRICT")
    if (
        cameras[0].header_ns,
        cameras[PREFIX_CAMERA_COUNT - 1].header_ns,
        cameras[-1].header_ns,
    ) != (
        EXPECTED_FIRST_CAMERA_NS,
        EXPECTED_BOUNDARY_CAMERA_NS,
        EXPECTED_LAST_CAMERA_NS,
    ):
        raise ContractError("CAMERA_ENDPOINT_TIMESTAMP_MISMATCH")
    if (imus[0].raw_header_ns, imus[-1].raw_header_ns) != (
        EXPECTED_FIRST_IMU_RAW_NS,
        EXPECTED_LAST_IMU_RAW_NS,
    ):
        raise ContractError("IMU_ENDPOINT_TIMESTAMP_MISMATCH")
    if not imus[0].output_header_ns <= cameras[0].header_ns:
        raise ContractError("IMU_DOES_NOT_BRACKET_CAMERA_START")
    if not imus[-1].output_header_ns >= cameras[-1].header_ns:
        raise ContractError("IMU_DOES_NOT_BRACKET_CAMERA_END")
    return tuple(cameras), tuple(imus), audit


def load_references(path: Path, cameras: Sequence[CameraSample]) -> tuple[ReferencePose, ...]:
    resolved = _regular_file(path, "REFERENCE_PROXY")
    if resolved.stat().st_size != REFERENCE_SIZE_BYTES or sha256_file(resolved) != REFERENCE_SHA256:
        raise ContractError("REFERENCE_PROXY_IDENTITY_MISMATCH")
    wanted = set(SCORE_REFERENCE_INDICES)
    poses: dict[int, tuple[tuple[float, float, float], tuple[float, float, float, float]]] = {}
    with resolved.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            fields = line.split()
            if len(fields) != 8:
                raise ContractError(f"REFERENCE_COLUMN_COUNT_MISMATCH:{line_number}")
            try:
                index_float = float(fields[0])
                values = tuple(float(item) for item in fields[1:])
            except ValueError as error:
                raise ContractError(f"REFERENCE_NONNUMERIC:{line_number}") from error
            if not index_float.is_integer() or not all(math.isfinite(item) for item in values):
                raise ContractError(f"REFERENCE_INVALID_ROW:{line_number}")
            global_index = int(index_float)
            if global_index not in wanted:
                continue
            if global_index in poses:
                raise ContractError("REFERENCE_DUPLICATE_TARGET_INDEX")
            quaternion = values[3:7]
            norm = math.sqrt(sum(item * item for item in quaternion))
            if abs(norm - 1.0) > 1e-6:
                raise ContractError("REFERENCE_NONUNIT_QUATERNION")
            poses[global_index] = (values[0:3], quaternion)  # type: ignore[assignment]
    if set(poses) != wanted:
        raise ContractError("REFERENCE_TARGET_GRID_INCOMPLETE")
    by_global = {sample.global_index: sample for sample in cameras}
    return tuple(
        ReferencePose(
            global_camera_index=index,
            header_ns=by_global[index].header_ns,
            position_xyz=poses[index][0],
            quaternion_xyzw=poses[index][1],
        )
        for index in SCORE_REFERENCE_INDICES
    )


def validate_prefix(prefix_root: Path, cameras: Sequence[CameraSample]) -> tuple[dict[str, object], list[dict[str, object]]]:
    manifest_path = _regular_file(prefix_root / "conversion_manifest.json", "PREFIX_MANIFEST")
    if sha256_file(manifest_path) != PREFIX_MANIFEST_SHA256:
        raise ContractError("PREFIX_MANIFEST_IDENTITY_MISMATCH")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rows = manifest["camera"]["images"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ContractError("PREFIX_MANIFEST_SCHEMA_INVALID") from error
    if not isinstance(rows, list) or len(rows) != PREFIX_CAMERA_COUNT:
        raise ContractError("PREFIX_CAMERA_COUNT_MISMATCH")
    validated: list[dict[str, object]] = []
    for relative, (row, sample) in enumerate(zip(rows, cameras[:PREFIX_CAMERA_COUNT])):
        if not isinstance(row, Mapping):
            raise ContractError("PREFIX_IMAGE_ROW_INVALID")
        if row.get("source_index") != relative:
            raise ContractError("PREFIX_SOURCE_INDEX_MISMATCH")
        if row.get("raw_header_ns") != sample.header_ns:
            raise ContractError("PREFIX_TIMESTAMP_MISMATCH")
        if row.get("source_pixel_sha256") != sample.source_pixel_sha256:
            raise ContractError("PREFIX_SOURCE_PIXEL_HASH_MISMATCH")
        relative_path = row.get("relative_path")
        if not isinstance(relative_path, str) or Path(relative_path).parts != ("rgb", f"{sample.header_ns}.png"):
            raise ContractError("PREFIX_RELATIVE_PATH_MISMATCH")
        png = _regular_file(prefix_root / relative_path, "PREFIX_PNG")
        if png.parent.resolve() != (prefix_root / "rgb").resolve():
            raise ContractError("PREFIX_PNG_PATH_ESCAPE")
        observed_hash = sha256_file(png)
        if observed_hash != row.get("png_sha256") or png.stat().st_size != row.get("png_size_bytes"):
            raise ContractError("PREFIX_PNG_IDENTITY_MISMATCH")
        validated.append(
            {
                "path": png,
                "png_sha256": observed_hash,
                "png_size_bytes": png.stat().st_size,
            }
        )
    return (
        {
            "root": str(prefix_root.resolve()),
            "manifest_sha256": PREFIX_MANIFEST_SHA256,
            "camera_count": PREFIX_CAMERA_COUNT,
        },
        validated,
    )


def encode_lossless_png(sample: CameraSample) -> bytes:
    try:
        import cv2
        import numpy as np
    except ImportError as error:
        raise ContractError("OPENCV_NUMPY_IMPORT_FAILED") from error
    source = np.frombuffer(sample.pixels, dtype=np.uint8).reshape(sample.height, sample.width)
    ok, encoded = cv2.imencode(".png", source)
    if not ok:
        raise ContractError("PNG_ENCODE_FAILED")
    payload = bytes(encoded)
    decoded = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if decoded is None or decoded.dtype != source.dtype or decoded.shape != source.shape:
        raise ContractError("PNG_DECODE_SCHEMA_CHANGED")
    if not np.array_equal(decoded, source):
        raise ContractError("PNG_PIXEL_CHANGED")
    return payload


def _link_or_copy(source: Path, target: Path) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
        return "hardlink"
    except OSError:
        shutil.copyfile(source, target)
        return "copy"


@contextmanager
def atomic_directory(target: Path) -> Iterator[Path]:
    if target.exists() or target.is_symlink():
        raise ContractError("OUTPUT_ALREADY_EXISTS")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.tmp-", dir=str(target.parent)))
    try:
        yield staging
        if target.exists() or target.is_symlink():
            raise ContractError("OUTPUT_APPEARED_DURING_EXPORT")
        os.rename(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _timestamp_seconds(ns: int) -> str:
    seconds, fraction = divmod(ns, 1_000_000_000)
    return f"{seconds}.{fraction:09d}"


def _float_text(value: float) -> str:
    if not math.isfinite(value):
        raise ContractError("NONFINITE_OUTPUT_VALUE")
    return format(value, ".17g")


def imu_csv_bytes(imus: Sequence[ImuSample]) -> bytes:
    rows = ["#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],w_RS_S_z [rad s^-1],a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],a_RS_S_z [m s^-2]"]
    for sample in imus:
        values = (*sample.gyro_xyz, *sample.accel_xyz)
        rows.append(str(sample.output_header_ns) + "," + ",".join(_float_text(item) for item in values))
    return "\n".join(rows).encode("ascii")


def reference_tum_bytes(references: Sequence[ReferencePose]) -> bytes:
    rows = []
    for pose in references:
        values = (*pose.position_xyz, *pose.quaternion_xyzw)
        rows.append(_timestamp_seconds(pose.header_ns) + " " + " ".join(_float_text(item) for item in values))
    return ("\n".join(rows) + "\n").encode("ascii")


def write_artifact(
    output: Path,
    window_bag: Path,
    provenance_identity: Mapping[str, object],
    reference_path: Path,
    prefix_root: Path,
    selection: Selection,
) -> dict[str, object]:
    if len(selection.cameras) != CAMERA_COUNT or len(selection.imus) != IMU_COUNT:
        raise ContractError("WRITE_SELECTION_COUNT_MISMATCH")
    if len(selection.references) != len(SCORE_REFERENCE_INDICES):
        raise ContractError("WRITE_REFERENCE_COUNT_MISMATCH")
    prefix_identity, prefix_rows = validate_prefix(prefix_root, selection.cameras)

    with atomic_directory(output) as staging:
        canonical_dir = staging / "shared" / "cam0" / "data"
        image_rows: list[dict[str, object]] = []
        for sample in selection.cameras:
            target = canonical_dir / f"{sample.header_ns}.png"
            if sample.relative_index < PREFIX_CAMERA_COUNT:
                old = prefix_rows[sample.relative_index]
                mode = _link_or_copy(old["path"], target)  # type: ignore[arg-type]
                png_hash = str(old["png_sha256"])
                png_size = int(old["png_size_bytes"])
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                payload = encode_lossless_png(sample)
                target.write_bytes(payload)
                mode = "encoded_new_lossless"
                png_hash = sha256_bytes(payload)
                png_size = len(payload)
            if target.stat().st_size != png_size or sha256_file(target) != png_hash:
                raise ContractError("CANONICAL_PNG_POSTWRITE_IDENTITY_MISMATCH")
            image_rows.append(
                {
                    "relative_index": sample.relative_index,
                    "global_source_index": sample.global_index,
                    "raw_header_ns": sample.header_ns,
                    "source_pixel_sha256": sample.source_pixel_sha256,
                    "png_sha256": png_hash,
                    "png_size_bytes": png_size,
                    "materialization": mode,
                    "relative_path": f"shared/cam0/data/{sample.header_ns}.png",
                }
            )

        times_payload = ("\n".join(str(row["raw_header_ns"]) for row in image_rows) + "\n").encode("ascii")
        (staging / "shared" / "cam0_times.txt").write_bytes(times_payload)
        (staging / "shared" / "reference_proxy.tum").write_bytes(reference_tum_bytes(selection.references))
        mapping_rows = ["global_camera_index,header_ns,role"] + [
            f"{pose.global_camera_index},{pose.header_ns},SCORE"
            for pose in selection.references
        ]
        (staging / "shared" / "reference_mapping.csv").write_text(
            "\n".join(mapping_rows) + "\n", encoding="ascii"
        )

        hf_cam = staging / "hfnet" / "mav0" / "cam0" / "data"
        hf_modes: dict[str, int] = {}
        for row in image_rows:
            source = staging / str(row["relative_path"])
            mode = _link_or_copy(source, hf_cam / source.name)
            hf_modes[mode] = hf_modes.get(mode, 0) + 1
        hf_cam_csv = ["#timestamp [ns],filename"] + [
            f"{row['raw_header_ns']},{row['raw_header_ns']}.png" for row in image_rows
        ]
        (staging / "hfnet" / "mav0" / "cam0" / "data.csv").write_bytes(
            "\n".join(hf_cam_csv).encode("ascii")
        )
        imu_path = staging / "hfnet" / "mav0" / "imu0" / "data.csv"
        imu_path.parent.mkdir(parents=True, exist_ok=True)
        imu_path.write_bytes(imu_csv_bytes(selection.imus))
        (staging / "hfnet" / "cam0_times.txt").write_bytes(times_payload)

        manifest: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "status": STATUS_EXPORTED,
            "source": {
                "derived_window_bag": dict(
                    provenance_identity.get("derived_window_bag")  # type: ignore[arg-type]
                    or _identity(window_bag)
                ),
                "provenance": dict(provenance_identity),
                "canonical_raw_archive": {
                    "size_bytes": RAW_TAR_SIZE_BYTES,
                    "sha256": RAW_TAR_SHA256,
                    "converter_relative_path": RAW_CONVERTER_RELATIVE,
                    "converter_sha256": RAW_CONVERTER_SHA256,
                },
                "known_full_bag_cross_source_catalog_not_producer_provenance": {
                    "size_bytes": FULL_BAG_SIZE_BYTES,
                    "sha256": FULL_BAG_SHA256,
                    "topic_counts": FULL_BAG_TOPIC_COUNTS,
                },
            },
            "window": {
                "feed_global_camera_indices_inclusive": [GLOBAL_CAMERA_FIRST, GLOBAL_CAMERA_LAST],
                "camera_count": CAMERA_COUNT,
                "preroll_global_camera_indices_inclusive": list(PREROLL_GLOBAL_INDICES),
                "score_global_camera_indices_inclusive": list(SCORE_GLOBAL_INDICES),
                "score_reference_global_indices": list(SCORE_REFERENCE_INDICES),
                "score_reference_count": len(SCORE_REFERENCE_INDICES),
            },
            "camera": {
                "topic": CAMERA_TOPIC,
                "message_type": CAMERA_TYPE,
                "width": CAMERA_WIDTH,
                "height": CAMERA_HEIGHT,
                "encoding": CAMERA_ENCODING,
                "first_header_ns": selection.cameras[0].header_ns,
                "boundary_header_ns": selection.cameras[PREFIX_CAMERA_COUNT - 1].header_ns,
                "last_header_ns": selection.cameras[-1].header_ns,
                "images": image_rows,
                "prefix_reuse": prefix_identity,
                "newly_encoded_relative_indices_inclusive": [PREFIX_CAMERA_COUNT, CAMERA_COUNT - 1],
            },
            "imu": {
                "topic": IMU_TOPIC,
                "message_type": IMU_TYPE,
                "global_indices_inclusive": [GLOBAL_IMU_FIRST, GLOBAL_IMU_LAST],
                "count": IMU_COUNT,
                "time_transform": f"output_ns=raw_header_ns+{IMU_SHIFT_NS}",
                "first_raw_header_ns": selection.imus[0].raw_header_ns,
                "last_raw_header_ns": selection.imus[-1].raw_header_ns,
                "first_output_header_ns": selection.imus[0].output_header_ns,
                "last_output_header_ns": selection.imus[-1].output_header_ns,
                "brackets_camera": True,
            },
            "reference": {
                "identity": _identity(reference_path),
                "role": "same-image offline COLMAP, scale corrected with depth metadata; not sensor-independent ground truth",
                "pose_convention": "world_T_camera",
                "target_rows": len(selection.references),
                "mapping": [
                    {"global_camera_index": pose.global_camera_index, "header_ns": pose.header_ns}
                    for pose in selection.references
                ],
            },
            "views": {
                "canonical_png_root": "shared/cam0/data",
                "canonical_times": "shared/cam0_times.txt",
                "reference_tum": "shared/reference_proxy.tum",
                "hfnet_euroc_root": "hfnet",
                "hfnet_camera_link_modes": hf_modes,
                "project_ros_window_bag": "provided by the separately frozen one-pass source-window exporter; not duplicated here",
            },
            "topic_audit": selection.topic_audit,
            "claims": {
                "hfnet_started": False,
                "anyfeature_started": False,
                "aqua_fe_started": False,
                "official_source_modified": False,
                "accuracy_result_generated": False,
            },
        }
        manifest_path = staging / "conversion_manifest.json"
        manifest_path.write_bytes(canonical_json_bytes(manifest))
    return manifest


def prepare(window_bag: Path, provenance: Path, reference: Path) -> tuple[dict[str, object], Selection]:
    provenance_identity = validate_provenance(provenance, window_bag)
    cameras, imus, topic_audit = read_window_bag(
        window_bag,
        provenance_identity["output_topic_counts"],  # type: ignore[arg-type]
    )
    references = load_references(reference, cameras)
    return provenance_identity, Selection(cameras, imus, references, topic_audit)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("preflight", "export"), default="preflight")
    parser.add_argument("--source-window-bag", type=Path, default=DEFAULT_WINDOW_BAG)
    parser.add_argument("--source-provenance", type=Path, default=DEFAULT_PROVENANCE)
    parser.add_argument("--prefix-root", type=Path, default=DEFAULT_PREFIX_ROOT)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(tuple(sys.argv[1:] if argv is None else argv))
    try:
        provenance, selection = prepare(
            args.source_window_bag, args.source_provenance, args.reference
        )
        if args.action == "preflight":
            validate_prefix(args.prefix_root, selection.cameras)
            print(
                json.dumps(
                    {
                        "status": "PREFLIGHT_PASSED_NO_OUTPUT_WRITTEN",
                        "camera_count": len(selection.cameras),
                        "imu_count": len(selection.imus),
                        "reference_count": len(selection.references),
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.output is None:
            raise ContractError("OUTPUT_REQUIRED_FOR_EXPORT")
        manifest = write_artifact(
            args.output,
            args.source_window_bag,
            provenance,
            args.reference,
            args.prefix_root,
            selection,
        )
        print(json.dumps({"status": manifest["status"], "output": str(args.output)}))
        return 0
    except ContractError as error:
        print(f"CONTRACT_BLOCKED:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
