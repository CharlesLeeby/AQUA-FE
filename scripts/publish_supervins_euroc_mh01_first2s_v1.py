#!/usr/bin/env python3
"""Publish the frozen official EuRoC MH_01 first-two-second prefix once.

Images are losslessly decoded from the official PNGs and copied as raw mono8
pixels.  No resize, color conversion, normalization, compression, bag, cam1,
ground truth, or derived feature message is produced.
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
MANIFEST = ROOT / "papers/supervins_v1_official_euroc_mh01_first2s_input_manifest_v1.json"
MANIFEST_SHA256 = "a8ec6e7e878ec28e018b78fc1cd891acfa5a05825264d3b58d8b4630fa51a398"
MANIFEST_SIZE = 6866
DATASET = Path("/mnt/data/AQUA-FE_WS/datasets/official_euroc_v1/MH01/MH_01_easy")
MAV0 = DATASET / "mav0"
CAMERA_CSV = MAV0 / "cam0/data.csv"
CAMERA_DATA = MAV0 / "cam0/data"
IMU_CSV = MAV0 / "imu0/data.csv"
START_NS = 1403636579763555584
END_NS = 1403636581763555584
AUTHORIZATION_TOKEN = "SUPERVINS_STAGE3_MH01_FIRST2S_PUBLISH_ONCE"


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


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


def validate_and_materialize():
    errors = []
    manifest_identity = file_identity(MANIFEST)
    if manifest_identity != {"sha256": MANIFEST_SHA256, "size_bytes": MANIFEST_SIZE}:
        errors.append("manifest_identity")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("status") != "FROZEN_BEFORE_STAGE_3_ROS_OR_MODEL_START":
        errors.append("manifest_status")

    for path_text, expected in manifest["source_metadata_pins"].items():
        try:
            observed = file_identity(path_text)
        except OSError:
            observed = None
        if observed != expected:
            errors.append("source_metadata_pin:" + path_text)

    cam_rows_all = load_rows(CAMERA_CSV)
    imu_rows_all = load_rows(IMU_CSV)
    cam_rows = [row for row in cam_rows_all if START_NS <= int(row[0]) <= END_NS]
    imu_rows = [row for row in imu_rows_all if START_NS <= int(row[0]) <= END_NS]
    if len(cam_rows) != 41 or int(cam_rows[0][0]) != START_NS or int(cam_rows[-1][0]) != END_NS:
        errors.append("camera_selection")
    if len(imu_rows) != 401 or int(imu_rows[0][0]) != START_NS or int(imu_rows[-1][0]) != END_NS:
        errors.append("imu_selection")
    if any(int(b[0]) <= int(a[0]) for a, b in zip(cam_rows, cam_rows[1:])):
        errors.append("camera_order")
    if any(int(b[0]) <= int(a[0]) for a, b in zip(imu_rows, imu_rows[1:])):
        errors.append("imu_order")

    asset_digest = hashlib.sha256()
    decoded_digest = hashlib.sha256()
    cameras = []
    for timestamp_text, filename in cam_rows:
        timestamp_ns = int(timestamp_text)
        path = CAMERA_DATA / filename
        encoded = path.read_bytes()
        png_sha = sha256_bytes(encoded)
        image = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if image is None or image.shape != (480, 752) or image.dtype != np.uint8:
            errors.append("camera_decode:" + filename)
            continue
        if not image.flags["C_CONTIGUOUS"]:
            image = np.ascontiguousarray(image)
        pixels = image.tobytes(order="C")
        pixel_sha = sha256_bytes(pixels)
        relative = "mav0/cam0/data/" + filename
        asset_digest.update(
            f"{timestamp_ns}\0{relative}\0{len(encoded)}\0{png_sha}\n".encode("utf-8")
        )
        decoded_digest.update(
            f"{timestamp_ns}\0{image.shape[0]}\0{image.shape[1]}\0{image.dtype}\0{len(pixels)}\0{pixel_sha}\n".encode("utf-8")
        )
        cameras.append(
            {
                "timestamp_ns": timestamp_ns,
                "filename": filename,
                "pixels": pixels,
                "png_sha256": png_sha,
                "decoded_sha256": pixel_sha,
            }
        )

    imu_text = "".join(",".join(row) + "\n" for row in imu_rows)
    imu_digest = sha256_bytes(imu_text.encode("utf-8"))
    events = []
    for row in imu_rows:
        events.append((int(row[0]), 0, "I", ",".join(row)))
    for row in cam_rows:
        events.append((int(row[0]), 1, "C", row[1]))
    events.sort()
    event_digest = hashlib.sha256()
    for timestamp_ns, type_order, kind, payload in events:
        event_digest.update(
            f"{timestamp_ns}\0{type_order}\0{kind}\0{payload}\n".encode("utf-8")
        )

    expected = manifest["selected_content_digests"]
    observed_digests = {
        "camera_png_assets": asset_digest.hexdigest(),
        "camera_decoded_mono8_pixels": decoded_digest.hexdigest(),
        "imu_rows": imu_digest,
        "combined_events": event_digest.hexdigest(),
    }
    for key, observed in observed_digests.items():
        if observed != expected[key]["sha256"]:
            errors.append("selected_digest:" + key)

    imu_records = [
        {
            "timestamp_ns": int(row[0]),
            "angular_velocity": tuple(float(value) for value in row[1:4]),
            "linear_acceleration": tuple(float(value) for value in row[4:7]),
            "row": row,
        }
        for row in imu_rows
    ]
    camera_by_timestamp = {item["timestamp_ns"]: item for item in cameras}
    imu_by_timestamp = {item["timestamp_ns"]: item for item in imu_records}
    materialized_events = []
    for timestamp_ns, type_order, kind, _ in events:
        item = imu_by_timestamp[timestamp_ns] if kind == "I" else camera_by_timestamp[timestamp_ns]
        materialized_events.append((timestamp_ns, type_order, kind, item))

    summary = {
        "status": "READY_NO_ROS_STARTED" if not errors else "BLOCKED_INPUT_IDENTITY",
        "ready": not errors,
        "errors": errors,
        "manifest": manifest_identity,
        "sequence": "MH_01_easy_NOT_README_V2_01",
        "start_timestamp_ns": START_NS,
        "end_timestamp_ns": END_NS,
        "duration_ns": END_NS - START_NS,
        "camera_count": len(cameras),
        "imu_count": len(imu_records),
        "event_count": len(materialized_events),
        "digests": observed_digests,
        "image_shape": [480, 752],
        "image_dtype": "uint8",
        "ros_started": False,
    }
    return summary, materialized_events


def ros_time(timestamp_ns, rospy):
    return rospy.Time(timestamp_ns // 1_000_000_000, timestamp_ns % 1_000_000_000)


def publish_once(events):
    import rospy
    from sensor_msgs.msg import Image, Imu

    rospy.init_node("aqua_fe_euroc_mh01_first2s_publisher", anonymous=False, disable_signals=True)
    image_pub = rospy.Publisher("/cam0/image_raw", Image, queue_size=100, tcp_nodelay=True)
    imu_pub = rospy.Publisher("/imu0", Imu, queue_size=2000, tcp_nodelay=True)
    connection_deadline = time.monotonic() + 12.0
    while time.monotonic() < connection_deadline:
        if image_pub.get_num_connections() >= 1 and imu_pub.get_num_connections() >= 1:
            break
        if rospy.is_shutdown():
            raise RuntimeError("rospy_shutdown_before_connections")
        time.sleep(0.05)
    if image_pub.get_num_connections() < 1 or imu_pub.get_num_connections() < 1:
        raise RuntimeError("required_supervins_subscribers_not_connected")

    first_timestamp = events[0][0]
    wall_start = time.monotonic() + 0.20
    camera_count = 0
    imu_count = 0
    first_publish_wall = None
    last_publish_wall = None
    for timestamp_ns, _, kind, item in events:
        target = wall_start + (timestamp_ns - first_timestamp) / 1_000_000_000.0
        while True:
            remaining = target - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(remaining, 0.01))
        if rospy.is_shutdown():
            raise RuntimeError("rospy_shutdown_during_publish")
        if first_publish_wall is None:
            first_publish_wall = time.monotonic()
        if kind == "I":
            msg = Imu()
            msg.header.seq = imu_count
            msg.header.stamp = ros_time(timestamp_ns, rospy)
            msg.header.frame_id = "imu0"
            msg.orientation_covariance[0] = -1.0
            msg.angular_velocity.x, msg.angular_velocity.y, msg.angular_velocity.z = item["angular_velocity"]
            msg.linear_acceleration.x, msg.linear_acceleration.y, msg.linear_acceleration.z = item["linear_acceleration"]
            imu_pub.publish(msg)
            imu_count += 1
        else:
            msg = Image()
            msg.header.seq = camera_count
            msg.header.stamp = ros_time(timestamp_ns, rospy)
            msg.header.frame_id = "cam0"
            msg.height = 480
            msg.width = 752
            msg.encoding = "mono8"
            msg.is_bigendian = 0
            msg.step = 752
            msg.data = item["pixels"]
            image_pub.publish(msg)
            camera_count += 1
            print(
                json.dumps(
                    {
                        "event": "CAMERA_PUBLISHED",
                        "index": camera_count - 1,
                        "timestamp_ns": timestamp_ns,
                        "filename": item["filename"],
                        "decoded_sha256": item["decoded_sha256"],
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        last_publish_wall = time.monotonic()
    time.sleep(0.50)
    result = {
        "status": "PUBLISH_COMPLETE",
        "camera_count": camera_count,
        "imu_count": imu_count,
        "event_count": camera_count + imu_count,
        "first_timestamp_ns": START_NS,
        "last_timestamp_ns": END_NS,
        "source_span_seconds": (END_NS - START_NS) / 1_000_000_000.0,
        "wall_publish_span_seconds": last_publish_wall - first_publish_wall,
        "image_connections_at_end": image_pub.get_num_connections(),
        "imu_connections_at_end": imu_pub.get_num_connections(),
        "rosbag_used": False,
        "groundtruth_published": False,
        "cam1_published": False,
    }
    print(json.dumps(result, sort_keys=True), flush=True)
    rospy.signal_shutdown("frozen_prefix_complete")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("preflight", "run"), required=True)
    parser.add_argument("--authorization-token")
    args = parser.parse_args()
    summary, events = validate_and_materialize()
    if args.action == "preflight":
        print(json.dumps(summary, sort_keys=True))
        return 0 if summary["ready"] else 1
    if args.authorization_token != AUTHORIZATION_TOKEN:
        print(json.dumps({"status": "BLOCKED_INVALID_TOKEN_NO_ROS_STARTED"}, sort_keys=True))
        return 2
    if not summary["ready"]:
        print(json.dumps(summary, sort_keys=True))
        return 3
    print(json.dumps({**summary, "status": "INPUT_VERIFIED_STARTING_ROS_PUBLISHER"}, sort_keys=True), flush=True)
    try:
        result = publish_once(events)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "PUBLISH_FAILED_NO_RETRY",
                    "error": type(exc).__name__ + ":" + str(exc)[:500],
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 1
    return 0 if result["camera_count"] == 41 and result["imu_count"] == 401 else 1


if __name__ == "__main__":
    sys.exit(main())
