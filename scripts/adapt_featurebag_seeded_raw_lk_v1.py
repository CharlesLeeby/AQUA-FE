#!/usr/bin/env python3
"""Build an occurrence-preserving, SP/LG-seeded raw-frame LK feature bag.

This is a standalone offline coordinate adapter.  It does not run or modify the
learned matcher, persistent-ID tracker, exporter, or VINS.  The source feature
messages define the exact per-frame occurrence set, order, IDs, qualities, and
provenance.  Only pixel observations and the normalized/velocity fields derived
from those pixels are replaced.

The LK contract intentionally mirrors the preregistered B diagnostic probe:

* published frames are exactly two raw image frames apart;
* the previous adapted published point is the start point;
* the midpoint initial guess is the mean of the start and current learned point;
* start -> middle -> end and end -> middle -> start use initial-flow-seeded LK;
* all four status flags and a two-step forward/backward error <= 1 px are needed;
* otherwise the current learned observation is retained (occurrence-preserving
  fail-open).

There are deliberately no NCC, border, preprocessing, spatial-NMS, or per-window
tuning controls in this version.
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import asdict, dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import struct
from typing import Sequence

import cv2
import numpy as np
import rosbag
import yaml


FEATURE_TOPIC_DEFAULT = "/feature_tracker/feature"
PUBLISHED_RAW_STRIDE = 2
LK_WIN_SIZE = (21, 21)
LK_MAX_LEVEL = 3
LK_CRITERIA_COUNT = 30
LK_CRITERIA_EPS = 0.01
LK_MIN_EIG_THRESHOLD = 1e-4
LK_FB_MAX_PX = 1.0

REQUIRED_CHANNELS = (
    "id",
    "camera_id",
    "p_u",
    "p_v",
    "velocity_x",
    "velocity_y",
)


@dataclass(frozen=True)
class FeatureFrame:
    header_stamp_ns: int
    record_stamp_ns: int
    ids: np.ndarray
    pixels: np.ndarray


@dataclass(frozen=True)
class RawFrame:
    header_stamp_ns: int
    image: np.ndarray


@dataclass(frozen=True)
class FrameCarrierDiagnostics:
    frame_index: int
    header_stamp_ns: int
    observation_count: int
    birth_count: int
    continuation_count: int
    accepted_count: int
    fallback_count: int
    removed_count: int
    accepted_fraction: float
    fb_median_px: float
    fb_p95_px: float
    correction_median_px: float
    correction_p95_px: float


def _percentile(values: np.ndarray, percentile: float) -> float:
    values = np.asarray(values, dtype=np.float64).reshape(-1)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return float("nan")
    return float(np.percentile(values, percentile))


def _message_bytes(message) -> bytes:
    buffer = io.BytesIO()
    message.serialize(buffer)
    return buffer.getvalue()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_metadata(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "size_bytes": int(path.stat().st_size),
        "sha256": _sha256_file(path),
    }


def _json_safe(value):
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)):
        numeric = float(value)
        return numeric if np.isfinite(numeric) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def _topic_content_digest(
    path: Path,
    topics: set[str],
    max_record_stamp_ns: int | None = None,
) -> dict[str, dict[str, object]]:
    state = {
        topic: {"count": 0, "sha256": hashlib.sha256()} for topic in sorted(topics)
    }
    with rosbag.Bag(str(path), "r") as bag:
        for topic, message, stamp in bag.read_messages(topics=sorted(topics)):
            if (
                max_record_stamp_ns is not None
                and int(stamp.to_nsec()) > max_record_stamp_ns
            ):
                break
            raw = _message_bytes(message)
            digest = state[topic]["sha256"]
            digest.update(topic.encode("utf-8"))
            digest.update(b"\0")
            digest.update(struct.pack("<qQ", int(stamp.to_nsec()), len(raw)))
            digest.update(raw)
            state[topic]["count"] = int(state[topic]["count"]) + 1
    return {
        topic: {
            "count": int(values["count"]),
            "sha256": values["sha256"].hexdigest(),
        }
        for topic, values in state.items()
    }


def _channel_map(message) -> dict[str, object]:
    channels: dict[str, object] = {}
    for channel in message.channels:
        if channel.name in channels:
            raise ValueError(f"duplicate PointCloud channel: {channel.name}")
        channels[channel.name] = channel
    missing = [name for name in REQUIRED_CHANNELS if name not in channels]
    if missing:
        raise ValueError(f"missing required PointCloud channels: {missing}")
    point_count = len(message.points)
    bad_lengths = {
        channel.name: len(channel.values)
        for channel in message.channels
        if len(channel.values) != point_count
    }
    if bad_lengths:
        raise ValueError(
            f"PointCloud channel length mismatch for {point_count} points: {bad_lengths}"
        )
    return channels


def _frame_from_message(message, record_stamp_ns: int) -> FeatureFrame:
    channels = _channel_map(message)
    point_z = np.asarray([point.z for point in message.points], dtype=np.float64)
    if not np.all(np.isfinite(point_z)) or not np.all(point_z == 1.0):
        raise ValueError("source feature point.z must be finite and exactly 1.0")
    ids_float = np.asarray(channels["id"].values, dtype=np.float64)
    ids = ids_float.astype(np.int64)
    if not np.array_equal(ids_float, ids.astype(np.float64)):
        raise ValueError("feature IDs must be exactly integral")
    if len(np.unique(ids)) != len(ids):
        raise ValueError("source feature frame contains duplicate IDs")
    pixels = np.column_stack(
        (
            np.asarray(channels["p_u"].values, dtype=np.float32),
            np.asarray(channels["p_v"].values, dtype=np.float32),
        )
    ).astype(np.float32)
    if not np.all(np.isfinite(pixels)):
        raise ValueError("source feature frame contains non-finite pixels")
    header_stamp_ns = int(message.header.stamp.to_nsec())
    if header_stamp_ns <= 0:
        raise ValueError("feature header stamp must be positive")
    return FeatureFrame(
        header_stamp_ns=header_stamp_ns,
        record_stamp_ns=int(record_stamp_ns),
        ids=ids,
        pixels=pixels,
    )


def read_feature_frames(
    source_bag: Path,
    feature_topic: str,
    max_feature_frames: int | None = None,
) -> list[FeatureFrame]:
    if max_feature_frames is not None and max_feature_frames <= 0:
        raise ValueError("max_feature_frames must be positive when provided")
    frames: list[FeatureFrame] = []
    with rosbag.Bag(str(source_bag), "r") as bag:
        for _topic, message, record_stamp in bag.read_messages(topics=[feature_topic]):
            frames.append(_frame_from_message(message, int(record_stamp.to_nsec())))
            if max_feature_frames is not None and len(frames) >= max_feature_frames:
                break
    if not frames:
        raise ValueError(f"no feature messages found on {feature_topic}")
    header_stamps = np.asarray([frame.header_stamp_ns for frame in frames], dtype=np.int64)
    if np.any(np.diff(header_stamps) <= 0):
        raise ValueError("feature header stamps must be strictly increasing")
    return frames


def _mono8_image(message) -> np.ndarray:
    encoding = str(getattr(message, "encoding", "")).lower()
    if encoding not in {"mono8", "8uc1"}:
        raise ValueError(
            f"raw-LK v1 requires mono8/8UC1 images, got encoding={encoding!r}"
        )
    height = int(message.height)
    width = int(message.width)
    step = int(message.step)
    if height <= 0 or width <= 0 or step < width:
        raise ValueError(f"invalid image geometry: {width}x{height}, step={step}")
    raw = np.frombuffer(message.data, dtype=np.uint8)
    required = height * step
    if raw.size < required:
        raise ValueError(f"truncated image payload: {raw.size} < {required}")
    return raw[:required].reshape(height, step)[:, :width].copy()


def read_raw_frames(
    raw_bag: Path,
    image_topic: str,
    first_stamp_ns: int,
    last_stamp_ns: int,
) -> list[RawFrame]:
    frames: list[RawFrame] = []
    seen: set[int] = set()
    with rosbag.Bag(str(raw_bag), "r") as bag:
        for _topic, message, _record_stamp in bag.read_messages(topics=[image_topic]):
            header_stamp_ns = int(message.header.stamp.to_nsec())
            if header_stamp_ns < first_stamp_ns:
                continue
            if header_stamp_ns > last_stamp_ns:
                break
            if header_stamp_ns in seen:
                raise ValueError(f"duplicate raw image header stamp: {header_stamp_ns}")
            seen.add(header_stamp_ns)
            frames.append(RawFrame(header_stamp_ns, _mono8_image(message)))
    if not frames:
        raise ValueError(f"no raw images found on {image_topic} in feature time range")
    stamps = np.asarray([frame.header_stamp_ns for frame in frames], dtype=np.int64)
    if np.any(np.diff(stamps) <= 0):
        raise ValueError("raw image header stamps must be strictly increasing")
    return frames


def _seeded_lk(
    image0: np.ndarray,
    image1: np.ndarray,
    points0: np.ndarray,
    points1_seed: np.ndarray,
) -> tuple[np.ndarray | None, np.ndarray]:
    count = len(points0)
    if count == 0:
        return np.empty((0, 2), dtype=np.float32), np.empty((0,), dtype=bool)
    points1, status, _error = cv2.calcOpticalFlowPyrLK(
        image0,
        image1,
        np.asarray(points0, dtype=np.float32).reshape(-1, 1, 2),
        np.asarray(points1_seed, dtype=np.float32).reshape(-1, 1, 2).copy(),
        winSize=LK_WIN_SIZE,
        maxLevel=LK_MAX_LEVEL,
        criteria=(
            cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
            LK_CRITERIA_COUNT,
            LK_CRITERIA_EPS,
        ),
        flags=cv2.OPTFLOW_USE_INITIAL_FLOW,
        minEigThreshold=LK_MIN_EIG_THRESHOLD,
    )
    if points1 is None or status is None:
        return None, np.zeros((count,), dtype=bool)
    points1 = np.asarray(points1, dtype=np.float32).reshape(-1, 2)
    status = np.asarray(status).reshape(-1).astype(bool)
    if len(points1) != count or len(status) != count:
        return None, np.zeros((count,), dtype=bool)
    return points1, status


def _raw_indices_for_features(
    feature_frames: Sequence[FeatureFrame], raw_frames: Sequence[RawFrame]
) -> np.ndarray:
    index_by_stamp = {frame.header_stamp_ns: index for index, frame in enumerate(raw_frames)}
    missing = [
        frame.header_stamp_ns
        for frame in feature_frames
        if frame.header_stamp_ns not in index_by_stamp
    ]
    if missing:
        raise ValueError(
            f"feature stamps missing exact raw-image matches: {missing[:5]}"
            + ("..." if len(missing) > 5 else "")
        )
    indices = np.asarray(
        [index_by_stamp[frame.header_stamp_ns] for frame in feature_frames],
        dtype=np.int64,
    )
    if len(indices) > 1 and not np.all(np.diff(indices) == PUBLISHED_RAW_STRIDE):
        raise ValueError(
            "raw-LK v1 requires every feature frame to be exactly two raw frames apart; "
            f"observed strides={np.unique(np.diff(indices)).tolist()}"
        )
    return indices


def adapt_pixel_frames(
    feature_frames: Sequence[FeatureFrame], raw_frames: Sequence[RawFrame]
) -> tuple[list[np.ndarray], list[FrameCarrierDiagnostics]]:
    """Apply the frozen B-probe carrier while preserving every occurrence."""

    if not feature_frames:
        raise ValueError("feature_frames must not be empty")
    raw_indices = _raw_indices_for_features(feature_frames, raw_frames)
    adapted = [np.asarray(feature_frames[0].pixels, dtype=np.float32).copy()]
    first_count = len(feature_frames[0].ids)
    diagnostics = [
        FrameCarrierDiagnostics(
            frame_index=0,
            header_stamp_ns=feature_frames[0].header_stamp_ns,
            observation_count=first_count,
            birth_count=first_count,
            continuation_count=0,
            accepted_count=0,
            fallback_count=0,
            removed_count=0,
            accepted_fraction=float("nan"),
            fb_median_px=float("nan"),
            fb_p95_px=float("nan"),
            correction_median_px=0.0,
            correction_p95_px=0.0,
        )
    ]

    for frame_index in range(1, len(feature_frames)):
        previous_frame = feature_frames[frame_index - 1]
        current_frame = feature_frames[frame_index]
        previous_by_id = {
            int(feature_id): index for index, feature_id in enumerate(previous_frame.ids)
        }
        current = np.asarray(current_frame.pixels, dtype=np.float32).copy()
        current_indices: list[int] = []
        previous_indices: list[int] = []
        for current_index, feature_id in enumerate(current_frame.ids):
            previous_index = previous_by_id.get(int(feature_id))
            if previous_index is not None:
                current_indices.append(current_index)
                previous_indices.append(previous_index)
        current_indices_array = np.asarray(current_indices, dtype=np.int64)
        previous_indices_array = np.asarray(previous_indices, dtype=np.int64)

        continuation_count = len(current_indices_array)
        birth_count = len(current_frame.ids) - continuation_count
        removed_count = len(previous_frame.ids) - continuation_count
        good = np.zeros((continuation_count,), dtype=bool)
        fb = np.full((continuation_count,), np.nan, dtype=np.float32)

        if continuation_count:
            points0 = adapted[-1][previous_indices_array].astype(np.float32)
            points2_seed = current_frame.pixels[current_indices_array].astype(np.float32)
            points1_seed = ((points0 + points2_seed) * 0.5).astype(np.float32)
            raw0 = int(raw_indices[frame_index - 1])
            raw2 = int(raw_indices[frame_index])
            if raw2 != raw0 + PUBLISHED_RAW_STRIDE:
                raise AssertionError("validated raw stride changed unexpectedly")
            image0 = raw_frames[raw0].image
            image1 = raw_frames[raw0 + 1].image
            image2 = raw_frames[raw2].image

            points1, status01 = _seeded_lk(image0, image1, points0, points1_seed)
            if points1 is not None:
                points2, status12 = _seeded_lk(image1, image2, points1, points2_seed)
            else:
                points2, status12 = None, np.zeros((continuation_count,), dtype=bool)
            if points2 is not None:
                points1_back, status21 = _seeded_lk(
                    image2, image1, points2, points1.copy()
                )
            else:
                points1_back, status21 = None, np.zeros((continuation_count,), dtype=bool)
            if points1_back is not None:
                points0_back, status10 = _seeded_lk(
                    image1, image0, points1_back, points0.copy()
                )
            else:
                points0_back, status10 = None, np.zeros((continuation_count,), dtype=bool)

            if points2 is not None and points0_back is not None:
                fb = np.linalg.norm(points0_back - points0, axis=1).astype(np.float32)
                finite_chain = (
                    np.all(np.isfinite(points1), axis=1)
                    & np.all(np.isfinite(points2), axis=1)
                    & np.all(np.isfinite(points1_back), axis=1)
                    & np.all(np.isfinite(points0_back), axis=1)
                )
                good = (
                    status01
                    & status12
                    & status21
                    & status10
                    & finite_chain
                    & np.isfinite(fb)
                    & (fb <= LK_FB_MAX_PX)
                )
                current[current_indices_array[good]] = points2[good]

        correction = np.linalg.norm(current - current_frame.pixels, axis=1)
        accepted_count = int(np.sum(good))
        fallback_count = continuation_count - accepted_count
        diagnostics.append(
            FrameCarrierDiagnostics(
                frame_index=frame_index,
                header_stamp_ns=current_frame.header_stamp_ns,
                observation_count=len(current_frame.ids),
                birth_count=birth_count,
                continuation_count=continuation_count,
                accepted_count=accepted_count,
                fallback_count=fallback_count,
                removed_count=removed_count,
                accepted_fraction=(
                    float(accepted_count / continuation_count)
                    if continuation_count
                    else float("nan")
                ),
                fb_median_px=_percentile(fb, 50.0),
                fb_p95_px=_percentile(fb, 95.0),
                correction_median_px=_percentile(correction, 50.0),
                correction_p95_px=_percentile(correction, 95.0),
            )
        )
        adapted.append(current)
    return adapted, diagnostics


def load_pinhole_camera(camera_yaml: Path) -> tuple[np.ndarray, np.ndarray]:
    text = "\n".join(
        line
        for line in camera_yaml.read_text(encoding="utf-8").splitlines()
        if not line.startswith("%YAML:")
    )
    data = yaml.safe_load(text) or {}
    if "cam0" in data:
        data = data["cam0"]
    model = str(data.get("model_type", data.get("distortion_model", "PINHOLE"))).upper()
    if model not in {"PINHOLE", "PLUMB_BOB"}:
        raise ValueError(f"raw-LK v1 supports pinhole cameras only, got {model!r}")
    projection = data.get("projection_parameters", {})
    distortion = data.get("distortion_parameters", {})
    try:
        fx = float(projection["fx"])
        fy = float(projection["fy"])
        cx = float(projection["cx"])
        cy = float(projection["cy"])
    except KeyError as exc:
        raise ValueError(f"missing pinhole projection parameter: {exc}") from exc
    camera_matrix = np.asarray(
        [[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]], dtype=np.float64
    )
    distortion_vector = np.asarray(
        [
            float(distortion.get("k1", 0.0)),
            float(distortion.get("k2", 0.0)),
            float(distortion.get("p1", 0.0)),
            float(distortion.get("p2", 0.0)),
        ],
        dtype=np.float64,
    )
    return camera_matrix, distortion_vector


def normalized_frames(
    pixel_frames: Sequence[np.ndarray], camera_matrix: np.ndarray, distortion: np.ndarray
) -> list[np.ndarray]:
    normalized: list[np.ndarray] = []
    for pixels in pixel_frames:
        if len(pixels) == 0:
            normalized.append(np.empty((0, 2), dtype=np.float32))
            continue
        points = cv2.undistortPoints(
            np.asarray(pixels, dtype=np.float32).reshape(-1, 1, 2),
            camera_matrix,
            distortion,
        )
        normalized.append(points.reshape(-1, 2).astype(np.float32))
    return normalized


def velocity_frames(
    feature_frames: Sequence[FeatureFrame], normalized: Sequence[np.ndarray]
) -> list[np.ndarray]:
    velocities = [np.zeros_like(normalized[0], dtype=np.float32)]
    for frame_index in range(1, len(feature_frames)):
        previous_frame = feature_frames[frame_index - 1]
        current_frame = feature_frames[frame_index]
        dt = (current_frame.header_stamp_ns - previous_frame.header_stamp_ns) * 1e-9
        if not np.isfinite(dt) or dt <= 0.0:
            raise ValueError(f"non-positive published-frame dt at frame {frame_index}: {dt}")
        previous_by_id = {
            int(feature_id): index for index, feature_id in enumerate(previous_frame.ids)
        }
        velocity = np.zeros_like(normalized[frame_index], dtype=np.float32)
        for current_index, feature_id in enumerate(current_frame.ids):
            previous_index = previous_by_id.get(int(feature_id))
            if previous_index is None:
                continue
            velocity[current_index] = (
                normalized[frame_index][current_index]
                - normalized[frame_index - 1][previous_index]
            ) / float(dt)
        velocities.append(velocity)
    return velocities


def _adapt_feature_message(
    source_message,
    pixels: np.ndarray,
    normalized: np.ndarray,
    velocities: np.ndarray,
):
    message = copy.deepcopy(source_message)
    channels = _channel_map(message)
    count = len(message.points)
    if not (len(pixels) == len(normalized) == len(velocities) == count):
        raise ValueError("adapted arrays do not match source observation count")
    channels["p_u"].values = [float(value) for value in pixels[:, 0]]
    channels["p_v"].values = [float(value) for value in pixels[:, 1]]
    channels["velocity_x"].values = [float(value) for value in velocities[:, 0]]
    channels["velocity_y"].values = [float(value) for value in velocities[:, 1]]
    for index in range(count):
        message.points[index].x = float(normalized[index, 0])
        message.points[index].y = float(normalized[index, 1])
        message.points[index].z = 1.0
    return message


def _algorithm_contract() -> dict[str, object]:
    return {
        "name": "sp_lg_seeded_raw_frame_lk_carrier_offline_v1",
        "published_raw_stride": PUBLISHED_RAW_STRIDE,
        "win_size": list(LK_WIN_SIZE),
        "max_level": LK_MAX_LEVEL,
        "criteria_count": LK_CRITERIA_COUNT,
        "criteria_eps": LK_CRITERIA_EPS,
        "min_eig_threshold": LK_MIN_EIG_THRESHOLD,
        "bidirectional_fb_max_px": LK_FB_MAX_PX,
        "initial_flow_seeded": True,
        "ncc": False,
        "border_gate": False,
        "preprocess": False,
        "spatial_nms": False,
        "occurrence_policy": "source_exact_fail_open",
    }


def _write_bag_no_clobber(
    source_bag: Path,
    output_bag: Path,
    feature_topic: str,
    feature_frames: Sequence[FeatureFrame],
    pixel_frames: Sequence[np.ndarray],
    normalized: Sequence[np.ndarray],
    velocities: Sequence[np.ndarray],
    truncated: bool,
) -> None:
    if output_bag.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output_bag}")
    output_bag.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_bag.with_name(f".{output_bag.name}.tmp.{os.getpid()}")
    if temporary.exists():
        raise FileExistsError(f"temporary output already exists: {temporary}")
    feature_index = 0
    cutoff_ns = feature_frames[-1].record_stamp_ns if truncated else None
    try:
        with rosbag.Bag(str(source_bag), "r") as input_bag, rosbag.Bag(
            str(temporary), "w"
        ) as output:
            for topic, message, record_stamp, connection_header in input_bag.read_messages(
                return_connection_header=True
            ):
                record_ns = int(record_stamp.to_nsec())
                if cutoff_ns is not None and record_ns > cutoff_ns:
                    break
                if topic == feature_topic:
                    if feature_index >= len(feature_frames):
                        if truncated:
                            continue
                        raise ValueError("source bag has more feature frames than prepared")
                    expected = feature_frames[feature_index]
                    if int(message.header.stamp.to_nsec()) != expected.header_stamp_ns:
                        raise ValueError(
                            f"feature order/stamp changed at frame {feature_index}"
                        )
                    message = _adapt_feature_message(
                        message,
                        pixel_frames[feature_index],
                        normalized[feature_index],
                        velocities[feature_index],
                    )
                    feature_index += 1
                output.write(
                    topic,
                    message,
                    record_stamp,
                    connection_header=connection_header,
                )
        if feature_index != len(feature_frames):
            raise ValueError(
                f"wrote {feature_index} feature frames, expected {len(feature_frames)}"
            )
        os.link(temporary, output_bag)
        temporary.unlink()
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def _write_json_no_clobber(path: Path, payload: dict[str, object]) -> None:
    created = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as handle:
            created = True
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
    except Exception:
        if created:
            path.unlink(missing_ok=True)
        raise


def adapt_bag(
    source_feature_bag: str | Path,
    raw_image_bag: str | Path,
    camera_yaml: str | Path,
    output_bag: str | Path,
    *,
    image_topic: str,
    feature_topic: str = FEATURE_TOPIC_DEFAULT,
    max_feature_frames: int | None = None,
    diagnostics_json: str | Path | None = None,
) -> dict[str, object]:
    source_feature_bag = Path(source_feature_bag).resolve()
    raw_image_bag = Path(raw_image_bag).resolve()
    camera_yaml = Path(camera_yaml).resolve()
    output_bag = Path(output_bag).resolve()
    diagnostics_path = Path(diagnostics_json).resolve() if diagnostics_json else None
    for path, label in (
        (source_feature_bag, "source feature bag"),
        (raw_image_bag, "raw image bag"),
        (camera_yaml, "camera YAML"),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} does not exist: {path}")
    if output_bag in {source_feature_bag, raw_image_bag, camera_yaml}:
        raise ValueError("output_bag must not alias any input")
    if output_bag.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output_bag}")
    if diagnostics_path is not None:
        if diagnostics_path in {
            source_feature_bag,
            raw_image_bag,
            camera_yaml,
            output_bag,
        }:
            raise ValueError("diagnostics_json must not alias an input or output bag")
        if diagnostics_path.exists():
            raise FileExistsError(
                f"refusing to overwrite existing diagnostics: {diagnostics_path}"
            )

    all_feature_count = 0
    with rosbag.Bag(str(source_feature_bag), "r") as bag:
        topic_info = bag.get_type_and_topic_info().topics.get(feature_topic)
        all_feature_count = int(topic_info.message_count) if topic_info else 0
    feature_frames = read_feature_frames(
        source_feature_bag, feature_topic, max_feature_frames=max_feature_frames
    )
    truncated = len(feature_frames) < all_feature_count
    raw_frames = read_raw_frames(
        raw_image_bag,
        image_topic,
        feature_frames[0].header_stamp_ns,
        feature_frames[-1].header_stamp_ns,
    )
    pixel_frames, frame_diagnostics = adapt_pixel_frames(feature_frames, raw_frames)
    camera_matrix, distortion = load_pinhole_camera(camera_yaml)
    normalized = normalized_frames(pixel_frames, camera_matrix, distortion)
    velocities = velocity_frames(feature_frames, normalized)

    preserved_topics = set()
    with rosbag.Bag(str(source_feature_bag), "r") as bag:
        preserved_topics = set(bag.get_type_and_topic_info().topics) - {feature_topic}
    digest_cutoff_ns = feature_frames[-1].record_stamp_ns if truncated else None
    before_digests = _topic_content_digest(
        source_feature_bag,
        preserved_topics,
        max_record_stamp_ns=digest_cutoff_ns,
    )
    _write_bag_no_clobber(
        source_feature_bag,
        output_bag,
        feature_topic,
        feature_frames,
        pixel_frames,
        normalized,
        velocities,
        truncated=truncated,
    )
    try:
        after_digests = _topic_content_digest(
            output_bag,
            preserved_topics,
            max_record_stamp_ns=digest_cutoff_ns,
        )
        if before_digests != after_digests:
            raise RuntimeError(
                "non-feature topic content changed within the adaptation cutoff"
            )

        total_continuations = int(
            sum(row.continuation_count for row in frame_diagnostics)
        )
        total_accepted = int(sum(row.accepted_count for row in frame_diagnostics))
        total_fallback = int(sum(row.fallback_count for row in frame_diagnostics))
        total_births = int(sum(row.birth_count for row in frame_diagnostics))
        diagnostics = _json_safe(
            {
                "algorithm": _algorithm_contract(),
                "inputs": {
                    "source_feature_bag": str(source_feature_bag),
                    "raw_image_bag": str(raw_image_bag),
                    "camera_yaml": str(camera_yaml),
                    "image_topic": image_topic,
                    "feature_topic": feature_topic,
                },
                "artifacts": {
                    "source_feature_bag": _file_metadata(source_feature_bag),
                    "raw_image_bag": _file_metadata(raw_image_bag),
                    "camera_yaml": _file_metadata(camera_yaml),
                    "output_bag": _file_metadata(output_bag),
                    "adapter_source": _file_metadata(Path(__file__).resolve()),
                },
                "output_bag": str(output_bag),
                "max_feature_frames": max_feature_frames,
                "truncated": truncated,
                "digest_cutoff_record_stamp_ns": digest_cutoff_ns,
                "feature_frames": len(feature_frames),
                "observations": int(sum(len(frame.ids) for frame in feature_frames)),
                "births": total_births,
                "continuations": total_continuations,
                "accepted": total_accepted,
                "fallback": total_fallback,
                "accepted_fraction": (
                    float(total_accepted / total_continuations)
                    if total_continuations
                    else float("nan")
                ),
                "preserved_topic_digests_before": before_digests,
                "preserved_topic_digests_after": after_digests,
                "frame_diagnostics": [asdict(row) for row in frame_diagnostics],
            }
        )
        if diagnostics_path is not None:
            _write_json_no_clobber(diagnostics_path, diagnostics)
    except Exception:
        output_bag.unlink(missing_ok=True)
        raise
    return diagnostics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-feature-bag", required=True)
    parser.add_argument("--raw-image-bag", required=True)
    parser.add_argument("--camera-yaml", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--image-topic", required=True)
    parser.add_argument("--feature-topic", default=FEATURE_TOPIC_DEFAULT)
    parser.add_argument(
        "--max-feature-frames",
        type=int,
        default=None,
        help="Optional prefix-only test output; the full canonical run omits this.",
    )
    parser.add_argument("--diagnostics-json", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    diagnostics = adapt_bag(
        args.source_feature_bag,
        args.raw_image_bag,
        args.camera_yaml,
        args.output_bag,
        image_topic=args.image_topic,
        feature_topic=args.feature_topic,
        max_feature_frames=args.max_feature_frames,
        diagnostics_json=args.diagnostics_json,
    )
    summary = {
        key: diagnostics[key]
        for key in (
            "output_bag",
            "truncated",
            "feature_frames",
            "observations",
            "births",
            "continuations",
            "accepted",
            "fallback",
            "accepted_fraction",
        )
    }
    print(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
