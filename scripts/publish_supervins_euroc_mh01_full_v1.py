#!/usr/bin/env python3
"""Stream the frozen complete official EuRoC MH01 cam0+imu0 sequence once.

The source timestamps and event order are unchanged.  Wall replay is slowed to
0.2 source seconds per wall second to bound the learned frontend backlog.  No
bag, cam1, ground truth, preprocessing, or lossy image conversion is used.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np


ROOT = Path("/home/ma/AQUA-FE_WS")
MANIFEST = ROOT / "papers/supervins_v1_official_euroc_mh01_full_input_manifest_v1.json"
MANIFEST_SHA256 = "31fbc4a8d968f6eda7fb013b4ea830c9226459986a4917b786bfb86f0ced2a44"
MANIFEST_SIZE = 7142
DATASET = Path("/mnt/data/AQUA-FE_WS/datasets/official_euroc_v1/MH01/MH_01_easy")
MAV0 = DATASET / "mav0"
CAMERA_CSV = MAV0 / "cam0/data.csv"
CAMERA_DATA = MAV0 / "cam0/data"
IMU_CSV = MAV0 / "imu0/data.csv"
CAMERA_COUNT = 3682
IMU_COUNT = 36820
EVENT_COUNT = 40502
FIRST_EVENT_NS = 1403636579758555392
LAST_EVENT_NS = 1403636763853555456
SOURCE_TIME_PER_WALL_TIME = 0.2
AUTHORIZATION_TOKEN = "SUPERVINS_STAGE4_MH01_FULL_PUBLISH_ONCE"
NODE_NAME = "aqua_fe_euroc_mh01_full_publisher"
NUL = "\x00"


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_identity(path):
    path = Path(path)
    return {"sha256": sha256_file(path), "size_bytes": path.stat().st_size}


def load_rows(path):
    with Path(path).open("r", encoding="utf-8", newline="") as stream:
        return [row for row in csv.reader(stream) if row and not row[0].startswith("#")]


def decode_camera(timestamp_text, filename):
    timestamp_ns = int(timestamp_text)
    path = CAMERA_DATA / filename
    encoded = path.read_bytes()
    png_sha = hashlib.sha256(encoded).hexdigest()
    image = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None or image.shape != (480, 752) or image.dtype != np.uint8:
        raise ValueError("invalid_camera_decode:" + filename)
    if not image.flags["C_CONTIGUOUS"]:
        image = np.ascontiguousarray(image)
    pixels = image.tobytes(order="C")
    return {
        "timestamp_ns": timestamp_ns,
        "filename": filename,
        "encoded": encoded,
        "png_sha256": png_sha,
        "pixels": pixels,
        "decoded_sha256": hashlib.sha256(pixels).hexdigest(),
    }


def update_camera_digests(asset_digest, decoded_digest, camera):
    relative = "mav0/cam0/data/" + camera["filename"]
    asset_digest.update(
        f"{camera['timestamp_ns']}{NUL}{relative}{NUL}{len(camera['encoded'])}{NUL}{camera['png_sha256']}\n".encode("utf-8")
    )
    decoded_digest.update(
        f"{camera['timestamp_ns']}{NUL}480{NUL}752{NUL}uint8{NUL}{len(camera['pixels'])}{NUL}{camera['decoded_sha256']}\n".encode("utf-8")
    )


def validate_full_input():
    errors = []
    manifest_identity = file_identity(MANIFEST)
    if manifest_identity != {"sha256": MANIFEST_SHA256, "size_bytes": MANIFEST_SIZE}:
        errors.append("manifest_identity")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("status") != "FROZEN_BEFORE_FULL_TRAJECTORY_ROS_OR_MODEL_START":
        errors.append("manifest_status")
    for path_text, expected in manifest["source_metadata_pins"].items():
        try:
            observed = file_identity(path_text)
        except OSError:
            observed = None
        if observed != expected:
            errors.append("source_metadata_pin:" + path_text)

    cam_rows = load_rows(CAMERA_CSV)
    imu_rows = load_rows(IMU_CSV)
    if len(cam_rows) != CAMERA_COUNT or int(cam_rows[0][0]) != 1403636579763555584 or int(cam_rows[-1][0]) != 1403636763813555456:
        errors.append("camera_selection")
    if len(imu_rows) != IMU_COUNT or int(imu_rows[0][0]) != FIRST_EVENT_NS or int(imu_rows[-1][0]) != LAST_EVENT_NS:
        errors.append("imu_selection")
    if any(int(b[0]) <= int(a[0]) for a, b in zip(cam_rows, cam_rows[1:])):
        errors.append("camera_order")
    if any(int(b[0]) <= int(a[0]) for a, b in zip(imu_rows, imu_rows[1:])):
        errors.append("imu_order")

    asset_digest = hashlib.sha256()
    decoded_digest = hashlib.sha256()
    total_png_bytes = 0
    total_pixel_bytes = 0
    try:
        for timestamp_text, filename in cam_rows:
            camera = decode_camera(timestamp_text, filename)
            update_camera_digests(asset_digest, decoded_digest, camera)
            total_png_bytes += len(camera["encoded"])
            total_pixel_bytes += len(camera["pixels"])
    except (OSError, ValueError) as exc:
        errors.append(type(exc).__name__ + ":" + str(exc)[:300])

    imu_text = "".join(",".join(row) + "\n" for row in imu_rows)
    imu_digest = hashlib.sha256(imu_text.encode("utf-8")).hexdigest()
    combined_digest = hashlib.sha256()
    cam_index = imu_index = 0
    event_count = 0
    while cam_index < len(cam_rows) or imu_index < len(imu_rows):
        next_cam = int(cam_rows[cam_index][0]) if cam_index < len(cam_rows) else None
        next_imu = int(imu_rows[imu_index][0]) if imu_index < len(imu_rows) else None
        if next_imu is not None and (next_cam is None or next_imu <= next_cam):
            row = imu_rows[imu_index]
            combined_digest.update(f"{next_imu}{NUL}0{NUL}I{NUL}{','.join(row)}\n".encode("utf-8"))
            imu_index += 1
        else:
            row = cam_rows[cam_index]
            combined_digest.update(f"{next_cam}{NUL}1{NUL}C{NUL}{row[1]}\n".encode("utf-8"))
            cam_index += 1
        event_count += 1

    observed_digests = {
        "camera_png_assets": asset_digest.hexdigest(),
        "camera_decoded_mono8_pixels": decoded_digest.hexdigest(),
        "imu_rows": imu_digest,
        "combined_events": combined_digest.hexdigest(),
    }
    expected = manifest["selected_content_digests"]
    for key, value in observed_digests.items():
        if value != expected[key]["sha256"]:
            errors.append("selected_digest:" + key)
    if total_png_bytes != expected["camera_png_assets"]["total_png_bytes"]:
        errors.append("total_png_bytes")
    if total_pixel_bytes != expected["camera_decoded_mono8_pixels"]["total_pixel_bytes"]:
        errors.append("total_pixel_bytes")
    if event_count != EVENT_COUNT:
        errors.append("event_count")

    return {
        "status": "READY_FULL_INPUT_NO_ROS_STARTED" if not errors else "BLOCKED_FULL_INPUT_IDENTITY",
        "ready": not errors,
        "errors": errors,
        "manifest": manifest_identity,
        "sequence": "MH_01_easy_FULL_NOT_README_V2_01",
        "camera_count": len(cam_rows),
        "imu_count": len(imu_rows),
        "event_count": event_count,
        "first_event_timestamp_ns": FIRST_EVENT_NS,
        "last_event_timestamp_ns": LAST_EVENT_NS,
        "source_duration_seconds": (LAST_EVENT_NS - FIRST_EVENT_NS) / 1e9,
        "source_time_per_wall_time": SOURCE_TIME_PER_WALL_TIME,
        "digests": observed_digests,
        "total_png_bytes": total_png_bytes,
        "total_pixel_bytes": total_pixel_bytes,
        "ros_started": False,
    }, cam_rows, imu_rows


def ros_time(timestamp_ns, rospy):
    return rospy.Time(timestamp_ns // 1_000_000_000, timestamp_ns % 1_000_000_000)


def publish_full(cam_rows, imu_rows, expected_digests):
    import rospy
    from sensor_msgs.msg import Image, Imu

    rospy.init_node(NODE_NAME, anonymous=False, disable_signals=True)
    # Synchronous rospy transport avoids an unobservable publisher-side async
    # queue/drop boundary.  The estimator's pinned subscriber queues remain
    # 100 images and 2000 IMU messages respectively.
    image_pub = rospy.Publisher("/cam0/image_raw", Image, queue_size=None, tcp_nodelay=True)
    imu_pub = rospy.Publisher("/imu0", Imu, queue_size=None, tcp_nodelay=True)
    connection_deadline = time.monotonic() + 30.0
    while time.monotonic() < connection_deadline:
        if image_pub.get_num_connections() >= 1 and imu_pub.get_num_connections() >= 1:
            break
        if rospy.is_shutdown():
            raise RuntimeError("rospy_shutdown_before_connections")
        time.sleep(0.05)
    if image_pub.get_num_connections() < 1 or imu_pub.get_num_connections() < 1:
        raise RuntimeError("required_supervins_subscribers_not_connected")

    wall_start = time.monotonic() + 0.25
    first_publish_wall = last_publish_wall = None
    cam_index = imu_index = event_count = 0
    asset_digest = hashlib.sha256()
    decoded_digest = hashlib.sha256()
    imu_digest = hashlib.sha256()
    combined_digest = hashlib.sha256()

    while cam_index < len(cam_rows) or imu_index < len(imu_rows):
        next_cam = int(cam_rows[cam_index][0]) if cam_index < len(cam_rows) else None
        next_imu = int(imu_rows[imu_index][0]) if imu_index < len(imu_rows) else None
        use_imu = next_imu is not None and (next_cam is None or next_imu <= next_cam)
        timestamp_ns = next_imu if use_imu else next_cam
        target = wall_start + ((timestamp_ns - FIRST_EVENT_NS) / 1e9) / SOURCE_TIME_PER_WALL_TIME
        while True:
            remaining = target - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(remaining, 0.01))
        if rospy.is_shutdown():
            raise RuntimeError("rospy_shutdown_during_publish")
        if first_publish_wall is None:
            first_publish_wall = time.monotonic()

        if use_imu:
            row = imu_rows[imu_index]
            msg = Imu()
            msg.header.seq = imu_index
            msg.header.stamp = ros_time(timestamp_ns, rospy)
            msg.header.frame_id = "imu0"
            msg.orientation_covariance[0] = -1.0
            msg.angular_velocity.x, msg.angular_velocity.y, msg.angular_velocity.z = (float(value) for value in row[1:4])
            msg.linear_acceleration.x, msg.linear_acceleration.y, msg.linear_acceleration.z = (float(value) for value in row[4:7])
            imu_pub.publish(msg)
            row_text = ",".join(row)
            imu_digest.update((row_text + "\n").encode("utf-8"))
            combined_digest.update(f"{timestamp_ns}{NUL}0{NUL}I{NUL}{row_text}\n".encode("utf-8"))
            imu_index += 1
        else:
            timestamp_text, filename = cam_rows[cam_index]
            camera = decode_camera(timestamp_text, filename)
            update_camera_digests(asset_digest, decoded_digest, camera)
            msg = Image()
            msg.header.seq = cam_index
            msg.header.stamp = ros_time(timestamp_ns, rospy)
            msg.header.frame_id = "cam0"
            msg.height = 480
            msg.width = 752
            msg.encoding = "mono8"
            msg.is_bigendian = 0
            msg.step = 752
            msg.data = camera["pixels"]
            image_pub.publish(msg)
            combined_digest.update(f"{timestamp_ns}{NUL}1{NUL}C{NUL}{filename}\n".encode("utf-8"))
            print(json.dumps({"event": "CAMERA_PUBLISHED", "index": cam_index, "timestamp_ns": timestamp_ns, "filename": filename, "decoded_sha256": camera["decoded_sha256"]}, sort_keys=True), flush=True)
            cam_index += 1
        event_count += 1
        last_publish_wall = time.monotonic()

    time.sleep(1.0)
    observed_digests = {
        "camera_png_assets": asset_digest.hexdigest(),
        "camera_decoded_mono8_pixels": decoded_digest.hexdigest(),
        "imu_rows": imu_digest.hexdigest(),
        "combined_events": combined_digest.hexdigest(),
    }
    digest_match = observed_digests == expected_digests
    result = {
        "status": "PUBLISH_COMPLETE" if digest_match else "PUBLISH_COMPLETE_DIGEST_MISMATCH",
        "camera_count": cam_index,
        "imu_count": imu_index,
        "event_count": event_count,
        "first_timestamp_ns": FIRST_EVENT_NS,
        "last_timestamp_ns": LAST_EVENT_NS,
        "source_span_seconds": (LAST_EVENT_NS - FIRST_EVENT_NS) / 1e9,
        "source_time_per_wall_time": SOURCE_TIME_PER_WALL_TIME,
        "wall_publish_span_seconds": last_publish_wall - first_publish_wall,
        "publisher_transport": "synchronous_rospy_queue_size_none",
        "image_connections_at_end": image_pub.get_num_connections(),
        "imu_connections_at_end": imu_pub.get_num_connections(),
        "digests": observed_digests,
        "digests_match_frozen_manifest": digest_match,
        "rosbag_used": False,
        "groundtruth_published": False,
        "cam1_published": False,
    }
    print(json.dumps(result, sort_keys=True), flush=True)
    rospy.signal_shutdown("frozen_full_sequence_complete")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("preflight", "run"), required=True)
    parser.add_argument("--authorization-token")
    args = parser.parse_args()
    summary, cam_rows, imu_rows = validate_full_input()
    if args.action == "preflight":
        print(json.dumps(summary, sort_keys=True))
        return 0 if summary["ready"] else 1
    if args.authorization_token != AUTHORIZATION_TOKEN:
        print(json.dumps({"status": "BLOCKED_INVALID_TOKEN_NO_ROS_STARTED"}, sort_keys=True))
        return 2
    if not summary["ready"]:
        print(json.dumps(summary, sort_keys=True))
        return 3
    print(json.dumps({**summary, "status": "FULL_INPUT_VERIFIED_STARTING_ROS_PUBLISHER"}, sort_keys=True), flush=True)
    try:
        result = publish_full(cam_rows, imu_rows, summary["digests"])
    except Exception as exc:
        print(json.dumps({"status": "PUBLISH_FAILED_NO_RETRY", "error": type(exc).__name__ + ":" + str(exc)[:500]}, sort_keys=True), flush=True)
        return 1
    return 0 if result["status"] == "PUBLISH_COMPLETE" and result["camera_count"] == CAMERA_COUNT and result["imu_count"] == IMU_COUNT else 1


if __name__ == "__main__":
    sys.exit(main())
