#!/usr/bin/env python3
"""Inject AQUALOC COLMAP GT messages into an exported feature bag.

Some cached external-feature bags were exported from raw windows that did not
carry `/aqualoc/colmap_gt`.  The VINS trajectory can still be evaluated if we
reconstruct the GT topic from the original raw image timestamps and the AQUALOC
COLMAP text trajectory.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import rosbag
import rospy
from geometry_msgs.msg import Quaternion
from nav_msgs.msg import Odometry
from std_msgs.msg import Header


@dataclass(frozen=True)
class GtRow:
    position: tuple[float, float, float]
    orientation: tuple[float, float, float, float]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-bag", required=True)
    parser.add_argument("--raw-bag", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--gt-txt", required=True)
    parser.add_argument("--start-index", type=int, required=True)
    parser.add_argument("--image-topic", default="/camera/image_raw")
    parser.add_argument("--gt-topic", default="/aqualoc/colmap_gt")
    parser.add_argument("--gt-frame-id", default="aqualoc_world")
    parser.add_argument("--gt-child-frame-id", default="aqualoc_camera")
    args = parser.parse_args()

    input_bag = Path(args.input_bag)
    raw_bag = Path(args.raw_bag)
    output_bag = Path(args.output_bag)
    gt_txt = Path(args.gt_txt)
    output_bag.parent.mkdir(parents=True, exist_ok=True)

    gt_rows = read_gt(gt_txt)
    gt_events = build_gt_events(
        raw_bag=raw_bag,
        image_topic=str(args.image_topic),
        gt_rows=gt_rows,
        start_index=int(args.start_index),
        gt_topic=str(args.gt_topic),
        gt_frame_id=str(args.gt_frame_id),
        gt_child_frame_id=str(args.gt_child_frame_id),
    )

    existing_gt = 0
    copied = []
    with rosbag.Bag(str(input_bag), "r") as in_bag:
        for topic, msg, stamp in in_bag.read_messages():
            if topic == args.gt_topic:
                existing_gt += 1
                continue
            copied.append((stamp.to_sec(), topic, msg, stamp))

    merged = copied + gt_events
    merged.sort(key=lambda item: (item[0], item[1]))
    with rosbag.Bag(str(output_bag), "w") as out_bag:
        for _, topic, msg, stamp in merged:
            out_bag.write(topic, msg, stamp)

    print(f"wrote {output_bag}")
    print(f"copied_messages={len(copied)} existing_gt_removed={existing_gt} injected_gt={len(gt_events)}")
    return 0


def read_gt(path: Path) -> dict[int, GtRow]:
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
                position=(float(parts[1]), float(parts[2]), float(parts[3])),
                orientation=(float(parts[4]), float(parts[5]), float(parts[6]), float(parts[7])),
            )
    return rows


def build_gt_events(
    *,
    raw_bag: Path,
    image_topic: str,
    gt_rows: dict[int, GtRow],
    start_index: int,
    gt_topic: str,
    gt_frame_id: str,
    gt_child_frame_id: str,
) -> list[tuple[float, str, Odometry, rospy.Time]]:
    events: list[tuple[float, str, Odometry, rospy.Time]] = []
    with rosbag.Bag(str(raw_bag), "r") as bag:
        local_index = 0
        for _, image_msg, stamp in bag.read_messages(topics=[image_topic]):
            frame_index = start_index + local_index
            local_index += 1
            row = gt_rows.get(frame_index)
            if row is None:
                continue
            msg = make_gt_msg(row, image_msg.header.stamp, gt_frame_id, gt_child_frame_id)
            events.append((image_msg.header.stamp.to_sec(), gt_topic, msg, image_msg.header.stamp))
    return events


def make_gt_msg(row: GtRow, stamp: rospy.Time, frame_id: str, child_frame_id: str) -> Odometry:
    msg = Odometry()
    msg.header = Header(stamp=stamp, frame_id=frame_id)
    msg.child_frame_id = child_frame_id
    msg.pose.pose.position.x, msg.pose.pose.position.y, msg.pose.pose.position.z = row.position
    qx, qy, qz, qw = row.orientation
    msg.pose.pose.orientation = Quaternion(x=qx, y=qy, z=qz, w=qw)
    return msg


if __name__ == "__main__":
    raise SystemExit(main())
