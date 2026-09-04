#!/usr/bin/env python3
"""Export frozen AQUALOC A02 camera data for paper-era AnyFeature-VSLAM.

This is a high-level, fail-closed data adapter.  It never edits, builds, or
runs AnyFeature-VSLAM.  The authoritative consumer contract is the RSS-2024
repository state at commit ``6aa014b724f7a61bcbff2f8f28f20836986a43dc``:

* ``rgb.txt`` has no header or comments and contains ``seconds path`` rows;
* images live below ``rgb/`` and are lossless PNG files;
* ``calibration.yaml`` uses the OpenCV keys consumed by the stock system.

Only two outcome-independent profiles exist: the first 200 camera messages or
all 901 camera messages.  ROS header nanoseconds name the images and are
rendered exactly (nine fractional digits) in ``rgb.txt``.  Every encoded PNG
is decoded and compared byte-for-byte with the source mono8 payload.

The full profile requires a sealed prefix artifact.  It re-audits and copies
camera frames 0--199 byte-for-byte, then encodes only frames 200--900.
Registered R2D2 namespaces already attached to the prefix are tolerated but
are neither copied nor interpreted; their integrity belongs to the learned
feature materializer, so a learned-only failure cannot block camera promotion.

Existing output paths are never overwritten.  A complete artifact is staged
in a sibling directory and atomically renamed.  The default action is a
read-only preflight; ``--action export`` is required to create an artifact.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


ADAPTER_VERSION = "aqualoc-anyfeature-camera-v1"
ADAPTER_SCRIPT_RELATIVE = "scripts/export_aqualoc_to_anyfeature_v1.py"
SEQUENCE_IDENTITY_SCHEMA = "aqualoc-anyfeature-sequence-identity-v1"

ANYFEATURE_ORIGIN = "https://github.com/alejandrofontan/AnyFeature-VSLAM.git"
ANYFEATURE_PAPER_COMMIT = "6aa014b724f7a61bcbff2f8f28f20836986a43dc"
ANYFEATURE_CONTRACT_FILE_SHA256 = {
    "README.md": "54bb83ae94b871af64ca15a27bfe871bbce4dbdeeea6d1a87abd34cf72d9c612",
    "src/mono.cpp": "6b7926aefa29d93285b80b2f35644cf1574aa6f8f76b707f3e0847cad60e0a82",
    "src/Image.cpp": "95d7f6f8493c7383c023967b8c7f8db4531002c0012a26ef58e1c87e5564dccd",
    "src/Feature_r2d2_128.cpp": (
        "21e56aab8997ea8a9ed05a3534ea33ffc57f6ff5ce1f039d57bd76f84708b512"
    ),
    "src/Utils.cpp": "8af8f97cfe31f5862263fba04f5074fc92eea019cee31dc8185cd6f7e59c2e28",
}

WORKSPACE_DEFAULT = Path(__file__).resolve().parents[1]
SOURCE_RELATIVE = "datasets/aqualoc/rosbags/archaeo02_4500_5400.bag"
SOURCE_SIZE_BYTES = 222_477_260
SOURCE_SHA256 = "8cceb4c76065f3862e60428b14ba10f9a26fc7249e11e9e9d090fed2437238a8"
CALIBRATION_RELATIVE = (
    "datasets/full_downloads/aqualoc/Archaeological_site_sequences/"
    "archaeo_calibration_files/archaeo_camera_calib.yaml"
)
CALIBRATION_SIZE_BYTES = 337
CALIBRATION_SHA256 = (
    "e8ce9ad65d82ae563c676689444abd210f81c362586473c5752ee5f9bf2c32e2"
)

CAMERA_TOPIC = "/camera/image_raw"
CAMERA_MESSAGE_TYPE = "sensor_msgs/Image"
CAMERA_WIDTH = 968
CAMERA_HEIGHT = 608
CAMERA_ENCODING = "mono8"
CAMERA_NOMINAL_FPS = 20.0

STATUS_PREFLIGHT_READY = "PREFLIGHT_READY"
STATUS_EXPORTED = "EXPORTED"
STATUS_INTEGRITY_ERROR = "INTEGRITY_ERROR"
RC_READY = 0
RC_INTEGRITY_ERROR = 2

CAMERA_ARTIFACT_ROOT_ENTRIES = frozenset(
    {"rgb", "rgb.txt", "calibration.yaml", "conversion_manifest.json"}
)
OPTIONAL_DOWNSTREAM_ROOT_ENTRIES = frozenset(
    {"r2d2", "producer_run_manifest.json", "producer_evidence"}
)


class ContractError(RuntimeError):
    """An input or output violates the frozen conversion contract."""


@dataclass(frozen=True)
class ExportProfile:
    name: str
    expected_total_images: int
    first_index: int
    last_index: int
    expected_first_stamp_ns: int | None
    expected_last_stamp_ns: int | None
    evaluation_eligible_full_window: bool
    prefix_reuse_count: int = 0
    prefix_profile_name: str | None = None

    @property
    def count(self) -> int:
        return self.last_index - self.first_index + 1


PROFILES = {
    "a02-prefix200": ExportProfile(
        name="a02-prefix200",
        expected_total_images=901,
        first_index=0,
        last_index=199,
        expected_first_stamp_ns=1_542_829_016_700_435_392,
        expected_last_stamp_ns=1_542_829_026_649_564_544,
        evaluation_eligible_full_window=False,
    ),
    "a02-full": ExportProfile(
        name="a02-full",
        expected_total_images=901,
        first_index=0,
        last_index=900,
        expected_first_stamp_ns=1_542_829_016_700_435_392,
        expected_last_stamp_ns=None,
        evaluation_eligible_full_window=True,
        prefix_reuse_count=200,
        prefix_profile_name="a02-prefix200",
    ),
}


@dataclass(frozen=True)
class CameraContract:
    topic: str = CAMERA_TOPIC
    message_type: str = CAMERA_MESSAGE_TYPE
    width: int = CAMERA_WIDTH
    height: int = CAMERA_HEIGHT
    encoding: str = CAMERA_ENCODING
    nominal_fps: float = CAMERA_NOMINAL_FPS


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
class CameraSelection:
    samples: tuple[CameraSample, ...]
    topic_audit: Mapping[str, Mapping[str, Any]]
    all_first_header_ns: int
    all_last_header_ns: int
    scanned_count: int


@dataclass(frozen=True)
class Calibration:
    camera_model: str
    distortion_model: str
    intrinsics: tuple[float, float, float, float]
    distortion_coeffs: tuple[float, float, float, float]
    resolution: tuple[int, int]
    rostopic: str


@dataclass(frozen=True)
class PrefixArtifact:
    root: Path
    manifest_path: Path
    manifest_sha256: str
    sequence_identity_sha256: str
    rgb_payload: bytes
    calibration_payload: bytes
    image_paths: tuple[Path, ...]
    image_sha256: tuple[str, ...]
    image_size_bytes: tuple[int, ...]


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


def adapter_identity() -> dict[str, str]:
    script = Path(__file__).resolve()
    return {
        "script": ADAPTER_SCRIPT_RELATIVE,
        "resolved_script": str(script),
        "sha256": sha256_file(script),
    }


def sequence_identity_record(
    *,
    adapter_sha256: str,
    profile_name: str,
    source_bag_sha256: str,
    source_calibration_sha256: str,
    rgb_txt_sha256: str,
    output_calibration_sha256: str,
    image_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": SEQUENCE_IDENTITY_SCHEMA,
        "adapter_version": ADAPTER_VERSION,
        "adapter_sha256": adapter_sha256,
        "profile": profile_name,
        "source_bag_sha256": source_bag_sha256,
        "source_calibration_sha256": source_calibration_sha256,
        "rgb_txt_sha256": rgb_txt_sha256,
        "output_calibration_sha256": output_calibration_sha256,
        "images": [
            {
                "source_index": int(row["source_index"]),
                "raw_header_ns": int(row["raw_header_ns"]),
                "relative_path": str(row["relative_path"]),
                "source_pixel_sha256": str(row["source_pixel_sha256"]),
                "png_sha256": str(row["png_sha256"]),
                "png_size_bytes": int(row["png_size_bytes"]),
            }
            for row in image_rows
        ],
    }


def sequence_identity_sha256(**kwargs: Any) -> str:
    record = sequence_identity_record(**kwargs)
    return hashlib.sha256(canonical_json(record).encode("utf-8")).hexdigest()


def ros_time_to_ns(stamp: Any) -> int:
    if hasattr(stamp, "to_nsec"):
        return int(stamp.to_nsec())
    seconds = getattr(stamp, "secs", getattr(stamp, "sec", None))
    nanoseconds = getattr(stamp, "nsecs", getattr(stamp, "nanosec", None))
    if seconds is None or nanoseconds is None:
        raise ContractError("ROS_TIME_SCHEMA_MISSING")
    return int(seconds) * 1_000_000_000 + int(nanoseconds)


def timestamp_seconds_text(stamp_ns: int) -> str:
    if stamp_ns < 0:
        raise ContractError("NEGATIVE_CAMERA_TIMESTAMP")
    return f"{stamp_ns // 1_000_000_000}.{stamp_ns % 1_000_000_000:09d}"


def timestamp_text_to_ns(text: str) -> int:
    if re.fullmatch(r"[0-9]+\.[0-9]{9}", text) is None:
        raise ContractError(f"RGB_TXT_TIMESTAMP_NOT_CANONICAL:{text}")
    try:
        value = Decimal(text) * Decimal(1_000_000_000)
    except InvalidOperation as exc:
        raise ContractError(f"RGB_TXT_TIMESTAMP_INVALID:{text}") from exc
    integral = value.to_integral_value()
    if value != integral:
        raise ContractError(f"RGB_TXT_TIMESTAMP_SUBNANOSECOND:{text}")
    return int(integral)


def rgb_txt_bytes(samples: Sequence[CameraSample]) -> bytes:
    lines = [
        f"{timestamp_seconds_text(sample.header_ns)} rgb/{sample.header_ns}.png"
        for sample in samples
    ]
    payload = ("\n".join(lines) + "\n").encode("ascii")
    validate_rgb_txt_payload(payload, samples)
    return payload


def validate_rgb_txt_payload(
    payload: bytes, samples: Sequence[CameraSample]
) -> None:
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ContractError("RGB_TXT_NOT_ASCII") from exc
    if not text.endswith("\n"):
        raise ContractError("RGB_TXT_FINAL_NEWLINE_MISSING")
    if "\r" in text:
        raise ContractError("RGB_TXT_CRLF_OR_CARRIAGE_RETURN")
    lines = text[:-1].split("\n") if text else []
    if len(lines) != len(samples):
        raise ContractError("RGB_TXT_ROW_COUNT_MISMATCH")
    for row_index, (line, sample) in enumerate(zip(lines, samples)):
        expected = (
            f"{timestamp_seconds_text(sample.header_ns)} rgb/{sample.header_ns}.png"
        )
        if line != expected:
            raise ContractError(f"RGB_TXT_ROW_NOT_CANONICAL:{row_index}")


def _topic_info(bag: Any) -> dict[str, dict[str, Any]]:
    info = bag.get_type_and_topic_info()
    connection_counts: dict[str, int] = {}
    for connection in bag._connections.values():  # ROS1 exposes no public equivalent.
        connection_counts[connection.topic] = connection_counts.get(connection.topic, 0) + 1
    return {
        topic: {
            "message_type": row.msg_type,
            "message_count": int(row.message_count),
            "connection_count": connection_counts.get(topic, 0),
        }
        for topic, row in info.topics.items()
    }


def _validate_topic(
    topics: Mapping[str, Mapping[str, Any]],
    profile: ExportProfile,
    contract: CameraContract,
) -> None:
    row = topics.get(contract.topic)
    if row is None:
        raise ContractError("CAMERA_TOPIC_MISSING")
    if row.get("message_type") != contract.message_type:
        raise ContractError("CAMERA_MESSAGE_TYPE_MISMATCH")
    if int(row.get("message_count", -1)) != profile.expected_total_images:
        raise ContractError("CAMERA_TOTAL_COUNT_MISMATCH")
    if int(row.get("connection_count", -1)) != 1:
        raise ContractError("CAMERA_CONNECTION_COUNT_MISMATCH")


def _image_payload(message: Any, contract: CameraContract) -> bytes:
    if getattr(message, "_type", None) != contract.message_type:
        raise ContractError("CAMERA_RUNTIME_MESSAGE_TYPE_MISMATCH")
    width = int(message.width)
    height = int(message.height)
    encoding = str(message.encoding).lower()
    step = int(message.step)
    if (width, height) != (contract.width, contract.height):
        raise ContractError("CAMERA_DIMENSION_MISMATCH")
    if encoding != contract.encoding.lower():
        raise ContractError("CAMERA_ENCODING_MISMATCH")
    if int(getattr(message, "is_bigendian", 0)) != 0:
        raise ContractError("CAMERA_BIG_ENDIAN_UNSUPPORTED")
    if step != contract.width:
        raise ContractError("CAMERA_STEP_MISMATCH")
    payload = bytes(message.data)
    if len(payload) != contract.width * contract.height:
        raise ContractError("CAMERA_PAYLOAD_SIZE_MISMATCH")
    return payload


def read_camera_selection(
    source_bag: Path,
    profile: ExportProfile,
    contract: CameraContract = CameraContract(),
) -> CameraSelection:
    try:
        import rosbag
    except ImportError as exc:  # pragma: no cover - environment gate
        raise ContractError("ROSBAG_PYTHON_UNAVAILABLE") from exc

    samples: list[CameraSample] = []
    count = 0
    previous_ns: int | None = None
    first_ns: int | None = None
    last_ns: int | None = None
    with rosbag.Bag(str(source_bag), "r") as bag:
        topics = _topic_info(bag)
        _validate_topic(topics, profile, contract)
        for _, message, record_stamp in bag.read_messages(topics=[contract.topic]):
            header_ns = ros_time_to_ns(message.header.stamp)
            record_ns = ros_time_to_ns(record_stamp)
            if record_ns != header_ns:
                raise ContractError("CAMERA_RECORD_HEADER_STAMP_MISMATCH")
            if previous_ns is not None and header_ns <= previous_ns:
                raise ContractError("CAMERA_STAMP_NOT_STRICTLY_MONOTONIC")
            payload = _image_payload(message, contract)
            first_ns = header_ns if first_ns is None else first_ns
            last_ns = header_ns
            previous_ns = header_ns
            if profile.first_index <= count <= profile.last_index:
                samples.append(
                    CameraSample(
                        source_index=count,
                        header_ns=header_ns,
                        record_ns=record_ns,
                        width=int(message.width),
                        height=int(message.height),
                        encoding=str(message.encoding),
                        step=int(message.step),
                        pixels=payload,
                        pixel_sha256=hashlib.sha256(payload).hexdigest(),
                    )
                )
            count += 1

    if count != profile.expected_total_images:
        raise ContractError("CAMERA_SCANNED_COUNT_MISMATCH")
    if len(samples) != profile.count:
        raise ContractError("CAMERA_SELECTION_COUNT_MISMATCH")
    if first_ns is None or last_ns is None:
        raise ContractError("CAMERA_SEQUENCE_EMPTY")
    selection = CameraSelection(
        samples=tuple(samples),
        topic_audit=topics,
        all_first_header_ns=first_ns,
        all_last_header_ns=last_ns,
        scanned_count=count,
    )
    validate_selection(selection, profile)
    return selection


def validate_selection(selection: CameraSelection, profile: ExportProfile) -> None:
    samples = selection.samples
    if [sample.source_index for sample in samples] != list(
        range(profile.first_index, profile.last_index + 1)
    ):
        raise ContractError("CAMERA_SOURCE_INDEX_SEQUENCE_MISMATCH")
    if any(
        current.header_ns <= previous.header_ns
        for previous, current in zip(samples, samples[1:])
    ):
        raise ContractError("SELECTED_CAMERA_STAMPS_NOT_STRICT")
    if (
        profile.expected_first_stamp_ns is not None
        and samples[0].header_ns != profile.expected_first_stamp_ns
    ):
        raise ContractError("FIRST_SELECTED_CAMERA_STAMP_MISMATCH")
    if (
        profile.expected_last_stamp_ns is not None
        and samples[-1].header_ns != profile.expected_last_stamp_ns
    ):
        raise ContractError("LAST_SELECTED_CAMERA_STAMP_MISMATCH")
    if len(samples) < 2:
        raise ContractError("CAMERA_SELECTION_TOO_SHORT")


def load_calibration(path: Path) -> Calibration:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment gate
        raise ContractError("PYTHON_YAML_UNAVAILABLE") from exc
    try:
        root = yaml.safe_load(path.read_text(encoding="utf-8"))
        row = root["cam0"]
        intrinsics = tuple(float(value) for value in row["intrinsics"])
        distortion = tuple(float(value) for value in row["distortion_coeffs"])
        resolution = tuple(int(value) for value in row["resolution"])
        calibration = Calibration(
            camera_model=str(row["camera_model"]),
            distortion_model=str(row["distortion_model"]),
            intrinsics=intrinsics,  # type: ignore[arg-type]
            distortion_coeffs=distortion,  # type: ignore[arg-type]
            resolution=resolution,  # type: ignore[arg-type]
            rostopic=str(row["rostopic"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("CALIBRATION_SCHEMA_INVALID") from exc
    if calibration.camera_model != "pinhole":
        raise ContractError("CALIBRATION_CAMERA_MODEL_MISMATCH")
    if calibration.distortion_model != "radtan":
        raise ContractError("CALIBRATION_DISTORTION_MODEL_MISMATCH")
    if len(calibration.intrinsics) != 4 or len(calibration.distortion_coeffs) != 4:
        raise ContractError("CALIBRATION_VECTOR_LENGTH_MISMATCH")
    if calibration.resolution != (CAMERA_WIDTH, CAMERA_HEIGHT):
        raise ContractError("CALIBRATION_RESOLUTION_MISMATCH")
    if calibration.rostopic != CAMERA_TOPIC:
        raise ContractError("CALIBRATION_TOPIC_MISMATCH")
    if not all(
        math.isfinite(value)
        for value in (*calibration.intrinsics, *calibration.distortion_coeffs)
    ):
        raise ContractError("CALIBRATION_NONFINITE_VALUE")
    return calibration


def anyfeature_calibration_bytes(
    calibration: Calibration, nominal_fps: float = CAMERA_NOMINAL_FPS
) -> bytes:
    fx, fy, cx, cy = calibration.intrinsics
    k1, k2, p1, p2 = calibration.distortion_coeffs
    width, height = calibration.resolution
    lines = [
        "%YAML:1.0",
        "",
        "# Camera calibration and distortion parameters (OpenCV)",
        f"Camera.fx: {format(fx, '.17g')}",
        f"Camera.fy: {format(fy, '.17g')}",
        f"Camera.cx: {format(cx, '.17g')}",
        f"Camera.cy: {format(cy, '.17g')}",
        "",
        f"Camera.k1: {format(k1, '.17g')}",
        f"Camera.k2: {format(k2, '.17g')}",
        f"Camera.p1: {format(p1, '.17g')}",
        f"Camera.p2: {format(p2, '.17g')}",
        "Camera.k3: 0",
        "",
        f"Camera.w: {width}",
        f"Camera.h: {height}",
        "",
        "# Camera frames per second",
        f"Camera.fps: {format(nominal_fps, '.17g')}",
    ]
    return ("\n".join(lines) + "\n").encode("ascii")


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
    if hashlib.sha256(decoded.tobytes(order="C")).hexdigest() != sample.pixel_sha256:
        raise ContractError(f"PNG_PIXEL_HASH_CHANGED:{sample.source_index}")
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
    for relative, file_hash in rows:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def observed_fps(samples: Sequence[CameraSample]) -> float:
    duration_s = (samples[-1].header_ns - samples[0].header_ns) / 1e9
    if duration_s <= 0:
        raise ContractError("CAMERA_DURATION_NOT_POSITIVE")
    return (len(samples) - 1) / duration_s


def _artifact_scope(profile: ExportProfile) -> str:
    if profile.name == "a02-prefix200":
        return "A02_CAMERA_INDICES_0_199_PREFIX_ONLY"
    if profile.name == "a02-full":
        return "A02_CAMERA_INDICES_0_900_FULL"
    suffix = "FULL" if profile.evaluation_eligible_full_window else "PREFIX_ONLY"
    return (
        f"CAMERA_INDICES_{profile.first_index}_{profile.last_index}_{suffix}"
    )


def _prefix_profile(profile: ExportProfile, samples: Sequence[CameraSample]) -> ExportProfile:
    reuse_count = profile.prefix_reuse_count
    if reuse_count <= 0 or len(samples) < reuse_count:
        raise ContractError("PREFIX_REUSE_COUNT_INVALID")
    if not profile.prefix_profile_name:
        raise ContractError("PREFIX_PROFILE_NAME_REQUIRED")
    prefix_samples = samples[:reuse_count]
    return ExportProfile(
        name=profile.prefix_profile_name,
        expected_total_images=profile.expected_total_images,
        first_index=prefix_samples[0].source_index,
        last_index=prefix_samples[-1].source_index,
        expected_first_stamp_ns=prefix_samples[0].header_ns,
        expected_last_stamp_ns=prefix_samples[-1].header_ns,
        evaluation_eligible_full_window=False,
    )


def _build_conversion_manifest(
    *,
    source_bag: Path,
    source_hash: str,
    source_calibration: Path,
    calibration_hash: str,
    calibration: Calibration,
    selection: CameraSelection,
    profile: ExportProfile,
    contract: CameraContract,
    image_rows: Sequence[Mapping[str, Any]],
    rgb_hash: str,
    output_calibration_hash: str,
    tree_rows: Sequence[tuple[str, str]],
    prefix: PrefixArtifact | None,
) -> dict[str, Any]:
    current_adapter = adapter_identity()
    identity_record = sequence_identity_record(
        adapter_sha256=current_adapter["sha256"],
        profile_name=profile.name,
        source_bag_sha256=source_hash,
        source_calibration_sha256=calibration_hash,
        rgb_txt_sha256=rgb_hash,
        output_calibration_sha256=output_calibration_hash,
        image_rows=image_rows,
    )
    identity_hash = hashlib.sha256(
        canonical_json(identity_record).encode("utf-8")
    ).hexdigest()
    source_bag_resolved = source_bag.resolve()
    source_calibration_resolved = source_calibration.resolve()
    manifest: dict[str, Any] = {
        "adapter_version": ADAPTER_VERSION,
        "adapter_identity": current_adapter,
        "status": STATUS_EXPORTED,
        "profile": profile.name,
        "artifact_scope": _artifact_scope(profile),
        "evaluation_eligible_full_window": profile.evaluation_eligible_full_window,
        "source": {
            "bag": str(source_bag_resolved),
            "resolved_bag": str(source_bag_resolved),
            "size_bytes": source_bag.stat().st_size,
            "sha256": source_hash,
            "camera_topic_audit": selection.topic_audit[contract.topic],
            "calibration": {
                "path": str(source_calibration_resolved),
                "resolved_path": str(source_calibration_resolved),
                "size_bytes": source_calibration.stat().st_size,
                "sha256": calibration_hash,
            },
        },
        "upstream_contract": {
            "origin": ANYFEATURE_ORIGIN,
            "paper_commit": ANYFEATURE_PAPER_COMMIT,
            "file_sha256": ANYFEATURE_CONTRACT_FILE_SHA256,
            "timestamp_reader": "src/mono.cpp: headerless rgb.txt; seconds path",
            "feature_path_mapping": (
                "src/Image.cpp: /rgb/ -> /r2d2/{keypoints,scores,descriptors}/; "
                "png -> bin"
            ),
        },
        "camera": {
            "count": len(selection.samples),
            "source_indices_inclusive": [
                selection.samples[0].source_index,
                selection.samples[-1].source_index,
            ],
            "selected_header_ns_inclusive": [
                selection.samples[0].header_ns,
                selection.samples[-1].header_ns,
            ],
            "all_header_ns_inclusive": [
                selection.all_first_header_ns,
                selection.all_last_header_ns,
            ],
            "strictly_monotonic": True,
            "schema": asdict(contract),
            "observed_average_fps": observed_fps(selection.samples),
            "rgb_txt": {
                "path": "rgb.txt",
                "sha256": rgb_hash,
                "row_count": len(selection.samples),
                "header_or_comment_rows": 0,
                "timestamp_text_precision": "exact integer ns rendered with 9 decimals",
                "final_newline": True,
            },
            "images": list(image_rows),
        },
        "calibration": {
            "input": asdict(calibration),
            "output_path": "calibration.yaml",
            "output_sha256": output_calibration_hash,
            "k3": 0.0,
            "nominal_fps": contract.nominal_fps,
        },
        "sequence_identity": {
            "schema": SEQUENCE_IDENTITY_SCHEMA,
            "record": identity_record,
            "sha256": identity_hash,
        },
        "prefix_reuse": (
            {
                "required": True,
                "count": profile.prefix_reuse_count,
                "source_indices_inclusive": [0, profile.prefix_reuse_count - 1],
                "prefix_root": str(prefix.root.resolve()),
                "prefix_conversion_manifest": str(prefix.manifest_path.resolve()),
                "prefix_conversion_manifest_sha256": prefix.manifest_sha256,
                "prefix_sequence_identity_sha256": prefix.sequence_identity_sha256,
                "rgb_txt_prefix_bytes_sha256": hashlib.sha256(
                    prefix.rgb_payload
                ).hexdigest(),
                "calibration_byte_identity": True,
                "png_byte_identity": True,
                "newly_encoded_source_indices_inclusive": [
                    profile.prefix_reuse_count,
                    profile.last_index,
                ],
            }
            if prefix is not None
            else {"required": False, "count": 0}
        ),
        "payload_tree_sha256_excluding_manifest": _aggregate_rows(
            sorted(tree_rows)
        ),
        "claims": {
            "anyfeature_source_modified": False,
            "anyfeature_built": False,
            "anyfeature_started": False,
            "r2d2_model_downloaded": False,
            "features_materialized": False,
            "trajectory_produced": False,
        },
    }
    return manifest


def _regular_file(path: Path, label: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise ContractError(f"{label}_MISSING_OR_SYMLINK:{path}")


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    _regular_file(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label}_INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label}_ROOT_NOT_OBJECT")
    return value


def _verify_png_pixels(path: Path, sample: CameraSample, label: str) -> None:
    try:
        import cv2
        import numpy as np
    except ImportError as exc:  # pragma: no cover - environment gate
        raise ContractError("CV2_OR_NUMPY_UNAVAILABLE") from exc
    payload = path.read_bytes()
    decoded = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_UNCHANGED)
    expected = np.frombuffer(sample.pixels, np.uint8).reshape(
        sample.height, sample.width
    )
    if decoded is None or decoded.shape != expected.shape or decoded.dtype != expected.dtype:
        raise ContractError(f"{label}_PNG_SCHEMA_MISMATCH")
    if not np.array_equal(decoded, expected):
        raise ContractError(f"{label}_PNG_PIXEL_MISMATCH")
    if hashlib.sha256(decoded.tobytes(order="C")).hexdigest() != sample.pixel_sha256:
        raise ContractError(f"{label}_PNG_PIXEL_HASH_MISMATCH")


def validate_prefix_artifact(
    prefix_root: Path,
    source_bag: Path,
    source_calibration: Path,
    selection: CameraSelection,
    profile: ExportProfile,
    source_hash: str,
    calibration_hash: str,
    calibration: Calibration,
    contract: CameraContract = CameraContract(),
) -> PrefixArtifact:
    """Audit a sealed prefix before it can seed a full export."""
    reuse_count = profile.prefix_reuse_count
    if reuse_count <= 0:
        raise ContractError("PREFIX_REUSE_NOT_DEFINED_FOR_PROFILE")
    if not prefix_root.is_dir() or prefix_root.is_symlink():
        raise ContractError("PREFIX_ROOT_MISSING_OR_SYMLINK")
    if len(selection.samples) < reuse_count:
        raise ContractError("PREFIX_REUSE_COUNT_EXCEEDS_SELECTION")
    # Downstream learned artifacts may already exist at this preregistered
    # point.  Restrict their namespaces, but do not inspect/dereference them:
    # their schema, hashes, completeness, and symlink policy are owned by the
    # materializer.  Camera-owned entries remain fully fail-closed below.
    root_entries = list(prefix_root.iterdir())
    root_names = {path.name for path in root_entries}
    if not CAMERA_ARTIFACT_ROOT_ENTRIES.issubset(root_names):
        raise ContractError("PREFIX_ROOT_FILE_SET_MISMATCH")
    if not root_names.issubset(
        CAMERA_ARTIFACT_ROOT_ENTRIES | OPTIONAL_DOWNSTREAM_ROOT_ENTRIES
    ):
        raise ContractError("PREFIX_ROOT_ENTRY_NOT_ALLOWED")
    if any(
        path.is_symlink() and path.name in CAMERA_ARTIFACT_ROOT_ENTRIES
        for path in root_entries
    ):
        raise ContractError("PREFIX_CAMERA_ROOT_ENTRY_SYMLINK")

    manifest_path = prefix_root / "conversion_manifest.json"
    manifest = _load_json_object(manifest_path, "PREFIX_CONVERSION_MANIFEST")
    expected_adapter = adapter_identity()
    if (
        manifest.get("adapter_version") != ADAPTER_VERSION
        or manifest.get("status") != STATUS_EXPORTED
    ):
        raise ContractError("PREFIX_MANIFEST_IDENTITY_MISMATCH")
    if manifest.get("adapter_identity") != expected_adapter:
        raise ContractError("PREFIX_MANIFEST_ADAPTER_SHA256_MISMATCH")
    expected_prefix_profile = _prefix_profile(profile, selection.samples)
    if manifest.get("profile") != expected_prefix_profile.name:
        raise ContractError("PREFIX_MANIFEST_PROFILE_MISMATCH")
    if manifest.get("source", {}).get("sha256") != source_hash:
        raise ContractError("PREFIX_SOURCE_BAG_SHA256_MISMATCH")
    if (
        manifest.get("source", {}).get("calibration", {}).get("sha256")
        != calibration_hash
    ):
        raise ContractError("PREFIX_SOURCE_CALIBRATION_SHA256_MISMATCH")

    prefix_samples = selection.samples[:reuse_count]
    rgb_path = prefix_root / "rgb.txt"
    _regular_file(rgb_path, "PREFIX_RGB_TXT")
    rgb_payload = rgb_path.read_bytes()
    if rgb_payload != rgb_txt_bytes(prefix_samples):
        raise ContractError("PREFIX_RGB_TXT_BYTE_MISMATCH")
    rgb_hash = hashlib.sha256(rgb_payload).hexdigest()

    calibration_path = prefix_root / "calibration.yaml"
    _regular_file(calibration_path, "PREFIX_CALIBRATION")
    calibration_payload = calibration_path.read_bytes()
    if calibration_payload != anyfeature_calibration_bytes(
        calibration, contract.nominal_fps
    ):
        raise ContractError("PREFIX_CALIBRATION_BYTE_MISMATCH")
    output_calibration_hash = hashlib.sha256(calibration_payload).hexdigest()

    camera = manifest.get("camera")
    if not isinstance(camera, dict) or camera.get("count") != reuse_count:
        raise ContractError("PREFIX_MANIFEST_CAMERA_COUNT_MISMATCH")
    image_rows = camera.get("images")
    if not isinstance(image_rows, list) or len(image_rows) != reuse_count:
        raise ContractError("PREFIX_MANIFEST_IMAGE_ROWS_MISMATCH")

    rgb_directory = prefix_root / "rgb"
    if not rgb_directory.is_dir() or rgb_directory.is_symlink():
        raise ContractError("PREFIX_RGB_DIRECTORY_MISSING_OR_SYMLINK")
    expected_names = {f"{sample.header_ns}.png" for sample in prefix_samples}
    allowed_archive_names = {
        f"{sample.header_ns}.png.r2d2" for sample in prefix_samples
    }
    rgb_entries = list(rgb_directory.iterdir())
    rgb_names = {path.name for path in rgb_entries}
    if not expected_names.issubset(rgb_names):
        raise ContractError("PREFIX_PNG_FILE_SET_MISMATCH")
    if not rgb_names.issubset(expected_names | allowed_archive_names):
        raise ContractError("PREFIX_PNG_FILE_SET_MISMATCH")
    camera_png_entries = [path for path in rgb_entries if path.name in expected_names]
    if any(path.is_symlink() for path in camera_png_entries):
        raise ContractError("PREFIX_CAMERA_PNG_SYMLINK")
    if any(not path.is_file() for path in camera_png_entries):
        raise ContractError("PREFIX_CAMERA_PNG_NOT_REGULAR_FILE")

    paths: list[Path] = []
    hashes: list[str] = []
    sizes: list[int] = []
    normalized_rows: list[dict[str, Any]] = []
    tree_rows: list[tuple[str, str]] = []
    for row_index, (row, sample) in enumerate(zip(image_rows, prefix_samples)):
        if not isinstance(row, dict):
            raise ContractError(f"PREFIX_MANIFEST_IMAGE_ROW_NOT_OBJECT:{row_index}")
        relative = f"rgb/{sample.header_ns}.png"
        path = prefix_root / relative
        _regular_file(path, f"PREFIX_PNG:{row_index}")
        size = path.stat().st_size
        digest = sha256_file(path)
        expected_row = {
            "source_index": sample.source_index,
            "raw_header_ns": sample.header_ns,
            "record_ns": sample.record_ns,
            "relative_path": relative,
            "source_pixel_sha256": sample.pixel_sha256,
            "png_sha256": digest,
            "png_size_bytes": size,
            "pixel_identity_verified": True,
            "reused_from_prefix": False,
        }
        if row != expected_row:
            raise ContractError(f"PREFIX_MANIFEST_IMAGE_ROW_MISMATCH:{row_index}")
        _verify_png_pixels(path, sample, f"PREFIX:{row_index}")
        paths.append(path)
        hashes.append(digest)
        sizes.append(size)
        normalized_rows.append(expected_row)
        tree_rows.append((relative, digest))

    expected_identity_record = sequence_identity_record(
        adapter_sha256=expected_adapter["sha256"],
        profile_name=expected_prefix_profile.name,
        source_bag_sha256=source_hash,
        source_calibration_sha256=calibration_hash,
        rgb_txt_sha256=rgb_hash,
        output_calibration_sha256=output_calibration_hash,
        image_rows=normalized_rows,
    )
    expected_identity = hashlib.sha256(
        canonical_json(expected_identity_record).encode("utf-8")
    ).hexdigest()
    if manifest.get("sequence_identity") != {
        "schema": SEQUENCE_IDENTITY_SCHEMA,
        "record": expected_identity_record,
        "sha256": expected_identity,
    }:
        raise ContractError("PREFIX_SEQUENCE_IDENTITY_SHA256_MISMATCH")

    tree_rows.extend(
        [("rgb.txt", rgb_hash), ("calibration.yaml", output_calibration_hash)]
    )
    prefix_selection = CameraSelection(
        samples=tuple(prefix_samples),
        topic_audit=selection.topic_audit,
        all_first_header_ns=selection.all_first_header_ns,
        all_last_header_ns=selection.all_last_header_ns,
        scanned_count=selection.scanned_count,
    )
    expected_manifest = _build_conversion_manifest(
        source_bag=source_bag,
        source_hash=source_hash,
        source_calibration=source_calibration,
        calibration_hash=calibration_hash,
        calibration=calibration,
        selection=prefix_selection,
        profile=expected_prefix_profile,
        contract=contract,
        image_rows=normalized_rows,
        rgb_hash=rgb_hash,
        output_calibration_hash=output_calibration_hash,
        tree_rows=tree_rows,
        prefix=None,
    )
    if manifest != json.loads(canonical_json(expected_manifest)):
        raise ContractError("PREFIX_CONVERSION_MANIFEST_TAMPERED")

    return PrefixArtifact(
        root=prefix_root.resolve(),
        manifest_path=manifest_path.resolve(),
        manifest_sha256=sha256_file(manifest_path),
        sequence_identity_sha256=expected_identity,
        rgb_payload=rgb_payload,
        calibration_payload=calibration_payload,
        image_paths=tuple(paths),
        image_sha256=tuple(hashes),
        image_size_bytes=tuple(sizes),
    )


def write_artifact(
    output_root: Path,
    source_bag: Path,
    source_hash: str,
    source_calibration: Path,
    calibration_hash: str,
    calibration: Calibration,
    selection: CameraSelection,
    profile: ExportProfile,
    contract: CameraContract = CameraContract(),
    prefix_root: Path | None = None,
) -> dict[str, Any]:
    validate_output_destination(output_root, prefix_root)
    generated_calibration_payload = anyfeature_calibration_bytes(
        calibration, contract.nominal_fps
    )
    prefix: PrefixArtifact | None = None
    if profile.prefix_reuse_count:
        if prefix_root is None:
            raise ContractError("PREFIX_ROOT_REQUIRED_FOR_FULL_EXPORT")
        prefix = validate_prefix_artifact(
            prefix_root,
            source_bag,
            source_calibration,
            selection,
            profile,
            source_hash,
            calibration_hash,
            calibration,
            contract,
        )
    elif prefix_root is not None:
        raise ContractError("PREFIX_ROOT_NOT_ALLOWED_FOR_PREFIX_EXPORT")

    with atomic_directory(output_root) as staging:
        rgb_directory = staging / "rgb"
        rgb_directory.mkdir()
        tree_rows: list[tuple[str, str]] = []
        image_rows: list[dict[str, Any]] = []
        for output_index, sample in enumerate(selection.samples):
            relative = f"rgb/{sample.header_ns}.png"
            output_path = staging / relative
            reused = prefix is not None and output_index < profile.prefix_reuse_count
            if reused:
                assert prefix is not None
                shutil.copyfile(prefix.image_paths[output_index], output_path)
                encoded = output_path.read_bytes()
                if hashlib.sha256(encoded).hexdigest() != prefix.image_sha256[output_index]:
                    raise ContractError(f"PREFIX_COPY_SHA256_MISMATCH:{output_index}")
                if len(encoded) != prefix.image_size_bytes[output_index]:
                    raise ContractError(f"PREFIX_COPY_SIZE_MISMATCH:{output_index}")
            else:
                encoded = encode_lossless_png(sample)
                output_path.write_bytes(encoded)
            png_hash = hashlib.sha256(encoded).hexdigest()
            tree_rows.append((relative, png_hash))
            image_rows.append(
                {
                    "source_index": sample.source_index,
                    "raw_header_ns": sample.header_ns,
                    "record_ns": sample.record_ns,
                    "relative_path": relative,
                    "source_pixel_sha256": sample.pixel_sha256,
                    "png_sha256": png_hash,
                    "png_size_bytes": len(encoded),
                    "pixel_identity_verified": True,
                    "reused_from_prefix": reused,
                }
            )

        rgb_payload = rgb_txt_bytes(selection.samples)
        (staging / "rgb.txt").write_bytes(rgb_payload)
        rgb_hash = hashlib.sha256(rgb_payload).hexdigest()
        tree_rows.append(("rgb.txt", rgb_hash))

        calibration_payload = (
            prefix.calibration_payload if prefix is not None else generated_calibration_payload
        )
        (staging / "calibration.yaml").write_bytes(calibration_payload)
        output_calibration_hash = hashlib.sha256(calibration_payload).hexdigest()
        tree_rows.append(("calibration.yaml", output_calibration_hash))

        manifest = _build_conversion_manifest(
            source_bag=source_bag,
            source_hash=source_hash,
            source_calibration=source_calibration,
            calibration_hash=calibration_hash,
            calibration=calibration,
            selection=selection,
            profile=profile,
            contract=contract,
            image_rows=image_rows,
            rgb_hash=rgb_hash,
            output_calibration_hash=output_calibration_hash,
            tree_rows=tree_rows,
            prefix=prefix,
        )
        (staging / "conversion_manifest.json").write_text(
            canonical_json(manifest), encoding="utf-8"
        )
    return manifest


def validate_static_identity(
    source_bag: Path,
    source_calibration: Path,
    expected_source_size: int = SOURCE_SIZE_BYTES,
    expected_source_sha256: str = SOURCE_SHA256,
    expected_calibration_size: int = CALIBRATION_SIZE_BYTES,
    expected_calibration_sha256: str = CALIBRATION_SHA256,
) -> tuple[str, str, Calibration]:
    _regular_file(source_bag, "SOURCE_BAG")
    if source_bag.stat().st_size != expected_source_size:
        raise ContractError("SOURCE_BAG_SIZE_MISMATCH")
    source_hash = sha256_file(source_bag)
    if source_hash != expected_source_sha256:
        raise ContractError("SOURCE_BAG_SHA256_MISMATCH")
    _regular_file(source_calibration, "SOURCE_CALIBRATION")
    if source_calibration.stat().st_size != expected_calibration_size:
        raise ContractError("SOURCE_CALIBRATION_SIZE_MISMATCH")
    calibration_hash = sha256_file(source_calibration)
    if calibration_hash != expected_calibration_sha256:
        raise ContractError("SOURCE_CALIBRATION_SHA256_MISMATCH")
    calibration = load_calibration(source_calibration)
    return source_hash, calibration_hash, calibration


def prepare(
    source_bag: Path,
    source_calibration: Path,
    profile: ExportProfile,
    contract: CameraContract = CameraContract(),
    expected_source_size: int = SOURCE_SIZE_BYTES,
    expected_source_sha256: str = SOURCE_SHA256,
    expected_calibration_size: int = CALIBRATION_SIZE_BYTES,
    expected_calibration_sha256: str = CALIBRATION_SHA256,
) -> tuple[str, str, Calibration, CameraSelection]:
    source_hash, calibration_hash, calibration = validate_static_identity(
        source_bag,
        source_calibration,
        expected_source_size,
        expected_source_sha256,
        expected_calibration_size,
        expected_calibration_sha256,
    )
    selection = read_camera_selection(source_bag, profile, contract)
    return source_hash, calibration_hash, calibration, selection


def preflight_result(
    source_bag: Path,
    source_hash: str,
    source_calibration: Path,
    calibration_hash: str,
    calibration: Calibration,
    selection: CameraSelection,
    profile: ExportProfile,
    prefix: PrefixArtifact | None = None,
) -> dict[str, Any]:
    return {
        "adapter_version": ADAPTER_VERSION,
        "adapter_identity": adapter_identity(),
        "status": STATUS_PREFLIGHT_READY,
        "profile": profile.name,
        "source": {
            "bag": str(source_bag),
            "size_bytes": source_bag.stat().st_size,
            "sha256": source_hash,
            "calibration": {
                "path": str(source_calibration),
                "sha256": calibration_hash,
                "parsed": asdict(calibration),
            },
            "camera_topic_audit": selection.topic_audit[CAMERA_TOPIC],
        },
        "selection": {
            "count": len(selection.samples),
            "source_indices_inclusive": [profile.first_index, profile.last_index],
            "header_ns_inclusive": [
                selection.samples[0].header_ns,
                selection.samples[-1].header_ns,
            ],
            "strictly_monotonic": True,
            "observed_average_fps": observed_fps(selection.samples),
        },
        "upstream_contract": {
            "origin": ANYFEATURE_ORIGIN,
            "paper_commit": ANYFEATURE_PAPER_COMMIT,
            "file_sha256": ANYFEATURE_CONTRACT_FILE_SHA256,
        },
        "prefix_reuse": (
            {
                "required": True,
                "count": profile.prefix_reuse_count,
                "prefix_root": str(prefix.root),
                "prefix_conversion_manifest": str(prefix.manifest_path),
                "prefix_conversion_manifest_sha256": prefix.manifest_sha256,
                "prefix_sequence_identity_sha256": prefix.sequence_identity_sha256,
                "png_bytes_audited": True,
            }
            if prefix is not None
            else {"required": False, "count": 0}
        ),
        "claims": {
            "output_created": False,
            "anyfeature_source_modified": False,
            "anyfeature_started": False,
            "trajectory_produced": False,
        },
    }


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def validate_report_destination(
    path: Path,
    *,
    source_bag: Path,
    source_calibration: Path,
    prefix_root: Path | None,
    output_root: Path | None,
) -> None:
    if path.exists() or path.is_symlink():
        raise ContractError(f"REPORT_ALREADY_EXISTS:{path}")
    resolved = path.resolve(strict=False)
    forbidden: list[tuple[str, Path]] = [
        ("SOURCE_BAG_PARENT", source_bag.resolve(strict=False).parent),
        (
            "SOURCE_CALIBRATION_PARENT",
            source_calibration.resolve(strict=False).parent,
        ),
    ]
    if prefix_root is not None:
        forbidden.append(("PREFIX_ROOT", prefix_root.resolve(strict=False)))
    if output_root is not None:
        output_resolved = output_root.resolve(strict=False)
        forbidden.append(("OUTPUT_ROOT", output_resolved))
        output_parent = output_resolved.parent
        try:
            relative = resolved.relative_to(output_parent)
        except ValueError:
            pass
        else:
            if relative.parts and relative.parts[0].startswith(
                f".{output_resolved.name}.tmp-"
            ):
                raise ContractError("REPORT_PATH_INSIDE_OUTPUT_STAGING")
    for label, root in forbidden:
        if _path_is_within(resolved, root):
            raise ContractError(f"REPORT_PATH_INSIDE_{label}:{resolved}")


def validate_output_destination(
    output_root: Path, prefix_root: Path | None
) -> None:
    if output_root.exists() or output_root.is_symlink():
        raise ContractError(f"OUTPUT_ALREADY_EXISTS:{output_root}")
    if prefix_root is not None and _path_is_within(
        output_root.resolve(strict=False), prefix_root.resolve(strict=False)
    ):
        raise ContractError("OUTPUT_ROOT_INSIDE_PREFIX_ROOT")


def _write_report_atomic(path: Path, text: str) -> None:
    """Atomically publish a new report with link(2) O_EXCL semantics."""
    if path.exists() or path.is_symlink():
        raise ContractError(f"REPORT_ALREADY_EXISTS:{path}")
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
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise ContractError(f"REPORT_ALREADY_EXISTS:{path}") from exc
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                raise ContractError(f"REPORT_ALREADY_EXISTS:{path}") from exc
            raise ContractError(f"REPORT_EXCLUSIVE_PUBLISH_FAILED:{exc.errno}") from exc
    except BaseException:
        raise
    finally:
        temporary.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action", choices=("preflight", "export"), default="preflight"
    )
    parser.add_argument("--profile", choices=tuple(PROFILES), default="a02-prefix200")
    parser.add_argument(
        "--source-bag", type=Path, default=WORKSPACE_DEFAULT / SOURCE_RELATIVE
    )
    parser.add_argument(
        "--source-calibration",
        type=Path,
        default=WORKSPACE_DEFAULT / CALIBRATION_RELATIVE,
    )
    parser.add_argument("--output-sequence-root", type=Path)
    parser.add_argument("--prefix-root", type=Path)
    parser.add_argument("--report-json", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    profile = PROFILES[args.profile]
    report_destination_valid = args.report_json is None
    try:
        if args.report_json is not None:
            validate_report_destination(
                args.report_json,
                source_bag=args.source_bag,
                source_calibration=args.source_calibration,
                prefix_root=args.prefix_root,
                output_root=args.output_sequence_root,
            )
            report_destination_valid = True
        if profile.prefix_reuse_count and args.prefix_root is None:
            raise ContractError("PREFIX_ROOT_REQUIRED_FOR_FULL_EXPORT")
        if not profile.prefix_reuse_count and args.prefix_root is not None:
            raise ContractError("PREFIX_ROOT_NOT_ALLOWED_FOR_PREFIX_EXPORT")
        if args.action == "export":
            if args.output_sequence_root is None:
                raise ContractError("OUTPUT_SEQUENCE_ROOT_REQUIRED")
            validate_output_destination(args.output_sequence_root, args.prefix_root)
        source_hash, calibration_hash, calibration, selection = prepare(
            args.source_bag, args.source_calibration, profile
        )
        if args.action == "preflight":
            prefix: PrefixArtifact | None = None
            if args.prefix_root is not None:
                prefix = validate_prefix_artifact(
                    args.prefix_root,
                    args.source_bag,
                    args.source_calibration,
                    selection,
                    profile,
                    source_hash,
                    calibration_hash,
                    calibration,
                )
            result = preflight_result(
                args.source_bag,
                source_hash,
                args.source_calibration,
                calibration_hash,
                calibration,
                selection,
                profile,
                prefix,
            )
        else:
            assert args.output_sequence_root is not None
            result = write_artifact(
                args.output_sequence_root,
                args.source_bag,
                source_hash,
                args.source_calibration,
                calibration_hash,
                calibration,
                selection,
                profile,
                prefix_root=args.prefix_root,
            )
        rc = RC_READY
    except ContractError as exc:
        result = {
            "adapter_version": ADAPTER_VERSION,
            "status": STATUS_INTEGRITY_ERROR,
            "errors": [str(exc)],
            "claims": {
                "anyfeature_source_modified": False,
                "anyfeature_built": False,
                "anyfeature_started": False,
                "trajectory_produced": False,
            },
        }
        rc = RC_INTEGRITY_ERROR
    except Exception as exc:  # Retain a fail-closed diagnostic class.
        result = {
            "adapter_version": ADAPTER_VERSION,
            "status": STATUS_INTEGRITY_ERROR,
            "errors": [f"UNEXPECTED_{type(exc).__name__}:{exc}"],
            "claims": {
                "anyfeature_source_modified": False,
                "anyfeature_built": False,
                "anyfeature_started": False,
                "trajectory_produced": False,
            },
        }
        rc = RC_INTEGRITY_ERROR
    rendered = canonical_json(result)
    if args.report_json is not None and report_destination_valid:
        try:
            _write_report_atomic(args.report_json, rendered)
        except ContractError as exc:
            result = {
                "adapter_version": ADAPTER_VERSION,
                "status": STATUS_INTEGRITY_ERROR,
                "errors": [str(exc)],
                "claims": {
                    "anyfeature_source_modified": False,
                    "anyfeature_built": False,
                    "anyfeature_started": False,
                    "trajectory_produced": False,
                },
            }
            rc = RC_INTEGRITY_ERROR
            rendered = canonical_json(result)
    sys.stdout.write(rendered)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
