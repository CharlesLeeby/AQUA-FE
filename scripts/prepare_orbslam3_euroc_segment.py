#!/usr/bin/env python3
"""Export a timestamp-aligned ROS bag segment in ORB-SLAM3's EuRoC layout."""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from pathlib import Path

import cv2
import numpy as np
import rosbag
import rospy
from cv_bridge import CvBridge, CvBridgeError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bag", required=True)
    parser.add_argument("--image-topic", required=True)
    parser.add_argument("--imu-topic", required=True)
    parser.add_argument("--gt-tum", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--start-offset", type=float, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--every-n", type=int, default=1)
    parser.add_argument("--imu-margin", type=float, default=0.5)
    parser.add_argument("--gt-margin", type=float, default=0.6)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def message_stamp(msg: object, fallback: rospy.Time) -> rospy.Time:
    header = getattr(msg, "header", None)
    stamp = getattr(header, "stamp", None)
    if stamp is not None and stamp.to_nsec() > 0:
        return stamp
    return fallback


def to_mono8(bridge: CvBridge, msg: object) -> np.ndarray:
    # AFRL stereo bags publish compressed images; keep the EuRoC exporter
    # compatible with both raw sensor_msgs/Image and CompressedImage.
    if hasattr(msg, "data") and not hasattr(msg, "encoding"):
        compressed = np.frombuffer(msg.data, dtype=np.uint8)
        image = cv2.imdecode(compressed, cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise RuntimeError("failed to decode compressed image")
        return np.asarray(image, dtype=np.uint8)
    try:
        image = bridge.imgmsg_to_cv2(msg, desired_encoding="mono8")
    except CvBridgeError as exc:
        raise RuntimeError(f"failed to decode image with encoding {getattr(msg, 'encoding', '?')}: {exc}") from exc
    image = np.asarray(image)
    if image.ndim != 2 or image.dtype != np.uint8:
        raise RuntimeError(f"expected mono8 image, got shape={image.shape} dtype={image.dtype}")
    return image


def load_gt_rows(path: Path, start_sec: float, end_sec: float) -> list[list[str]]:
    rows: list[list[str]] = []
    with path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split()
            if len(fields) < 8:
                continue
            try:
                stamp = float(fields[0])
            except ValueError:
                continue
            if start_sec <= stamp <= end_sec:
                rows.append(fields[:8])
    return rows


def main() -> int:
    args = parse_args()
    if args.duration <= 0:
        raise SystemExit("--duration must be positive")
    if args.start_offset < 0:
        raise SystemExit("--start-offset must be non-negative")
    if args.every_n < 1:
        raise SystemExit("--every-n must be at least 1")

    bag_path = Path(args.bag).resolve()
    gt_path = Path(args.gt_tum).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not bag_path.is_file():
        raise SystemExit(f"missing bag: {bag_path}")
    if not gt_path.is_file():
        raise SystemExit(f"missing TUM ground truth: {gt_path}")
    if output_dir.exists():
        if not args.overwrite:
            raise SystemExit(f"output exists; pass --overwrite to replace it: {output_dir}")
        shutil.rmtree(output_dir)

    image_dir = output_dir / "mav0" / "cam0" / "data"
    imu_dir = output_dir / "mav0" / "imu0"
    gt_dir = output_dir / "mav0" / "state_groundtruth_estimate0"
    image_dir.mkdir(parents=True)
    imu_dir.mkdir(parents=True)
    gt_dir.mkdir(parents=True)

    bridge = CvBridge()
    image_stamps: list[int] = []
    imu_rows: list[tuple[int, float, float, float, float, float, float]] = []
    seen_images = 0
    skipped_duplicate_images = 0
    skipped_duplicate_imu = 0
    image_shape: tuple[int, int] | None = None
    image_encoding = ""

    with rosbag.Bag(str(bag_path), "r") as bag:
        bag_start = float(bag.get_start_time())
        bag_end = float(bag.get_end_time())
        segment_start = bag_start + float(args.start_offset)
        segment_end = segment_start + float(args.duration)
        if segment_start >= bag_end or segment_end > bag_end + 1e-6:
            raise SystemExit(
                f"requested [{segment_start:.6f}, {segment_end:.6f}] outside bag "
                f"[{bag_start:.6f}, {bag_end:.6f}]"
            )

        read_start = rospy.Time.from_sec(max(bag_start, segment_start - max(0.0, args.imu_margin)))
        read_end = rospy.Time.from_sec(segment_end)
        for topic, msg, record_stamp in bag.read_messages(
            topics=[args.image_topic, args.imu_topic],
            start_time=read_start,
            end_time=read_end,
        ):
            stamp = message_stamp(msg, record_stamp)
            stamp_sec = stamp.to_sec()
            stamp_ns = stamp.to_nsec()
            if topic == args.imu_topic:
                if stamp_sec < segment_start - max(0.0, args.imu_margin):
                    continue
                if imu_rows and stamp_ns == imu_rows[-1][0]:
                    skipped_duplicate_imu += 1
                    continue
                angular_velocity = msg.angular_velocity
                linear_acceleration = msg.linear_acceleration
                values = (
                    stamp_ns,
                    float(angular_velocity.x),
                    float(angular_velocity.y),
                    float(angular_velocity.z),
                    float(linear_acceleration.x),
                    float(linear_acceleration.y),
                    float(linear_acceleration.z),
                )
                if all(math.isfinite(value) for value in values[1:]):
                    imu_rows.append(values)
                continue

            if not (segment_start <= stamp_sec <= segment_end):
                continue
            source_index = seen_images
            seen_images += 1
            if source_index % args.every_n != 0:
                continue
            if image_stamps and stamp_ns == image_stamps[-1]:
                skipped_duplicate_images += 1
                continue
            image = to_mono8(bridge, msg)
            if not cv2.imwrite(str(image_dir / f"{stamp_ns}.png"), image):
                raise RuntimeError(f"failed to write image at {stamp_ns}")
            image_stamps.append(stamp_ns)
            image_shape = image.shape
            image_encoding = str(getattr(msg, "encoding", ""))

    if not image_stamps:
        raise SystemExit("no images exported")
    if not imu_rows:
        raise SystemExit("no IMU samples exported")
    if imu_rows[0][0] > image_stamps[0]:
        raise SystemExit("first IMU timestamp is later than first image timestamp")

    times_path = output_dir / "cam0_times.txt"
    times_path.write_text("".join(f"{stamp}\n" for stamp in image_stamps), encoding="ascii")

    with (imu_dir / "data.csv").open("w", newline="", encoding="ascii") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "#timestamp [ns]",
                "w_RS_S_x [rad s^-1]",
                "w_RS_S_y [rad s^-1]",
                "w_RS_S_z [rad s^-1]",
                "a_RS_S_x [m s^-2]",
                "a_RS_S_y [m s^-2]",
                "a_RS_S_z [m s^-2]",
            ]
        )
        writer.writerows(imu_rows)

    gt_rows = load_gt_rows(
        gt_path,
        image_stamps[0] * 1e-9 - max(0.0, args.gt_margin),
        image_stamps[-1] * 1e-9 + max(0.0, args.gt_margin),
    )
    if not gt_rows:
        raise SystemExit("no ground-truth poses overlap the exported images")
    gt_text = "".join(" ".join(row) + "\n" for row in gt_rows)
    (output_dir / "groundtruth_tum.txt").write_text(gt_text, encoding="ascii")

    with (gt_dir / "data.csv").open("w", newline="", encoding="ascii") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "#timestamp",
                "p_RS_R_x [m]",
                "p_RS_R_y [m]",
                "p_RS_R_z [m]",
                "q_RS_w []",
                "q_RS_x []",
                "q_RS_y []",
                "q_RS_z []",
            ]
        )
        for stamp, px, py, pz, qx, qy, qz, qw in gt_rows:
            writer.writerow([int(round(float(stamp) * 1e9)), px, py, pz, qw, qx, qy, qz])

    metadata = {
        "bag": str(bag_path),
        "image_topic": args.image_topic,
        "imu_topic": args.imu_topic,
        "gt_tum": str(gt_path),
        "bag_start_sec": bag_start,
        "segment_start_sec": segment_start,
        "segment_end_sec": segment_end,
        "start_offset_sec": float(args.start_offset),
        "duration_sec": float(args.duration),
        "every_n": int(args.every_n),
        "first_image_ns": image_stamps[0],
        "last_image_ns": image_stamps[-1],
        "image_count": len(image_stamps),
        "image_height": int(image_shape[0]) if image_shape else 0,
        "image_width": int(image_shape[1]) if image_shape else 0,
        "source_image_encoding": image_encoding,
        "imu_count": len(imu_rows),
        "first_imu_ns": imu_rows[0][0],
        "last_imu_ns": imu_rows[-1][0],
        "gt_count": len(gt_rows),
        "skipped_duplicate_images": skipped_duplicate_images,
        "skipped_duplicate_imu": skipped_duplicate_imu,
    }
    (output_dir / "export_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(json.dumps(metadata, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
