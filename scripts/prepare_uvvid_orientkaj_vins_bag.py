#!/usr/bin/env python3
"""Prepare a UVVID Orientkaj MP4/flight-data segment as a VINS-friendly bag."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import rosbag
import rospy
from cv_bridge import CvBridge
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Image
from std_msgs.msg import Header


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--flight-bag", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--video-start-stamp", type=float, required=True)
    parser.add_argument("--start-offset", type=float, default=0.0)
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--image-topic", default="/uvvid/oak_left/image_mono")
    parser.add_argument("--imu-topic-in", default="/bluerov2/mavros/imu/data")
    parser.add_argument("--imu-topic", default="/uvvid/imu")
    parser.add_argument("--odom-topic-in", default="/bluerov2/mavros/global_position/local")
    parser.add_argument("--gt-topic", default="/uvvid/local_odom_gt")
    parser.add_argument("--image-frame-id", default="oak_d_lite_left_camera_optical_frame")
    parser.add_argument("--gt-frame-id", default="uvvid_map")
    parser.add_argument("--gt-child-frame-id", default="uvvid_body")
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--image-scale", type=float, default=1.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.duration <= 0.0:
        raise SystemExit("--duration must be positive")
    if args.image_scale <= 0.0:
        raise SystemExit("--image-scale must be positive")

    video = Path(args.video)
    flight_bag = Path(args.flight_bag)
    output_bag = Path(args.output_bag)
    output_bag.parent.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise SystemExit(f"failed to open video: {video}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 0.0:
        raise SystemExit(f"invalid FPS for {video}: {fps}")

    start_stamp = float(args.video_start_stamp) + float(args.start_offset)
    end_stamp = start_stamp + float(args.duration)
    start_frame = max(0, int(round(float(args.start_offset) * fps)))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    bridge = CvBridge()
    image_msgs: list[tuple[rospy.Time, Image]] = []
    frame_idx = start_frame
    while True:
        if args.max_frames > 0 and len(image_msgs) >= int(args.max_frames):
            break
        stamp_sec = float(args.video_start_stamp) + frame_idx / fps
        if stamp_sec >= end_stamp:
            break
        ok, frame = cap.read()
        if not ok:
            break
        if stamp_sec >= start_stamp:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
            if abs(float(args.image_scale) - 1.0) > 1e-6:
                height, width = gray.shape[:2]
                size = (
                    max(1, int(round(width * float(args.image_scale)))),
                    max(1, int(round(height * float(args.image_scale)))),
                )
                gray = cv2.resize(gray, size, interpolation=cv2.INTER_AREA)
            stamp = rospy.Time.from_sec(stamp_sec)
            msg = bridge.cv2_to_imgmsg(gray, encoding="mono8")
            msg.header = Header(stamp=stamp, frame_id=args.image_frame_id)
            image_msgs.append((stamp, msg))
        frame_idx += 1
    cap.release()

    bag_start = rospy.Time.from_sec(start_stamp)
    bag_end = rospy.Time.from_sec(end_stamp)
    timeline: list[tuple[rospy.Time, str, object]] = []
    timeline.extend((stamp, args.image_topic, msg) for stamp, msg in image_msgs)
    imu_count = 0
    gt_count = 0
    with rosbag.Bag(str(flight_bag), "r") as src:
        for topic, msg, stamp in src.read_messages(
            topics=[args.imu_topic_in, args.odom_topic_in],
            start_time=bag_start,
            end_time=bag_end,
        ):
            msg_stamp = message_stamp(msg, stamp)
            if topic == args.imu_topic_in:
                msg.header.stamp = msg_stamp
                timeline.append((msg_stamp, args.imu_topic, msg))
                imu_count += 1
            elif topic == args.odom_topic_in:
                timeline.append(
                    (
                        msg_stamp,
                        args.gt_topic,
                        make_gt_msg(msg, msg_stamp, args.gt_frame_id, args.gt_child_frame_id),
                    )
                )
                gt_count += 1

    timeline.sort(key=lambda item: item[0].to_sec())
    with rosbag.Bag(str(output_bag), "w") as dst:
        for stamp, topic, msg in timeline:
            dst.write(topic, msg, stamp)

    print(f"wrote {output_bag}")
    print(
        f"images={len(image_msgs)} imu={imu_count} gt={gt_count} "
        f"start={start_stamp:.6f} end={end_stamp:.6f} fps={fps:.6f}"
    )
    return 0


def message_stamp(msg, fallback: rospy.Time) -> rospy.Time:
    stamp = getattr(getattr(msg, "header", None), "stamp", None)
    if stamp is not None and stamp.to_sec() > 0.0:
        return stamp
    return fallback


def make_gt_msg(src: Odometry, stamp: rospy.Time, frame_id: str, child_frame_id: str) -> Odometry:
    msg = Odometry()
    msg.header = Header(stamp=stamp, frame_id=frame_id)
    msg.child_frame_id = child_frame_id
    msg.pose = src.pose
    msg.twist = src.twist
    return msg


if __name__ == "__main__":
    raise SystemExit(main())
