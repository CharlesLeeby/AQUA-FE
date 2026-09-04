#!/usr/bin/env python3
"""Add cam1 observations to a frozen MIMIR VINS feature bag.

Each existing classical cam0 observation is used as the seed for same-timestamp
left-to-right pyramidal LK. Accepted matches keep the same feature ID and are
appended with camera_id=1, which is the external-feature stereo contract used
by VINS-Fusion. Learned cam0 tracks remain active as temporal seeds, but their
right observations are disabled by default because MIMIR-UW ablations showed
that local photometric checks do not make their stereo depth no-harm. Explicit
diagnostic policies can re-enable learned right matching.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np
import rosbag
from geometry_msgs.msg import Point32


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-bag", required=True, type=Path)
    parser.add_argument("--sequence-dir", required=True, type=Path)
    parser.add_argument("--output-bag", required=True, type=Path)
    parser.add_argument("--metrics-csv", required=True, type=Path)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--win-size", type=int, default=41)
    parser.add_argument("--max-level", type=int, default=4)
    parser.add_argument("--max-fb-px", type=float, default=0.5)
    parser.add_argument("--max-epipolar-px", type=float, default=0.5)
    parser.add_argument("--min-disparity-px", type=float, default=0.6)
    parser.add_argument("--max-disparity-px", type=float, default=80.0)
    parser.add_argument("--border-px", type=float, default=2.0)
    parser.add_argument("--min-ncc", type=float, default=0.7)
    parser.add_argument("--ncc-radius", type=int, default=4)
    parser.add_argument(
        "--learned-right-policy",
        choices=("left-only", "global-ncc", "local-lk"),
        default="left-only",
        help=(
            "Stereo policy for learned cam0 seeds. The safe default keeps "
            "them in cam0 only; global-ncc adds full-epipolar verification; "
            "local-lk reproduces the unsafe diagnostic ablation."
        ),
    )
    parser.add_argument(
        "--learned-global-max-disparity-diff-px",
        type=float,
        default=1.0,
        help=(
            "For learned cam0 seeds, require the local-LK disparity to agree "
            "with the best NCC match over the full epipolar disparity range. "
            "Set to 0 to disable."
        ),
    )
    parser.add_argument(
        "--learned-global-ncc-radius",
        type=int,
        default=6,
        help="Patch radius for learned full-epipolar NCC verification.",
    )
    parser.add_argument(
        "--max-feature-frames",
        type=int,
        default=0,
        help="Optional short materialization limit for validation; 0 exports the full bag.",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_camera(sequence_dir: Path, camera: str) -> tuple[Path, dict[str, object]]:
    camera_dir = sequence_dir / "auv0/rgb" / camera
    sensor = json.loads((camera_dir / "sensor.yaml").read_text(encoding="utf-8"))
    if sensor.get("camera_model") != "pinhole":
        raise RuntimeError(f"unsupported {camera} model: {sensor.get('camera_model')}")
    return camera_dir, sensor


def channel_map(message: object) -> dict[str, object]:
    return {channel.name: channel for channel in message.channels}


def patch_ncc(
    left: np.ndarray,
    right: np.ndarray,
    left_point: np.ndarray,
    right_point: np.ndarray,
    radius: int,
) -> float:
    size = (2 * radius + 1, 2 * radius + 1)
    left_patch = cv2.getRectSubPix(left, size, tuple(float(v) for v in left_point))
    right_patch = cv2.getRectSubPix(right, size, tuple(float(v) for v in right_point))
    left_zero = left_patch.astype(np.float32) - float(left_patch.mean())
    right_zero = right_patch.astype(np.float32) - float(right_patch.mean())
    denominator = float(np.linalg.norm(left_zero) * np.linalg.norm(right_zero))
    if denominator <= 1e-9:
        return -1.0
    return float(np.sum(left_zero * right_zero) / denominator)


def best_epipolar_ncc_disparity(
    left: np.ndarray,
    right: np.ndarray,
    left_point: np.ndarray,
    min_disparity: float,
    max_disparity: float,
    radius: int,
) -> tuple[float, float] | None:
    """Return the integer-pixel disparity of the global epipolar NCC peak."""

    left_u, left_v = [float(value) for value in left_point]
    center_u = int(round(left_u))
    center_v = int(round(left_v))
    if (
        center_u - radius < 0
        or center_u + radius >= left.shape[1]
        or center_v - radius < 0
        or center_v + radius >= left.shape[0]
    ):
        return None
    template = left[
        center_v - radius : center_v + radius + 1,
        center_u - radius : center_u + radius + 1,
    ]
    min_center = max(radius, int(math.floor(left_u - max_disparity)))
    max_center = min(
        right.shape[1] - radius - 1,
        int(math.ceil(left_u - min_disparity)),
    )
    if min_center > max_center:
        return None
    strip = right[
        center_v - radius : center_v + radius + 1,
        min_center - radius : max_center + radius + 1,
    ]
    profile = cv2.matchTemplate(strip, template, cv2.TM_CCOEFF_NORMED).reshape(-1)
    if not len(profile) or not np.isfinite(profile).any():
        return None
    best_index = int(np.nanargmax(profile))
    best_center = min_center + best_index
    return left_u - float(best_center), float(profile[best_index])


def append_right_observation(
    message: object,
    left_index: int,
    feature_id: int,
    right_u: float,
    right_v: float,
    right_x: float,
    right_y: float,
    right_velocity: np.ndarray,
    stereo_quality: float,
) -> None:
    channels = channel_map(message)
    message.points.append(Point32(x=right_x, y=right_y, z=1.0))
    for channel in message.channels:
        name = channel.name
        if name == "id":
            value = float(feature_id)
        elif name == "camera_id":
            value = 1.0
        elif name == "p_u":
            value = right_u
        elif name == "p_v":
            value = right_v
        elif name == "velocity_x":
            value = float(right_velocity[0])
        elif name == "velocity_y":
            value = float(right_velocity[1])
        elif name == "quality":
            value = min(float(channel.values[left_index]), stereo_quality)
        elif name == "sigma":
            value = max(float(channel.values[left_index]), 1.0 / max(stereo_quality, 0.05))
        else:
            value = float(channel.values[left_index])
        channel.values.append(value)

    # Make malformed inputs fail at materialization time rather than inside VINS.
    expected = len(message.points)
    if any(len(channel.values) != expected for channel in channels.values()):
        raise RuntimeError("feature channel length mismatch after stereo append")


def main() -> int:
    args = parse_args()
    feature_bag = args.feature_bag.resolve()
    output_bag = args.output_bag.resolve()
    metrics_csv = args.metrics_csv.resolve()
    if output_bag.exists():
        raise SystemExit(f"refusing to overwrite output bag: {output_bag}")
    if args.win_size < 3 or args.win_size % 2 == 0:
        raise SystemExit("--win-size must be an odd integer >= 3")
    if args.learned_global_ncc_radius < 1:
        raise SystemExit("--learned-global-ncc-radius must be positive")

    sequence_dir = args.sequence_dir.resolve()
    cam0_dir, cam0_sensor = load_camera(sequence_dir, "cam0")
    cam1_dir, cam1_sensor = load_camera(sequence_dir, "cam1")
    intrinsics1 = np.asarray(cam1_sensor["intrinsics"], dtype=float)
    fx1, fy1 = float(intrinsics1[0, 0]), float(intrinsics1[1, 1])
    cx1, cy1 = float(intrinsics1[0, 2]), float(intrinsics1[1, 2])
    if cam0_sensor["resolution"] != cam1_sensor["resolution"]:
        raise SystemExit("cam0/cam1 resolutions differ")
    width, height = [int(value) for value in cam1_sensor["resolution"]]

    output_bag.parent.mkdir(parents=True, exist_ok=True)
    metrics_csv.parent.mkdir(parents=True, exist_ok=True)
    previous_right: dict[int, tuple[int, np.ndarray]] = {}
    metric_rows: list[dict[str, object]] = []
    totals = {
        "feature_frames": 0,
        "left_observations": 0,
        "right_observations": 0,
        "learned_left_observations": 0,
        "learned_right_observations": 0,
        "learned_right_rejected_policy": 0,
        "learned_right_rejected_global_disparity": 0,
    }

    lk_options = {
        "winSize": (args.win_size, args.win_size),
        "maxLevel": args.max_level,
        "criteria": (
            cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
            30,
            0.01,
        ),
    }
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    with rosbag.Bag(str(feature_bag)) as source, rosbag.Bag(
        str(output_bag), "w", compression=rosbag.Compression.LZ4
    ) as destination:
        for topic, source_message, bag_stamp in source.read_messages():
            if args.max_feature_frames > 0 and totals["feature_frames"] >= args.max_feature_frames:
                break
            if topic != args.feature_topic:
                destination.write(topic, source_message, bag_stamp)
                continue

            message = copy.deepcopy(source_message)
            for channel in message.channels:
                channel.values = list(channel.values)
            channels = channel_map(message)
            required = {"id", "camera_id", "p_u", "p_v", "velocity_x", "velocity_y"}
            missing = sorted(required - set(channels))
            if missing:
                raise RuntimeError(f"missing VINS feature channels: {missing}")
            if any(int(round(value)) != 0 for value in channels["camera_id"].values):
                raise RuntimeError("input feature bag already contains non-cam0 observations")

            stamp_ns = int(message.header.stamp.to_nsec())
            filename = f"{stamp_ns}.png"
            left_image = cv2.imread(str(cam0_dir / "data" / filename), cv2.IMREAD_GRAYSCALE)
            right_image = cv2.imread(str(cam1_dir / "data" / filename), cv2.IMREAD_GRAYSCALE)
            if left_image is None or right_image is None:
                raise RuntimeError(f"missing synchronized stereo images for {stamp_ns}")
            left_image = clahe.apply(left_image)
            right_image = clahe.apply(right_image)

            left_count = len(message.points)
            left_points = np.asarray(
                list(zip(channels["p_u"].values, channels["p_v"].values)),
                dtype=np.float32,
            ).reshape(-1, 1, 2)
            right_points, forward_status, _ = cv2.calcOpticalFlowPyrLK(
                left_image, right_image, left_points, None, **lk_options
            )
            backward_points, backward_status, _ = cv2.calcOpticalFlowPyrLK(
                right_image, left_image, right_points, None, **lk_options
            )
            right_xy = right_points[:, 0, :]
            fb_error = np.linalg.norm(left_points[:, 0, :] - backward_points[:, 0, :], axis=1)
            epipolar_error = np.abs(left_points[:, 0, 1] - right_xy[:, 1])
            disparity = left_points[:, 0, 0] - right_xy[:, 0]
            valid = (
                (forward_status[:, 0] > 0)
                & (backward_status[:, 0] > 0)
                & np.isfinite(right_xy).all(axis=1)
                & (right_xy[:, 0] >= args.border_px)
                & (right_xy[:, 0] < width - args.border_px)
                & (right_xy[:, 1] >= args.border_px)
                & (right_xy[:, 1] < height - args.border_px)
                & (fb_error <= args.max_fb_px)
                & (epipolar_error <= args.max_epipolar_px)
                & (disparity >= args.min_disparity_px)
                & (disparity <= args.max_disparity_px)
            )
            ncc = np.full(left_count, -1.0, dtype=float)
            for candidate in np.flatnonzero(valid):
                ncc[candidate] = patch_ncc(
                    left_image,
                    right_image,
                    left_points[candidate, 0],
                    right_xy[candidate],
                    args.ncc_radius,
                )
            valid &= ncc >= args.min_ncc

            learned_values = channels.get("is_learned")
            learned_left = (
                np.asarray(learned_values.values[:left_count], dtype=float) > 0.5
                if learned_values is not None
                else np.zeros(left_count, dtype=bool)
            )
            learned_global_difference = np.full(left_count, math.nan, dtype=float)
            learned_global_best_ncc = np.full(left_count, math.nan, dtype=float)
            learned_rejected_policy = 0
            learned_global_attempted = 0
            if args.learned_right_policy == "left-only":
                learned_rejected_policy = int((valid & learned_left).sum())
                valid &= ~learned_left
            elif (
                args.learned_right_policy == "global-ncc"
                and args.learned_global_max_disparity_diff_px > 0.0
            ):
                for candidate in np.flatnonzero(valid & learned_left):
                    learned_global_attempted += 1
                    global_match = best_epipolar_ncc_disparity(
                        left_image,
                        right_image,
                        left_points[candidate, 0],
                        args.min_disparity_px,
                        args.max_disparity_px,
                        args.learned_global_ncc_radius,
                    )
                    if global_match is None:
                        valid[candidate] = False
                        continue
                    best_disparity, best_ncc = global_match
                    learned_global_difference[candidate] = abs(
                        float(disparity[candidate]) - best_disparity
                    )
                    learned_global_best_ncc[candidate] = best_ncc
                    if (
                        learned_global_difference[candidate]
                        > args.learned_global_max_disparity_diff_px
                    ):
                        valid[candidate] = False
            matched_indices = np.flatnonzero(valid)
            current_right: dict[int, tuple[int, np.ndarray]] = {}
            for left_index in matched_indices:
                feature_id = int(round(channels["id"].values[left_index]))
                right_u, right_v = [float(value) for value in right_xy[left_index]]
                right_norm = np.array(
                    [(right_u - cx1) / fx1, (right_v - cy1) / fy1], dtype=float
                )
                previous = previous_right.get(feature_id)
                velocity = np.zeros(2, dtype=float)
                if previous is not None and stamp_ns > previous[0]:
                    velocity = (right_norm - previous[1]) / ((stamp_ns - previous[0]) * 1e-9)
                current_right[feature_id] = (stamp_ns, right_norm)
                quality = math.exp(
                    -0.5 * float(fb_error[left_index]) ** 2
                    -0.5 * float(epipolar_error[left_index]) ** 2
                )
                quality *= max(0.0, min(1.0, float(ncc[left_index])))
                append_right_observation(
                    message,
                    int(left_index),
                    feature_id,
                    right_u,
                    right_v,
                    float(right_norm[0]),
                    float(right_norm[1]),
                    velocity,
                    max(0.05, min(1.0, quality)),
                )
            previous_right.update(current_right)
            destination.write(topic, message, bag_stamp)

            learned_right = int(learned_left[matched_indices].sum())
            learned_rejected_global = (
                learned_global_attempted - learned_right
                if args.learned_right_policy == "global-ncc"
                and args.learned_global_max_disparity_diff_px > 0.0
                else 0
            )
            totals["feature_frames"] += 1
            totals["left_observations"] += left_count
            totals["right_observations"] += len(matched_indices)
            totals["learned_left_observations"] += int(learned_left.sum())
            totals["learned_right_observations"] += learned_right
            totals["learned_right_rejected_policy"] += learned_rejected_policy
            totals["learned_right_rejected_global_disparity"] += learned_rejected_global
            metric_rows.append(
                {
                    "stamp_ns": stamp_ns,
                    "left_observations": left_count,
                    "right_observations": len(matched_indices),
                    "stereo_match_ratio": len(matched_indices) / left_count if left_count else 0.0,
                    "learned_left_observations": int(learned_left.sum()),
                    "learned_right_observations": learned_right,
                    "learned_right_rejected_policy": learned_rejected_policy,
                    "learned_right_rejected_global_disparity": learned_rejected_global,
                    "learned_global_disparity_diff_median_px": (
                        float(
                            np.median(
                                learned_global_difference[
                                    matched_indices[learned_left[matched_indices]]
                                ]
                            )
                        )
                        if learned_right
                        else math.nan
                    ),
                    "learned_global_best_ncc_median": (
                        float(
                            np.median(
                                learned_global_best_ncc[
                                    matched_indices[learned_left[matched_indices]]
                                ]
                            )
                        )
                        if learned_right
                        else math.nan
                    ),
                    "median_disparity_px": (
                        float(np.median(disparity[matched_indices]))
                        if len(matched_indices)
                        else math.nan
                    ),
                    "median_fb_px": (
                        float(np.median(fb_error[matched_indices]))
                        if len(matched_indices)
                        else math.nan
                    ),
                    "median_epipolar_px": (
                        float(np.median(epipolar_error[matched_indices]))
                        if len(matched_indices)
                        else math.nan
                    ),
                    "median_ncc": (
                        float(np.median(ncc[matched_indices]))
                        if len(matched_indices)
                        else math.nan
                    ),
                }
            )

    with metrics_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(metric_rows[0]))
        writer.writeheader()
        writer.writerows(metric_rows)

    manifest = {
        "schema_version": "aqua-fe-mimir-stereo-lk-augmentation-v1",
        "feature_bag": str(feature_bag),
        "feature_bag_sha256": sha256(feature_bag),
        "sequence_dir": str(sequence_dir),
        "output_bag": str(output_bag),
        "output_bag_sha256": sha256(output_bag),
        "metrics_csv": str(metrics_csv),
        "parameters": {
            "win_size": args.win_size,
            "max_level": args.max_level,
            "max_fb_px": args.max_fb_px,
            "max_epipolar_px": args.max_epipolar_px,
            "min_disparity_px": args.min_disparity_px,
            "max_disparity_px": args.max_disparity_px,
            "border_px": args.border_px,
            "min_ncc": args.min_ncc,
            "ncc_radius": args.ncc_radius,
            "learned_right_policy": args.learned_right_policy,
            "learned_global_max_disparity_diff_px": (
                args.learned_global_max_disparity_diff_px
            ),
            "learned_global_ncc_radius": args.learned_global_ncc_radius,
        },
        "totals": totals,
        "lineage_policy": (
            "cam1 observation keeps the cam0 feature ID and all non-geometric "
            "lineage fields, including is_learned"
        ),
    }
    manifest_path = output_bag.with_suffix(output_bag.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"output_bag={output_bag}")
    print(f"metrics_csv={metrics_csv}")
    for key, value in totals.items():
        print(f"{key}={value}")
    if totals["left_observations"]:
        print(
            "stereo_match_ratio="
            f"{totals['right_observations'] / totals['left_observations']:.6f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
