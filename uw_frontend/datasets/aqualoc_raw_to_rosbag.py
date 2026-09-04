from __future__ import annotations

import argparse
import csv
import io
import tarfile
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
    frame_name: str


@dataclass(frozen=True)
class ImuRow:
    stamp_ns: int
    gyro: tuple[float, float, float]
    accel: tuple[float, float, float]


@dataclass(frozen=True)
class GtRow:
    frame_index: int
    position: tuple[float, float, float]
    orientation: tuple[float, float, float, float]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert an AQUALOC raw tar.gz window into a compact ROS bag."
    )
    parser.add_argument("--input", required=True, help="AQUALOC raw_data tar/tar.gz archive.")
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--sequence-name", default="harbor_sequence_07")
    parser.add_argument("--raw-root", default="raw_data")
    parser.add_argument("--image-dir", default="harbor_images_sequence_07")
    parser.add_argument("--image-csv", default="harbor_img_sequence_07.csv")
    parser.add_argument("--imu-csv", default="harbor_imu_sequence_07.csv")
    parser.add_argument("--gt-txt", default=None, help="Optional AQUALOC COLMAP GT txt.")
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--end-index", type=int, default=None, help="Inclusive image index.")
    parser.add_argument("--image-topic", default="/camera/image_raw")
    parser.add_argument("--imu-topic", default="/rtimulib_node/imu")
    parser.add_argument("--gt-topic", default="/aqualoc/colmap_gt")
    parser.add_argument("--camera-frame-id", default="aqualoc_camera")
    parser.add_argument("--imu-frame-id", default="aqualoc_imu")
    parser.add_argument("--gt-frame-id", default="aqualoc_world")
    parser.add_argument("--imu-margin-s", type=float, default=0.25)
    args = parser.parse_args()

    input_path = Path(args.input)
    output_bag = Path(args.output_bag)
    output_bag.parent.mkdir(parents=True, exist_ok=True)

    with tarfile.open(input_path, "r:*") as tar:
        image_rows = _read_image_rows(tar, _member_path(args.raw_root, args.image_csv))
        imu_rows = _read_imu_rows(tar, _member_path(args.raw_root, args.imu_csv))
        start = max(0, int(args.start_index))
        end = len(image_rows) - 1 if args.end_index is None else min(int(args.end_index), len(image_rows) - 1)
        if start > end:
            raise SystemExit(f"empty image window: start={start}, end={end}")
        window_images = image_rows[start : end + 1]
        gt_rows = _read_gt(Path(args.gt_txt)) if args.gt_txt else {}

        t0_ns = window_images[0].stamp_ns
        t1_ns = window_images[-1].stamp_ns
        margin_ns = int(max(0.0, args.imu_margin_s) * 1e9)
        window_imu = [
            row for row in imu_rows if (t0_ns - margin_ns) <= row.stamp_ns <= (t1_ns + margin_ns)
        ]

        with rosbag.Bag(str(output_bag), "w", compression=rosbag.Compression.BZ2) as bag:
            image_count = 0
            imu_count = 0
            gt_count = 0

            events: list[tuple[int, str, int | ImuRow]] = []
            events.extend((row.stamp_ns, "imu", row) for row in window_imu)
            events.extend((row.stamp_ns, "image", start + idx) for idx, row in enumerate(window_images))
            events.sort(key=lambda item: item[0])

            for stamp_ns, kind, payload in events:
                stamp = _ros_time(stamp_ns)
                if kind == "imu":
                    assert isinstance(payload, ImuRow)
                    bag.write(args.imu_topic, _make_imu_msg(payload, args.imu_frame_id), stamp)
                    imu_count += 1
                    continue

                frame_index = int(payload)
                row = image_rows[frame_index]
                image_member = _member_path(args.raw_root, args.image_dir, row.frame_name)
                image = _read_gray_image(tar, image_member)
                image_msg = _make_image_msg(image, stamp, args.camera_frame_id)
                bag.write(args.image_topic, image_msg, stamp)
                image_count += 1
                gt_row = gt_rows.get(frame_index)
                if gt_row is not None:
                    gt_msg = _make_gt_msg(gt_row, stamp, args.gt_frame_id, args.camera_frame_id)
                    bag.write(args.gt_topic, gt_msg, stamp)
                    gt_count += 1

    print(f"wrote {output_bag}")
    print(f"images={image_count} imu={imu_count} gt={gt_count}")
    print(f"span_s={(t1_ns - t0_ns) * 1e-9:.3f}")
    return 0


def _member_path(*parts: str) -> str:
    cleaned = [part.strip("/") for part in parts if part and part != "."]
    return "/".join(cleaned)


def _read_csv_from_tar(tar: tarfile.TarFile, member: str) -> list[list[str]]:
    extracted = tar.extractfile(member)
    if extracted is None:
        raise FileNotFoundError(member)
    text = io.TextIOWrapper(extracted, encoding="utf-8")
    return [row for row in csv.reader(text) if row and not row[0].startswith("#")]


def _read_image_rows(tar: tarfile.TarFile, member: str) -> list[ImageRow]:
    rows = _read_csv_from_tar(tar, member)
    return [ImageRow(int(row[0]), row[1]) for row in rows]


def _read_imu_rows(tar: tarfile.TarFile, member: str) -> list[ImuRow]:
    rows = _read_csv_from_tar(tar, member)
    result: list[ImuRow] = []
    for row in rows:
        result.append(
            ImuRow(
                stamp_ns=int(row[0]),
                gyro=(float(row[1]), float(row[2]), float(row[3])),
                accel=(float(row[4]), float(row[5]), float(row[6])),
            )
        )
    return result


def _read_gt(path: Path) -> dict[int, GtRow]:
    rows: dict[int, GtRow] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 8:
                continue
            frame_index = int(round(float(parts[0])))
            rows[frame_index] = GtRow(
                frame_index=frame_index,
                position=(float(parts[1]), float(parts[2]), float(parts[3])),
                orientation=(float(parts[4]), float(parts[5]), float(parts[6]), float(parts[7])),
            )
    return rows


def _read_gray_image(tar: tarfile.TarFile, member: str) -> np.ndarray:
    extracted = tar.extractfile(member)
    if extracted is None:
        raise FileNotFoundError(member)
    data = np.frombuffer(extracted.read(), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"failed to decode image: {member}")
    return image


def _make_image_msg(image: np.ndarray, stamp: rospy.Time, frame_id: str) -> Image:
    msg = Image()
    msg.header = Header(stamp=stamp, frame_id=frame_id)
    msg.height = int(image.shape[0])
    msg.width = int(image.shape[1])
    msg.encoding = "mono8"
    msg.is_bigendian = 0
    msg.step = int(image.shape[1])
    msg.data = image.tobytes()
    return msg


def _make_imu_msg(row: ImuRow, frame_id: str) -> Imu:
    msg = Imu()
    msg.header = Header(stamp=_ros_time(row.stamp_ns), frame_id=frame_id)
    msg.angular_velocity.x, msg.angular_velocity.y, msg.angular_velocity.z = row.gyro
    msg.linear_acceleration.x, msg.linear_acceleration.y, msg.linear_acceleration.z = row.accel
    return msg


def _make_gt_msg(row: GtRow, stamp: rospy.Time, frame_id: str, child_frame_id: str) -> Odometry:
    msg = Odometry()
    msg.header = Header(stamp=stamp, frame_id=frame_id)
    msg.child_frame_id = child_frame_id
    msg.pose.pose.position.x, msg.pose.pose.position.y, msg.pose.pose.position.z = row.position
    qx, qy, qz, qw = row.orientation
    msg.pose.pose.orientation = Quaternion(x=qx, y=qy, z=qz, w=qw)
    return msg


def _ros_time(stamp_ns: int) -> rospy.Time:
    secs = stamp_ns // 1_000_000_000
    nsecs = stamp_ns % 1_000_000_000
    return rospy.Time(int(secs), int(nsecs))


if __name__ == "__main__":
    raise SystemExit(main())
