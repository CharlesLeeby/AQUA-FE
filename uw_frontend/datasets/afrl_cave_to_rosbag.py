from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import rosbag
import rospy
from cv_bridge import CvBridge
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Image
from std_msgs.msg import Header


@dataclass(frozen=True)
class GtRow:
    stamp: float
    position: tuple[float, float, float]
    orientation: tuple[float, float, float, float]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract an AFRL cave compressed-image/IMU/Colmap-GT segment to a VINS-friendly ROS bag."
    )
    parser.add_argument("--input-bag", required=True)
    parser.add_argument("--gt-txt", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--start", type=float, default=None, help="Start stamp in seconds. Defaults to bag start.")
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--image-topic-in", default="/slave1/image_raw/compressed")
    parser.add_argument("--imu-topic-in", default="/imu/imu")
    parser.add_argument("--image-topic", default="/camera/image_raw")
    parser.add_argument("--imu-topic", default="/imu/imu")
    parser.add_argument("--gt-topic", default="/afrl/colmap_gt")
    parser.add_argument("--image-frame-id", default="afrl_camera")
    parser.add_argument("--gt-frame-id", default="afrl_world")
    parser.add_argument(
        "--gt-timestamp-mode",
        choices=["auto", "raw", "afrl_digits"],
        default="auto",
        help="How to parse COLMAP GT stamps. 'afrl_digits' repairs cemetery-style stamps like 153.522486209.",
    )
    parser.add_argument("--grayscale", action="store_true", help="Write mono8 images instead of bgr8.")
    parser.add_argument(
        "--image-scale",
        type=float,
        default=1.0,
        help="Optional isotropic image resize scale written to the output bag.",
    )
    args = parser.parse_args()
    if args.image_scale <= 0.0:
        raise SystemExit(f"--image-scale must be positive, got {args.image_scale}")

    input_bag = Path(args.input_bag)
    output_bag = Path(args.output_bag)
    output_bag.parent.mkdir(parents=True, exist_ok=True)

    bridge = CvBridge()
    with rosbag.Bag(str(input_bag), "r") as src:
        start = float(args.start) if args.start is not None else float(src.get_start_time())
        end = start + max(0.0, float(args.duration))
        gt_rows = _read_gt(
            Path(args.gt_txt),
            mode=args.gt_timestamp_mode,
            reference_start=float(src.get_start_time()),
            reference_end=float(src.get_end_time()),
        )
        image_count = 0
        imu_count = 0
        gt_count = 0
        with rosbag.Bag(str(output_bag), "w") as dst:
            topics = [args.image_topic_in, args.imu_topic_in]
            for topic, msg, stamp in src.read_messages(
                topics=topics,
                start_time=rospy.Time.from_sec(start),
                end_time=rospy.Time.from_sec(end),
            ):
                msg_stamp = _message_stamp(msg, stamp)
                if topic == args.image_topic_in:
                    image = _decode_compressed_image(msg)
                    if image is None:
                        continue
                    if abs(float(args.image_scale) - 1.0) > 1e-6:
                        image = _resize_image(image, float(args.image_scale))
                    if args.grayscale:
                        if image.ndim == 3:
                            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                        out_msg = bridge.cv2_to_imgmsg(image, encoding="mono8")
                    else:
                        if image.ndim == 2:
                            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
                        out_msg = bridge.cv2_to_imgmsg(image, encoding="bgr8")
                    out_msg.header = Header(stamp=msg_stamp, frame_id=args.image_frame_id)
                    dst.write(args.image_topic, out_msg, msg_stamp)
                    gt = _nearest_gt(gt_rows, msg_stamp.to_sec(), max_dt=0.10)
                    if gt is not None:
                        dst.write(
                            args.gt_topic,
                            _make_gt_msg(gt, msg_stamp, args.gt_frame_id, args.image_frame_id),
                            msg_stamp,
                        )
                        gt_count += 1
                    image_count += 1
                elif topic == args.imu_topic_in:
                    msg.header.stamp = msg_stamp
                    dst.write(args.imu_topic, msg, msg_stamp)
                    imu_count += 1

    print(f"wrote {output_bag}")
    print(f"images={image_count} imu={imu_count} gt={gt_count}")
    print(f"span_s={float(args.duration):.3f}")
    return 0


def _decode_compressed_image(msg) -> np.ndarray | None:
    data = np.frombuffer(msg.data, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _resize_image(image: np.ndarray, scale: float) -> np.ndarray:
    height, width = image.shape[:2]
    out_width = max(1, int(round(width * scale)))
    out_height = max(1, int(round(height * scale)))
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    return cv2.resize(image, (out_width, out_height), interpolation=interpolation)


def _message_stamp(msg, fallback) -> rospy.Time:
    stamp = getattr(getattr(msg, "header", None), "stamp", None)
    if stamp is not None and stamp.to_sec() > 0.0:
        return stamp
    return fallback


def _read_gt(
    path: Path,
    *,
    mode: str = "auto",
    reference_start: float | None = None,
    reference_end: float | None = None,
) -> list[GtRow]:
    rows: list[GtRow] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 8:
                continue
            stamp = _parse_gt_stamp(
                parts[0],
                mode=mode,
                reference_start=reference_start,
                reference_end=reference_end,
            )
            pos = (float(parts[1]), float(parts[2]), float(parts[3]))
            quat = (float(parts[4]), float(parts[5]), float(parts[6]), float(parts[7]))
            rows.append(GtRow(stamp=stamp, position=pos, orientation=quat))
    rows.sort(key=lambda item: item.stamp)
    return rows


def _parse_gt_stamp(
    value: str,
    *,
    mode: str,
    reference_start: float | None,
    reference_end: float | None,
) -> float:
    if mode == "raw":
        return float(value)
    if mode == "afrl_digits":
        return _parse_afrl_digit_stamp(value)
    raw = float(value)
    if _stamp_overlaps_reference(raw, reference_start, reference_end):
        return raw
    repaired = _parse_afrl_digit_stamp(value)
    if _stamp_overlaps_reference(repaired, reference_start, reference_end):
        return repaired
    return raw


def _parse_afrl_digit_stamp(value: str) -> float:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) <= 10:
        return float(value)
    return float(f"{digits[:10]}.{digits[10:]}")


def _stamp_overlaps_reference(
    stamp: float,
    reference_start: float | None,
    reference_end: float | None,
) -> bool:
    if reference_start is None or reference_end is None:
        return False
    return reference_start - 5.0 <= stamp <= reference_end + 5.0


def _nearest_gt(rows: list[GtRow], stamp: float, max_dt: float) -> GtRow | None:
    if not rows:
        return None
    lo = 0
    hi = len(rows) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if rows[mid].stamp < stamp:
            lo = mid + 1
        else:
            hi = mid
    candidates = [lo]
    if lo > 0:
        candidates.append(lo - 1)
    idx = min(candidates, key=lambda i: abs(rows[i].stamp - stamp))
    return rows[idx] if abs(rows[idx].stamp - stamp) <= max_dt else None


def _make_gt_msg(row: GtRow, stamp: rospy.Time, frame_id: str, child_frame_id: str) -> Odometry:
    msg = Odometry()
    msg.header = Header(stamp=stamp, frame_id=frame_id)
    msg.child_frame_id = child_frame_id
    msg.pose.pose.position.x, msg.pose.pose.position.y, msg.pose.pose.position.z = row.position
    qx, qy, qz, qw = row.orientation
    msg.pose.pose.orientation.x = qx
    msg.pose.pose.orientation.y = qy
    msg.pose.pose.orientation.z = qz
    msg.pose.pose.orientation.w = qw
    return msg


if __name__ == "__main__":
    raise SystemExit(main())
