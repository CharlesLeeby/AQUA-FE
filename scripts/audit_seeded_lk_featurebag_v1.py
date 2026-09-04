#!/usr/bin/env python3
"""Read-only scientific gate for a seeded-LK feature-bag adaptation.

The source and candidate bags must have the same feature-frame contract.  Only
pixel coordinates, normalized coordinates, and velocities may differ.  The
candidate then has to pass two fixed, prespecified temporal-geometry gates:

* median three-frame same-ID pixel second difference < 0.3 px;
* median adjacent-frame Essential-MAGSAC inlier ratio > 0.90 at 0.3 px.

The CLI emits exactly one canonical JSON document.  Exit status is 0 for PASS,
1 for a scientific/contract FAIL, and 2 for an input, capability, or runtime
ERROR.  It never starts ROS and never writes to either input bag.
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


SCHEMA_VERSION = "aqua-fe-seeded-lk-featurebag-audit-v1"
DEFAULT_FEATURE_TOPIC = "/feature_tracker/feature"
SECOND_DIFFERENCE_GATE_PX = 0.3
ESSENTIAL_PIXEL_THRESHOLD = 0.3
ESSENTIAL_INLIER_RATIO_GATE = 0.90
ESSENTIAL_PROBABILITY = 0.999
ESSENTIAL_MAX_ITERS = 200
ESSENTIAL_MIN_CORRESPONDENCES = 8
RANSAC_SEED = 0
MAX_REPORTED_VIOLATIONS = 20
NORMALIZED_FROM_PIXEL_MAX_ERROR = 1e-6
VELOCITY_ABS_TOLERANCE = 1e-5

ALLOWED_CHANGED_CHANNELS = frozenset(
    {"p_u", "p_v", "velocity_x", "velocity_y"}
)
REQUIRED_CHANNELS = frozenset({"id"}) | ALLOWED_CHANGED_CHANNELS


class AuditInputError(RuntimeError):
    """A malformed input or unavailable runtime capability."""


@dataclass(frozen=True)
class CameraModel:
    fx: float
    fy: float
    cx: float
    cy: float
    distortion: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0)

    @property
    def focal_mean_px(self) -> float:
        return 0.5 * (float(self.fx) + float(self.fy))

    @property
    def camera_matrix(self) -> np.ndarray:
        return np.asarray(
            [
                [float(self.fx), 0.0, float(self.cx)],
                [0.0, float(self.fy), float(self.cy)],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )

    @property
    def distortion_vector(self) -> np.ndarray:
        return np.asarray(self.distortion, dtype=np.float64)


@dataclass(frozen=True)
class FeatureFrame:
    """Decoded feature message with both mutable and protected fields."""

    index: int
    record_stamp_ns: int
    header_stamp_ns: int
    header_seq: int
    header_frame_id: str
    ids: np.ndarray
    pixel_points: np.ndarray
    normalized_points: np.ndarray
    point_z: np.ndarray
    velocities: np.ndarray
    channel_names: tuple[str, ...]
    preserved_channels: Mapping[str, np.ndarray]


EssentialSolver = Callable[[np.ndarray, np.ndarray, float], np.ndarray]


def require_usac_magsac_available() -> None:
    """Hard error instead of silently falling back to classic RANSAC."""

    if getattr(cv2, "USAC_MAGSAC", None) is None:
        raise AuditInputError(
            "cv2.USAC_MAGSAC is required; use an isolated OpenCV build "
            "with USAC support"
        )


def _validate_camera(camera: CameraModel) -> None:
    values = (camera.fx, camera.fy, camera.cx, camera.cy, *camera.distortion)
    if not all(math.isfinite(float(value)) for value in values):
        raise AuditInputError("camera K and D parameters must be finite")
    if float(camera.fx) <= 0.0 or float(camera.fy) <= 0.0:
        raise AuditInputError("camera focal lengths must be positive")
    if len(camera.distortion) not in {4, 5, 8, 12, 14}:
        raise AuditInputError(
            "camera distortion must contain 4, 5, 8, 12, or 14 coefficients"
        )


def _node_sequence(node: object) -> list[float] | None:
    if node is None or node.empty():
        return None
    if node.isSeq():
        return [float(node.at(index).real()) for index in range(int(node.size()))]
    if node.isMap():
        data = node.getNode("data")
        if not data.empty() and data.isSeq():
            return [
                float(data.at(index).real()) for index in range(int(data.size()))
            ]
    try:
        matrix = node.mat()
    except Exception:
        matrix = None
    if matrix is None:
        return None
    return [float(value) for value in np.asarray(matrix).reshape(-1)]


def _projection_from_node(container: object) -> tuple[float, float, float, float] | None:
    projection = container.getNode("projection_parameters")
    if not projection.empty() and projection.isMap():
        nodes = [projection.getNode(name) for name in ("fx", "fy", "cx", "cy")]
        if all(not node.empty() for node in nodes):
            return tuple(float(node.real()) for node in nodes)  # type: ignore[return-value]
    intrinsics = _node_sequence(container.getNode("intrinsics"))
    if intrinsics is not None and len(intrinsics) == 4:
        return tuple(intrinsics)  # type: ignore[return-value]
    camera_matrix = _node_sequence(container.getNode("camera_matrix"))
    if camera_matrix is None:
        camera_matrix = _node_sequence(container.getNode("K"))
    if camera_matrix is not None and len(camera_matrix) == 9:
        return (
            camera_matrix[0],
            camera_matrix[4],
            camera_matrix[2],
            camera_matrix[5],
        )
    return None


def _distortion_from_node(container: object) -> tuple[float, ...] | None:
    distortion = container.getNode("distortion_parameters")
    if not distortion.empty() and distortion.isMap():
        required_names = ("k1", "k2", "p1", "p2")
        required = [distortion.getNode(name) for name in required_names]
        if all(not node.empty() for node in required):
            values = [float(node.real()) for node in required]
            optional_names = (
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
            )
            for name in optional_names:
                node = distortion.getNode(name)
                if node.empty():
                    break
                values.append(float(node.real()))
            return tuple(values)
    for name in ("distortion_coeffs", "distortion_coefficients", "D"):
        values = _node_sequence(container.getNode(name))
        if values is not None:
            return tuple(values)
    return None


def load_camera_model(path: Path) -> CameraModel:
    """Load fixed pinhole K and D from either the YAML root or ``cam0``."""

    if not path.is_file():
        raise FileNotFoundError(path)
    storage = cv2.FileStorage(str(path), cv2.FILE_STORAGE_READ)
    if not storage.isOpened():
        raise AuditInputError(f"could not open camera YAML: {path}")
    try:
        root = storage.root()
        cam0 = storage.getNode("cam0")
        containers = [cam0, root] if not cam0.empty() else [root]
        projection = None
        distortion = None
        for container in containers:
            projection = _projection_from_node(container)
            distortion = _distortion_from_node(container)
            if projection is not None and distortion is not None:
                break
    finally:
        storage.release()
    if projection is None:
        raise AuditInputError(
            f"camera YAML has no supported K at root or cam0: {path}"
        )
    if distortion is None:
        raise AuditInputError(
            f"camera YAML has no supported D at root or cam0: {path}"
        )
    camera = CameraModel(*projection, distortion=distortion)
    _validate_camera(camera)
    return camera


def _stamp_to_nsec(stamp: object, *, label: str) -> int:
    method = getattr(stamp, "to_nsec", None)
    if callable(method):
        return int(method())
    secs = getattr(stamp, "secs", None)
    nsecs = getattr(stamp, "nsecs", None)
    if secs is None or nsecs is None:
        raise AuditInputError(f"{label} has no exact nanosecond representation")
    return int(secs) * 1_000_000_000 + int(nsecs)


def load_feature_frames(
    bag_path: Path, feature_topic: str = DEFAULT_FEATURE_TOPIC
) -> list[FeatureFrame]:
    """Decode feature PointCloud messages without starting a ROS graph."""

    if not bag_path.is_file():
        raise FileNotFoundError(bag_path)
    try:
        import rosbag  # type: ignore
    except ModuleNotFoundError as exc:
        raise AuditInputError("rosbag is required for feature-bag input") from exc

    frames: list[FeatureFrame] = []
    with rosbag.Bag(str(bag_path), "r") as bag:
        for _, message, record_stamp in bag.read_messages(topics=[feature_topic]):
            frame_index = len(frames)
            points = list(getattr(message, "points", ()))
            point_count = len(points)
            channels = list(getattr(message, "channels", ()))
            names = tuple(str(channel.name) for channel in channels)
            if len(names) != len(set(names)):
                raise AuditInputError(
                    f"frame {frame_index}: duplicate channel names"
                )
            missing = sorted(REQUIRED_CHANNELS - set(names))
            if missing:
                raise AuditInputError(
                    f"frame {frame_index}: missing required channels {missing}"
                )
            channel_values: dict[str, np.ndarray] = {}
            for channel in channels:
                values = np.asarray(channel.values, dtype=np.float32)
                if values.shape != (point_count,):
                    raise AuditInputError(
                        f"frame {frame_index}: channel {channel.name!r} length "
                        f"{len(values)} != point count {point_count}"
                    )
                if not np.isfinite(values).all():
                    raise AuditInputError(
                        f"frame {frame_index}: channel {channel.name!r} "
                        "contains non-finite values"
                    )
                channel_values[str(channel.name)] = values

            raw_ids = channel_values["id"].astype(np.float64)
            rounded_ids = np.rint(raw_ids)
            if not np.array_equal(raw_ids, rounded_ids):
                raise AuditInputError(
                    f"frame {frame_index}: IDs must be exactly integer-valued"
                )
            ids = rounded_ids.astype(np.int64)
            if len(np.unique(ids)) != len(ids):
                raise AuditInputError(
                    f"frame {frame_index}: duplicate feature ID within frame"
                )

            normalized = np.asarray(
                [(point.x, point.y) for point in points], dtype=np.float32
            ).reshape((-1, 2))
            point_z = np.asarray([point.z for point in points], dtype=np.float32)
            pixel = np.column_stack(
                (channel_values["p_u"], channel_values["p_v"])
            ).astype(np.float32, copy=False)
            velocity = np.column_stack(
                (channel_values["velocity_x"], channel_values["velocity_y"])
            ).astype(np.float32, copy=False)
            if not (
                np.isfinite(normalized).all()
                and np.isfinite(point_z).all()
                and np.isfinite(pixel).all()
                and np.isfinite(velocity).all()
            ):
                raise AuditInputError(
                    f"frame {frame_index}: feature geometry contains non-finite values"
                )

            header = getattr(message, "header", None)
            if header is None:
                raise AuditInputError(f"frame {frame_index}: missing message header")
            preserved = {
                name: values.copy()
                for name, values in channel_values.items()
                if name not in ALLOWED_CHANGED_CHANNELS
            }
            frames.append(
                FeatureFrame(
                    index=frame_index,
                    record_stamp_ns=_stamp_to_nsec(
                        record_stamp, label=f"frame {frame_index} record stamp"
                    ),
                    header_stamp_ns=_stamp_to_nsec(
                        header.stamp, label=f"frame {frame_index} header stamp"
                    ),
                    header_seq=int(header.seq),
                    header_frame_id=str(header.frame_id),
                    ids=ids,
                    pixel_points=pixel,
                    normalized_points=normalized,
                    point_z=point_z,
                    velocities=velocity,
                    channel_names=names,
                    preserved_channels=preserved,
                )
            )
    if not frames:
        raise AuditInputError(f"no messages found on feature topic {feature_topic}")
    return frames


def _serialized_message(message: object) -> bytes:
    buffer = io.BytesIO()
    serialize = getattr(message, "serialize", None)
    if not callable(serialize):
        raise AuditInputError(
            f"message type {type(message).__name__} has no serialize method"
        )
    serialize(buffer)
    return buffer.getvalue()


def nonfeature_content_digest(
    bag_path: Path,
    feature_topic: str = DEFAULT_FEATURE_TOPIC,
    *,
    record_cutoff_ns: int | None = None,
) -> dict[str, object]:
    """Digest ordered (topic, record stamp, serialized payload) tuples."""

    if not bag_path.is_file():
        raise FileNotFoundError(bag_path)
    try:
        import rosbag  # type: ignore
    except ModuleNotFoundError as exc:
        raise AuditInputError("rosbag is required for feature-bag input") from exc

    digest = hashlib.sha256()
    topic_state: dict[str, dict[str, object]] = {}
    selected_count = 0
    after_cutoff_count = 0
    with rosbag.Bag(str(bag_path), "r") as bag:
        for topic, message, record_stamp in bag.read_messages():
            topic = str(topic)
            if topic == feature_topic:
                continue
            stamp_ns = _stamp_to_nsec(record_stamp, label=f"{topic} record stamp")
            if record_cutoff_ns is not None and stamp_ns > record_cutoff_ns:
                after_cutoff_count += 1
                continue
            payload = _serialized_message(message)
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
            selected_count += 1
    return {
        "record_cutoff_ns": (
            int(record_cutoff_ns) if record_cutoff_ns is not None else None
        ),
        "selected_message_count": selected_count,
        "messages_after_cutoff": after_cutoff_count,
        "sha256": digest.hexdigest(),
        "topics": {
            topic: {
                "count": int(state["count"]),
                "sha256": state["sha256"].hexdigest(),
            }
            for topic, state in sorted(topic_state.items())
        },
    }


def compare_nonfeature_topics(
    source_bag: Path,
    candidate_bag: Path,
    feature_topic: str = DEFAULT_FEATURE_TOPIC,
    *,
    candidate_prefix_cutoff_ns: int | None = None,
) -> dict[str, object]:
    """Compare all non-feature content, optionally as a strict bag prefix."""

    source = nonfeature_content_digest(
        source_bag, feature_topic, record_cutoff_ns=candidate_prefix_cutoff_ns
    )
    candidate = nonfeature_content_digest(
        candidate_bag, feature_topic, record_cutoff_ns=candidate_prefix_cutoff_ns
    )
    violation_counts: dict[str, int] = {}
    if (
        source["selected_message_count"] != candidate["selected_message_count"]
        or source["sha256"] != candidate["sha256"]
    ):
        violation_counts["NONFEATURE_CONTENT_CHANGED"] = 1
    if (
        candidate_prefix_cutoff_ns is not None
        and int(candidate["messages_after_cutoff"]) != 0
    ):
        violation_counts["CANDIDATE_NONFEATURE_AFTER_PREFIX_CUTOFF"] = int(
            candidate["messages_after_cutoff"]
        )
    return {
        "pass": not violation_counts,
        "mode": (
            "candidate_record_prefix"
            if candidate_prefix_cutoff_ns is not None
            else "full_exact"
        ),
        "candidate_prefix_cutoff_ns": (
            int(candidate_prefix_cutoff_ns)
            if candidate_prefix_cutoff_ns is not None
            else None
        ),
        "tuple_contract": "ordered(topic,record_stamp_ns,serialized_payload)",
        "source": source,
        "candidate": candidate,
        "violation_counts": violation_counts,
    }


def _same_array(left: np.ndarray, right: np.ndarray) -> bool:
    return left.shape == right.shape and bool(np.array_equal(left, right))


def compare_immutable_contract(
    source: Sequence[FeatureFrame],
    candidate: Sequence[FeatureFrame],
    *,
    allow_candidate_prefix: bool = False,
) -> dict[str, object]:
    """Verify feature structure, metadata, and all protected fields."""

    violation_counts: dict[str, int] = {}
    first_violations: list[dict[str, object]] = []

    def record(kind: str, frame_index: int | None = None) -> None:
        violation_counts[kind] = violation_counts.get(kind, 0) + 1
        if len(first_violations) < MAX_REPORTED_VIOLATIONS:
            item: dict[str, object] = {"kind": kind}
            if frame_index is not None:
                item["frame_index"] = int(frame_index)
            first_violations.append(item)

    if allow_candidate_prefix:
        if len(candidate) > len(source):
            record("CANDIDATE_LONGER_THAN_SOURCE_PREFIX")
        comparison_source = source[: len(candidate)]
    else:
        if len(source) != len(candidate):
            record("FRAME_COUNT_CHANGED")
        comparison_source = source

    for frame in source:
        if not bool(np.all(frame.point_z == np.float32(1.0))):
            record("SOURCE_POINT_Z_NOT_EXACT_ONE", frame.index)
    for frame in candidate:
        if not bool(np.all(frame.point_z == np.float32(1.0))):
            record("CANDIDATE_POINT_Z_NOT_EXACT_ONE", frame.index)

    for index, (left, right) in enumerate(zip(comparison_source, candidate)):
        if left.record_stamp_ns != right.record_stamp_ns:
            record("RECORD_STAMP_CHANGED", index)
        if left.header_stamp_ns != right.header_stamp_ns:
            record("HEADER_STAMP_CHANGED", index)
        if (
            left.header_seq != right.header_seq
            or left.header_frame_id != right.header_frame_id
        ):
            record("HEADER_METADATA_CHANGED", index)
        if len(left.ids) != len(right.ids):
            record("OBSERVATION_COUNT_CHANGED", index)
        if not _same_array(left.ids, right.ids):
            record("ORDERED_IDS_CHANGED", index)
        if left.channel_names != right.channel_names:
            record("CHANNEL_SCHEMA_CHANGED", index)
        if set(left.preserved_channels) != set(right.preserved_channels):
            record("PRESERVED_CHANNEL_SET_CHANGED", index)
        else:
            for name in sorted(left.preserved_channels):
                if not _same_array(
                    left.preserved_channels[name], right.preserved_channels[name]
                ):
                    record(f"PRESERVED_CHANNEL_CHANGED:{name}", index)

    source_occurrence: dict[int, list[int]] = {}
    candidate_occurrence: dict[int, list[int]] = {}
    for frames, output in (
        (comparison_source, source_occurrence),
        (candidate, candidate_occurrence),
    ):
        for frame_index, frame in enumerate(frames):
            for feature_id in frame.ids:
                output.setdefault(int(feature_id), []).append(frame_index)
    if source_occurrence != candidate_occurrence:
        record("ID_OCCURRENCE_CHANGED")

    passed = not violation_counts
    return {
        "pass": passed,
        "mode": "candidate_prefix" if allow_candidate_prefix else "full_exact",
        "allowed_changed_fields": [
            "normalized_point_x",
            "normalized_point_y",
            "p_u",
            "p_v",
            "velocity_x",
            "velocity_y",
        ],
        "source_frame_count": len(source),
        "candidate_frame_count": len(candidate),
        "compared_source_frame_count": len(comparison_source),
        "source_observation_count": int(sum(len(frame.ids) for frame in source)),
        "candidate_observation_count": int(
            sum(len(frame.ids) for frame in candidate)
        ),
        "violation_counts": violation_counts,
        "first_violations": first_violations,
        "first_violations_truncated": sum(violation_counts.values())
        > len(first_violations),
    }


def candidate_measurement_contract(
    candidate: Sequence[FeatureFrame], camera: CameraModel
) -> dict[str, object]:
    """Independently verify pixel->normalized and published-dt velocity fields."""

    _validate_camera(camera)
    violation_counts: dict[str, int] = {}
    first_violations: list[dict[str, object]] = []
    normalized_errors: list[float] = []
    velocity_errors: list[float] = []

    def record(kind: str, frame_index: int, max_error: float | None = None) -> None:
        violation_counts[kind] = violation_counts.get(kind, 0) + 1
        if len(first_violations) < MAX_REPORTED_VIOLATIONS:
            item: dict[str, object] = {
                "kind": kind,
                "frame_index": int(frame_index),
            }
            if max_error is not None:
                item["max_error"] = float(max_error)
            first_violations.append(item)

    previous: FeatureFrame | None = None
    for frame_index, frame in enumerate(candidate):
        count = len(frame.ids)
        if count:
            expected_normalized = cv2.undistortPoints(
                np.asarray(frame.pixel_points, dtype=np.float64).reshape(-1, 1, 2),
                camera.camera_matrix,
                camera.distortion_vector,
            ).reshape(-1, 2)
            frame_normalized_error = np.linalg.norm(
                expected_normalized
                - np.asarray(frame.normalized_points, dtype=np.float64),
                axis=1,
            )
            normalized_errors.extend(float(value) for value in frame_normalized_error)
            max_normalized_error = float(np.max(frame_normalized_error))
            if max_normalized_error > NORMALIZED_FROM_PIXEL_MAX_ERROR:
                record(
                    "CANDIDATE_NORMALIZED_FROM_PIXEL_MISMATCH",
                    frame_index,
                    max_normalized_error,
                )

        expected_velocity = np.zeros((count, 2), dtype=np.float64)
        if previous is not None:
            dt = (frame.header_stamp_ns - previous.header_stamp_ns) * 1e-9
            if not math.isfinite(float(dt)) or dt <= 0.0:
                record("NON_POSITIVE_PUBLISHED_DT", frame_index)
            else:
                previous_by_id = {
                    int(feature_id): index
                    for index, feature_id in enumerate(previous.ids)
                }
                for current_index, feature_id in enumerate(frame.ids):
                    previous_index = previous_by_id.get(int(feature_id))
                    if previous_index is None:
                        continue
                    expected_velocity[current_index] = (
                        np.asarray(frame.normalized_points[current_index], dtype=np.float64)
                        - np.asarray(
                            previous.normalized_points[previous_index], dtype=np.float64
                        )
                    ) / float(dt)
        if count:
            frame_velocity_error = np.linalg.norm(
                np.asarray(frame.velocities, dtype=np.float64) - expected_velocity,
                axis=1,
            )
            velocity_errors.extend(float(value) for value in frame_velocity_error)
            max_velocity_error = float(np.max(frame_velocity_error))
            if max_velocity_error > VELOCITY_ABS_TOLERANCE:
                record(
                    "CANDIDATE_VELOCITY_MISMATCH",
                    frame_index,
                    max_velocity_error,
                )
        previous = frame

    return {
        "pass": not violation_counts,
        "normalized_from_pixel": {
            "method": "cv2.undistortPoints",
            "comparison": "max_euclidean_error_less_than_or_equal",
            "tolerance": NORMALIZED_FROM_PIXEL_MAX_ERROR,
            "error_distribution": _quantiles(normalized_errors),
        },
        "velocity_from_adjacent_published": {
            "birth_policy": "exact_zero",
            "dt_source": "adjacent_feature_header_stamp",
            "comparison": "max_euclidean_error_less_than_or_equal",
            "absolute_tolerance": VELOCITY_ABS_TOLERANCE,
            "error_distribution": _quantiles(velocity_errors),
        },
        "violation_counts": violation_counts,
        "first_violations": first_violations,
        "first_violations_truncated": sum(violation_counts.values())
        > len(first_violations),
    }


def _quantiles(values: Sequence[float]) -> dict[str, object]:
    array = np.asarray(values, dtype=np.float64)
    if len(array) == 0:
        return {
            "count": 0,
            "p10": None,
            "median": None,
            "p90": None,
            "p95": None,
            "p99": None,
        }
    return {
        "count": int(len(array)),
        "p10": float(np.percentile(array, 10)),
        "median": float(np.median(array)),
        "p90": float(np.percentile(array, 90)),
        "p95": float(np.percentile(array, 95)),
        "p99": float(np.percentile(array, 99)),
    }


def three_frame_second_difference(
    frames: Sequence[FeatureFrame],
) -> dict[str, object]:
    """Pooled pixel second difference for IDs in three adjacent frames."""

    point_maps = [
        {
            int(feature_id): frame.pixel_points[index]
            for index, feature_id in enumerate(frame.ids)
        }
        for frame in frames
    ]
    values: list[float] = []
    evaluated_triplets = 0
    for middle in range(1, len(frames) - 1):
        common = sorted(
            point_maps[middle - 1].keys()
            & point_maps[middle].keys()
            & point_maps[middle + 1].keys()
        )
        if not common:
            continue
        evaluated_triplets += 1
        for feature_id in common:
            delta = (
                point_maps[middle + 1][feature_id]
                - 2.0 * point_maps[middle][feature_id]
                + point_maps[middle - 1][feature_id]
            )
            values.append(float(np.linalg.norm(delta)))
    return {
        "units": "pixel",
        "evaluated_frame_triplets": evaluated_triplets,
        "distribution": _quantiles(values),
    }


def magsac_essential_inlier_mask(
    points0_normalized: np.ndarray,
    points1_normalized: np.ndarray,
    focal_mean_px: float,
) -> np.ndarray:
    """Return the exact 0.3 px Essential-USAC_MAGSAC inlier mask."""

    require_usac_magsac_available()
    if not math.isfinite(float(focal_mean_px)) or float(focal_mean_px) <= 0.0:
        raise AuditInputError("focal_mean_px must be finite and positive")
    left = np.ascontiguousarray(points0_normalized, dtype=np.float32).reshape(-1, 2)
    right = np.ascontiguousarray(points1_normalized, dtype=np.float32).reshape(-1, 2)
    if left.shape != right.shape:
        raise AuditInputError("Essential point arrays must have matching shape")
    if len(left) < ESSENTIAL_MIN_CORRESPONDENCES:
        raise AuditInputError("Essential solver requires at least eight pairs")
    cv2.setRNGSeed(RANSAC_SEED)
    try:
        essential, mask = cv2.findEssentialMat(
            left,
            right,
            np.eye(3, dtype=np.float64),
            method=cv2.USAC_MAGSAC,
            prob=ESSENTIAL_PROBABILITY,
            threshold=ESSENTIAL_PIXEL_THRESHOLD / float(focal_mean_px),
            maxIters=ESSENTIAL_MAX_ITERS,
        )
    except Exception as exc:
        raise AuditInputError(
            f"findEssentialMat failed: {type(exc).__name__}: {exc}"
        ) from exc
    if essential is None or mask is None:
        raise AuditInputError("findEssentialMat returned no model or mask")
    flat = np.asarray(mask).reshape(-1)
    if len(flat) != len(left):
        raise AuditInputError(
            f"Essential mask length {len(flat)} != correspondence count {len(left)}"
        )
    return flat != 0


def adjacent_essential_inlier_ratios(
    frames: Sequence[FeatureFrame],
    focal_mean_px: float,
    *,
    solver: EssentialSolver = magsac_essential_inlier_mask,
) -> dict[str, object]:
    """Evaluate every adjacent pair with at least eight common IDs."""

    point_maps = [
        {
            int(feature_id): frame.normalized_points[index]
            for index, feature_id in enumerate(frame.ids)
        }
        for frame in frames
    ]
    ratios: list[float] = []
    common_counts: list[float] = []
    skipped = 0
    for left_index in range(len(frames) - 1):
        common = sorted(
            point_maps[left_index].keys() & point_maps[left_index + 1].keys()
        )
        if len(common) < ESSENTIAL_MIN_CORRESPONDENCES:
            skipped += 1
            continue
        left = np.asarray(
            [point_maps[left_index][feature_id] for feature_id in common],
            dtype=np.float32,
        )
        right = np.asarray(
            [point_maps[left_index + 1][feature_id] for feature_id in common],
            dtype=np.float32,
        )
        mask = np.asarray(solver(left, right, focal_mean_px), dtype=bool).reshape(-1)
        if len(mask) != len(common):
            raise AuditInputError(
                f"Essential solver mask length {len(mask)} != {len(common)}"
            )
        ratios.append(float(np.mean(mask)))
        common_counts.append(float(len(common)))
    return {
        "pixel_threshold": ESSENTIAL_PIXEL_THRESHOLD,
        "method": "USAC_MAGSAC",
        "evaluated_adjacent_pairs": len(ratios),
        "skipped_fewer_than_8": skipped,
        "inlier_ratio_distribution": _quantiles(ratios),
        "common_id_count_distribution": _quantiles(common_counts),
    }


def evaluate_feature_frames(
    source: Sequence[FeatureFrame],
    candidate: Sequence[FeatureFrame],
    camera: CameraModel,
    *,
    solver: EssentialSolver = magsac_essential_inlier_mask,
    allow_candidate_prefix: bool = False,
    nonfeature_contract: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Pure comparison and fixed scientific gate over decoded frames."""

    _validate_camera(camera)
    structural_contract = compare_immutable_contract(
        source,
        candidate,
        allow_candidate_prefix=allow_candidate_prefix,
    )
    measurement_contract = candidate_measurement_contract(candidate, camera)
    nonfeature_pass = (
        True
        if nonfeature_contract is None
        else bool(nonfeature_contract.get("pass", False))
    )
    contract = dict(structural_contract)
    contract["candidate_measurements"] = measurement_contract
    contract["non_feature_topics"] = (
        dict(nonfeature_contract) if nonfeature_contract is not None else None
    )
    contract["pass"] = bool(structural_contract["pass"]) and bool(
        measurement_contract["pass"]
    ) and nonfeature_pass
    second = three_frame_second_difference(candidate)
    essential = adjacent_essential_inlier_ratios(
        candidate, camera.focal_mean_px, solver=solver
    )
    second_median = second["distribution"]["median"]  # type: ignore[index]
    essential_median = essential["inlier_ratio_distribution"]["median"]  # type: ignore[index]
    second_pass = (
        second_median is not None
        and float(second_median) < SECOND_DIFFERENCE_GATE_PX
    )
    essential_pass = (
        essential_median is not None
        and float(essential_median) > ESSENTIAL_INLIER_RATIO_GATE
    )
    reasons: list[str] = []
    if not structural_contract["pass"]:
        reasons.append("IMMUTABLE_CONTRACT_CHANGED")
    if not measurement_contract["pass"]:
        reasons.append("CANDIDATE_MEASUREMENT_CONTRACT_INVALID")
    if not nonfeature_pass:
        reasons.append("NON_FEATURE_TOPICS_CHANGED")
    if second_median is None:
        reasons.append("NO_THREE_FRAME_COMMON_IDS")
    elif not second_pass:
        reasons.append("SECOND_DIFFERENCE_MEDIAN_NOT_BELOW_0.3PX")
    if essential_median is None:
        reasons.append("NO_ADJACENT_ESSENTIAL_PAIRS")
    elif not essential_pass:
        reasons.append("ESSENTIAL_INLIER_MEDIAN_NOT_ABOVE_0.90")
    passed = not reasons
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "pass": passed,
        "reasons": reasons,
        "fixed_gate": {
            "second_difference": {
                "comparison": "strict_less_than",
                "threshold_px": SECOND_DIFFERENCE_GATE_PX,
                "pass": second_pass,
            },
            "adjacent_essential": {
                "comparison": "strict_greater_than",
                "inlier_ratio_threshold": ESSENTIAL_INLIER_RATIO_GATE,
                "pixel_threshold": ESSENTIAL_PIXEL_THRESHOLD,
                "method": "USAC_MAGSAC",
                "pass": essential_pass,
            },
        },
        "camera": {
            "fx": float(camera.fx),
            "fy": float(camera.fy),
            "cx": float(camera.cx),
            "cy": float(camera.cy),
            "distortion": [float(value) for value in camera.distortion],
            "focal_mean_px": float(camera.focal_mean_px),
        },
        "contract": contract,
        "metrics": {
            "three_frame_second_difference": second,
            "adjacent_essential": essential,
        },
    }


def canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit a coordinate-only seeded-LK feature-bag adaptation."
    )
    parser.add_argument("--source-bag", type=Path, required=True)
    parser.add_argument("--candidate-bag", type=Path, required=True)
    parser.add_argument("--camera-yaml", type=Path, required=True)
    parser.add_argument("--feature-topic", default=DEFAULT_FEATURE_TOPIC)
    parser.add_argument(
        "--allow-candidate-prefix",
        action="store_true",
        help=(
            "Allow candidate feature frames to be an exact source prefix and "
            "compare non-feature content through the candidate's last feature "
            "record stamp."
        ),
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        help="Optionally write the same canonical JSON emitted on stdout.",
    )
    return parser


def _emit(payload: dict[str, object], output_json: Path | None) -> None:
    rendered = canonical_json(payload) + "\n"
    if output_json is not None:
        with output_json.open("x", encoding="ascii") as handle:
            handle.write(rendered)
    print(rendered, end="")


def _prepare_output_json(
    output_json: Path | None, input_paths: Sequence[Path]
) -> Path | None:
    if output_json is None:
        return None
    resolved = output_json.expanduser().resolve(strict=False)
    resolved_inputs = {
        path.expanduser().resolve(strict=False) for path in input_paths
    }
    if resolved in resolved_inputs:
        raise AuditInputError("output-json must not alias any input")
    if resolved.exists() or resolved.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing output-json: {resolved}")
    return resolved


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    source_bag = args.source_bag.expanduser().resolve(strict=False)
    candidate_bag = args.candidate_bag.expanduser().resolve(strict=False)
    camera_yaml = args.camera_yaml.expanduser().resolve(strict=False)
    input_identity = {
        "source_bag": str(source_bag),
        "candidate_bag": str(candidate_bag),
        "camera_yaml": str(camera_yaml),
        "feature_topic": str(args.feature_topic),
        "allow_candidate_prefix": bool(args.allow_candidate_prefix),
    }
    output_json: Path | None = None
    output_preflight_passed = False
    try:
        output_json = _prepare_output_json(
            args.output_json,
            (source_bag, candidate_bag, camera_yaml),
        )
        output_preflight_passed = True
        require_usac_magsac_available()
        camera = load_camera_model(camera_yaml)
        source = load_feature_frames(source_bag, args.feature_topic)
        candidate = load_feature_frames(candidate_bag, args.feature_topic)
        prefix_cutoff_ns = (
            candidate[-1].record_stamp_ns if args.allow_candidate_prefix else None
        )
        nonfeature_contract = compare_nonfeature_topics(
            source_bag,
            candidate_bag,
            args.feature_topic,
            candidate_prefix_cutoff_ns=prefix_cutoff_ns,
        )
        result = evaluate_feature_frames(
            source,
            candidate,
            camera,
            allow_candidate_prefix=args.allow_candidate_prefix,
            nonfeature_contract=nonfeature_contract,
        )
        result["input"] = input_identity
        _emit(result, output_json)
    except Exception as exc:
        error = {
            "schema_version": SCHEMA_VERSION,
            "status": "ERROR",
            "pass": False,
            "input": input_identity,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
        try:
            _emit(error, output_json if output_preflight_passed else None)
        except Exception as output_exc:
            print(
                canonical_json(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "status": "ERROR",
                        "pass": False,
                        "input": input_identity,
                        "error": {
                            "type": type(output_exc).__name__,
                            "message": str(output_exc),
                        },
                    }
                )
            )
        return 2
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
