#!/usr/bin/env python3
"""Export the frozen A02 COLMAP-plus-pressure reference proxy to strict TUM.

This is a high-level, no-clobber dataset exporter.  It reads only the frozen
A02 bag's raw camera and ``/aqualoc/colmap_gt`` topics.  The 46 reference poses
must already occur at exactly the camera header timestamps for source indices
``0, 20, ..., 900``.  The exporter performs no association tolerance,
interpolation, normalization, coordinate transform, or trajectory evaluation.

The Odometry ``pose.pose`` field is preserved as ``world_T_camera``: position
followed by the original xyzw quaternion.  Timestamp seconds are rendered
directly from integer header nanoseconds with nine fractional digits.

Return codes:

* 0: the exact source and all structural/pose contracts pass; TUM and manifest
  are published;
* 1: the exact bag was readable but its topic, timestamp, or pose contract
  failed; a no-clobber failure manifest is published and no TUM is written;
* 2: invocation, source identity, runtime, TOCTOU, publication, or no-clobber
  preflight blocks the attempt; no output artifact is promised.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
PREREGISTRATION = ROOT / "papers/anyfeature_vslam_r2d2_a02_preregistration.md"

SCHEMA_VERSION = "aqua-fe-anyfeature-a02-reference-proxy-export-v1"
REFERENCE_ROLE = (
    "same-image COLMAP plus pressure-scale reference proxy; not independent "
    "ground truth"
)
SOURCE_PATH = ROOT / "datasets/aqualoc/rosbags/archaeo02_4500_5400.bag"
SOURCE_SIZE_BYTES = 222_477_260
SOURCE_SHA256 = "8cceb4c76065f3862e60428b14ba10f9a26fc7249e11e9e9d090fed2437238a8"

CAMERA_TOPIC = "/camera/image_raw"
REFERENCE_TOPIC = "/aqualoc/colmap_gt"
CAMERA_MESSAGE_TYPE = "sensor_msgs/Image"
REFERENCE_MESSAGE_TYPE = "nav_msgs/Odometry"
EXPECTED_CAMERA_COUNT = 901
EXPECTED_REFERENCE_COUNT = 46
REFERENCE_CAMERA_INDICES = tuple(range(0, 901, 20))
EXPECTED_FIRST_CAMERA_NS = 1_542_829_016_700_435_392
EXPECTED_LAST_CAMERA_NS = 1_542_829_061_692_686_528
QUATERNION_UNIT_TOLERANCE = 1e-6

TUM_FILENAME = "reference_proxy.tum"
MANIFEST_FILENAME = "reference_proxy_manifest.json"

RC_EXPORTED = 0
RC_DATA_CONTRACT_FAILED = 1
RC_CONTRACT_BLOCKED = 2


class ContractError(RuntimeError):
    """Preflight or publication contract blocked formal execution."""


class DataContractError(RuntimeError):
    """The exact bag was read, but its frozen data contract did not hold."""

    def __init__(
        self, code: str, message: str, details: Optional[Mapping[str, object]] = None
    ):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


@dataclass(frozen=True)
class CameraRecord:
    source_index: int
    header_ns: int
    record_ns: int
    message_type: str


@dataclass(frozen=True)
class ReferenceRecord:
    reference_index: int
    camera_index: int
    header_ns: int
    record_ns: int
    position: Tuple[float, float, float]
    quaternion_xyzw: Tuple[float, float, float, float]
    quaternion_norm: float
    message_type: str
    frame_id: str
    child_frame_id: str


@dataclass(frozen=True)
class ReferenceExport:
    cameras: Tuple[CameraRecord, ...]
    references: Tuple[ReferenceRecord, ...]
    tum_bytes: bytes


BagOpener = Callable[[Path], object]


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_identity(path: Path) -> Dict[str, object]:
    absolute = path.expanduser().resolve(strict=True)
    return {
        "path": str(absolute),
        "size_bytes": absolute.stat().st_size,
        "sha256": sha256_file(absolute),
    }


def require_regular_file(path: Path, label: str) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ContractError("{} must not be a symlink".format(label))
    try:
        absolute = expanded.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ContractError("{} is unavailable: {}".format(label, error)) from error
    if not absolute.is_file() or absolute.is_symlink():
        raise ContractError("{} must be a regular non-symlink file".format(label))
    return absolute


def require_source_identity(path: Path) -> Dict[str, object]:
    identity = file_identity(path)
    if identity["size_bytes"] != SOURCE_SIZE_BYTES:
        raise ContractError(
            "source bag size mismatch: expected {}, observed {}".format(
                SOURCE_SIZE_BYTES, identity["size_bytes"]
            )
        )
    if identity["sha256"] != SOURCE_SHA256:
        raise ContractError(
            "source bag SHA-256 mismatch: expected {}, observed {}".format(
                SOURCE_SHA256, identity["sha256"]
            )
        )
    return identity


def stamp_to_ns(stamp: object, *, topic: str, row_index: int, kind: str) -> int:
    try:
        value = stamp.to_nsec()  # type: ignore[attr-defined]
    except Exception as error:
        raise DataContractError(
            "INVALID_{}_STAMP".format(kind.upper()),
            "{} row {} has no integer nanosecond {} stamp".format(
                topic, row_index, kind
            ),
        ) from error
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DataContractError(
            "INVALID_{}_STAMP".format(kind.upper()),
            "{} row {} {} stamp must be a positive integer nanosecond value".format(
                topic, row_index, kind
            ),
            {"observed": value},
        )
    return value


def message_header_ns(message: object, *, topic: str, row_index: int) -> int:
    try:
        stamp = message.header.stamp  # type: ignore[attr-defined]
    except Exception as error:
        raise DataContractError(
            "MISSING_HEADER_STAMP",
            "{} row {} has no header.stamp".format(topic, row_index),
        ) from error
    return stamp_to_ns(stamp, topic=topic, row_index=row_index, kind="header")


def require_message_type(
    message: object, *, expected: str, topic: str, row_index: int
) -> str:
    observed = getattr(message, "_type", None)
    if observed != expected:
        raise DataContractError(
            "MESSAGE_TYPE_MISMATCH",
            "{} row {} type mismatch: expected {}, observed {!r}".format(
                topic, row_index, expected, observed
            ),
            {"expected": expected, "observed": observed},
        )
    return str(observed)


def finite_float(value: object, *, field: str, row_index: int) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise DataContractError(
            "INVALID_POSE_FIELD",
            "reference row {} {} is not numeric".format(row_index, field),
        ) from error
    if not math.isfinite(number):
        raise DataContractError(
            "NONFINITE_POSE",
            "reference row {} {} must be finite".format(row_index, field),
        )
    return number


def extract_world_t_camera(
    message: object, *, row_index: int
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float, float], float, str, str]:
    try:
        pose = message.pose.pose  # type: ignore[attr-defined]
        position = pose.position
        orientation = pose.orientation
    except Exception as error:
        raise DataContractError(
            "INVALID_ODOMETRY_POSE",
            "reference row {} lacks nav_msgs/Odometry pose.pose".format(row_index),
        ) from error
    position_values = tuple(
        finite_float(value, field=field, row_index=row_index)
        for value, field in (
            (position.x, "position.x"),
            (position.y, "position.y"),
            (position.z, "position.z"),
        )
    )
    quaternion_values = tuple(
        finite_float(value, field=field, row_index=row_index)
        for value, field in (
            (orientation.x, "orientation.x"),
            (orientation.y, "orientation.y"),
            (orientation.z, "orientation.z"),
            (orientation.w, "orientation.w"),
        )
    )
    quaternion_norm = math.sqrt(sum(value * value for value in quaternion_values))
    if (
        not math.isfinite(quaternion_norm)
        or quaternion_norm <= 1e-12
        or abs(quaternion_norm - 1.0) > QUATERNION_UNIT_TOLERANCE
    ):
        raise DataContractError(
            "NONUNIT_QUATERNION",
            "reference row {} quaternion norm {} is outside 1 +/- {}".format(
                row_index, format(quaternion_norm, ".17g"), QUATERNION_UNIT_TOLERANCE
            ),
            {"quaternion_norm": quaternion_norm},
        )
    frame_id = str(getattr(getattr(message, "header", None), "frame_id", ""))
    child_frame_id = str(getattr(message, "child_frame_id", ""))
    return (
        position_values,  # type: ignore[return-value]
        quaternion_values,  # type: ignore[return-value]
        quaternion_norm,
        frame_id,
        child_frame_id,
    )


def ns_to_epoch_seconds(stamp_ns: int) -> str:
    seconds, nanoseconds = divmod(stamp_ns, 1_000_000_000)
    return "{}.{:09d}".format(seconds, nanoseconds)


def tum_float(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError("TUM components must be finite")
    return format(value, ".17g")


def encode_tum(references: Sequence[ReferenceRecord]) -> bytes:
    lines = []
    for record in references:
        components = list(record.position) + list(record.quaternion_xyzw)
        lines.append(
            ns_to_epoch_seconds(record.header_ns)
            + " "
            + " ".join(tum_float(value) for value in components)
            + "\n"
        )
    payload = "".join(lines).encode("ascii")
    if len(payload.splitlines()) != EXPECTED_REFERENCE_COUNT:
        raise DataContractError(
            "TUM_ROW_COUNT_MISMATCH", "encoded TUM does not contain 46 rows"
        )
    return payload


def build_reference_export(
    events: Iterable[Tuple[str, object, object]]
) -> ReferenceExport:
    """Validate synthetic or rosbag events and build the exact TUM payload."""

    cameras: List[CameraRecord] = []
    raw_references: List[Tuple[int, int, str, Tuple[float, float, float], Tuple[float, float, float, float], float, str, str]] = []
    for topic, message, record_stamp in events:
        if topic == CAMERA_TOPIC:
            row_index = len(cameras)
            message_type = require_message_type(
                message,
                expected=CAMERA_MESSAGE_TYPE,
                topic=CAMERA_TOPIC,
                row_index=row_index,
            )
            header_ns = message_header_ns(
                message, topic=CAMERA_TOPIC, row_index=row_index
            )
            record_ns = stamp_to_ns(
                record_stamp,
                topic=CAMERA_TOPIC,
                row_index=row_index,
                kind="record",
            )
            if record_ns != header_ns:
                raise DataContractError(
                    "CAMERA_RECORD_HEADER_MISMATCH",
                    "camera row {} record/header mismatch".format(row_index),
                    {"header_ns": header_ns, "record_ns": record_ns},
                )
            if cameras and header_ns <= cameras[-1].header_ns:
                raise DataContractError(
                    "CAMERA_TIMESTAMPS_NOT_STRICT",
                    "camera header timestamps must be strictly increasing",
                    {"source_index": row_index, "header_ns": header_ns},
                )
            cameras.append(
                CameraRecord(row_index, header_ns, record_ns, message_type)
            )
            continue

        if topic == REFERENCE_TOPIC:
            row_index = len(raw_references)
            message_type = require_message_type(
                message,
                expected=REFERENCE_MESSAGE_TYPE,
                topic=REFERENCE_TOPIC,
                row_index=row_index,
            )
            header_ns = message_header_ns(
                message, topic=REFERENCE_TOPIC, row_index=row_index
            )
            record_ns = stamp_to_ns(
                record_stamp,
                topic=REFERENCE_TOPIC,
                row_index=row_index,
                kind="record",
            )
            if record_ns != header_ns:
                raise DataContractError(
                    "REFERENCE_RECORD_HEADER_MISMATCH",
                    "reference row {} record/header mismatch".format(row_index),
                    {"header_ns": header_ns, "record_ns": record_ns},
                )
            if raw_references and header_ns <= raw_references[-1][0]:
                raise DataContractError(
                    "REFERENCE_TIMESTAMPS_NOT_STRICT",
                    "reference header timestamps must be strictly increasing",
                    {"reference_index": row_index, "header_ns": header_ns},
                )
            position, quaternion, norm, frame_id, child_frame_id = (
                extract_world_t_camera(message, row_index=row_index)
            )
            raw_references.append(
                (
                    header_ns,
                    record_ns,
                    message_type,
                    position,
                    quaternion,
                    norm,
                    frame_id,
                    child_frame_id,
                )
            )

    if len(cameras) != EXPECTED_CAMERA_COUNT:
        raise DataContractError(
            "CAMERA_COUNT_MISMATCH",
            "expected 901 camera messages, observed {}".format(len(cameras)),
            {"expected": EXPECTED_CAMERA_COUNT, "observed": len(cameras)},
        )
    if len(raw_references) != EXPECTED_REFERENCE_COUNT:
        raise DataContractError(
            "REFERENCE_COUNT_MISMATCH",
            "expected 46 reference messages, observed {}".format(
                len(raw_references)
            ),
            {"expected": EXPECTED_REFERENCE_COUNT, "observed": len(raw_references)},
        )
    if cameras[0].header_ns != EXPECTED_FIRST_CAMERA_NS:
        raise DataContractError(
            "FIRST_CAMERA_TIMESTAMP_MISMATCH",
            "camera index 0 timestamp mismatch",
            {
                "expected": EXPECTED_FIRST_CAMERA_NS,
                "observed": cameras[0].header_ns,
            },
        )
    if cameras[-1].header_ns != EXPECTED_LAST_CAMERA_NS:
        raise DataContractError(
            "LAST_CAMERA_TIMESTAMP_MISMATCH",
            "camera index 900 timestamp mismatch",
            {
                "expected": EXPECTED_LAST_CAMERA_NS,
                "observed": cameras[-1].header_ns,
            },
        )

    selected_camera_stamps = tuple(
        cameras[index].header_ns for index in REFERENCE_CAMERA_INDICES
    )
    observed_reference_stamps = tuple(row[0] for row in raw_references)
    if observed_reference_stamps != selected_camera_stamps:
        mismatch_index = next(
            index
            for index, (observed, expected) in enumerate(
                zip(observed_reference_stamps, selected_camera_stamps)
            )
            if observed != expected
        )
        raise DataContractError(
            "REFERENCE_CAMERA_INDEX_MAPPING_MISMATCH",
            "reference row {} does not equal camera index {} header timestamp".format(
                mismatch_index, REFERENCE_CAMERA_INDICES[mismatch_index]
            ),
            {
                "reference_index": mismatch_index,
                "camera_index": REFERENCE_CAMERA_INDICES[mismatch_index],
                "expected_camera_header_ns": selected_camera_stamps[mismatch_index],
                "observed_reference_header_ns": observed_reference_stamps[mismatch_index],
            },
        )

    frame_ids = {row[6] for row in raw_references}
    child_frame_ids = {row[7] for row in raw_references}
    if len(frame_ids) != 1 or len(child_frame_ids) != 1:
        raise DataContractError(
            "REFERENCE_FRAME_IDS_NOT_CONSTANT",
            "reference Odometry frame_id and child_frame_id must each be constant",
            {
                "frame_ids": sorted(frame_ids),
                "child_frame_ids": sorted(child_frame_ids),
            },
        )

    references = tuple(
        ReferenceRecord(
            reference_index=index,
            camera_index=REFERENCE_CAMERA_INDICES[index],
            header_ns=row[0],
            record_ns=row[1],
            message_type=row[2],
            position=row[3],
            quaternion_xyzw=row[4],
            quaternion_norm=row[5],
            frame_id=row[6],
            child_frame_id=row[7],
        )
        for index, row in enumerate(raw_references)
    )
    return ReferenceExport(tuple(cameras), references, encode_tum(references))


def reference_row_manifest(record: ReferenceRecord) -> Dict[str, object]:
    return {
        "reference_index": record.reference_index,
        "camera_index": record.camera_index,
        "header_ns": record.header_ns,
        "record_ns": record.record_ns,
        "epoch_seconds": ns_to_epoch_seconds(record.header_ns),
        "position": list(record.position),
        "quaternion_xyzw": list(record.quaternion_xyzw),
        "quaternion_norm": record.quaternion_norm,
        "frame_id": record.frame_id,
        "child_frame_id": record.child_frame_id,
    }


def build_success_manifest(
    export: ReferenceExport,
    identities: Mapping[str, Mapping[str, object]],
) -> Dict[str, object]:
    tum_sha256 = hashlib.sha256(export.tum_bytes).hexdigest()
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "EXPORTED",
        "return_code": RC_EXPORTED,
        "reference_role": REFERENCE_ROLE,
        "reference_is_independent_ground_truth": False,
        "pose_semantics": {
            "source": "nav_msgs/Odometry.pose.pose",
            "transform": "world_T_camera",
            "translation": "camera position in the COLMAP-plus-pressure reference world",
            "quaternion_order": "qx qy qz qw",
            "coordinate_or_pose_modification": False,
            "quaternion_components_preserved_without_normalization": True,
        },
        "inputs": {name: dict(identity) for name, identity in identities.items()},
        "contract": {
            "camera_topic": CAMERA_TOPIC,
            "reference_topic": REFERENCE_TOPIC,
            "camera_message_type": CAMERA_MESSAGE_TYPE,
            "reference_message_type": REFERENCE_MESSAGE_TYPE,
            "camera_count": EXPECTED_CAMERA_COUNT,
            "reference_count": EXPECTED_REFERENCE_COUNT,
            "reference_camera_indices": list(REFERENCE_CAMERA_INDICES),
            "mapping": "reference header stamps equal camera indices 0,20,...,900 exactly",
            "association_tolerance_ns": 0,
            "interpolation": False,
            "record_stamp_equals_header_stamp": True,
            "timestamps_strictly_increasing_unique": True,
            "expected_first_camera_ns": EXPECTED_FIRST_CAMERA_NS,
            "expected_last_camera_ns": EXPECTED_LAST_CAMERA_NS,
            "quaternion_unit_tolerance": QUATERNION_UNIT_TOLERANCE,
        },
        "audit": {
            "camera_count": len(export.cameras),
            "camera_first_header_ns": export.cameras[0].header_ns,
            "camera_last_header_ns": export.cameras[-1].header_ns,
            "reference_count": len(export.references),
            "reference_first_header_ns": export.references[0].header_ns,
            "reference_last_header_ns": export.references[-1].header_ns,
            "camera_message_types": sorted(
                {record.message_type for record in export.cameras}
            ),
            "reference_message_types": sorted(
                {record.message_type for record in export.references}
            ),
            "frame_ids": sorted({record.frame_id for record in export.references}),
            "child_frame_ids": sorted(
                {record.child_frame_id for record in export.references}
            ),
            "quaternion_norm_min": min(
                record.quaternion_norm for record in export.references
            ),
            "quaternion_norm_max": max(
                record.quaternion_norm for record in export.references
            ),
            "rows": [
                reference_row_manifest(record) for record in export.references
            ],
        },
        "output": {
            "tum_filename": TUM_FILENAME,
            "manifest_filename": MANIFEST_FILENAME,
            "tum_sha256": tum_sha256,
            "tum_size_bytes": len(export.tum_bytes),
            "tum_row_count": EXPECTED_REFERENCE_COUNT,
            "timestamp_format": "integer header ns rendered as sec.nanosec with 9 digits",
            "pose_component_format": "IEEE-754 float rendered with 17 significant digits",
            "tum_has_header_or_comments": False,
        },
    }


def build_failure_manifest(
    error: DataContractError,
    identities: Mapping[str, Mapping[str, object]],
) -> Dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "DATA_CONTRACT_FAILED",
        "return_code": RC_DATA_CONTRACT_FAILED,
        "reference_role": REFERENCE_ROLE,
        "reference_is_independent_ground_truth": False,
        "inputs": {name: dict(identity) for name, identity in identities.items()},
        "contract": {
            "camera_topic": CAMERA_TOPIC,
            "reference_topic": REFERENCE_TOPIC,
            "camera_count": EXPECTED_CAMERA_COUNT,
            "reference_count": EXPECTED_REFERENCE_COUNT,
            "reference_camera_indices": list(REFERENCE_CAMERA_INDICES),
            "association_tolerance_ns": 0,
            "interpolation": False,
        },
        "failure": {
            "code": error.code,
            "message": str(error),
            "details": error.details,
        },
        "output": {
            "tum_written": False,
            "manifest_filename": MANIFEST_FILENAME,
        },
    }


def publish_no_clobber(
    output_dir: Path,
    manifest: Mapping[str, object],
    tum_bytes: Optional[bytes],
) -> Dict[str, object]:
    absolute = output_dir.expanduser().resolve(strict=False)
    if absolute.exists() or absolute.is_symlink():
        raise ContractError("no-clobber output already exists: {}".format(absolute))
    try:
        absolute.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        raise ContractError("could not create no-clobber output: {}".format(error)) from error
    if tum_bytes is not None:
        with (absolute / TUM_FILENAME).open("xb") as stream:
            stream.write(tum_bytes)
            stream.flush()
            os.fsync(stream.fileno())
    manifest_bytes = canonical_json_bytes(manifest)
    with (absolute / MANIFEST_FILENAME).open("xb") as stream:
        stream.write(manifest_bytes)
        stream.flush()
        os.fsync(stream.fileno())
    return {
        "output_dir": str(absolute),
        "manifest": str(absolute / MANIFEST_FILENAME),
        "tum": str(absolute / TUM_FILENAME) if tum_bytes is not None else None,
    }


def default_bag_opener(path: Path) -> object:
    try:
        import rosbag
    except (ImportError, OSError) as error:
        raise ContractError("ROS1 rosbag runtime is unavailable: {}".format(error)) from error
    try:
        return rosbag.Bag(str(path), "r")
    except Exception as error:
        raise DataContractError(
            "BAG_OPEN_FAILED", "exact source bag could not be opened: {}".format(error)
        ) from error


def iter_bag_events(bag: object) -> Iterable[Tuple[str, object, object]]:
    try:
        yield from bag.read_messages(topics=[CAMERA_TOPIC, REFERENCE_TOPIC])  # type: ignore[attr-defined]
    except DataContractError:
        raise
    except Exception as error:
        raise DataContractError(
            "BAG_READ_FAILED", "exact source bag could not be read: {}".format(error)
        ) from error


def close_bag(bag: object) -> None:
    try:
        bag.close()  # type: ignore[attr-defined]
    except Exception as error:
        raise DataContractError(
            "BAG_CLOSE_FAILED", "exact source bag could not be closed: {}".format(error)
        ) from error


def same_identity(
    left: Mapping[str, object], right: Mapping[str, object]
) -> bool:
    return all(left.get(key) == right.get(key) for key in ("path", "size_bytes", "sha256"))


def run_formal_export(
    bag_path: Path,
    output_dir: Path,
    *,
    bag_opener: BagOpener = default_bag_opener,
) -> Tuple[int, Dict[str, object]]:
    output_absolute = output_dir.expanduser().resolve(strict=False)
    if output_absolute.exists() or output_absolute.is_symlink():
        raise ContractError("no-clobber output already exists: {}".format(output_absolute))
    bag_absolute = require_regular_file(bag_path, "source bag")
    source_identity = require_source_identity(bag_absolute)
    evaluator_identity = file_identity(require_regular_file(Path(__file__), "exporter"))
    preregistration_identity = file_identity(
        require_regular_file(PREREGISTRATION, "preregistration")
    )
    identities = {
        "source_bag": source_identity,
        "exporter": evaluator_identity,
        "preregistration": preregistration_identity,
    }

    bag = None
    data_error: Optional[DataContractError] = None
    export: Optional[ReferenceExport] = None
    try:
        bag = bag_opener(bag_absolute)
        export = build_reference_export(iter_bag_events(bag))
    except DataContractError as error:
        data_error = error
    finally:
        if bag is not None:
            try:
                close_bag(bag)
            except DataContractError as error:
                if data_error is None:
                    data_error = error

    identity_paths = {
        "source_bag": bag_absolute,
        "exporter": Path(__file__),
        "preregistration": PREREGISTRATION,
    }
    for name, path in identity_paths.items():
        observed_after = file_identity(path)
        if not same_identity(identities[name], observed_after):
            raise ContractError("{} changed during export".format(name))

    if data_error is not None:
        manifest = build_failure_manifest(data_error, identities)
        publication = publish_no_clobber(output_absolute, manifest, None)
        return RC_DATA_CONTRACT_FAILED, publication
    if export is None:
        raise ContractError("export produced neither data nor a classified failure")
    manifest = build_success_manifest(export, identities)
    publication = publish_no_clobber(output_absolute, manifest, export.tum_bytes)
    return RC_EXPORTED, publication


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export the frozen A02 46-pose same-image COLMAP plus pressure-scale "
            "reference proxy; it is not independent ground truth."
        )
    )
    parser.add_argument("--bag", type=Path, default=SOURCE_PATH)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return_code, publication = run_formal_export(args.bag, args.output_dir)
    except (ContractError, OSError) as error:
        document = {
            "schema_version": SCHEMA_VERSION,
            "status": "CONTRACT_BLOCKED",
            "return_code": RC_CONTRACT_BLOCKED,
            "error": str(error),
        }
        sys.stdout.buffer.write(canonical_json_bytes(document))
        return RC_CONTRACT_BLOCKED
    document = {
        "schema_version": SCHEMA_VERSION,
        "status": "EXPORTED" if return_code == 0 else "DATA_CONTRACT_FAILED",
        "return_code": return_code,
        **publication,
    }
    sys.stdout.buffer.write(canonical_json_bytes(document))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
