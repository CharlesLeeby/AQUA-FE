#!/usr/bin/env python3
"""Build a matched-dose GFTT/LK replacement for selected feature lineages.

The output starts from the target VINS feature bag. Selected target IDs are
removed, and retrospectively matched GFTT gap seeds are inserted on exactly the
same feature frames. All non-feature messages and all other observations remain
unchanged. The replacement carries the target observation's quality and sigma,
so the diagnostic controls published dose and backend weighting. Candidate
selection uses full-interval survival and proximity to the target locations; it
is not an online or detector-isolation causal control.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np
import rosbag
import rospy
from cv_bridge import CvBridge
from geometry_msgs.msg import Point32

from uw_frontend.ros.export_vins_features import (
    _load_pinhole_camera,
    _pixels_to_normalized,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-bag", required=True)
    parser.add_argument("--raw-bag", required=True)
    parser.add_argument("--camera-config", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--stats-json", required=True)
    parser.add_argument("--stats-csv", required=True)
    parser.add_argument("--target-id", action="append", type=int, required=True)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--image-topic", default="/camera/image_raw")
    parser.add_argument("--new-id-base", type=int, default=15_000_000)
    parser.add_argument(
        "--control-source-code",
        type=int,
        default=0,
        help="Source code written for replacement observations.",
    )
    parser.add_argument(
        "--preserve-target-ids",
        action="store_true",
        help="Keep the removed target IDs for the replacement observations.",
    )
    parser.add_argument(
        "--allow-sparse-target-schedule",
        action="store_true",
        help=(
            "Permit a target ID to be absent on intermediate feature frames. "
            "The classical control is still tracked through the complete interval, "
            "but is published only on the target ID's observed frames."
        ),
    )
    parser.add_argument("--max-candidates", type=int, default=512)
    parser.add_argument("--quality-level", type=float, default=0.01)
    parser.add_argument("--min-distance", type=int, default=18)
    parser.add_argument("--block-size", type=int, default=7)
    parser.add_argument("--exclusion-radius", type=int, default=18)
    parser.add_argument("--max-image-dt", type=float, default=0.002)
    parser.add_argument("--max-fb-error", type=float, default=1.0)
    return parser.parse_args()


def channel_map(msg) -> dict[str, object]:
    return {channel.name: channel for channel in msg.channels}


def observation_index(msg, feature_id: int) -> int | None:
    ids = channel_map(msg).get("id")
    if ids is None:
        return None
    for index, value in enumerate(ids.values):
        if int(round(float(value))) == int(feature_id):
            return index
    return None


def load_feature_messages(path: Path, topic: str) -> list[object]:
    with rosbag.Bag(str(path), "r") as bag:
        return [msg for _topic, msg, _stamp in bag.read_messages(topics=[topic])]


def load_images(
    path: Path,
    topic: str,
    feature_stamps: list[float],
    max_dt: float,
) -> list[np.ndarray]:
    bridge = CvBridge()
    matches: list[tuple[float, object] | None] = [None] * len(feature_stamps)
    index_padding = max(0.5, float(max_dt))
    with rosbag.Bag(str(path), "r") as bag:
        for _topic, msg, stamp in bag.read_messages(
            topics=[topic],
            start_time=rospy.Time.from_sec(min(feature_stamps) - index_padding),
            end_time=rospy.Time.from_sec(max(feature_stamps) + index_padding),
        ):
            msg_stamp = float(msg.header.stamp.to_sec())
            if msg_stamp <= 0.0:
                msg_stamp = float(stamp.to_sec())
            nearest = min(
                range(len(feature_stamps)),
                key=lambda index: abs(feature_stamps[index] - msg_stamp),
            )
            delta = abs(feature_stamps[nearest] - msg_stamp)
            current = matches[nearest]
            if delta <= max_dt and (current is None or delta < current[0]):
                matches[nearest] = (delta, copy.deepcopy(msg))
    missing = [index for index, item in enumerate(matches) if item is None]
    if missing:
        raise RuntimeError(f"no raw image match for relative feature frames {missing}")
    return [
        bridge.imgmsg_to_cv2(item[1], desired_encoding="mono8")
        for item in matches
        if item is not None
    ]


def detect_and_track(
    images: list[np.ndarray],
    first_message,
    target_ids: set[int],
    args: argparse.Namespace,
) -> tuple[np.ndarray, list[np.ndarray], np.ndarray]:
    height, width = images[0].shape[:2]
    mask = np.full((height, width), 255, dtype=np.uint8)
    channels = channel_map(first_message)
    ids = [int(round(float(value))) for value in channels["id"].values]
    pixels = zip(channels["p_u"].values, channels["p_v"].values)
    for feature_id, (u, v) in zip(ids, pixels):
        if feature_id in target_ids:
            continue
        cv2.circle(
            mask,
            (int(round(float(u))), int(round(float(v)))),
            int(args.exclusion_radius),
            0,
            -1,
        )
    cv2.setRNGSeed(20260803)
    detected = cv2.goodFeaturesToTrack(
        images[0],
        maxCorners=int(args.max_candidates),
        qualityLevel=float(args.quality_level),
        minDistance=float(args.min_distance),
        mask=mask,
        blockSize=int(args.block_size),
        useHarrisDetector=False,
    )
    if detected is None:
        raise RuntimeError("GFTT returned no gap candidates")
    points = detected.astype(np.float32)
    trajectories = [points.reshape(-1, 2).copy()]
    alive = np.ones(len(points), dtype=bool)
    previous = images[0]
    lk = {
        "winSize": (21, 21),
        "maxLevel": 3,
        "criteria": (
            cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
            30,
            0.01,
        ),
    }
    for image in images[1:]:
        forward, status, _error = cv2.calcOpticalFlowPyrLK(
            previous, image, points, None, **lk
        )
        backward, back_status, _back_error = cv2.calcOpticalFlowPyrLK(
            image, previous, forward, None, **lk
        )
        fb_error = np.linalg.norm((points - backward).reshape(-1, 2), axis=1)
        good = (
            (status.reshape(-1) == 1)
            & (back_status.reshape(-1) == 1)
            & (fb_error < float(args.max_fb_error))
        )
        current = forward.reshape(-1, 2)
        inside = (
            (current[:, 0] >= 0.0)
            & (current[:, 0] < width)
            & (current[:, 1] >= 0.0)
            & (current[:, 1] < height)
        )
        alive &= good & inside
        trajectories.append(current.copy())
        points = forward
        previous = image
    return detected.reshape(-1, 2), trajectories, alive


def target_initial_pixels(first_message, target_ids: list[int]) -> dict[int, tuple[float, float]]:
    channels = channel_map(first_message)
    result: dict[int, tuple[float, float]] = {}
    for feature_id in target_ids:
        index = observation_index(first_message, feature_id)
        if index is None:
            raise RuntimeError(f"target ID {feature_id} is absent from the first target frame")
        result[feature_id] = (
            float(channels["p_u"].values[index]),
            float(channels["p_v"].values[index]),
        )
    return result


def assign_candidates(
    target_pixels: dict[int, tuple[float, float]],
    initial_candidates: np.ndarray,
    alive: np.ndarray,
) -> tuple[dict[int, int], dict[int, float]]:
    available = {int(index) for index in np.flatnonzero(alive)}
    assignments: dict[int, int] = {}
    distances: dict[int, float] = {}
    for feature_id in sorted(target_pixels):
        if not available:
            raise RuntimeError("not enough full-interval classical candidates")
        target = target_pixels[feature_id]
        selected = min(
            available,
            key=lambda index: (
                math.dist(target, tuple(float(x) for x in initial_candidates[index])),
                index,
            ),
        )
        assignments[feature_id] = selected
        distances[feature_id] = math.dist(
            target, tuple(float(x) for x in initial_candidates[selected])
        )
        available.remove(selected)
    return assignments, distances


def filter_indices(msg, removed: set[int]) -> None:
    keep = [index not in removed for index in range(len(msg.points))]
    msg.points = [point for point, accepted in zip(msg.points, keep) if accepted]
    for channel in msg.channels:
        if len(channel.values) == len(keep):
            channel.values = [
                float(value)
                for value, accepted in zip(channel.values, keep)
                if accepted
            ]


def append_control_observation(
    msg,
    target_values: dict[str, float],
    feature_id: int,
    pixel: np.ndarray,
    normalized: np.ndarray,
    velocity: np.ndarray,
    source_code: int,
) -> None:
    msg.points.append(
        Point32(x=float(normalized[0]), y=float(normalized[1]), z=1.0)
    )
    replacements = {
        "id": float(feature_id),
        "camera_id": 0.0,
        "p_u": float(pixel[0]),
        "p_v": float(pixel[1]),
        "velocity_x": float(velocity[0]),
        "velocity_y": float(velocity[1]),
        "gx": 0.0,
        "gy": 0.0,
        "gz": 0.0,
        "source_code": float(source_code),
        "is_learned": 0.0,
    }
    for channel in msg.channels:
        value = replacements.get(channel.name, target_values.get(channel.name, 0.0))
        channel.values.append(float(value))


def replace_control_observation(
    msg,
    index: int,
    target_values: dict[str, float],
    feature_id: int,
    pixel: np.ndarray,
    normalized: np.ndarray,
    velocity: np.ndarray,
    source_code: int,
) -> None:
    msg.points[index] = Point32(
        x=float(normalized[0]), y=float(normalized[1]), z=1.0
    )
    replacements = {
        "id": float(feature_id),
        "camera_id": 0.0,
        "p_u": float(pixel[0]),
        "p_v": float(pixel[1]),
        "velocity_x": float(velocity[0]),
        "velocity_y": float(velocity[1]),
        "gx": 0.0,
        "gy": 0.0,
        "gz": 0.0,
        "source_code": float(source_code),
        "is_learned": 0.0,
    }
    for channel in msg.channels:
        if len(channel.values) != len(msg.points):
            continue
        value = replacements.get(channel.name, target_values.get(channel.name, 0.0))
        values = list(channel.values)
        values[index] = float(value)
        channel.values = values


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def control_id(args: argparse.Namespace, target_id: int, offset: int) -> int:
    if bool(args.preserve_target_ids):
        return int(target_id)
    return int(args.new_id_base) + int(offset)


def write_control(args: argparse.Namespace) -> dict[str, object]:
    target_bag = Path(args.target_bag)
    output_bag = Path(args.output_bag)
    target_ids = sorted(set(int(item) for item in args.target_id))
    target_set = set(target_ids)
    messages = load_feature_messages(target_bag, args.feature_topic)
    frames_by_id: dict[int, list[int]] = {feature_id: [] for feature_id in target_ids}
    for frame_index, msg in enumerate(messages):
        for feature_id in target_ids:
            if observation_index(msg, feature_id) is not None:
                frames_by_id[feature_id].append(frame_index)
    if any(not frames for frames in frames_by_id.values()):
        raise RuntimeError(f"target IDs missing from feature bag: {frames_by_id}")
    first_frame = min(min(frames) for frames in frames_by_id.values())
    last_frame = max(max(frames) for frames in frames_by_id.values())
    interval = list(range(first_frame, last_frame + 1))
    if (
        not bool(args.allow_sparse_target_schedule)
        and any(
            frames != list(range(frames[0], frames[-1] + 1))
            for frames in frames_by_id.values()
        )
    ):
        raise RuntimeError(
            "this diagnostic requires every target lineage to be contiguous"
        )
    if any(frames[0] != first_frame for frames in frames_by_id.values()):
        raise RuntimeError(
            "this diagnostic requires target lineages to share one start event"
        )
    feature_stamps = [float(messages[index].header.stamp.to_sec()) for index in interval]
    images = load_images(
        Path(args.raw_bag), args.image_topic, feature_stamps, float(args.max_image_dt)
    )
    initial, trajectories, alive = detect_and_track(
        images, messages[first_frame], target_set, args
    )
    target_pixels = target_initial_pixels(messages[first_frame], target_ids)
    assignments, distances = assign_candidates(target_pixels, initial, alive)
    camera = _load_pinhole_camera(Path(args.camera_config))

    pixels_by_id: dict[int, list[np.ndarray]] = {}
    normalized_by_id: dict[int, np.ndarray] = {}
    velocity_by_id: dict[int, np.ndarray] = {}
    for target_id, candidate_index in assignments.items():
        pixels = [trajectory[candidate_index] for trajectory in trajectories]
        normalized = _pixels_to_normalized(np.asarray(pixels), camera)
        velocities = np.zeros_like(normalized)
        for index in range(len(normalized)):
            if index > 0:
                delta_t = feature_stamps[index] - feature_stamps[index - 1]
                velocities[index] = (normalized[index] - normalized[index - 1]) / delta_t
        pixels_by_id[target_id] = pixels
        normalized_by_id[target_id] = normalized
        velocity_by_id[target_id] = velocities

    output_bag.parent.mkdir(parents=True, exist_ok=True)
    feature_index = 0
    removed_observations = 0
    inserted_observations = 0
    with rosbag.Bag(str(target_bag), "r") as source, rosbag.Bag(
        str(output_bag), "w"
    ) as destination:
        for topic, msg, stamp in source.read_messages():
            if topic == args.feature_topic:
                if first_frame <= feature_index <= last_frame:
                    relative = feature_index - first_frame
                    channels = channel_map(msg)
                    removed: set[int] = set()
                    values_by_id: dict[int, dict[str, float]] = {}
                    active_target_ids = [
                        target_id
                        for target_id in target_ids
                        if feature_index in frames_by_id[target_id]
                    ]
                    for target_id in active_target_ids:
                        index = observation_index(msg, target_id)
                        if index is None:
                            raise RuntimeError(
                                f"target ID {target_id} missing at feature frame {feature_index}"
                            )
                        removed.add(index)
                        values_by_id[target_id] = {
                            name: float(channel.values[index])
                            for name, channel in channels.items()
                            if len(channel.values) == len(msg.points)
                        }
                    if args.preserve_target_ids:
                        for offset, target_id in enumerate(target_ids):
                            if target_id not in active_target_ids:
                                continue
                            index = observation_index(msg, target_id)
                            if index is None:
                                raise RuntimeError(
                                    f"target ID {target_id} disappeared before replacement"
                                )
                            replace_control_observation(
                                msg,
                                index,
                                values_by_id[target_id],
                                control_id(args, target_id, offset),
                                pixels_by_id[target_id][relative],
                                normalized_by_id[target_id][relative],
                                velocity_by_id[target_id][relative],
                                int(args.control_source_code),
                            )
                            removed_observations += 1
                            inserted_observations += 1
                    else:
                        filter_indices(msg, removed)
                        removed_observations += len(removed)
                        for offset, target_id in enumerate(target_ids):
                            if target_id not in active_target_ids:
                                continue
                            append_control_observation(
                                msg,
                                values_by_id[target_id],
                                control_id(args, target_id, offset),
                                pixels_by_id[target_id][relative],
                                normalized_by_id[target_id][relative],
                                velocity_by_id[target_id][relative],
                                int(args.control_source_code),
                            )
                            inserted_observations += 1
                feature_index += 1
            destination.write(topic, msg, stamp)

    assignments_json = []
    for offset, target_id in enumerate(target_ids):
        candidate_index = assignments[target_id]
        assignments_json.append(
            {
                "target_id": target_id,
                "control_id": control_id(args, target_id, offset),
                "candidate_index": candidate_index,
                "initial_distance_px": distances[target_id],
                "target_initial_pixel": list(target_pixels[target_id]),
                "control_initial_pixel": [float(x) for x in initial[candidate_index]],
                "control_final_pixel": [
                    float(x)
                    for x in trajectories[
                        frames_by_id[target_id][-1] - first_frame
                    ][candidate_index]
                ],
                "target_frames": frames_by_id[target_id],
            }
        )
    return {
        "schema_version": "gftt-matched-lineage-control-v2",
        "target_bag": str(target_bag),
        "raw_bag": str(args.raw_bag),
        "camera_config": str(args.camera_config),
        "output_bag": str(output_bag),
        "feature_topic": str(args.feature_topic),
        "image_topic": str(args.image_topic),
        "feature_frames": feature_index,
        "first_replaced_frame": first_frame,
        "last_replaced_frame": last_frame,
        "replaced_frames": len(interval),
        "target_ids": target_ids,
        "control_id_mode": (
            "preserve_target_ids" if args.preserve_target_ids else "new_id_base"
        ),
        "new_id_base": int(args.new_id_base),
        "removed_observations": removed_observations,
        "inserted_observations": inserted_observations,
        "target_frames_by_id": {
            str(feature_id): frames_by_id[feature_id]
            for feature_id in target_ids
        },
        "allow_sparse_target_schedule": bool(args.allow_sparse_target_schedule),
        "gftt_candidates": int(len(initial)),
        "full_interval_survivors": int(np.count_nonzero(alive)),
        "control_parameters": {
            "max_candidates": int(args.max_candidates),
            "quality_level": float(args.quality_level),
            "min_distance": int(args.min_distance),
            "block_size": int(args.block_size),
            "exclusion_radius": int(args.exclusion_radius),
            "max_image_dt": float(args.max_image_dt),
            "max_fb_error": float(args.max_fb_error),
            "lk_win_size": [21, 21],
            "lk_max_level": 3,
            "lk_criteria_count": 30,
            "lk_criteria_epsilon": 0.01,
            "opencv_rng_seed": 20260803,
            "first_frame_velocity": "zero",
            "control_source_code": int(args.control_source_code),
        },
        "opencv_version": str(cv2.__version__),
        "python_version": str(sys.version.split()[0]),
        "assignments": assignments_json,
        "builder_script_sha256": sha256(Path(__file__).resolve()),
        "camera_config_sha256": sha256(Path(args.camera_config)),
        "target_bag_sha256": sha256(target_bag),
        "raw_bag_sha256": sha256(Path(args.raw_bag)),
        "output_bag_sha256": sha256(output_bag),
    }


def main() -> int:
    args = parse_args()
    stats = write_control(args)
    stats_path = Path(args.stats_json)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    csv_path = Path(args.stats_csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    row = dict(stats)
    for key, value in list(row.items()):
        if isinstance(value, (dict, list)):
            row[key] = json.dumps(value, sort_keys=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    print(json.dumps(stats, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
