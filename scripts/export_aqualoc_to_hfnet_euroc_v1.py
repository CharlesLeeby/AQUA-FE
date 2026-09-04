#!/usr/bin/env python3
"""Export the frozen AQUALOC A02 prefix to HFNet-SLAM's EuRoC layout.

This is a high-level, fail-closed data adapter.  It does not edit, build, or
run HFNet-SLAM.  The only production contract is:

* source bag ``archaeo02_4500_5400.bag`` at its frozen byte identity;
* camera topic ``/camera/image_raw``, source indices 0..199;
* IMU topic ``/rtimulib_node/imu``, source indices 38..2027;
* image filenames and ``cam0_times.txt`` use raw camera header nanoseconds;
* IMU timestamps are placed in camera time with
  ``t_out = t_raw + 53,694,112 ns`` (Kalibr td=-0.053694112369382575 s);
* PNG decoding reproduces every source mono8 pixel exactly;
* ``imu0/data.csv`` has no final newline.  This matters because the frozen
  upstream loader accesses ``s[0]`` before checking whether an EOF line is
  empty.

Output is staged in a sibling directory and atomically renamed.  Existing
targets are never overwritten.  The default action is read-only preflight;
``--action export`` is required to materialize the unique 200-frame prefix.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


ADAPTER_VERSION = "aqualoc-hfnet-euroc-v1"
HFNET_COMMIT = "c354c72588a97bb6f6a9c7c8317530795956ec80"
HFNET_ORIGIN = "https://github.com/LiuLimingCode/HFNet_SLAM.git"
HFNET_FILE_SHA256 = {
    "README.md": "84d2b2ccae43b28647cd733d26d9003a19f96af53e349423560f2323bcdbdb75",
    "CMakeLists.txt": "8f51fbcb9ed8182e5ab6998d1ad73aec0df685759174f9c910636d2c971b259e",
    "Examples/Monocular-Inertial/mono_inertial_euroc.cc": (
        "fa3effb0c2b99bc4dd83abda443180cf2f017f61710e02fa6b3f9278cc774d39"
    ),
    "Examples/Monocular-Inertial/EuRoC.yaml": (
        "9bbf682649b32ab2292979c7bf63b9fe12787948e74811838259aa723ab8ed01"
    ),
    "src/System.cc": "4621d33384b904b68c1041bc5a1acd28eac07fc75481f89733ceeb3470215cc6",
    "src/Tracking.cc": "e2cadda4cf9391129b097107ea1d35224a09d6ccf3b13eb87024120730a0b7e2",
}

WORKSPACE_DEFAULT = Path(__file__).resolve().parents[1]
SOURCE_RELATIVE = "datasets/aqualoc/rosbags/archaeo02_4500_5400.bag"
SOURCE_SIZE_BYTES = 222_477_260
SOURCE_SHA256 = "8cceb4c76065f3862e60428b14ba10f9a26fc7249e11e9e9d090fed2437238a8"
HFNET_ROOT_DEFAULT = Path.home() / "SLAM" / "HFNet-SLAM-paper-2023-r1"

CAMERA_TOPIC = "/camera/image_raw"
IMU_TOPIC = "/rtimulib_node/imu"
CAMERA_MESSAGE_TYPE = "sensor_msgs/Image"
IMU_MESSAGE_TYPE = "sensor_msgs/Imu"
KALIBR_TIMESHIFT_CAM_IMU_S = -0.053694112369382575
IMU_OUTPUT_SHIFT_NS = 53_694_112

CSV_HEADER = (
    "#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],"
    "w_RS_S_z [rad s^-1],a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],"
    "a_RS_S_z [m s^-2]"
)

STATUS_PREFLIGHT_READY = "PREFLIGHT_READY"
STATUS_EXPORTED = "EXPORTED"
STATUS_INTEGRITY_ERROR = "INTEGRITY_ERROR"
RC_READY = 0
RC_INTEGRITY_ERROR = 2


class ContractError(RuntimeError):
    """The source, upstream checkout, or output violates the frozen contract."""


@dataclass(frozen=True)
class PrefixContract:
    image_topic: str
    imu_topic: str
    expected_image_type: str
    expected_imu_type: str
    expected_total_images: int
    expected_total_imus: int
    image_first_index: int
    image_last_index: int
    imu_first_index: int
    imu_last_index: int
    width: int
    height: int
    encoding: str
    imu_shift_ns: int
    expected_first_image_stamp_ns: int | None = None
    expected_last_image_stamp_ns: int | None = None
    expected_first_imu_raw_stamp_ns: int | None = None
    expected_last_imu_raw_stamp_ns: int | None = None

    @property
    def image_count(self) -> int:
        return self.image_last_index - self.image_first_index + 1

    @property
    def imu_count(self) -> int:
        return self.imu_last_index - self.imu_first_index + 1


A02_PREFIX_CONTRACT = PrefixContract(
    image_topic=CAMERA_TOPIC,
    imu_topic=IMU_TOPIC,
    expected_image_type=CAMERA_MESSAGE_TYPE,
    expected_imu_type=IMU_MESSAGE_TYPE,
    expected_total_images=901,
    expected_total_imus=9_091,
    image_first_index=0,
    image_last_index=199,
    imu_first_index=38,
    imu_last_index=2_027,
    width=968,
    height=608,
    encoding="mono8",
    imu_shift_ns=IMU_OUTPUT_SHIFT_NS,
    expected_first_image_stamp_ns=1_542_829_016_700_435_392,
    expected_last_image_stamp_ns=1_542_829_026_649_564_544,
    expected_first_imu_raw_stamp_ns=1_542_829_016_645_312_000,
    expected_last_imu_raw_stamp_ns=1_542_829_026_596_966_304,
)


@dataclass(frozen=True)
class CameraSample:
    source_index: int
    header_ns: int
    record_ns: int
    width: int
    height: int
    encoding: str
    step: int
    pixels: bytes
    pixel_sha256: str


@dataclass(frozen=True)
class ImuSample:
    source_index: int
    raw_header_ns: int
    output_header_ns: int
    record_ns: int
    gyro_xyz: tuple[float, float, float]
    accel_xyz: tuple[float, float, float]


@dataclass(frozen=True)
class SourceSelection:
    cameras: tuple[CameraSample, ...]
    imus: tuple[ImuSample, ...]
    topic_audit: Mapping[str, Mapping[str, Any]]
    all_image_first_ns: int
    all_image_last_ns: int
    all_imu_first_ns: int
    all_imu_last_ns: int


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"


def ros_time_to_ns(stamp: Any) -> int:
    if hasattr(stamp, "to_nsec"):
        return int(stamp.to_nsec())
    seconds = getattr(stamp, "secs", getattr(stamp, "sec", None))
    nanoseconds = getattr(stamp, "nsecs", getattr(stamp, "nanosec", None))
    if seconds is None or nanoseconds is None:
        raise ContractError("ROS_TIME_SCHEMA_MISSING")
    return int(seconds) * 1_000_000_000 + int(nanoseconds)


def shifted_imu_stamp_ns(raw_header_ns: int, shift_ns: int = IMU_OUTPUT_SHIFT_NS) -> int:
    return int(raw_header_ns) + int(shift_ns)


def _run_git(root: Path, arguments: Sequence[str]) -> tuple[int, str, str]:
    process = subprocess.run(
        ["git", "-C", str(root), *arguments],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return process.returncode, process.stdout.strip(), process.stderr.strip()


def audit_hfnet_checkout(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    if not root.is_dir():
        return {
            "root": str(root),
            "errors": ["HFNET_ROOT_MISSING"],
            "expected_commit": HFNET_COMMIT,
        }
    rc, head, _ = _run_git(root, ["rev-parse", "HEAD"])
    if rc != 0 or head != HFNET_COMMIT:
        errors.append("HFNET_COMMIT_MISMATCH")
    rc, origin, _ = _run_git(root, ["remote", "get-url", "origin"])
    if rc != 0 or origin != HFNET_ORIGIN:
        errors.append("HFNET_ORIGIN_MISMATCH")
    rc, tracked_status, _ = _run_git(
        root, ["status", "--porcelain=v1", "--untracked-files=no"]
    )
    if rc != 0 or tracked_status:
        errors.append("HFNET_TRACKED_WORKTREE_DIRTY")
    actual_hashes: dict[str, str | None] = {}
    for relative, expected in HFNET_FILE_SHA256.items():
        path = root / relative
        actual = sha256_file(path) if path.is_file() else None
        actual_hashes[relative] = actual
        if actual != expected:
            errors.append(f"HFNET_FILE_HASH_MISMATCH:{relative}")
    return {
        "root": str(root),
        "expected_commit": HFNET_COMMIT,
        "actual_commit": head if rc == 0 else None,
        "expected_origin": HFNET_ORIGIN,
        "actual_origin": origin,
        "tracked_worktree_status": tracked_status,
        "expected_file_sha256": HFNET_FILE_SHA256,
        "actual_file_sha256": actual_hashes,
        "errors": errors,
    }


def _topic_info(bag: Any) -> dict[str, dict[str, Any]]:
    info = bag.get_type_and_topic_info()
    connection_counts: dict[str, int] = {}
    for connection in bag._connections.values():  # ROS1 has no public equivalent.
        connection_counts[connection.topic] = connection_counts.get(connection.topic, 0) + 1
    return {
        topic: {
            "message_type": row.msg_type,
            "message_count": int(row.message_count),
            "connection_count": connection_counts.get(topic, 0),
        }
        for topic, row in info.topics.items()
    }


def _validate_topic_contract(
    topics: Mapping[str, Mapping[str, Any]], contract: PrefixContract
) -> None:
    requirements = (
        (
            contract.image_topic,
            contract.expected_image_type,
            contract.expected_total_images,
            "CAMERA",
        ),
        (
            contract.imu_topic,
            contract.expected_imu_type,
            contract.expected_total_imus,
            "IMU",
        ),
    )
    for topic, expected_type, expected_count, label in requirements:
        row = topics.get(topic)
        if row is None:
            raise ContractError(f"{label}_TOPIC_MISSING")
        if row.get("message_type") != expected_type:
            raise ContractError(f"{label}_MESSAGE_TYPE_MISMATCH")
        if int(row.get("message_count", -1)) != expected_count:
            raise ContractError(f"{label}_TOTAL_COUNT_MISMATCH")
        if int(row.get("connection_count", -1)) != 1:
            raise ContractError(f"{label}_CONNECTION_COUNT_MISMATCH")


def _image_payload(msg: Any, contract: PrefixContract) -> bytes:
    if getattr(msg, "_type", None) != contract.expected_image_type:
        raise ContractError("CAMERA_RUNTIME_MESSAGE_TYPE_MISMATCH")
    width = int(msg.width)
    height = int(msg.height)
    encoding = str(msg.encoding).lower()
    step = int(msg.step)
    if (width, height) != (contract.width, contract.height):
        raise ContractError("CAMERA_DIMENSION_MISMATCH")
    if encoding != contract.encoding.lower():
        raise ContractError("CAMERA_ENCODING_MISMATCH")
    if int(getattr(msg, "is_bigendian", 0)) != 0:
        raise ContractError("CAMERA_BIG_ENDIAN_UNSUPPORTED")
    if step != contract.width:
        raise ContractError("CAMERA_STEP_MISMATCH")
    payload = bytes(msg.data)
    if len(payload) != contract.width * contract.height:
        raise ContractError("CAMERA_PAYLOAD_SIZE_MISMATCH")
    return payload


def _imu_values(msg: Any, contract: PrefixContract) -> tuple[tuple[float, ...], tuple[float, ...]]:
    if getattr(msg, "_type", None) != contract.expected_imu_type:
        raise ContractError("IMU_RUNTIME_MESSAGE_TYPE_MISMATCH")
    gyro = (
        float(msg.angular_velocity.x),
        float(msg.angular_velocity.y),
        float(msg.angular_velocity.z),
    )
    accel = (
        float(msg.linear_acceleration.x),
        float(msg.linear_acceleration.y),
        float(msg.linear_acceleration.z),
    )
    if not all(math.isfinite(item) for item in (*gyro, *accel)):
        raise ContractError("IMU_NONFINITE_VALUE")
    return gyro, accel


def read_source_selection(source_bag: Path, contract: PrefixContract) -> SourceSelection:
    try:
        import rosbag
    except ImportError as exc:  # pragma: no cover - environment gate
        raise ContractError("ROSBAG_PYTHON_UNAVAILABLE") from exc

    cameras: list[CameraSample] = []
    imus: list[ImuSample] = []
    image_index = 0
    imu_index = 0
    previous_image_ns: int | None = None
    previous_imu_ns: int | None = None
    all_image_first_ns: int | None = None
    all_imu_first_ns: int | None = None
    all_image_last_ns: int | None = None
    all_imu_last_ns: int | None = None

    with rosbag.Bag(str(source_bag), "r") as bag:
        topics = _topic_info(bag)
        _validate_topic_contract(topics, contract)
        for topic, msg, record_stamp in bag.read_messages(
            topics=[contract.image_topic, contract.imu_topic]
        ):
            record_ns = ros_time_to_ns(record_stamp)
            header_ns = ros_time_to_ns(msg.header.stamp)
            if record_ns != header_ns:
                raise ContractError(f"RECORD_HEADER_STAMP_MISMATCH:{topic}")
            if topic == contract.image_topic:
                payload = _image_payload(msg, contract)
                if previous_image_ns is not None and header_ns <= previous_image_ns:
                    raise ContractError("CAMERA_STAMP_NOT_STRICTLY_MONOTONIC")
                previous_image_ns = header_ns
                all_image_first_ns = header_ns if all_image_first_ns is None else all_image_first_ns
                all_image_last_ns = header_ns
                if contract.image_first_index <= image_index <= contract.image_last_index:
                    cameras.append(
                        CameraSample(
                            source_index=image_index,
                            header_ns=header_ns,
                            record_ns=record_ns,
                            width=int(msg.width),
                            height=int(msg.height),
                            encoding=str(msg.encoding),
                            step=int(msg.step),
                            pixels=payload,
                            pixel_sha256=hashlib.sha256(payload).hexdigest(),
                        )
                    )
                image_index += 1
            elif topic == contract.imu_topic:
                gyro, accel = _imu_values(msg, contract)
                if previous_imu_ns is not None and header_ns <= previous_imu_ns:
                    raise ContractError("IMU_STAMP_NOT_STRICTLY_MONOTONIC")
                previous_imu_ns = header_ns
                all_imu_first_ns = header_ns if all_imu_first_ns is None else all_imu_first_ns
                all_imu_last_ns = header_ns
                if contract.imu_first_index <= imu_index <= contract.imu_last_index:
                    imus.append(
                        ImuSample(
                            source_index=imu_index,
                            raw_header_ns=header_ns,
                            output_header_ns=shifted_imu_stamp_ns(
                                header_ns, contract.imu_shift_ns
                            ),
                            record_ns=record_ns,
                            gyro_xyz=gyro,  # type: ignore[arg-type]
                            accel_xyz=accel,  # type: ignore[arg-type]
                        )
                    )
                imu_index += 1

    if image_index != contract.expected_total_images:
        raise ContractError("CAMERA_SCANNED_COUNT_MISMATCH")
    if imu_index != contract.expected_total_imus:
        raise ContractError("IMU_SCANNED_COUNT_MISMATCH")
    if len(cameras) != contract.image_count:
        raise ContractError("CAMERA_SELECTION_COUNT_MISMATCH")
    if len(imus) != contract.imu_count:
        raise ContractError("IMU_SELECTION_COUNT_MISMATCH")
    assert all_image_first_ns is not None and all_image_last_ns is not None
    assert all_imu_first_ns is not None and all_imu_last_ns is not None
    selection = SourceSelection(
        cameras=tuple(cameras),
        imus=tuple(imus),
        topic_audit=topics,
        all_image_first_ns=all_image_first_ns,
        all_image_last_ns=all_image_last_ns,
        all_imu_first_ns=all_imu_first_ns,
        all_imu_last_ns=all_imu_last_ns,
    )
    validate_selection(selection, contract)
    return selection


def _check_expected(actual: int, expected: int | None, label: str) -> None:
    if expected is not None and actual != expected:
        raise ContractError(f"{label}_MISMATCH")


def validate_selection(selection: SourceSelection, contract: PrefixContract) -> None:
    cameras = selection.cameras
    imus = selection.imus
    if [sample.source_index for sample in cameras] != list(
        range(contract.image_first_index, contract.image_last_index + 1)
    ):
        raise ContractError("CAMERA_SOURCE_INDEX_SEQUENCE_MISMATCH")
    if [sample.source_index for sample in imus] != list(
        range(contract.imu_first_index, contract.imu_last_index + 1)
    ):
        raise ContractError("IMU_SOURCE_INDEX_SEQUENCE_MISMATCH")
    if any(
        current.header_ns <= previous.header_ns
        for previous, current in zip(cameras, cameras[1:])
    ):
        raise ContractError("SELECTED_CAMERA_STAMPS_NOT_STRICT")
    if any(
        current.output_header_ns <= previous.output_header_ns
        for previous, current in zip(imus, imus[1:])
    ):
        raise ContractError("SELECTED_IMU_STAMPS_NOT_STRICT")
    if not imus[0].output_header_ns <= cameras[0].header_ns:
        raise ContractError("SHIFTED_IMU_DOES_NOT_BRACKET_FIRST_CAMERA")
    if not imus[-1].output_header_ns >= cameras[-1].header_ns:
        raise ContractError("SHIFTED_IMU_DOES_NOT_BRACKET_LAST_CAMERA")
    _check_expected(
        cameras[0].header_ns,
        contract.expected_first_image_stamp_ns,
        "FIRST_SELECTED_CAMERA_STAMP",
    )
    _check_expected(
        cameras[-1].header_ns,
        contract.expected_last_image_stamp_ns,
        "LAST_SELECTED_CAMERA_STAMP",
    )
    _check_expected(
        imus[0].raw_header_ns,
        contract.expected_first_imu_raw_stamp_ns,
        "FIRST_SELECTED_IMU_RAW_STAMP",
    )
    _check_expected(
        imus[-1].raw_header_ns,
        contract.expected_last_imu_raw_stamp_ns,
        "LAST_SELECTED_IMU_RAW_STAMP",
    )


def imu_csv_bytes(samples: Sequence[ImuSample]) -> bytes:
    lines = [CSV_HEADER]
    for sample in samples:
        values = (*sample.gyro_xyz, *sample.accel_xyz)
        lines.append(
            str(sample.output_header_ns)
            + ","
            + ",".join(format(value, ".17g") for value in values)
        )
    payload = "\n".join(lines).encode("utf-8")
    if payload.endswith(b"\n"):
        raise AssertionError("HFNet CSV must not have a final newline")
    return payload


def camera_times_bytes(samples: Sequence[CameraSample]) -> bytes:
    return ("\n".join(str(sample.header_ns) for sample in samples) + "\n").encode(
        "ascii"
    )


def encode_lossless_png(sample: CameraSample) -> bytes:
    try:
        import cv2
        import numpy as np
    except ImportError as exc:  # pragma: no cover - environment gate
        raise ContractError("CV2_OR_NUMPY_UNAVAILABLE") from exc
    source = np.frombuffer(sample.pixels, dtype=np.uint8).reshape(
        sample.height, sample.width
    )
    ok, encoded = cv2.imencode(".png", source)
    if not ok:
        raise ContractError(f"PNG_ENCODE_FAILED:{sample.source_index}")
    encoded_bytes = bytes(encoded)
    decoded = cv2.imdecode(
        np.frombuffer(encoded_bytes, dtype=np.uint8), cv2.IMREAD_UNCHANGED
    )
    if decoded is None:
        raise ContractError(f"PNG_DECODE_FAILED:{sample.source_index}")
    if decoded.shape != source.shape or decoded.dtype != source.dtype:
        raise ContractError(f"PNG_SCHEMA_CHANGED:{sample.source_index}")
    if not np.array_equal(decoded, source):
        raise ContractError(f"PNG_PIXEL_CHANGED:{sample.source_index}")
    return encoded_bytes


@contextmanager
def atomic_directory(target: Path) -> Iterator[Path]:
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


def _aggregate_rows(rows: Sequence[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for name, file_hash in rows:
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def write_artifact(
    output_sequence_root: Path,
    source_bag: Path,
    source_sha256: str,
    selection: SourceSelection,
    contract: PrefixContract,
    upstream_audit: Mapping[str, Any],
) -> dict[str, Any]:
    with atomic_directory(output_sequence_root) as staging:
        image_directory = staging / "mav0" / "cam0" / "data"
        image_directory.mkdir(parents=True)
        image_rows: list[dict[str, Any]] = []
        aggregate_rows: list[tuple[str, str]] = []
        for sample in selection.cameras:
            filename = f"{sample.header_ns}.png"
            relative = f"mav0/cam0/data/{filename}"
            encoded = encode_lossless_png(sample)
            (image_directory / filename).write_bytes(encoded)
            output_hash = hashlib.sha256(encoded).hexdigest()
            image_rows.append(
                {
                    "source_index": sample.source_index,
                    "raw_header_ns": sample.header_ns,
                    "filename": filename,
                    "source_pixel_sha256": sample.pixel_sha256,
                    "png_sha256": output_hash,
                    "pixel_identity_verified": True,
                }
            )
            aggregate_rows.append((relative, output_hash))

        times_payload = camera_times_bytes(selection.cameras)
        times_path = staging / "cam0_times.txt"
        times_path.write_bytes(times_payload)
        times_hash = hashlib.sha256(times_payload).hexdigest()
        aggregate_rows.append(("cam0_times.txt", times_hash))

        csv_payload = imu_csv_bytes(selection.imus)
        imu_path = staging / "mav0" / "imu0" / "data.csv"
        imu_path.parent.mkdir(parents=True)
        imu_path.write_bytes(csv_payload)
        csv_hash = hashlib.sha256(csv_payload).hexdigest()
        aggregate_rows.append(("mav0/imu0/data.csv", csv_hash))

        imu_duration_s = (
            selection.imus[-1].output_header_ns
            - selection.imus[0].output_header_ns
        ) / 1e9
        observed_imu_rate_hz = (len(selection.imus) - 1) / imu_duration_s
        manifest: dict[str, Any] = {
            "adapter_version": ADAPTER_VERSION,
            "status": STATUS_EXPORTED,
            "artifact_scope": "A02_CAMERA_INDICES_0_199_PREFIX_ONLY",
            "evaluation_eligible_full_window": False,
            "source": {
                "bag": str(source_bag),
                "resolved_bag": str(source_bag.resolve()),
                "size_bytes": source_bag.stat().st_size,
                "sha256": source_sha256,
                "topics": selection.topic_audit,
            },
            "upstream": dict(upstream_audit),
            "contract": {
                **asdict(contract),
                "kalibr_timeshift_cam_imu_s": KALIBR_TIMESHIFT_CAM_IMU_S,
                "imu_time_transform": "output_ns=raw_header_ns+53694112",
                "image_time_transform": "none; raw ROS header ns",
                "hfnet_input_reader": (
                    "Examples/Monocular-Inertial/mono_inertial_euroc.cc"
                ),
                "hfnet_invocation_paths": {
                    "sequence_root": "<this artifact>",
                    "times_file": "<this artifact>/cam0_times.txt",
                    "images": "<this artifact>/mav0/cam0/data/<timestamp>.png",
                    "imu": "<this artifact>/mav0/imu0/data.csv",
                },
            },
            "camera": {
                "count": len(selection.cameras),
                "source_indices_inclusive": [
                    selection.cameras[0].source_index,
                    selection.cameras[-1].source_index,
                ],
                "first_raw_header_ns": selection.cameras[0].header_ns,
                "last_raw_header_ns": selection.cameras[-1].header_ns,
                "strictly_monotonic": True,
                "schema": {
                    "width": contract.width,
                    "height": contract.height,
                    "encoding": contract.encoding,
                    "step": contract.width,
                },
                "times_file": {
                    "path": "cam0_times.txt",
                    "sha256": times_hash,
                    "line_count": len(selection.cameras),
                    "final_newline": True,
                },
                "images": image_rows,
            },
            "imu": {
                "count": len(selection.imus),
                "source_indices_inclusive": [
                    selection.imus[0].source_index,
                    selection.imus[-1].source_index,
                ],
                "first_raw_header_ns": selection.imus[0].raw_header_ns,
                "last_raw_header_ns": selection.imus[-1].raw_header_ns,
                "first_output_header_ns": selection.imus[0].output_header_ns,
                "last_output_header_ns": selection.imus[-1].output_header_ns,
                "observed_rate_hz": observed_imu_rate_hz,
                "brackets_camera_prefix": True,
                "csv": {
                    "path": "mav0/imu0/data.csv",
                    "sha256": csv_hash,
                    "header": CSV_HEADER,
                    "data_row_count": len(selection.imus),
                    "final_newline": False,
                },
            },
            "payload_tree_sha256_excluding_manifest": _aggregate_rows(
                sorted(aggregate_rows)
            ),
            "claims": {
                "hfnet_source_modified": False,
                "hfnet_started": False,
                "trajectory_produced": False,
                "full_a02_window_exported": False,
            },
        }
        (staging / "conversion_manifest.json").write_text(
            canonical_json(manifest), encoding="utf-8"
        )
    return manifest


def validate_static_identity(
    source_bag: Path,
    expected_size: int,
    expected_sha256: str,
    hfnet_root: Path,
) -> tuple[str, dict[str, Any]]:
    if not source_bag.is_file():
        raise ContractError("SOURCE_BAG_MISSING")
    if source_bag.stat().st_size != expected_size:
        raise ContractError("SOURCE_BAG_SIZE_MISMATCH")
    source_hash = sha256_file(source_bag)
    if source_hash != expected_sha256:
        raise ContractError("SOURCE_BAG_SHA256_MISMATCH")
    upstream = audit_hfnet_checkout(hfnet_root)
    if upstream["errors"]:
        raise ContractError(";".join(upstream["errors"]))
    expected_shift = round(-KALIBR_TIMESHIFT_CAM_IMU_S * 1e9)
    if expected_shift != IMU_OUTPUT_SHIFT_NS:
        raise ContractError("KALIBR_TIMESHIFT_ROUNDING_CONTRACT_MISMATCH")
    return source_hash, upstream


def prepare(
    source_bag: Path,
    hfnet_root: Path,
    contract: PrefixContract = A02_PREFIX_CONTRACT,
    expected_size: int = SOURCE_SIZE_BYTES,
    expected_sha256: str = SOURCE_SHA256,
) -> tuple[str, dict[str, Any], SourceSelection]:
    source_hash, upstream = validate_static_identity(
        source_bag, expected_size, expected_sha256, hfnet_root
    )
    selection = read_source_selection(source_bag, contract)
    return source_hash, upstream, selection


def preflight_result(
    source_bag: Path,
    source_hash: str,
    upstream: Mapping[str, Any],
    selection: SourceSelection,
    contract: PrefixContract,
) -> dict[str, Any]:
    return {
        "adapter_version": ADAPTER_VERSION,
        "status": STATUS_PREFLIGHT_READY,
        "source": {
            "bag": str(source_bag),
            "size_bytes": source_bag.stat().st_size,
            "sha256": source_hash,
            "topics": selection.topic_audit,
        },
        "upstream": dict(upstream),
        "selection": {
            "camera_count": len(selection.cameras),
            "camera_indices_inclusive": [
                selection.cameras[0].source_index,
                selection.cameras[-1].source_index,
            ],
            "camera_header_ns_inclusive": [
                selection.cameras[0].header_ns,
                selection.cameras[-1].header_ns,
            ],
            "imu_count": len(selection.imus),
            "imu_indices_inclusive": [
                selection.imus[0].source_index,
                selection.imus[-1].source_index,
            ],
            "imu_raw_header_ns_inclusive": [
                selection.imus[0].raw_header_ns,
                selection.imus[-1].raw_header_ns,
            ],
            "imu_output_header_ns_inclusive": [
                selection.imus[0].output_header_ns,
                selection.imus[-1].output_header_ns,
            ],
            "imu_brackets_camera": True,
        },
        "contract": asdict(contract),
        "claims": {
            "output_created": False,
            "hfnet_started": False,
            "trajectory_produced": False,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action", choices=("preflight", "export"), default="preflight"
    )
    parser.add_argument(
        "--source-bag",
        type=Path,
        default=WORKSPACE_DEFAULT / SOURCE_RELATIVE,
    )
    parser.add_argument("--hfnet-root", type=Path, default=HFNET_ROOT_DEFAULT)
    parser.add_argument("--output-sequence-root", type=Path)
    parser.add_argument("--report-json", type=Path)
    return parser


def _write_report_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.tmp-", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source_hash, upstream, selection = prepare(
            args.source_bag, args.hfnet_root
        )
        if args.action == "preflight":
            result = preflight_result(
                args.source_bag,
                source_hash,
                upstream,
                selection,
                A02_PREFIX_CONTRACT,
            )
        else:
            if args.output_sequence_root is None:
                raise ContractError("OUTPUT_SEQUENCE_ROOT_REQUIRED")
            result = write_artifact(
                args.output_sequence_root,
                args.source_bag,
                source_hash,
                selection,
                A02_PREFIX_CONTRACT,
                upstream,
            )
        rc = RC_READY
    except ContractError as exc:
        result = {
            "adapter_version": ADAPTER_VERSION,
            "status": STATUS_INTEGRITY_ERROR,
            "errors": [str(exc)],
            "claims": {
                "hfnet_source_modified": False,
                "hfnet_started": False,
                "trajectory_produced": False,
            },
        }
        rc = RC_INTEGRITY_ERROR
    except Exception as exc:  # Always fail closed and retain the diagnostic class.
        result = {
            "adapter_version": ADAPTER_VERSION,
            "status": STATUS_INTEGRITY_ERROR,
            "errors": [f"UNEXPECTED_{type(exc).__name__}:{exc}"],
            "claims": {
                "hfnet_source_modified": False,
                "hfnet_started": False,
                "trajectory_produced": False,
            },
        }
        rc = RC_INTEGRITY_ERROR

    text = canonical_json(result)
    sys.stdout.write(text)
    if args.report_json:
        _write_report_atomic(args.report_json, text)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
