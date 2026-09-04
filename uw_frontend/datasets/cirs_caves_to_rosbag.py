#!/usr/bin/env python3
"""Prepare CIRS Girona Cala Viuda frames and text sensors as a VINS-friendly bag."""

from __future__ import annotations

import argparse
import csv
import json
import re
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from io import TextIOWrapper
from pathlib import Path

import cv2
import numpy as np
import rosbag
import rospy
from cv_bridge import CvBridge
from nav_msgs.msg import Odometry
from sensor_msgs.msg import CameraInfo
from sensor_msgs.msg import Image, Imu
from std_msgs.msg import Header


@dataclass(frozen=True)
class FrameStamp:
    index: int
    raw_name: str
    image_name: str
    stamp: float


class FrameSource:
    def __init__(self, path: Path):
        self.path = path
        self._zip: zipfile.ZipFile | None = None
        self._zip_by_basename: dict[str, str] = {}
        if path.is_file():
            self._zip = zipfile.ZipFile(path)
            self._zip_by_basename = {
                Path(name).name: name
                for name in self._zip.namelist()
                if not name.endswith("/")
            }

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()

    def read_gray(self, name: str) -> np.ndarray:
        if self._zip is not None:
            member = self._zip_by_basename.get(Path(name).name)
            if member is None:
                raise FileNotFoundError(f"{name} not found in {self.path}")
            data = np.frombuffer(self._zip.read(member), dtype=np.uint8)
            image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
        else:
            image = cv2.imread(str(self.path / name), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise RuntimeError(f"failed to decode image {name} from {self.path}")
        return image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", default="", help="frames zip file or extracted directory")
    parser.add_argument("--timestamps", default="")
    parser.add_argument("--camera-bag", default="")
    parser.add_argument("--camera-image-topic-in", default="/camera/image_raw")
    parser.add_argument("--camera-info-topic-in", default="/camera/camera_info")
    parser.add_argument("--sensor-zip", required=True, help="CIRS full_dataset.zip")
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--metadata-json", default="")
    parser.add_argument("--start-offset", type=float, default=0.0)
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--sensor-margin", type=float, default=0.5)
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--image-name-template", default="")
    parser.add_argument("--image-topic", default="/cirs/camera/image_mono")
    parser.add_argument("--imu-topic", default="/cirs/imu_xsens")
    parser.add_argument("--gt-topic", default="/cirs/odometry_gt")
    parser.add_argument("--image-frame-id", default="cirs_camera")
    parser.add_argument("--imu-frame-id", default="cirs_imu")
    parser.add_argument("--gt-frame-id", default="cirs_map")
    parser.add_argument("--gt-child-frame-id", default="cirs_body")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.duration <= 0.0:
        raise SystemExit("--duration must be positive")

    frames_path = Path(args.frames) if args.frames else None
    timestamps_path = Path(args.timestamps) if args.timestamps else None
    camera_bag = Path(args.camera_bag) if args.camera_bag else None
    sensor_zip = Path(args.sensor_zip)
    output_bag = Path(args.output_bag)
    metadata_path = Path(args.metadata_json) if args.metadata_json else output_bag.with_suffix(".json")
    output_bag.parent.mkdir(parents=True, exist_ok=True)

    bridge = CvBridge()
    timeline: list[tuple[rospy.Time, str, object]] = []
    camera_info: CameraInfo | None = None
    first_image_name = ""
    last_image_name = ""

    if camera_bag is not None:
        sequence_start = read_bag_start(camera_bag)
        start_stamp = sequence_start + float(args.start_offset)
        end_stamp = start_stamp + float(args.duration)
        image_count, image_shape, camera_info, first_image_name, last_image_name = append_camera_bag_images(
            timeline,
            camera_bag,
            args.camera_image_topic_in,
            args.camera_info_topic_in,
            start_stamp,
            end_stamp,
            int(args.max_frames),
            args.image_topic,
            args.image_frame_id,
        )
    else:
        if frames_path is None or timestamps_path is None:
            raise SystemExit("either --camera-bag or both --frames/--timestamps are required")
        frame_stamps = parse_frame_stamps(timestamps_path, args.image_name_template)
        if not frame_stamps:
            raise SystemExit(f"no frame timestamps in {timestamps_path}")
        sequence_start = frame_stamps[0].stamp
        start_stamp = sequence_start + float(args.start_offset)
        end_stamp = start_stamp + float(args.duration)
        selected = [row for row in frame_stamps if start_stamp <= row.stamp < end_stamp]
        if args.max_frames > 0:
            selected = selected[: int(args.max_frames)]
        if not selected:
            raise SystemExit(
                f"no frames selected for start_offset={args.start_offset} duration={args.duration}"
            )
        image_count, image_shape, first_image_name, last_image_name = append_frame_images(
            timeline,
            frames_path,
            selected,
            bridge,
            args.image_topic,
            args.image_frame_id,
        )

    sensor_start = start_stamp - float(args.sensor_margin)
    sensor_end = end_stamp + float(args.sensor_margin)
    imu_count = append_imu_messages(
        timeline,
        sensor_zip,
        sensor_start,
        sensor_end,
        args.imu_topic,
        args.imu_frame_id,
    )
    gt_count = append_odometry_messages(
        timeline,
        sensor_zip,
        sensor_start,
        sensor_end,
        args.gt_topic,
        args.gt_frame_id,
        args.gt_child_frame_id,
    )

    timeline.sort(key=lambda item: item[0].to_sec())
    with rosbag.Bag(str(output_bag), "w") as dst:
        for stamp, topic, msg in timeline:
            dst.write(topic, msg, stamp)

    height, width = image_shape if image_shape is not None else (0, 0)
    metadata = {
        "output_bag": str(output_bag),
        "frames": str(frames_path) if frames_path is not None else "",
        "timestamps": str(timestamps_path) if timestamps_path is not None else "",
        "camera_bag": str(camera_bag) if camera_bag is not None else "",
        "camera_image_topic_in": args.camera_image_topic_in,
        "camera_info_topic_in": args.camera_info_topic_in,
        "sensor_zip": str(sensor_zip),
        "sequence_start": sequence_start,
        "start_stamp": start_stamp,
        "end_stamp": end_stamp,
        "start_offset": float(args.start_offset),
        "duration": float(args.duration),
        "image_count": image_count,
        "imu_count": imu_count,
        "gt_count": gt_count,
        "image_width": width,
        "image_height": height,
        "first_image": first_image_name,
        "last_image": last_image_name,
        "image_topic": args.image_topic,
        "imu_topic": args.imu_topic,
        "gt_topic": args.gt_topic,
    }
    if camera_info is not None:
        metadata["camera_info"] = {
            "width": int(camera_info.width),
            "height": int(camera_info.height),
            "distortion_model": camera_info.distortion_model,
            "D": [float(v) for v in camera_info.D],
            "K": [float(v) for v in camera_info.K],
            "R": [float(v) for v in camera_info.R],
            "P": [float(v) for v in camera_info.P],
        }
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"wrote {output_bag}")
    print(
        f"images={image_count} imu={imu_count} gt={gt_count} "
        f"size={width}x{height} start={start_stamp:.6f} end={end_stamp:.6f}"
    )
    print(f"metadata={metadata_path}")
    return 0


def parse_frame_stamps(path: Path, image_name_template: str) -> list[FrameStamp]:
    rows: list[FrameStamp] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 2:
            continue
        raw_name = parts[0]
        stamp = float(parts[1])
        index = parse_frame_index(raw_name, len(rows))
        image_name = (
            image_name_template.format(index=index, raw_name=raw_name)
            if image_name_template
            else raw_name
        )
        rows.append(FrameStamp(index=index, raw_name=raw_name, image_name=image_name, stamp=stamp))
    rows.sort(key=lambda row: row.stamp)
    return rows


def parse_frame_index(name: str, fallback: int) -> int:
    match = re.search(r"(\d+)(?=\.[^.]+$)", Path(name).name)
    return int(match.group(1)) if match else fallback


def append_frame_images(
    timeline: list[tuple[rospy.Time, str, object]],
    frames_path: Path,
    selected: list[FrameStamp],
    bridge: CvBridge,
    topic: str,
    frame_id: str,
) -> tuple[int, tuple[int, int], str, str]:
    image_shape: tuple[int, int] | None = None
    source = FrameSource(frames_path)
    try:
        for row in selected:
            stamp = rospy.Time.from_sec(row.stamp)
            gray = source.read_gray(row.image_name)
            if image_shape is None:
                image_shape = gray.shape[:2]
            msg = bridge.cv2_to_imgmsg(gray, encoding="mono8")
            msg.header = Header(seq=row.index, stamp=stamp, frame_id=frame_id)
            timeline.append((stamp, topic, msg))
    finally:
        source.close()
    if image_shape is None:
        raise RuntimeError("selected frames produced no images")
    return len(selected), image_shape, selected[0].image_name, selected[-1].image_name


def read_bag_start(camera_bag: Path) -> float:
    with rosbag.Bag(str(camera_bag), "r") as bag:
        return float(bag.get_start_time())


def append_camera_bag_images(
    timeline: list[tuple[rospy.Time, str, object]],
    camera_bag: Path,
    image_topic_in: str,
    camera_info_topic_in: str,
    start_stamp: float,
    end_stamp: float,
    max_frames: int,
    image_topic_out: str,
    frame_id: str,
) -> tuple[int, tuple[int, int], CameraInfo | None, str, str]:
    start_time = rospy.Time.from_sec(start_stamp)
    end_time = rospy.Time.from_sec(end_stamp)
    image_count = 0
    image_shape: tuple[int, int] | None = None
    camera_info: CameraInfo | None = None
    first_image = ""
    last_image = ""
    topics = [image_topic_in, camera_info_topic_in]
    with rosbag.Bag(str(camera_bag), "r") as bag:
        for topic, msg, stamp in bag.read_messages(
            topics=topics,
            start_time=start_time,
            end_time=end_time,
        ):
            msg_stamp = message_stamp(msg, stamp)
            if topic == camera_info_topic_in and camera_info is None:
                camera_info = msg
            if topic != image_topic_in:
                continue
            if max_frames > 0 and image_count >= max_frames:
                continue
            msg.header.stamp = msg_stamp
            msg.header.frame_id = frame_id
            if image_shape is None:
                image_shape = (int(msg.height), int(msg.width))
                first_image = f"bag:{image_topic_in}:{msg_stamp.to_sec():.6f}"
            last_image = f"bag:{image_topic_in}:{msg_stamp.to_sec():.6f}"
            timeline.append((msg_stamp, image_topic_out, msg))
            image_count += 1
    if image_shape is None:
        raise SystemExit(
            f"no camera images selected from {camera_bag} for {start_stamp:.6f}-{end_stamp:.6f}"
        )
    return image_count, image_shape, camera_info, first_image, last_image


def message_stamp(msg, fallback: rospy.Time) -> rospy.Time:
    stamp = getattr(getattr(msg, "header", None), "stamp", None)
    if stamp is not None and stamp.to_sec() > 0.0:
        return stamp
    return fallback


def append_imu_messages(
    timeline: list[tuple[rospy.Time, str, object]],
    sensor_zip: Path,
    start_stamp: float,
    end_stamp: float,
    topic: str,
    frame_id: str,
) -> int:
    count = 0
    with open_zip_text(sensor_zip, "full_dataset/imu_xsens_mti_ros.txt") as handle:
        for row in csv.DictReader(handle):
            stamp = ns_to_sec(row["field.header.stamp"])
            if stamp < start_stamp or stamp > end_stamp:
                continue
            msg = Imu()
            msg.header = Header(
                seq=int(float(row.get("field.header.seq", count))),
                stamp=rospy.Time.from_sec(stamp),
                frame_id=frame_id,
            )
            msg.orientation.x = f(row, "field.orientation.x")
            msg.orientation.y = f(row, "field.orientation.y")
            msg.orientation.z = f(row, "field.orientation.z")
            msg.orientation.w = f(row, "field.orientation.w")
            msg.angular_velocity.x = f(row, "field.angular_velocity.x")
            msg.angular_velocity.y = f(row, "field.angular_velocity.y")
            msg.angular_velocity.z = f(row, "field.angular_velocity.z")
            msg.linear_acceleration.x = f(row, "field.linear_acceleration.x")
            msg.linear_acceleration.y = f(row, "field.linear_acceleration.y")
            msg.linear_acceleration.z = f(row, "field.linear_acceleration.z")
            msg.orientation_covariance = cov(row, "field.orientation_covariance", 9)
            msg.angular_velocity_covariance = cov(row, "field.angular_velocity_covariance", 9)
            msg.linear_acceleration_covariance = cov(row, "field.linear_acceleration_covariance", 9)
            timeline.append((msg.header.stamp, topic, msg))
            count += 1
    return count


def append_odometry_messages(
    timeline: list[tuple[rospy.Time, str, object]],
    sensor_zip: Path,
    start_stamp: float,
    end_stamp: float,
    topic: str,
    frame_id: str,
    child_frame_id: str,
) -> int:
    count = 0
    with open_zip_text(sensor_zip, "full_dataset/odometry.txt") as handle:
        for row in csv.DictReader(handle):
            stamp = ns_to_sec(row["field.header.stamp"])
            if stamp < start_stamp or stamp > end_stamp:
                continue
            msg = Odometry()
            msg.header = Header(
                seq=int(float(row.get("field.header.seq", count))),
                stamp=rospy.Time.from_sec(stamp),
                frame_id=frame_id,
            )
            msg.child_frame_id = child_frame_id
            msg.pose.pose.position.x = f(row, "field.pose.pose.position.x")
            msg.pose.pose.position.y = f(row, "field.pose.pose.position.y")
            msg.pose.pose.position.z = f(row, "field.pose.pose.position.z")
            msg.pose.pose.orientation.x = f(row, "field.pose.pose.orientation.x")
            msg.pose.pose.orientation.y = f(row, "field.pose.pose.orientation.y")
            msg.pose.pose.orientation.z = f(row, "field.pose.pose.orientation.z")
            msg.pose.pose.orientation.w = f(row, "field.pose.pose.orientation.w")
            msg.twist.twist.linear.x = f(row, "field.twist.twist.linear.x")
            msg.twist.twist.linear.y = f(row, "field.twist.twist.linear.y")
            msg.twist.twist.linear.z = f(row, "field.twist.twist.linear.z")
            msg.twist.twist.angular.x = f(row, "field.twist.twist.angular.x")
            msg.twist.twist.angular.y = f(row, "field.twist.twist.angular.y")
            msg.twist.twist.angular.z = f(row, "field.twist.twist.angular.z")
            msg.pose.covariance = cov(row, "field.pose.covariance", 36)
            msg.twist.covariance = cov(row, "field.twist.covariance", 36)
            timeline.append((msg.header.stamp, topic, msg))
            count += 1
    return count


@contextmanager
def open_zip_text(zip_path: Path, member: str):
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(member) as raw:
            yield TextIOWrapper(raw, encoding="utf-8")


def ns_to_sec(value: str) -> float:
    return float(value) * 1e-9


def f(row: dict[str, str], key: str, default: float = 0.0) -> float:
    value = row.get(key, "")
    return float(value) if value not in ("", None) else default


def cov(row: dict[str, str], prefix: str, count: int) -> list[float]:
    return [f(row, f"{prefix}{idx}") for idx in range(count)]


if __name__ == "__main__":
    raise SystemExit(main())
