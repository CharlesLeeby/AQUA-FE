#!/usr/bin/env python3
"""Export an AQUALOC ROS bag to ORB-SLAM3's EuRoC-style layout."""

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
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--image-topic", default="/camera/image_raw")
    parser.add_argument("--imu-topic", default="/rtimulib_node/imu")
    parser.add_argument("--gt-topic", default="/aqualoc/colmap_gt")
    parser.add_argument(
        "--gt-bag",
        help="Optional bag supplying the GT topic when the image/IMU bag has no GT.",
    )
    parser.add_argument(
        "--feature-times-bag",
        help="Optional feature bag whose header timestamps select exported images.",
    )
    parser.add_argument(
        "--feature-times-topic", default="/feature_tracker/feature"
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def message_stamp(msg: object, fallback: rospy.Time) -> rospy.Time:
    header = getattr(msg, "header", None)
    stamp = getattr(header, "stamp", None)
    if stamp is not None and stamp.to_nsec() > 0:
        return stamp
    return fallback


def to_mono8(bridge: CvBridge, msg: object) -> np.ndarray:
    try:
        image = bridge.imgmsg_to_cv2(msg, desired_encoding="mono8")
    except CvBridgeError as exc:
        raise RuntimeError(
            f"failed to decode image encoding={getattr(msg, 'encoding', '?')}: {exc}"
        ) from exc
    image = np.asarray(image)
    if image.ndim != 2 or image.dtype != np.uint8:
        raise RuntimeError(f"expected mono8 image, got {image.shape=} {image.dtype=}")
    return image


def first_topic_stamp(bag_path: Path, topic: str) -> int:
    with rosbag.Bag(str(bag_path), "r") as bag:
        for _, msg, record_stamp in bag.read_messages(topics=[topic]):
            return message_stamp(msg, record_stamp).to_nsec()
    raise RuntimeError(f"no messages on {topic} in {bag_path}")


def feature_image_times(bag_path: Path, topic: str) -> list[int]:
    times: list[int] = []
    with rosbag.Bag(str(bag_path), "r") as bag:
        for _, msg, record_stamp in bag.read_messages(topics=[topic]):
            stamp_ns = message_stamp(msg, record_stamp).to_nsec()
            if times and stamp_ns <= times[-1]:
                raise RuntimeError(
                    f"feature timestamps are not strictly increasing on {topic}"
                )
            times.append(stamp_ns)
    if not times:
        raise RuntimeError(f"no messages on {topic} in {bag_path}")
    return times


def main() -> int:
    args = parse_args()
    bag_path = Path(args.bag).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not bag_path.is_file():
        raise SystemExit(f"missing bag: {bag_path}")
    feature_times_bag = (
        Path(args.feature_times_bag).resolve() if args.feature_times_bag else None
    )
    if feature_times_bag is not None and not feature_times_bag.is_file():
        raise SystemExit(f"missing feature-times bag: {feature_times_bag}")
    gt_bag_path = Path(args.gt_bag).resolve() if args.gt_bag else None
    if gt_bag_path is not None and not gt_bag_path.is_file():
        raise SystemExit(f"missing GT bag: {gt_bag_path}")
    if output_dir.exists():
        if not args.overwrite:
            raise SystemExit(f"output exists; pass --overwrite to replace it: {output_dir}")
        shutil.rmtree(output_dir)

    image_dir = output_dir / "mav0/cam0/data"
    imu_dir = output_dir / "mav0/imu0"
    gt_dir = output_dir / "mav0/state_groundtruth_estimate0"
    image_dir.mkdir(parents=True)
    imu_dir.mkdir(parents=True)
    gt_dir.mkdir(parents=True)

    first_imu_ns = first_topic_stamp(bag_path, args.imu_topic)
    requested_image_times = (
        feature_image_times(feature_times_bag, args.feature_times_topic)
        if feature_times_bag is not None
        else []
    )
    requested_image_time_set = set(requested_image_times)
    bridge = CvBridge()
    image_stamps: list[int] = []
    imu_rows: list[tuple[int, float, float, float, float, float, float]] = []
    gt_rows: list[tuple[int, float, float, float, float, float, float, float]] = []
    skipped_images_before_imu = 0
    skipped_duplicate_images = 0
    skipped_duplicate_imu = 0
    skipped_duplicate_gt = 0
    image_shape: tuple[int, int] | None = None
    source_encoding = ""

    def append_gt(msg: object, record_stamp: rospy.Time) -> None:
        nonlocal skipped_duplicate_gt
        stamp_ns = message_stamp(msg, record_stamp).to_nsec()
        if gt_rows and stamp_ns == gt_rows[-1][0]:
            skipped_duplicate_gt += 1
            return
        if gt_rows and stamp_ns < gt_rows[-1][0]:
            raise RuntimeError("GT header timestamps are not monotonic")
        p = msg.pose.pose.position
        q = msg.pose.pose.orientation
        values = (
            stamp_ns,
            float(p.x),
            float(p.y),
            float(p.z),
            float(q.x),
            float(q.y),
            float(q.z),
            float(q.w),
        )
        if all(math.isfinite(value) for value in values[1:]):
            gt_rows.append(values)

    with rosbag.Bag(str(bag_path), "r") as bag:
        bag_start_sec = float(bag.get_start_time())
        bag_end_sec = float(bag.get_end_time())
        topics = [args.image_topic, args.imu_topic]
        if gt_bag_path is None:
            topics.append(args.gt_topic)
        for topic, msg, record_stamp in bag.read_messages(
            topics=topics
        ):
            stamp = message_stamp(msg, record_stamp)
            stamp_ns = stamp.to_nsec()
            if topic == args.image_topic:
                if stamp_ns < first_imu_ns:
                    skipped_images_before_imu += 1
                    continue
                if image_stamps and stamp_ns == image_stamps[-1]:
                    skipped_duplicate_images += 1
                    continue
                if image_stamps and stamp_ns < image_stamps[-1]:
                    raise RuntimeError("image header timestamps are not monotonic")
                if requested_image_time_set and stamp_ns not in requested_image_time_set:
                    continue
                image = to_mono8(bridge, msg)
                if not cv2.imwrite(str(image_dir / f"{stamp_ns}.png"), image):
                    raise RuntimeError(f"failed to write image {stamp_ns}")
                image_stamps.append(stamp_ns)
                image_shape = image.shape
                source_encoding = str(getattr(msg, "encoding", ""))
                continue

            if topic == args.imu_topic:
                if imu_rows and stamp_ns == imu_rows[-1][0]:
                    skipped_duplicate_imu += 1
                    continue
                if imu_rows and stamp_ns < imu_rows[-1][0]:
                    raise RuntimeError("IMU header timestamps are not monotonic")
                w = msg.angular_velocity
                a = msg.linear_acceleration
                values = (
                    stamp_ns,
                    float(w.x),
                    float(w.y),
                    float(w.z),
                    float(a.x),
                    float(a.y),
                    float(a.z),
                )
                if all(math.isfinite(value) for value in values[1:]):
                    imu_rows.append(values)
                continue

            append_gt(msg, record_stamp)

    if gt_bag_path is not None:
        with rosbag.Bag(str(gt_bag_path), "r") as bag:
            for _, msg, record_stamp in bag.read_messages(topics=[args.gt_topic]):
                append_gt(msg, record_stamp)

    if not image_stamps or not imu_rows or not gt_rows:
        raise SystemExit(
            f"incomplete export: images={len(image_stamps)} IMU={len(imu_rows)} GT={len(gt_rows)}"
        )
    if requested_image_times and image_stamps != requested_image_times:
        missing = sorted(requested_image_time_set.difference(image_stamps))
        unexpected = sorted(set(image_stamps).difference(requested_image_time_set))
        raise SystemExit(
            "feature-selected image mismatch: "
            f"missing={len(missing)} unexpected={len(unexpected)}"
        )
    if imu_rows[0][0] > image_stamps[0]:
        raise SystemExit("first IMU timestamp is later than first kept image")

    (output_dir / "cam0_times.txt").write_text(
        "".join(f"{stamp}\n" for stamp in image_stamps), encoding="ascii"
    )
    (output_dir / "groundtruth_tum.txt").write_text(
        "".join(
            f"{stamp * 1e-9:.9f} {px:.12f} {py:.12f} {pz:.12f} "
            f"{qx:.12f} {qy:.12f} {qz:.12f} {qw:.12f}\n"
            for stamp, px, py, pz, qx, qy, qz, qw in gt_rows
        ),
        encoding="ascii",
    )

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
            writer.writerow([stamp, px, py, pz, qw, qx, qy, qz])

    metadata = {
        "bag": str(bag_path),
        "image_topic": args.image_topic,
        "imu_topic": args.imu_topic,
        "gt_topic": args.gt_topic,
        "gt_bag": str(gt_bag_path) if gt_bag_path else None,
        "feature_times_bag": str(feature_times_bag) if feature_times_bag else None,
        "feature_times_topic": (
            args.feature_times_topic if feature_times_bag else None
        ),
        "requested_image_count": len(requested_image_times),
        "bag_start_sec": bag_start_sec,
        "bag_end_sec": bag_end_sec,
        "first_imu_ns": imu_rows[0][0],
        "last_imu_ns": imu_rows[-1][0],
        "first_kept_image_ns": image_stamps[0],
        "last_kept_image_ns": image_stamps[-1],
        "kept_images": len(image_stamps),
        "imu_count": len(imu_rows),
        "gt_count": len(gt_rows),
        "image_height": int(image_shape[0]) if image_shape else 0,
        "image_width": int(image_shape[1]) if image_shape else 0,
        "source_image_encoding": source_encoding,
        "skipped_images_before_imu": skipped_images_before_imu,
        "skipped_duplicate_images": skipped_duplicate_images,
        "skipped_duplicate_imu": skipped_duplicate_imu,
        "skipped_duplicate_gt": skipped_duplicate_gt,
    }
    (output_dir / "export_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(json.dumps(metadata, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
