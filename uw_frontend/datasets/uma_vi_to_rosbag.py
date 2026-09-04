from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

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
    gyro: tuple[float, float, float]
    accel: tuple[float, float, float]


@dataclass(frozen=True)
class TrajRow:
    stamp_ns: int
    position: tuple[float, float, float]
    orientation_wxyz: tuple[float, float, float, float]


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a UMA-VI sequence window to a compact VINS ROS bag.")
    parser.add_argument("--sequence-dir", required=True, help="Directory containing cam*/data.csv and imu0/*.csv.")
    parser.add_argument("--camera", default="cam2", help="Camera folder to export, e.g. cam2 for uEye left.")
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--start-offset", type=float, default=0.0, help="Window start offset from first camera frame, seconds.")
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--image-topic", default="/camera/image_raw")
    parser.add_argument("--imu-topic", default="/imu0/data")
    parser.add_argument("--gt-topic", default="/uma/gt")
    parser.add_argument("--image-frame-id", default="uma_cam")
    parser.add_argument("--imu-frame-id", default="uma_imu")
    parser.add_argument("--gt-frame-id", default="uma_world")
    parser.add_argument("--imu-margin-s", type=float, default=0.25)
    parser.add_argument("--grayscale", action="store_true", default=True)
    args = parser.parse_args()

    sequence_dir = Path(args.sequence_dir)
    camera_dir = sequence_dir / args.camera
    output_bag = Path(args.output_bag)
    output_bag.parent.mkdir(parents=True, exist_ok=True)

    image_rows_all = _read_image_rows(camera_dir / "data.csv")
    image_rows = [row for row in image_rows_all if (camera_dir / "data" / row.filename).exists()]
    imu_rows = _read_imu_rows(sequence_dir / "imu0" / "data.csv")
    traj_rows = _read_traj_rows(sequence_dir / "imu0_trajectory.csv")
    if not image_rows:
        raise SystemExit(f"no image rows in {camera_dir / 'data.csv'}")
    if not imu_rows:
        raise SystemExit(f"no imu rows in {sequence_dir / 'imu0' / 'data.csv'}")
    if not traj_rows:
        raise SystemExit(f"no trajectory rows in {sequence_dir / 'imu0_trajectory.csv'}")

    base_ns = image_rows[0].stamp_ns
    start_ns = base_ns + int(max(0.0, float(args.start_offset)) * 1e9)
    end_ns = start_ns + int(max(0.0, float(args.duration)) * 1e9)
    margin_ns = int(max(0.0, float(args.imu_margin_s)) * 1e9)

    window_images = [row for row in image_rows if start_ns <= row.stamp_ns <= end_ns]
    window_imu = [row for row in imu_rows if (start_ns - margin_ns) <= row.stamp_ns <= (end_ns + margin_ns)]
    window_traj = [row for row in traj_rows if start_ns <= row.stamp_ns <= end_ns]
    if not window_images:
        raise SystemExit(f"empty image window start_offset={args.start_offset} duration={args.duration}")

    events: list[tuple[int, str, ImageRow | ImuRow | TrajRow]] = []
    events.extend((row.stamp_ns, "image", row) for row in window_images)
    events.extend((row.stamp_ns, "imu", row) for row in window_imu)
    events.extend((row.stamp_ns, "gt", row) for row in window_traj)
    events.sort(key=lambda item: item[0])

    image_count = 0
    imu_count = 0
    gt_count = 0
    with rosbag.Bag(str(output_bag), "w", compression=rosbag.Compression.BZ2) as bag:
        for stamp_ns, kind, row in events:
            stamp = _ros_time(stamp_ns)
            if kind == "image":
                assert isinstance(row, ImageRow)
                image = _read_gray_image(camera_dir / "data" / row.filename)
                bag.write(args.image_topic, _make_image_msg(image, stamp, args.image_frame_id), stamp)
                image_count += 1
            elif kind == "imu":
                assert isinstance(row, ImuRow)
                bag.write(args.imu_topic, _make_imu_msg(row, stamp, args.imu_frame_id), stamp)
                imu_count += 1
            elif kind == "gt":
                assert isinstance(row, TrajRow)
                bag.write(args.gt_topic, _make_gt_msg(row, stamp, args.gt_frame_id), stamp)
                gt_count += 1

    print(f"wrote {output_bag}")
    print(f"images={image_count} imu={imu_count} gt={gt_count}")
    print(f"image_rows_csv={len(image_rows_all)} image_rows_existing={len(image_rows)}")
    print(f"span_s={(window_images[-1].stamp_ns - window_images[0].stamp_ns) * 1e-9:.3f}")
    print(f"start_stamp={window_images[0].stamp_ns * 1e-9:.9f}")
    print(f"end_stamp={window_images[-1].stamp_ns * 1e-9:.9f}")
    return 0


def _read_image_rows(path: Path) -> list[ImageRow]:
    rows = _read_csv(path)
    return [ImageRow(stamp_ns=int(row[0]), filename=row[1]) for row in rows]


def _read_imu_rows(path: Path) -> list[ImuRow]:
    out: list[ImuRow] = []
    for row in _read_csv(path):
        out.append(
            ImuRow(
                stamp_ns=int(row[0]),
                gyro=(float(row[1]), float(row[2]), float(row[3])),
                accel=(float(row[4]), float(row[5]), float(row[6])),
            )
        )
    return out


def _read_traj_rows(path: Path) -> list[TrajRow]:
    out: list[TrajRow] = []
    for row in _read_csv(path):
        out.append(
            TrajRow(
                stamp_ns=int(row[0]),
                position=(float(row[1]), float(row[2]), float(row[3])),
                orientation_wxyz=(float(row[4]), float(row[5]), float(row[6]), float(row[7])),
            )
        )
    return out


def _read_csv(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [row for row in csv.reader(handle) if row and not row[0].startswith("#")]


def _read_gray_image(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"failed to decode image: {path}")
    return image


def _ros_time(stamp_ns: int) -> rospy.Time:
    return rospy.Time.from_sec(float(stamp_ns) * 1e-9)


def _make_image_msg(image: np.ndarray, stamp: rospy.Time, frame_id: str) -> Image:
    msg = Image()
    msg.header = Header(stamp=stamp, frame_id=frame_id)
    msg.height = int(image.shape[0])
    msg.width = int(image.shape[1])
    msg.encoding = "mono8"
    msg.is_bigendian = 0
    msg.step = int(image.shape[1])
    msg.data = image.astype(np.uint8, copy=False).tobytes()
    return msg


def _make_imu_msg(row: ImuRow, stamp: rospy.Time, frame_id: str) -> Imu:
    msg = Imu()
    msg.header = Header(stamp=stamp, frame_id=frame_id)
    msg.angular_velocity.x, msg.angular_velocity.y, msg.angular_velocity.z = row.gyro
    msg.linear_acceleration.x, msg.linear_acceleration.y, msg.linear_acceleration.z = row.accel
    msg.orientation_covariance[0] = -1.0
    return msg


def _make_gt_msg(row: TrajRow, stamp: rospy.Time, frame_id: str) -> Odometry:
    msg = Odometry()
    msg.header = Header(stamp=stamp, frame_id=frame_id)
    msg.child_frame_id = "uma_imu"
    msg.pose.pose.position.x, msg.pose.pose.position.y, msg.pose.pose.position.z = row.position
    qw, qx, qy, qz = row.orientation_wxyz
    msg.pose.pose.orientation = Quaternion(x=qx, y=qy, z=qz, w=qw)
    return msg


if __name__ == "__main__":
    raise SystemExit(main())
