#!/usr/bin/env python3
"""Independent preregistered audit for the SuperPoint-birth + LK-carrier v1.

The schedule/reference bag supplies feature timestamps, message schema, and all
non-feature content.  The candidate owns its IDs and measurements.  This tool
does not import the adapter or any other feature-bag checker.

Exit codes: 0 PASS, 1 contract/scientific FAIL, 2 input/capability/runtime ERROR.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

import cv2
import numpy as np


SCHEMA_VERSION = "aqua-fe-superpoint-lk-carrier-audit-v1"
DEFAULT_FEATURE_TOPIC = "/feature_tracker/feature"
SUPERPOINT_AUDIT_METHOD_ID = "superpoint_detector_raw_frame_lk_carrier_v1"

NORMALIZED_TOLERANCE = 1e-6
VELOCITY_TOLERANCE = 1e-5
THINNING_RADIUS_PX = 20.0
GRID_ROWS = 6
GRID_COLS = 8
ESSENTIAL_THRESHOLD_PX = 0.3
ESSENTIAL_PROBABILITY = 0.999
ESSENTIAL_MAX_ITERS = 200
ESSENTIAL_MIN_PAIRS = 8
RANSAC_SEED = 0
MAX_REPORTED_VIOLATIONS = 20

BIRTH_MEDIAN_MAX = 0.05
BIRTH_P90_MAX = 0.10
EPISODE_MEDIAN_MIN = 10.0
EPISODE_LE2_FRACTION_MAX = 0.45
LAG10_MEDIAN_MIN = 250.0
LAG10_P10_MIN = 220.0
THIN20_MEDIAN_MIN = 250.0
THIN20_P10_MIN = 220.0
GRID_MEDIAN_MIN = 30.0
GRID_P10_MIN = 26.0
SECOND_DIFFERENCE_MEDIAN_MAX = 0.3
ESSENTIAL_MEDIAN_MIN = 0.90
ESSENTIAL_P10_MIN = 0.85

REQUIRED_CHANNELS = frozenset(
    {
        "id",
        "p_u",
        "p_v",
        "velocity_x",
        "velocity_y",
        "quality",
        "sigma",
        "source_code",
        "is_learned",
    }
)


class AuditInputError(RuntimeError):
    """Malformed input or unavailable required capability."""


@dataclass(frozen=True)
class AuditMethodSpec:
    method_id: str
    schema_version: str
    expected_source_code: int
    entrypoint_source: Path
    expected_observations_per_frame: int = 350

    def validate(self) -> None:
        if not self.method_id or not self.schema_version:
            raise ValueError("audit method id/schema must be nonempty")
        if (
            not isinstance(self.expected_source_code, int)
            or isinstance(self.expected_source_code, bool)
        ):
            raise ValueError("audit expected_source_code must be an integer")
        if (
            not isinstance(self.expected_observations_per_frame, int)
            or isinstance(self.expected_observations_per_frame, bool)
            or self.expected_observations_per_frame <= 0
        ):
            raise ValueError(
                "audit expected_observations_per_frame must be a positive integer"
            )
        if not Path(self.entrypoint_source).is_file():
            raise FileNotFoundError(self.entrypoint_source)

    def identity(self) -> dict[str, object]:
        self.validate()
        return {
            "method_id": self.method_id,
            "schema_version": self.schema_version,
            "expected_source_code": self.expected_source_code,
            "expected_observations_per_frame": (
                self.expected_observations_per_frame
            ),
        }


SUPERPOINT_AUDIT_METHOD_SPEC = AuditMethodSpec(
    method_id=SUPERPOINT_AUDIT_METHOD_ID,
    schema_version=SCHEMA_VERSION,
    expected_source_code=10,
    entrypoint_source=Path(__file__).resolve(),
    expected_observations_per_frame=350,
)


@dataclass(frozen=True)
class CameraModel:
    fx: float
    fy: float
    cx: float
    cy: float
    distortion: tuple[float, ...]
    width: int
    height: int
    model: str = "pinhole"

    @property
    def matrix(self) -> np.ndarray:
        return np.asarray(
            [
                [self.fx, 0.0, self.cx],
                [0.0, self.fy, self.cy],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )

    @property
    def distortion_vector(self) -> np.ndarray:
        return np.asarray(self.distortion, dtype=np.float64)

    @property
    def focal_mean_px(self) -> float:
        return 0.5 * (float(self.fx) + float(self.fy))

    def undistort_points(self, pixels: np.ndarray) -> np.ndarray:
        points = np.asarray(pixels, dtype=np.float64).reshape(-1, 1, 2)
        if self.model == "pinhole":
            result = cv2.undistortPoints(
                points,
                self.matrix,
                self.distortion_vector,
            )
        elif self.model == "kannala_brandt":
            result = cv2.fisheye.undistortPoints(
                points,
                self.matrix,
                self.distortion_vector,
            )
        else:
            raise AuditInputError(f"unsupported camera model {self.model!r}")
        return np.asarray(result, dtype=np.float64).reshape(-1, 2)


@dataclass(frozen=True)
class FeatureFrame:
    index: int
    record_stamp_ns: int
    header_stamp_ns: int
    header_seq: int
    header_frame_id: str
    schema: tuple[str, ...]
    channels: Mapping[str, np.ndarray]
    ids: np.ndarray
    pixels: np.ndarray
    normalized: np.ndarray
    point_z: np.ndarray
    velocities: np.ndarray
    decode_violations: tuple[str, ...] = ()


EssentialSolver = Callable[[np.ndarray, np.ndarray, float], np.ndarray]


def require_usac_magsac() -> None:
    if getattr(cv2, "USAC_MAGSAC", None) is None:
        raise AuditInputError("cv2.USAC_MAGSAC is required")


def _stamp_ns(stamp: object, label: str) -> int:
    to_nsec = getattr(stamp, "to_nsec", None)
    if callable(to_nsec):
        return int(to_nsec())
    secs = getattr(stamp, "secs", None)
    nsecs = getattr(stamp, "nsecs", None)
    if secs is None or nsecs is None:
        raise AuditInputError(f"{label} has no nanosecond representation")
    return int(secs) * 1_000_000_000 + int(nsecs)


def _node_sequence(node: object) -> list[float] | None:
    if node is None or node.empty():
        return None
    if node.isSeq():
        return [float(node.at(index).real()) for index in range(int(node.size()))]
    if node.isMap():
        data = node.getNode("data")
        if not data.empty() and data.isSeq():
            return [float(data.at(index).real()) for index in range(int(data.size()))]
    try:
        matrix = node.mat()
    except Exception:
        matrix = None
    if matrix is None:
        return None
    return [float(value) for value in np.asarray(matrix).reshape(-1)]


def _projection(container: object) -> tuple[float, float, float, float] | None:
    node = container.getNode("projection_parameters")
    if not node.empty() and node.isMap():
        children = [node.getNode(name) for name in ("fx", "fy", "cx", "cy")]
        if all(not child.empty() for child in children):
            values = [float(child.real()) for child in children]
            return values[0], values[1], values[2], values[3]
        children = [node.getNode(name) for name in ("mu", "mv", "u0", "v0")]
        if all(not child.empty() for child in children):
            values = [float(child.real()) for child in children]
            return values[0], values[1], values[2], values[3]
    values = _node_sequence(container.getNode("intrinsics"))
    if values is not None and len(values) == 4:
        return values[0], values[1], values[2], values[3]
    values = _node_sequence(container.getNode("camera_matrix"))
    if values is None:
        values = _node_sequence(container.getNode("K"))
    if values is not None and len(values) == 9:
        return values[0], values[4], values[2], values[5]
    return None


def _camera_model(container: object) -> str:
    for name in ("model_type", "distortion_model"):
        node = container.getNode(name)
        if not node.empty():
            value = str(node.string()).upper()
            if value in {"KANNALA_BRANDT", "EQUIDISTANT", "FISHEYE"}:
                return "kannala_brandt"
            if value in {"PINHOLE", "PLUMB_BOB", "RADTAN"}:
                return "pinhole"
    return "pinhole"


def _distortion(container: object, model: str = "pinhole") -> tuple[float, ...] | None:
    if model == "kannala_brandt":
        node = container.getNode("projection_parameters")
        if not node.empty() and node.isMap():
            children = [node.getNode(name) for name in ("k2", "k3", "k4", "k5")]
            if all(not child.empty() for child in children):
                return tuple(float(child.real()) for child in children)
    node = container.getNode("distortion_parameters")
    if not node.empty() and node.isMap():
        base = [node.getNode(name) for name in ("k1", "k2", "p1", "p2")]
        if all(not child.empty() for child in base):
            values = [float(child.real()) for child in base]
            for name in (
                "k3",
                "k4",
                "k5",
                "k6",
                "s1",
                "s2",
                "s3",
                "s4",
                "tau_x",
                "tau_y",
            ):
                child = node.getNode(name)
                if child.empty():
                    break
                values.append(float(child.real()))
            return tuple(values)
    for name in ("distortion_coeffs", "distortion_coefficients", "D"):
        values = _node_sequence(container.getNode(name))
        if values is not None:
            return tuple(values)
    return None


def _integer_node(container: object, names: Sequence[str]) -> int | None:
    for name in names:
        node = container.getNode(name)
        if not node.empty():
            return int(round(float(node.real())))
    return None


def _image_dimensions(container: object) -> tuple[int, int] | None:
    width = _integer_node(container, ("image_width", "width"))
    height = _integer_node(container, ("image_height", "height"))
    if width is not None and height is not None:
        return width, height
    resolution = _node_sequence(container.getNode("resolution"))
    if resolution is not None and len(resolution) == 2:
        return int(round(resolution[0])), int(round(resolution[1]))
    return None


def load_camera_model(path: Path) -> CameraModel:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    storage = cv2.FileStorage(str(path), cv2.FILE_STORAGE_READ)
    if not storage.isOpened():
        raise AuditInputError(f"could not open camera YAML: {path}")
    projection = None
    distortion = None
    width = None
    height = None
    model = None
    try:
        root = storage.root()
        cam0 = storage.getNode("cam0")
        containers = [cam0, root] if not cam0.empty() else [root]
        for container in containers:
            current_model = _camera_model(container)
            current_projection = _projection(container)
            current_distortion = _distortion(container, current_model)
            dimensions = _image_dimensions(container)
            current_width = dimensions[0] if dimensions is not None else None
            current_height = dimensions[1] if dimensions is not None else None
            if (
                current_projection is not None
                and current_distortion is not None
                and current_width is not None
                and current_height is not None
            ):
                projection = current_projection
                distortion = current_distortion
                width = current_width
                height = current_height
                model = current_model
                break
    finally:
        storage.release()
    if projection is None or distortion is None or width is None or height is None:
        raise AuditInputError("camera YAML must provide K, D, width, and height at root or cam0")
    camera = CameraModel(*projection, distortion, width, height, model or "pinhole")
    values = (*projection, *distortion)
    if not all(math.isfinite(float(value)) for value in values):
        raise AuditInputError("camera K/D contains non-finite values")
    if camera.fx <= 0.0 or camera.fy <= 0.0 or width <= 0 or height <= 0:
        raise AuditInputError("camera focal lengths and image dimensions must be positive")
    if camera.model == "kannala_brandt" and len(distortion) != 4:
        raise AuditInputError("Kannala-Brandt cameras require four coefficients")
    if camera.model == "pinhole" and len(distortion) not in {4, 5, 8, 12, 14}:
        raise AuditInputError("unsupported OpenCV distortion-vector length")
    return camera


def _padded_channel(
    channel_map: Mapping[str, np.ndarray], name: str, count: int
) -> np.ndarray:
    values = channel_map.get(name)
    if values is None or values.shape != (count,):
        return np.full((count,), np.nan, dtype=np.float64)
    return np.asarray(values, dtype=np.float64)


def load_feature_frames(
    bag_path: Path, feature_topic: str = DEFAULT_FEATURE_TOPIC
) -> list[FeatureFrame]:
    bag_path = Path(bag_path)
    if not bag_path.is_file():
        raise FileNotFoundError(bag_path)
    try:
        import rosbag  # type: ignore
    except ModuleNotFoundError as exc:
        raise AuditInputError("rosbag is required") from exc

    frames: list[FeatureFrame] = []
    with rosbag.Bag(str(bag_path), "r") as bag:
        for _, message, record_stamp in bag.read_messages(topics=[feature_topic]):
            index = len(frames)
            points = list(getattr(message, "points", ()))
            count = len(points)
            channel_messages = list(getattr(message, "channels", ()))
            schema = tuple(str(channel.name) for channel in channel_messages)
            violations: list[str] = []
            if len(schema) != len(set(schema)):
                violations.append("DUPLICATE_CHANNEL_NAME")
            channels: dict[str, np.ndarray] = {}
            for channel in channel_messages:
                name = str(channel.name)
                if name in channels:
                    continue
                try:
                    values = np.asarray(channel.values, dtype=np.float64)
                except Exception:
                    values = np.full((count,), np.nan, dtype=np.float64)
                    violations.append(f"CHANNEL_NOT_NUMERIC:{name}")
                if values.shape != (count,):
                    violations.append(f"CHANNEL_LENGTH:{name}")
                channels[name] = values
            for name in sorted(REQUIRED_CHANNELS - set(channels)):
                violations.append(f"MISSING_CHANNEL:{name}")

            raw_ids = _padded_channel(channels, "id", count)
            ids_valid = np.isfinite(raw_ids) & (raw_ids == np.rint(raw_ids))
            if not bool(np.all(ids_valid)):
                violations.append("ID_NOT_FINITE_INTEGRAL")
                ids = np.arange(count, dtype=np.int64) - (index + 1) * 1_000_000_000
            else:
                ids = np.rint(raw_ids).astype(np.int64)

            try:
                normalized = np.asarray(
                    [(float(point.x), float(point.y)) for point in points],
                    dtype=np.float64,
                ).reshape(-1, 2)
                point_z = np.asarray(
                    [float(point.z) for point in points], dtype=np.float64
                )
            except Exception:
                normalized = np.full((count, 2), np.nan, dtype=np.float64)
                point_z = np.full((count,), np.nan, dtype=np.float64)
                violations.append("POINT_GEOMETRY_NOT_NUMERIC")
            pixels = np.column_stack(
                (
                    _padded_channel(channels, "p_u", count),
                    _padded_channel(channels, "p_v", count),
                )
            )
            velocities = np.column_stack(
                (
                    _padded_channel(channels, "velocity_x", count),
                    _padded_channel(channels, "velocity_y", count),
                )
            )
            header = getattr(message, "header", None)
            if header is None:
                raise AuditInputError(f"feature frame {index} has no header")
            frames.append(
                FeatureFrame(
                    index=index,
                    record_stamp_ns=_stamp_ns(record_stamp, f"feature frame {index} record stamp"),
                    header_stamp_ns=_stamp_ns(header.stamp, f"feature frame {index} header stamp"),
                    header_seq=int(getattr(header, "seq", 0)),
                    header_frame_id=str(getattr(header, "frame_id", "")),
                    schema=schema,
                    channels=channels,
                    ids=ids,
                    pixels=pixels,
                    normalized=normalized,
                    point_z=point_z,
                    velocities=velocities,
                    decode_violations=tuple(violations),
                )
            )
    if not frames:
        raise AuditInputError(f"no feature frames found on {feature_topic}")
    return frames


def _message_bytes(message: object) -> bytes:
    serialize = getattr(message, "serialize", None)
    if not callable(serialize):
        raise AuditInputError(f"{type(message).__name__} has no serialize method")
    buffer = io.BytesIO()
    serialize(buffer)
    return buffer.getvalue()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_metadata(path: Path) -> dict[str, object]:
    path = Path(path).resolve()
    return {
        "path": str(path),
        "size_bytes": int(path.stat().st_size),
        "sha256": _sha256_file(path),
    }


def audit_artifact_metadata(method_spec: AuditMethodSpec) -> dict[str, object]:
    method_spec.validate()
    entrypoint = Path(method_spec.entrypoint_source).resolve()
    audit_base = Path(__file__).resolve()
    result = {
        "method": method_spec.identity(),
        "entrypoint": _file_metadata(entrypoint),
    }
    if entrypoint != audit_base:
        result["audit_base"] = _file_metadata(audit_base)
    return result


def nonfeature_digest(
    bag_path: Path,
    feature_topic: str,
    *,
    cutoff_ns: int | None,
) -> dict[str, object]:
    try:
        import rosbag  # type: ignore
    except ModuleNotFoundError as exc:
        raise AuditInputError("rosbag is required") from exc
    digest = hashlib.sha256()
    topic_state: dict[str, dict[str, object]] = {}
    selected = 0
    after_cutoff = 0
    with rosbag.Bag(str(bag_path), "r") as bag:
        for topic, message, record_stamp in bag.read_messages():
            topic = str(topic)
            if topic == feature_topic:
                continue
            stamp_ns = _stamp_ns(record_stamp, f"{topic} record stamp")
            if cutoff_ns is not None and stamp_ns > cutoff_ns:
                after_cutoff += 1
                continue
            payload = _message_bytes(message)
            topic_bytes = topic.encode("utf-8")
            framed = (
                struct.pack("<I", len(topic_bytes))
                + topic_bytes
                + struct.pack("<qQ", stamp_ns, len(payload))
                + payload
            )
            digest.update(framed)
            state = topic_state.setdefault(
                topic, {"count": 0, "sha256": hashlib.sha256()}
            )
            state["count"] = int(state["count"]) + 1
            state["sha256"].update(framed)
            selected += 1
    return {
        "cutoff_ns": int(cutoff_ns) if cutoff_ns is not None else None,
        "selected_message_count": selected,
        "messages_after_cutoff": after_cutoff,
        "sha256": digest.hexdigest(),
        "topics": {
            topic: {
                "count": int(state["count"]),
                "sha256": state["sha256"].hexdigest(),
            }
            for topic, state in sorted(topic_state.items())
        },
    }


def compare_nonfeature(
    reference_bag: Path,
    candidate_bag: Path,
    feature_topic: str,
    *,
    cutoff_ns: int | None,
) -> dict[str, object]:
    reference = nonfeature_digest(reference_bag, feature_topic, cutoff_ns=cutoff_ns)
    candidate = nonfeature_digest(candidate_bag, feature_topic, cutoff_ns=cutoff_ns)
    violations: dict[str, int] = {}
    if (
        reference["selected_message_count"] != candidate["selected_message_count"]
        or reference["sha256"] != candidate["sha256"]
    ):
        violations["NONFEATURE_TUPLES_CHANGED"] = 1
    if cutoff_ns is not None and int(candidate["messages_after_cutoff"]) != 0:
        violations["CANDIDATE_NONFEATURE_AFTER_CUTOFF"] = int(
            candidate["messages_after_cutoff"]
        )
    return {
        "pass": not violations,
        "mode": "prefix_through_cutoff" if cutoff_ns is not None else "full_exact",
        "tuple_contract": "ordered(topic,record_stamp_ns,serialized_payload)",
        "cutoff_ns": int(cutoff_ns) if cutoff_ns is not None else None,
        "reference": reference,
        "candidate": candidate,
        "violation_counts": violations,
    }


def _quantiles(values: Sequence[float]) -> dict[str, object]:
    array = np.asarray(values, dtype=np.float64)
    array = array[np.isfinite(array)]
    if len(array) == 0:
        return {
            "count": 0,
            "min": None,
            "p10": None,
            "median": None,
            "p90": None,
            "max": None,
        }
    return {
        "count": int(len(array)),
        "min": float(np.min(array)),
        "p10": float(np.percentile(array, 10)),
        "median": float(np.median(array)),
        "p90": float(np.percentile(array, 90)),
        "max": float(np.max(array)),
    }


def evaluate_contract(
    reference: Sequence[FeatureFrame],
    candidate: Sequence[FeatureFrame],
    camera: CameraModel,
    nonfeature: Mapping[str, object],
    *,
    allow_prefix: bool,
    method_spec: AuditMethodSpec = SUPERPOINT_AUDIT_METHOD_SPEC,
) -> dict[str, object]:
    method_spec.validate()
    counts: dict[str, int] = {}
    first: list[dict[str, object]] = []

    def record(kind: str, frame: int | None = None, detail: object | None = None) -> None:
        counts[kind] = counts.get(kind, 0) + 1
        if len(first) < MAX_REPORTED_VIOLATIONS:
            item: dict[str, object] = {"kind": kind}
            if frame is not None:
                item["frame_index"] = int(frame)
            if detail is not None:
                item["detail"] = detail
            first.append(item)

    if allow_prefix:
        if len(candidate) > len(reference):
            record("CANDIDATE_LONGER_THAN_REFERENCE")
        comparison_reference = reference[: len(candidate)]
    else:
        comparison_reference = reference
        if len(candidate) != len(reference):
            record("FEATURE_FRAME_COUNT_CHANGED")

    for index, (left, right) in enumerate(zip(comparison_reference, candidate)):
        if left.record_stamp_ns != right.record_stamp_ns:
            record("FEATURE_RECORD_SCHEDULE_CHANGED", index)
        if left.header_stamp_ns != right.header_stamp_ns:
            record("FEATURE_HEADER_SCHEDULE_CHANGED", index)
        if left.header_seq != right.header_seq or left.header_frame_id != right.header_frame_id:
            record("FEATURE_HEADER_METADATA_CHANGED", index)
        if left.schema != right.schema:
            record("CHANNEL_SCHEMA_CHANGED", index)

    retired: set[int] = set()
    previous_ids: set[int] = set()
    previous_frame: FeatureFrame | None = None
    normalized_errors: list[float] = []
    velocity_errors: list[float] = []
    observation_counts = [int(len(frame.ids)) for frame in candidate]
    observed_observation_count = (
        {
            "min": int(min(observation_counts)),
            "median": float(np.median(observation_counts)),
            "max": int(max(observation_counts)),
        }
        if observation_counts
        else {"min": None, "median": None, "max": None}
    )
    for index, frame in enumerate(candidate):
        for violation in frame.decode_violations:
            record(f"DECODE:{violation}", index)
        ids = [int(value) for value in frame.ids]
        current_ids = set(ids)
        if len(current_ids) != len(ids):
            record("DUPLICATE_ID_IN_FRAME", index)
        reused = sorted(current_ids & retired)
        if reused:
            record("DEAD_ID_REUSED", index, reused[:5])
        retired.update(previous_ids - current_ids)

        count = len(ids)
        if count != method_spec.expected_observations_per_frame:
            record(
                "OBSERVATION_COUNT_NOT_EXACT",
                index,
                {
                    "expected": method_spec.expected_observations_per_frame,
                    "observed": count,
                },
            )
        for name, required_value in (
            ("quality", 1.0),
            ("sigma", 1.0),
            ("source_code", float(method_spec.expected_source_code)),
            ("is_learned", 1.0),
        ):
            values = _padded_channel(frame.channels, name, count)
            if not bool(np.all(values == required_value)):
                record(f"CHANNEL_NOT_EXACT:{name}={required_value:g}", index)
        if not bool(np.all(frame.point_z == 1.0)):
            record("POINT_Z_NOT_EXACT_ONE", index)
        geometry_finite = bool(
            np.isfinite(frame.pixels).all()
            and np.isfinite(frame.normalized).all()
            and np.isfinite(frame.velocities).all()
        )
        if not geometry_finite:
            record("NONFINITE_CANDIDATE_GEOMETRY", index)
        in_bounds = bool(
            np.all(frame.pixels[:, 0] >= 0.0)
            and np.all(frame.pixels[:, 0] < camera.width)
            and np.all(frame.pixels[:, 1] >= 0.0)
            and np.all(frame.pixels[:, 1] < camera.height)
        )
        if not in_bounds:
            record("PIXEL_OUTSIDE_IMAGE", index)

        if count and geometry_finite:
            expected_normalized = camera.undistort_points(frame.pixels)
            errors = np.linalg.norm(expected_normalized - frame.normalized, axis=1)
            normalized_errors.extend(float(value) for value in errors)
            max_error = float(np.max(errors))
            if max_error > NORMALIZED_TOLERANCE:
                record("NORMALIZED_FROM_PIXEL_MISMATCH", index, max_error)

        expected_velocity = np.zeros((count, 2), dtype=np.float64)
        if previous_frame is not None:
            dt = (frame.header_stamp_ns - previous_frame.header_stamp_ns) * 1e-9
            if not math.isfinite(dt) or dt <= 0.0:
                record("NONPOSITIVE_PUBLISHED_DT", index, dt)
            else:
                previous_by_id = {
                    int(feature_id): point_index
                    for point_index, feature_id in enumerate(previous_frame.ids)
                }
                for point_index, feature_id in enumerate(frame.ids):
                    old_index = previous_by_id.get(int(feature_id))
                    if old_index is not None:
                        expected_velocity[point_index] = (
                            frame.normalized[point_index]
                            - previous_frame.normalized[old_index]
                        ) / dt
        if count and geometry_finite:
            errors = np.linalg.norm(frame.velocities - expected_velocity, axis=1)
            velocity_errors.extend(float(value) for value in errors)
            max_error = float(np.max(errors))
            if max_error > VELOCITY_TOLERANCE:
                record("VELOCITY_FROM_PUBLISHED_DT_MISMATCH", index, max_error)
        previous_ids = current_ids
        previous_frame = frame

    if not bool(nonfeature.get("pass", False)):
        record("NONFEATURE_CONTRACT_CHANGED")
    return {
        "pass": not counts,
        "mode": "explicit_prefix" if allow_prefix else "full_exact",
        "reference_frame_count": len(reference),
        "candidate_frame_count": len(candidate),
        "compared_reference_frame_count": len(comparison_reference),
        "observations_per_frame": {
            "expected": method_spec.expected_observations_per_frame,
            "observed": observed_observation_count,
        },
        "fixed_fields": {
            "observations_per_frame": method_spec.expected_observations_per_frame,
            "quality": 1.0,
            "sigma": 1.0,
            "source_code": float(method_spec.expected_source_code),
            "is_learned": 1.0,
            "point_z": 1.0,
            "normalized_tolerance": NORMALIZED_TOLERANCE,
            "velocity_tolerance": VELOCITY_TOLERANCE,
        },
        "normalized_error": _quantiles(normalized_errors),
        "velocity_error": _quantiles(velocity_errors),
        "nonfeature": dict(nonfeature),
        "violation_counts": counts,
        "first_violations": first,
        "first_violations_truncated": sum(counts.values()) > len(first),
    }


def deterministic_thinning_count(
    pixels: np.ndarray, ids: np.ndarray, ages: Mapping[int, int]
) -> int:
    """Age-descending, ID-ascending greedy 20 px thinning."""

    order = sorted(
        range(len(ids)),
        key=lambda index: (-int(ages.get(int(ids[index]), 1)), int(ids[index]), index),
    )
    kept: list[np.ndarray] = []
    radius_squared = THINNING_RADIUS_PX * THINNING_RADIUS_PX
    for index in order:
        point = np.asarray(pixels[index], dtype=np.float64)
        if not bool(np.isfinite(point).all()):
            continue
        if not kept:
            kept.append(point)
            continue
        distance_squared = np.sum((np.asarray(kept) - point) ** 2, axis=1)
        if bool(np.all(distance_squared >= radius_squared)):
            kept.append(point)
    return len(kept)


def magsac_essential_mask(
    left: np.ndarray, right: np.ndarray, focal_mean_px: float
) -> np.ndarray:
    require_usac_magsac()
    left = np.ascontiguousarray(left, dtype=np.float32).reshape(-1, 2)
    right = np.ascontiguousarray(right, dtype=np.float32).reshape(-1, 2)
    if left.shape != right.shape or len(left) < ESSENTIAL_MIN_PAIRS:
        raise AuditInputError("Essential solver requires matching arrays with >=8 pairs")
    cv2.setRNGSeed(RANSAC_SEED)
    try:
        essential, mask = cv2.findEssentialMat(
            left,
            right,
            np.eye(3, dtype=np.float64),
            method=cv2.USAC_MAGSAC,
            prob=ESSENTIAL_PROBABILITY,
            threshold=ESSENTIAL_THRESHOLD_PX / float(focal_mean_px),
            maxIters=ESSENTIAL_MAX_ITERS,
        )
    except Exception as exc:
        raise AuditInputError(f"findEssentialMat failed: {exc}") from exc
    if essential is None or mask is None:
        raise AuditInputError("findEssentialMat returned no model/mask")
    flat = np.asarray(mask).reshape(-1)
    if len(flat) != len(left):
        raise AuditInputError("findEssentialMat mask length mismatch")
    return flat != 0


def compute_metrics(
    frames: Sequence[FeatureFrame],
    camera: CameraModel,
    *,
    solver: EssentialSolver = magsac_essential_mask,
) -> dict[str, object]:
    id_sets: list[set[int]] = []
    point_maps: list[dict[int, np.ndarray]] = []
    active_lengths: dict[int, int] = {}
    retired_lengths: list[int] = []
    previous_ids: set[int] = set()
    birth_rates: list[float] = []
    thinning_counts: list[float] = []
    occupied_cells: list[float] = []

    for frame_index, frame in enumerate(frames):
        ids = [int(value) for value in frame.ids]
        current_ids = set(ids)
        id_sets.append(current_ids)
        point_maps.append(
            {
                int(feature_id): frame.pixels[index]
                for index, feature_id in enumerate(ids)
                if bool(np.isfinite(frame.pixels[index]).all())
            }
        )
        for lost_id in previous_ids - current_ids:
            retired_lengths.append(active_lengths.pop(lost_id))
        for feature_id in ids:
            active_lengths[feature_id] = active_lengths.get(feature_id, 0) + 1
        if frame_index:
            births = len(current_ids - previous_ids)
            birth_rates.append(float(births / max(1, len(ids))))

        thinning_counts.append(
            float(deterministic_thinning_count(frame.pixels, frame.ids, active_lengths))
        )
        finite_pixels = frame.pixels[np.isfinite(frame.pixels).all(axis=1)]
        if len(finite_pixels):
            grid_x = np.floor(finite_pixels[:, 0] / camera.width * GRID_COLS).astype(int)
            grid_y = np.floor(finite_pixels[:, 1] / camera.height * GRID_ROWS).astype(int)
            grid_x = np.clip(grid_x, 0, GRID_COLS - 1)
            grid_y = np.clip(grid_y, 0, GRID_ROWS - 1)
            occupied_cells.append(float(len(set((grid_y * GRID_COLS + grid_x).tolist()))))
        else:
            occupied_cells.append(0.0)
        previous_ids = current_ids
    retired_lengths.extend(active_lengths.values())

    lag10_counts = [
        float(len(id_sets[index] & id_sets[index - 10]))
        for index in range(10, len(id_sets))
    ]
    second_differences: list[float] = []
    for middle in range(1, len(point_maps) - 1):
        common = (
            point_maps[middle - 1].keys()
            & point_maps[middle].keys()
            & point_maps[middle + 1].keys()
        )
        for feature_id in common:
            delta = (
                point_maps[middle + 1][feature_id]
                - 2.0 * point_maps[middle][feature_id]
                + point_maps[middle - 1][feature_id]
            )
            second_differences.append(float(np.linalg.norm(delta)))

    essential_ratios: list[float] = []
    skipped_essential = 0
    normalized_maps = [
        {
            int(feature_id): frame.normalized[index]
            for index, feature_id in enumerate(frame.ids)
            if bool(np.isfinite(frame.normalized[index]).all())
        }
        for frame in frames
    ]
    for index in range(1, len(frames)):
        common = sorted(normalized_maps[index - 1].keys() & normalized_maps[index].keys())
        if len(common) < ESSENTIAL_MIN_PAIRS:
            skipped_essential += 1
            continue
        left = np.asarray([normalized_maps[index - 1][value] for value in common])
        right = np.asarray([normalized_maps[index][value] for value in common])
        mask = np.asarray(solver(left, right, camera.focal_mean_px)).reshape(-1)
        if len(mask) != len(common):
            raise AuditInputError("Essential solver mask length mismatch")
        essential_ratios.append(float(np.mean(mask != 0)))

    episode_array = np.asarray(retired_lengths, dtype=np.float64)
    episode_le2_fraction = (
        float(np.mean(episode_array <= 2.0)) if len(episode_array) else None
    )
    return {
        "birth_rate_after_first": _quantiles(birth_rates),
        "episode_lifetime_frames": _quantiles(retired_lengths),
        "episode_fraction_le2": episode_le2_fraction,
        "lag10_common_id_count": _quantiles(lag10_counts),
        "deterministic_20px_thinning_count": {
            "priority": "age_desc_then_id_asc",
            "radius_px": THINNING_RADIUS_PX,
            "distribution": _quantiles(thinning_counts),
        },
        "occupied_8x6_cells": _quantiles(occupied_cells),
        "three_frame_pixel_second_difference": _quantiles(second_differences),
        "adjacent_essential_inlier_ratio": {
            "method": "USAC_MAGSAC",
            "threshold_px": ESSENTIAL_THRESHOLD_PX,
            "evaluated_pairs": len(essential_ratios),
            "skipped_fewer_than_8": skipped_essential,
            "distribution": _quantiles(essential_ratios),
        },
    }


def _gate(value: object, operator: str, threshold: float) -> dict[str, object]:
    if value is None:
        passed = False
    elif operator == "<=":
        passed = float(value) <= threshold
    elif operator == ">=":
        passed = float(value) >= threshold
    elif operator == "<":
        passed = float(value) < threshold
    elif operator == ">":
        passed = float(value) > threshold
    else:
        raise AssertionError(operator)
    return {
        "value": float(value) if value is not None else None,
        "operator": operator,
        "threshold": threshold,
        "pass": passed,
    }


def evaluate(
    reference: Sequence[FeatureFrame],
    candidate: Sequence[FeatureFrame],
    camera: CameraModel,
    nonfeature: Mapping[str, object],
    *,
    allow_prefix: bool = False,
    method_spec: AuditMethodSpec = SUPERPOINT_AUDIT_METHOD_SPEC,
    solver: EssentialSolver = magsac_essential_mask,
) -> dict[str, object]:
    method_spec.validate()
    contract = evaluate_contract(
        reference,
        candidate,
        camera,
        nonfeature,
        allow_prefix=allow_prefix,
        method_spec=method_spec,
    )
    metrics = compute_metrics(candidate, camera, solver=solver)
    birth = metrics["birth_rate_after_first"]
    episode = metrics["episode_lifetime_frames"]
    lag10 = metrics["lag10_common_id_count"]
    thinning = metrics["deterministic_20px_thinning_count"]["distribution"]
    grid = metrics["occupied_8x6_cells"]
    second = metrics["three_frame_pixel_second_difference"]
    essential = metrics["adjacent_essential_inlier_ratio"]["distribution"]
    gates = {
        "contract": {"pass": bool(contract["pass"])},
        "birth_rate_median": _gate(birth["median"], "<=", BIRTH_MEDIAN_MAX),
        "birth_rate_p90": _gate(birth["p90"], "<=", BIRTH_P90_MAX),
        "episode_lifetime_median": _gate(
            episode["median"], ">=", EPISODE_MEDIAN_MIN
        ),
        "episode_fraction_le2": _gate(
            metrics["episode_fraction_le2"], "<=", EPISODE_LE2_FRACTION_MAX
        ),
        "lag10_common_median": _gate(lag10["median"], ">=", LAG10_MEDIAN_MIN),
        "lag10_common_p10": _gate(lag10["p10"], ">=", LAG10_P10_MIN),
        "thin20_count_median": _gate(
            thinning["median"], ">=", THIN20_MEDIAN_MIN
        ),
        "thin20_count_p10": _gate(thinning["p10"], ">=", THIN20_P10_MIN),
        "occupied_grid_median": _gate(grid["median"], ">=", GRID_MEDIAN_MIN),
        "occupied_grid_p10": _gate(grid["p10"], ">=", GRID_P10_MIN),
        "second_difference_median": _gate(
            second["median"], "<", SECOND_DIFFERENCE_MEDIAN_MAX
        ),
        "essential_inlier_median": _gate(
            essential["median"], ">", ESSENTIAL_MEDIAN_MIN
        ),
        "essential_inlier_p10": _gate(essential["p10"], ">", ESSENTIAL_P10_MIN),
    }
    failed = [name for name, gate in gates.items() if not bool(gate["pass"])]
    passed = not failed
    return {
        "schema_version": method_spec.schema_version,
        "method": method_spec.identity(),
        "status": "PASS" if passed else "FAIL",
        "pass": passed,
        "failed_gates": failed,
        "observations_per_frame": dict(contract["observations_per_frame"]),
        "camera": {
            "model": camera.model,
            "fx": camera.fx,
            "fy": camera.fy,
            "cx": camera.cx,
            "cy": camera.cy,
            "distortion": list(camera.distortion),
            "width": camera.width,
            "height": camera.height,
            "focal_mean_px": camera.focal_mean_px,
        },
        "contract": contract,
        "metrics": metrics,
        "gates": gates,
    }


def canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _emit(payload: Mapping[str, object], output_json: Path | None) -> None:
    rendered = canonical_json(payload) + "\n"
    if output_json is not None:
        with output_json.open("x", encoding="ascii") as handle:
            handle.write(rendered)
    print(rendered, end="")


def _prepare_output(output_json: Path | None, inputs: Sequence[Path]) -> Path | None:
    if output_json is None:
        return None
    output = output_json.expanduser().resolve(strict=False)
    resolved_inputs = {path.expanduser().resolve(strict=False) for path in inputs}
    if output in resolved_inputs:
        raise AuditInputError("output-json must not alias an input")
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"refusing to overwrite output-json: {output}")
    return output


def build_parser(description: str | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description or __doc__)
    parser.add_argument(
        "--reference-bag",
        "--schedule-bag",
        dest="reference_bag",
        type=Path,
        required=True,
    )
    parser.add_argument("--candidate-bag", type=Path, required=True)
    parser.add_argument("--camera-yaml", type=Path, required=True)
    parser.add_argument("--feature-topic", default=DEFAULT_FEATURE_TOPIC)
    parser.add_argument("--allow-candidate-prefix", action="store_true")
    parser.add_argument("--output-json", type=Path)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    method_spec: AuditMethodSpec = SUPERPOINT_AUDIT_METHOD_SPEC,
    parser: argparse.ArgumentParser | None = None,
) -> int:
    method_spec.validate()
    args = (parser or build_parser()).parse_args(argv)
    reference_bag = args.reference_bag.expanduser().resolve(strict=False)
    candidate_bag = args.candidate_bag.expanduser().resolve(strict=False)
    camera_yaml = args.camera_yaml.expanduser().resolve(strict=False)
    method_identity = method_spec.identity()
    identity = {
        "reference_bag": str(reference_bag),
        "candidate_bag": str(candidate_bag),
        "camera_yaml": str(camera_yaml),
        "feature_topic": str(args.feature_topic),
        "allow_candidate_prefix": bool(args.allow_candidate_prefix),
        "method": method_identity,
    }
    audit_artifact = audit_artifact_metadata(method_spec)
    output_json: Path | None = None
    output_ready = False
    try:
        output_json = _prepare_output(
            args.output_json, (reference_bag, candidate_bag, camera_yaml)
        )
        output_ready = True
        require_usac_magsac()
        camera = load_camera_model(camera_yaml)
        reference = load_feature_frames(reference_bag, args.feature_topic)
        candidate = load_feature_frames(candidate_bag, args.feature_topic)
        cutoff_ns = (
            candidate[-1].record_stamp_ns if args.allow_candidate_prefix else None
        )
        nonfeature = compare_nonfeature(
            reference_bag,
            candidate_bag,
            args.feature_topic,
            cutoff_ns=cutoff_ns,
        )
        result = evaluate(
            reference,
            candidate,
            camera,
            nonfeature,
            allow_prefix=args.allow_candidate_prefix,
            method_spec=method_spec,
        )
        result["schema_version"] = method_spec.schema_version
        result["method"] = method_identity
        result["input"] = identity
        result["audit_artifact"] = audit_artifact
        _emit(result, output_json)
        return 0 if result["pass"] else 1
    except Exception as exc:
        error = {
            "schema_version": method_spec.schema_version,
            "status": "ERROR",
            "pass": False,
            "method": method_identity,
            "input": identity,
            "audit_artifact": audit_artifact,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
        try:
            _emit(error, output_json if output_ready else None)
        except Exception as output_exc:
            fallback = dict(error)
            fallback["error"] = {
                "type": type(output_exc).__name__,
                "message": str(output_exc),
            }
            print(canonical_json(fallback))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
