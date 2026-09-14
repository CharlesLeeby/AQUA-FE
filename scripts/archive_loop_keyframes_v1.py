#!/usr/bin/env python3
"""Materialize ONE immutable native keyframe roster from passive VINS messages.

Inputs are a capture bag of /vins_estimator/{keyframe_pose,keyframe_point} and
the SAME converted mono8 image bag used for external KLT export. No reference
trajectory is read, no estimator runs, and no points/observations are invented.
Consume this archive for both C and L, not the live node's lossy image queue.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

POSE_TOPIC = "/vins_estimator/keyframe_pose"
POINT_TOPIC = "/vins_estimator/keyframe_point"
FIELDS = ["id", "timestamp_ns", "tx", "ty", "tz", "qw", "qx", "qy", "qz",
          "image", "points", "point_count", "image_sha256", "points_sha256"]


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def points_array(message) -> np.ndarray:
    if len(message.points) != len(message.channels):
        raise ValueError("PointCloud must contain one observation channel per 3D point")
    rows = []
    for xyz, channel in zip(message.points, message.channels):
        if len(channel.values) != 5:
            raise ValueError("Expected native normalized xy, pixel uv, feature ID")
        rows.append([xyz.x, xyz.y, xyz.z, *channel.values])
    data = np.asarray(rows, dtype="<f4").reshape(-1, 8)
    if not np.isfinite(data).all():
        raise ValueError("Nonfinite native map point or observation")
    ids = data[:, 7]
    if np.any(ids < 0) or np.any(ids != np.floor(ids)) or len(np.unique(ids)) != len(ids):
        raise ValueError("Native feature IDs must be distinct nonnegative integers")
    return data


def pose_values(message) -> list[float]:
    p, q = message.pose.pose.position, message.pose.pose.orientation
    values = [p.x, p.y, p.z, q.w, q.x, q.y, q.z]
    if not np.isfinite(values).all() or abs(np.linalg.norm(values[3:]) - 1) > 1e-6:
        raise ValueError("Invalid native body pose; do not silently normalize it")
    return values


def select_roster(poses: dict, points: dict) -> list[int]:
    if set(poses) != set(points):
        raise ValueError("Native pose/point header timestamp sets differ")
    # Preserve native SKIP_FIRST_CNT=10, SKIP_CNT=0, SKIP_DIS=0, initial last_t.
    selected, last_t = [], np.array([-100., -100., -100.])
    for stamp in sorted(poses)[10:]:
        t = np.asarray(pose_values(poses[stamp])[:3])
        if np.linalg.norm(t - last_t) > 0:
            selected.append(stamp)
            last_t = t
    return selected


def validate_archive(root: Path) -> dict:
    """Read-only integrity check before either arm consumes an archive.

    This validates saved measurements and identities, not geometric correctness.
    Source bags need not be rehashed for every consumer.
    """
    root = root.resolve()
    receipt = json.loads((root / "archive_receipt.json").read_text())
    if (receipt.get("schema") != "aqua-fe-native-keyframe-archive-v1"
            or receipt.get("status") != "COMPLETE"
            or receipt.get("exact_image_join_missing") != 0
            or receipt.get("ground_truth_used") is not False):
        raise ValueError("Incomplete or incompatible archive receipt")
    manifest = root / "keyframes.csv"
    if hash_file(manifest) != receipt.get("keyframes_csv_sha256"):
        raise ValueError("Archive roster hash mismatch")
    with manifest.open(newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != FIELDS:
            raise ValueError("Archive roster schema mismatch")
        rows = list(reader)
    if not rows or len(rows) != receipt.get("keyframes"):
        raise ValueError("Archive keyframe count mismatch")
    previous = 0
    for i, row in enumerate(rows):
        stamp = int(row["timestamp_ns"])
        if int(row["id"]) != i or stamp <= previous:
            raise ValueError("Invalid archive ID or non-increasing header time")
        previous = stamp
        pose = np.asarray([float(row[name]) for name in FIELDS[2:9]])
        if not np.isfinite(pose).all() or abs(np.linalg.norm(pose[3:]) - 1) > 1e-6:
            raise ValueError("Invalid archived native pose")
        count = int(row["point_count"])
        if not 0 <= count <= 350:
            raise ValueError("Invalid native point count")
        for column in ("image", "points"):
            relative = Path(row[column])
            path = (root / relative).resolve()
            if relative.is_absolute() or root not in path.parents:
                raise ValueError("Archive asset escapes its root")
            if hash_file(path) != row[column + "_sha256"]:
                raise ValueError("Archive asset hash mismatch: " + column)
        point_file = root / row["points"]
        if point_file.stat().st_size != count * 8 * 4:
            raise ValueError("Archive point payload size mismatch")
        data = np.fromfile(point_file, dtype="<f4").reshape(count, 8)
        ids = data[:, 7]
        if (not np.isfinite(data).all() or np.any(ids < 0)
                or np.any(ids != np.floor(ids)) or len(np.unique(ids)) != count):
            raise ValueError("Invalid archived native observations")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", type=Path, help="Validate an existing archive without ROS or writes")
    parser.add_argument("--capture-bag", type=Path)
    parser.add_argument("--images-bag", type=Path)
    parser.add_argument("--image-topic", default="/camera/image_raw")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.verify_only is not None:
        if any(x is not None for x in (args.capture_bag, args.images_bag, args.output_dir)):
            parser.error("Verification cannot be combined with archive creation")
        print(json.dumps(validate_archive(args.verify_only)))
        return
    if any(x is None for x in (args.capture_bag, args.images_bag, args.output_dir)):
        parser.error("Creation requires --capture-bag, --images-bag and --output-dir")
    import cv2
    import rosbag
    from cv_bridge import CvBridge

    if args.output_dir.exists():
        raise SystemExit("Refusing to overwrite an archive or incomplete attempt")
    poses, points = {}, {}
    with rosbag.Bag(str(args.capture_bag), "r") as bag:
        for topic, message, _ in bag.read_messages(topics=[POSE_TOPIC, POINT_TOPIC]):
            stamp = message.header.stamp.to_nsec()
            target = poses if topic == POSE_TOPIC else points
            if stamp <= 0 or stamp in target:
                raise ValueError("Duplicate/nonpositive native header timestamp")
            target[stamp] = message
    stamps = select_roster(poses, points)
    if not stamps:
        raise SystemExit("No keyframes after native selection; do not fabricate an archive")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "images").mkdir()
    (args.output_dir / "points").mkdir()
    stamp_to_id = {stamp: i for i, stamp in enumerate(stamps)}
    saved = {}
    bridge = CvBridge()
    with rosbag.Bag(str(args.images_bag), "r") as bag:
        for _, message, _ in bag.read_messages(topics=[args.image_topic]):
            stamp = message.header.stamp.to_nsec()
            if stamp not in stamp_to_id:
                continue
            if stamp in saved:
                raise ValueError("Duplicate source image for a selected header timestamp")
            if message.encoding not in ("mono8", "8UC1"):
                raise ValueError("Expected the frozen converted mono8 KLT source image")
            image = np.asarray(bridge.imgmsg_to_cv2(message, desired_encoding="passthrough"))
            if image.shape != (600, 800) or image.dtype != np.uint8:
                raise ValueError("Expected frozen half-resolution AFRL image (600,800) uint8")
            idx = stamp_to_id[stamp]
            image_rel, points_rel = f"images/{idx:06d}.png", f"points/{idx:06d}.bin"
            path = args.output_dir / image_rel
            if not cv2.imwrite(str(path), image, [cv2.IMWRITE_PNG_COMPRESSION, 3]):
                raise OSError("Failed to save keyframe PNG")
            point_data = points_array(points[stamp])
            point_path = args.output_dir / points_rel
            with point_path.open("xb") as stream:
                stream.write(point_data.tobytes())
            pose = pose_values(poses[stamp])
            saved[stamp] = dict(zip(FIELDS, [idx, stamp, *pose, image_rel, points_rel,
                len(point_data), hash_file(path), hash_file(point_path)]))
    missing = sorted(set(stamps) - set(saved))
    if missing:
        # Preserve the incomplete output, but do not create a success manifest.
        raise ValueError(f"{len(missing)} exact header images missing; first={missing[0]}")
    manifest = args.output_dir / "keyframes.csv"
    with manifest.open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(saved[stamp] for stamp in stamps)
    receipt = {
        "schema": "aqua-fe-native-keyframe-archive-v1",
        "status": "COMPLETE",
        "pose_frame": "world_T_imu_body",
        "points_layout": "little-endian float32 rows: world_XYZ,norm_xy,pixel_uv,feature_id",
        "selection": "native first10 skip; skip_count0; distance strictly greater than0",
        "capture_bag_sha256": hash_file(args.capture_bag),
        "images_bag_sha256": hash_file(args.images_bag),
        "keyframes_csv_sha256": hash_file(manifest),
        "native_pose_messages": len(poses),
        "keyframes": len(stamps),
        "exact_image_join_missing": 0,
        "geometry_verified": "Not evaluated",
        "ground_truth_used": False,
    }
    with (args.output_dir / "archive_receipt.json").open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
