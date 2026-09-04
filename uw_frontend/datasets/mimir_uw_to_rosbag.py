#!/usr/bin/env python3
"""Convert a MIMIR-UW track window into a compact ROS1 VINS input bag."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

import cv2
import numpy as np
import rosbag
import rospy
from geometry_msgs.msg import Quaternion
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Image, Imu
from std_msgs.msg import Header


@dataclass(frozen=True)
class ImageRow:
    stamp_ns: int
    filename: str


@dataclass(frozen=True)
class ImuRow:
    stamp_ns: int
    gyro: Tuple[float, float, float]
    accel: Tuple[float, float, float]


@dataclass(frozen=True)
class PoseRow:
    stamp_ns: int
    position: Tuple[float, float, float]
    orientation_wxyz: Tuple[float, float, float, float]


Row = Union[ImageRow, ImuRow, PoseRow]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert one MIMIR-UW track or time window to a ROS1 bag."
    )
    parser.add_argument(
        "--sequence-dir",
        required=True,
        type=Path,
        help="Track directory containing auv0/rgb, auv0/imu0, and pose_groundtruth.",
    )
    parser.add_argument("--output-bag", required=True, type=Path)
    parser.add_argument("--start-offset", type=float, default=0.0)
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Window duration in seconds; omit to export through the last image.",
    )
    parser.add_argument("--imu-margin-s", type=float, default=0.25)
    parser.add_argument(
        "--compression",
        choices=("none", "bz2", "lz4"),
        default="lz4",
        help="ROS bag compression; LZ4 is the fast default for replay datasets.",
    )
    parser.add_argument("--image-topic", default="/camera/image_raw")
    parser.add_argument(
        "--image1-topic",
        default="",
        help="Optional synchronized cam1 topic; enables stereo export when non-empty.",
    )
    parser.add_argument(
        "--omit-cam0",
        action="store_true",
        help="Write only cam1 (plus IMU/GT); requires --image1-topic.",
    )
    parser.add_argument(
        "--images-only",
        action="store_true",
        help="Do not write IMU or ground truth (useful for an auxiliary cam1-only bag).",
    )
    parser.add_argument("--imu-topic", default="/imu0")
    parser.add_argument("--gt-topic", default="/mimir/ground_truth")
    parser.add_argument("--image-frame-id", default="mimir_cam0")
    parser.add_argument("--image1-frame-id", default="mimir_cam1")
    parser.add_argument("--imu-frame-id", default="mimir_imu")
    parser.add_argument("--gt-frame-id", default="mimir_world")
    parser.add_argument("--body-frame-id", default="mimir_body")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Conversion manifest path; defaults beside the output bag.",
    )
    return parser.parse_args()


def _require_finite(values: Sequence[float], label: str) -> None:
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"non-finite {label}: {values}")


def _read_image_rows(path: Path) -> Tuple[List[ImageRow], List[Dict[str, object]]]:
    rows: List[ImageRow] = []
    duplicates: List[Dict[str, object]] = []
    seen: Dict[int, str] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["timestamp", "filename"]:
            raise ValueError(f"unexpected MIMIR camera CSV header in {path}: {reader.fieldnames}")
        for csv_line, record in enumerate(reader, start=2):
            stamp_ns = int(record["timestamp"])
            filename = record["filename"]
            previous = seen.get(stamp_ns)
            if previous is not None:
                if previous != filename:
                    raise ValueError(
                        f"conflicting camera rows at {stamp_ns}: {previous!r} != {filename!r}"
                    )
                duplicates.append(
                    {"csv_line": csv_line, "timestamp_ns": stamp_ns, "filename": filename}
                )
                continue
            seen[stamp_ns] = filename
            rows.append(ImageRow(stamp_ns=stamp_ns, filename=filename))
    _require_strictly_increasing([row.stamp_ns for row in rows], "camera")
    return rows, duplicates


def _read_imu_rows(path: Path) -> List[ImuRow]:
    rows: List[ImuRow] = []
    expected = [
        "timestamp",
        "vx",
        "vy",
        "vz",
        "ax",
        "ay",
        "az",
        "q_0_kf_w",
        "q_0_kf_x",
        "q_0_kf_y",
        "q_0_kf_z",
    ]
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != expected:
            raise ValueError(f"unexpected MIMIR IMU CSV header in {path}: {reader.fieldnames}")
        for record in reader:
            gyro = tuple(float(record[key]) for key in ("vx", "vy", "vz"))
            accel = tuple(float(record[key]) for key in ("ax", "ay", "az"))
            _require_finite(gyro + accel, "IMU sample")
            rows.append(ImuRow(stamp_ns=int(record["timestamp"]), gyro=gyro, accel=accel))
    _require_strictly_increasing([row.stamp_ns for row in rows], "IMU")
    return rows


def _read_pose_rows(path: Path) -> List[PoseRow]:
    rows: List[PoseRow] = []
    expected = [
        "timestamp",
        "t_0_kf_X",
        "t_0_kf_Y",
        "t_0_kf_Z",
        "q_0_kf_w",
        "q_0_kf_x",
        "q_0_kf_y",
        "q_0_kf_z",
    ]
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != expected:
            raise ValueError(f"unexpected MIMIR pose CSV header in {path}: {reader.fieldnames}")
        for record in reader:
            position = tuple(float(record[key]) for key in expected[1:4])
            orientation = tuple(float(record[key]) for key in expected[4:8])
            _require_finite(position + orientation, "ground-truth pose")
            rows.append(
                PoseRow(
                    stamp_ns=int(record["timestamp"]),
                    position=position,
                    orientation_wxyz=orientation,
                )
            )
    _require_strictly_increasing([row.stamp_ns for row in rows], "ground truth")
    return rows


def _require_strictly_increasing(stamps: Sequence[int], label: str) -> None:
    if not stamps:
        raise ValueError(f"empty {label} timeline")
    for index, (left, right) in enumerate(zip(stamps, stamps[1:])):
        if right <= left:
            raise ValueError(
                f"non-increasing {label} timestamp at index {index}: {left} -> {right}"
            )


def _ros_time(stamp_ns: int) -> rospy.Time:
    seconds, nanoseconds = divmod(int(stamp_ns), 1_000_000_000)
    return rospy.Time(secs=seconds, nsecs=nanoseconds)


def _read_gray_image(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"failed to decode MIMIR image: {path}")
    return image


def _make_image_msg(image: np.ndarray, stamp: rospy.Time, frame_id: str) -> Image:
    msg = Image()
    msg.header = Header(stamp=stamp, frame_id=frame_id)
    msg.height, msg.width = [int(value) for value in image.shape[:2]]
    msg.encoding = "mono8"
    msg.is_bigendian = 0
    msg.step = msg.width
    msg.data = image.astype(np.uint8, copy=False).tobytes()
    return msg


def _make_imu_msg(row: ImuRow, stamp: rospy.Time, frame_id: str) -> Imu:
    msg = Imu()
    msg.header = Header(stamp=stamp, frame_id=frame_id)
    msg.angular_velocity.x, msg.angular_velocity.y, msg.angular_velocity.z = row.gyro
    msg.linear_acceleration.x, msg.linear_acceleration.y, msg.linear_acceleration.z = row.accel
    msg.orientation_covariance[0] = -1.0
    return msg


def _make_gt_msg(
    row: PoseRow, stamp: rospy.Time, world_frame_id: str, body_frame_id: str
) -> Odometry:
    msg = Odometry()
    msg.header = Header(stamp=stamp, frame_id=world_frame_id)
    msg.child_frame_id = body_frame_id
    msg.pose.pose.position.x, msg.pose.pose.position.y, msg.pose.pose.position.z = row.position
    qw, qx, qy, qz = row.orientation_wxyz
    msg.pose.pose.orientation = Quaternion(x=qx, y=qy, z=qz, w=qw)
    return msg


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def main() -> int:
    args = parse_args()
    if args.omit_cam0 and not args.image1_topic:
        raise SystemExit("--omit-cam0 requires non-empty --image1-topic")
    sequence_dir = args.sequence_dir.resolve()
    auv_dir = sequence_dir / "auv0"
    camera_dir = auv_dir / "rgb" / "cam0"
    camera1_dir = auv_dir / "rgb" / "cam1"
    image_csv = camera_dir / "data.csv"
    image1_csv = camera1_dir / "data.csv"
    imu_csv = auv_dir / "imu0" / "data.csv"
    pose_csv = auv_dir / "pose_groundtruth" / "data.csv"
    required_files = [image_csv, imu_csv, pose_csv]
    if args.image1_topic:
        required_files.append(image1_csv)
    for required in required_files:
        if not required.is_file():
            raise SystemExit(f"missing MIMIR input: {required}")

    image_rows, duplicates = _read_image_rows(image_csv)
    image1_rows: List[ImageRow] = []
    duplicates1: List[Dict[str, object]] = []
    if args.image1_topic:
        image1_rows, duplicates1 = _read_image_rows(image1_csv)
        cam0_stamps = [row.stamp_ns for row in image_rows]
        cam1_stamps = [row.stamp_ns for row in image1_rows]
        if cam0_stamps != cam1_stamps:
            raise SystemExit(
                "MIMIR cam0/cam1 CSV timelines are not exactly synchronized"
            )
    imu_rows = _read_imu_rows(imu_csv)
    pose_rows = _read_pose_rows(pose_csv)

    start_offset_ns = int(max(0.0, args.start_offset) * 1e9)
    start_ns = image_rows[0].stamp_ns + start_offset_ns
    end_ns = (
        image_rows[-1].stamp_ns
        if args.duration is None
        else start_ns + int(max(0.0, args.duration) * 1e9)
    )
    margin_ns = int(max(0.0, args.imu_margin_s) * 1e9)
    window_images = [row for row in image_rows if start_ns <= row.stamp_ns <= end_ns]
    window_images1 = [
        row for row in image1_rows if start_ns <= row.stamp_ns <= end_ns
    ]
    window_imu = [
        row for row in imu_rows if (start_ns - margin_ns) <= row.stamp_ns <= (end_ns + margin_ns)
    ]
    window_pose = [row for row in pose_rows if start_ns <= row.stamp_ns <= end_ns]
    if not window_images:
        raise SystemExit(
            f"empty MIMIR image window: start_offset={args.start_offset}, duration={args.duration}"
        )
    if args.image1_topic and len(window_images1) != len(window_images):
        raise SystemExit(
            f"stereo window count mismatch: cam0={len(window_images)} cam1={len(window_images1)}"
        )
    if not window_imu or not window_pose:
        raise SystemExit("empty MIMIR IMU or ground-truth window")
    missing_images = []
    if not args.omit_cam0:
        missing_images.extend(
            str(camera_dir / "data" / row.filename)
            for row in window_images
            if not (camera_dir / "data" / row.filename).is_file()
        )
    if args.image1_topic:
        missing_images.extend(
            str(camera1_dir / "data" / row.filename)
            for row in window_images1
            if not (camera1_dir / "data" / row.filename).is_file()
        )
    if missing_images:
        raise SystemExit(
            f"missing {len(missing_images)} selected images; first={missing_images[0]}"
        )
    if not (
        window_imu[0].stamp_ns <= window_images[0].stamp_ns
        and window_images[-1].stamp_ns <= window_imu[-1].stamp_ns
    ):
        raise SystemExit("IMU window does not cover the selected camera window")

    # At equal timestamps, write IMU before GT and images so online consumers
    # can integrate the latest inertial measurement before a visual update.
    events: List[Tuple[int, int, str, Row]] = []
    if not args.images_only:
        events.extend((row.stamp_ns, 0, "imu", row) for row in window_imu)
        events.extend((row.stamp_ns, 1, "gt", row) for row in window_pose)
    if not args.omit_cam0:
        events.extend((row.stamp_ns, 2, "image", row) for row in window_images)
    events.extend((row.stamp_ns, 3, "image1", row) for row in window_images1)
    events.sort(key=lambda item: (item[0], item[1]))

    output_bag = args.output_bag.resolve()
    output_bag.parent.mkdir(parents=True, exist_ok=True)
    counts = {"image": 0, "imu": 0, "gt": 0}
    if args.image1_topic:
        counts["image1"] = 0
    compression = {
        "none": rosbag.Compression.NONE,
        "bz2": rosbag.Compression.BZ2,
        "lz4": rosbag.Compression.LZ4,
    }[args.compression]
    with rosbag.Bag(str(output_bag), "w", compression=compression) as bag:
        for stamp_ns, _priority, kind, row in events:
            stamp = _ros_time(stamp_ns)
            if kind == "imu":
                assert isinstance(row, ImuRow)
                bag.write(args.imu_topic, _make_imu_msg(row, stamp, args.imu_frame_id), stamp)
            elif kind == "gt":
                assert isinstance(row, PoseRow)
                bag.write(
                    args.gt_topic,
                    _make_gt_msg(row, stamp, args.gt_frame_id, args.body_frame_id),
                    stamp,
                )
            elif kind == "image":
                assert isinstance(row, ImageRow)
                image = _read_gray_image(camera_dir / "data" / row.filename)
                bag.write(
                    args.image_topic,
                    _make_image_msg(image, stamp, args.image_frame_id),
                    stamp,
                )
            else:
                assert kind == "image1"
                assert isinstance(row, ImageRow)
                image = _read_gray_image(camera1_dir / "data" / row.filename)
                bag.write(
                    args.image1_topic,
                    _make_image_msg(image, stamp, args.image1_frame_id),
                    stamp,
                )
            counts[kind] += 1

    manifest_path: Path = args.manifest or output_bag.with_suffix(
        output_bag.suffix + ".manifest.json"
    )
    manifest = {
        "schema_version": "aqua-fe-mimir-uw-rosbag-v1",
        "source_sequence_dir": str(sequence_dir),
        "source_files": {
            str(path.relative_to(sequence_dir)): {
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in required_files
        },
        "output_bag": str(output_bag),
        "output_bag_size": output_bag.stat().st_size,
        "output_bag_sha256": _sha256(output_bag),
        "topics": {
            "image": args.image_topic,
            "image1": args.image1_topic,
            "imu": args.imu_topic,
            "ground_truth": args.gt_topic,
        },
        "counts": counts,
        "deduplicated_camera_rows": duplicates,
        "deduplicated_camera1_rows": duplicates1,
        "window": {
            "requested_start_offset_s": args.start_offset,
            "requested_duration_s": args.duration,
            "first_image_stamp_ns": window_images[0].stamp_ns,
            "last_image_stamp_ns": window_images[-1].stamp_ns,
            "actual_image_span_s": (window_images[-1].stamp_ns - window_images[0].stamp_ns)
            * 1e-9,
            "imu_margin_s": args.imu_margin_s,
        },
        "timestamp_policy": "exact integer nanoseconds copied from MIMIR CSV",
        "compression": args.compression,
        "omit_cam0": bool(args.omit_cam0),
        "images_only": bool(args.images_only),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote_bag={output_bag}")
    print(f"manifest={manifest_path}")
    print(f"images={counts['image']} imu={counts['imu']} gt={counts['gt']}")
    if args.image1_topic:
        print(f"images1={counts['image1']}")
    print(f"deduplicated_camera_rows={len(duplicates)}")
    print(f"span_s={manifest['window']['actual_image_span_s']:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
