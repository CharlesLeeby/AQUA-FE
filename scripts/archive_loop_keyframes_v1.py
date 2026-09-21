#!/usr/bin/env python3
"""Materialize ONE immutable native keyframe roster from passive VINS messages.

Inputs are a capture bag of /vins_estimator/{keyframe_pose,keyframe_point} and
the SAME converted mono8 image bag used for external KLT export. No reference
trajectory is read, no estimator runs, and no points/observations are invented.
Consume this archive for both C and L, not the live node's lossy image queue.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess

import numpy as np

POSE_TOPIC = "/vins_estimator/keyframe_pose"
POINT_TOPIC = "/vins_estimator/keyframe_point"
FEATURE_TOPIC = "/feature_tracker/feature"
FIELDS = ["id", "timestamp_ns", "tx", "ty", "tz", "qw", "qx", "qy", "qz",
          "image", "points", "point_count", "image_sha256", "points_sha256"]


def native_header_ns(original_ns: int) -> int:
    """Exact ROS C++ Time(double(Time::toSec())) path, not nearest matching.

    feature_callback -> inputFeature(double) -> Headers[] -> pubKeyframe.
    C++ fromSec rounds positive fractional nanoseconds, unlike Python genpy's
    truncation. Preserve both original and native-published timestamps.
    """
    sec, nsec = divmod(int(original_ns), 1000000000)
    value = float(sec) + 1e-9 * float(nsec)
    integer = math.floor(value)
    fraction = math.floor((value - integer) * 1e9 + .5)
    return integer * 1000000000 + fraction


def exact_header_map(original_stamps):
    result = {}
    for stamp in original_stamps:
        native = native_header_ns(stamp)
        if native in result:
            raise ValueError("Duplicate/colliding feature timestamp; no ambiguous image join")
        result[native] = int(stamp)
    return result


def published_occurrences(rows, selected_stamps, every_n: int, frame_offset: int) -> dict[int, int]:
    """Resolve same-header raw images by the frozen export image-index phase.

    Image indices count image messages only, exactly as export_vins_features.py
    counts ``seen_images``. A selected stamp must map to one published image;
    otherwise the archive remains ambiguous and must fail.
    """
    if every_n < 1 or not 0 <= frame_offset < every_n:
        raise ValueError("Invalid frozen image sampling phase")
    occurrences, chosen = defaultdict(int), defaultdict(list)
    image_index = 0
    for row in rows:
        if int(row[5]) != 1:
            continue
        stamp = int(row[0])
        occurrence = occurrences[stamp]
        occurrences[stamp] += 1
        if stamp in selected_stamps and image_index % every_n == frame_offset:
            chosen[stamp].append(occurrence)
        image_index += 1
    if set(chosen) != set(selected_stamps) or any(len(items) != 1 for items in chosen.values()):
        raise ValueError("Selected keyframe lacks a unique frozen-phase source image")
    return {stamp: items[0] for stamp, items in chosen.items()}


def frozen_export_phase(exported: dict) -> tuple[int, int]:
    argv = exported.get("argv", [])
    def option(name: str, default: int) -> int:
        found = [argv[i + 1] for i, value in enumerate(argv[:-1]) if value == name]
        if len(found) > 1:
            raise ValueError("Ambiguous frozen exporter option: " + name)
        return int(found[0]) if found else default
    return option("--every-n", 1), option("--frame-offset", 0)


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
    if "header_identity_csv_sha256" in receipt:
        mapping = root / "header_identity.csv"
        if hash_file(mapping) != receipt["header_identity_csv_sha256"]:
            raise ValueError("Original/native timestamp mapping identity mismatch")
        with mapping.open() as f:
            headers = list(csv.DictReader(f))
        if len(headers) != receipt.get("keyframes"):
            raise ValueError("Timestamp mapping count mismatch")
        for row in headers:
            if native_header_ns(int(row["original_feature_ns"])) != int(row["native_published_ns"]):
                raise ValueError("Timestamp mapping does not reproduce the native publisher")
    with manifest.open(newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != FIELDS:
            raise ValueError("Archive roster schema mismatch")
        rows = list(reader)
    if not rows or len(rows) != receipt.get("keyframes"):
        raise ValueError("Archive keyframe count mismatch")
    if "header_identity_csv_sha256" in receipt:
        for row, mapping_row in zip(rows, headers):
            if row["id"] != mapping_row["id"] or row["timestamp_ns"] != mapping_row["native_published_ns"]:
                raise ValueError("Original/native timestamp mapping refers to another keyframe")
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
    parser.add_argument("--raw-image-topic", help="Use the identical canonical streamed AFRL conversion")
    parser.add_argument("--raw-index", type=Path)
    parser.add_argument("--export-receipt", type=Path, help="Reuse verified raw-bag hash under unchanged indexed file identity")
    parser.add_argument("--image-pool", type=Path, help="Task-local content-addressed PNG hardlinks shared across repeats")
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
    poses, points, original_features = {}, {}, []
    with rosbag.Bag(str(args.capture_bag), "r") as bag:
        for topic, message, _ in bag.read_messages(topics=[POSE_TOPIC, POINT_TOPIC, FEATURE_TOPIC]):
            stamp = message.header.stamp.to_nsec()
            if topic == FEATURE_TOPIC:
                original_features.append(stamp)
                continue
            target = poses if topic == POSE_TOPIC else points
            if stamp <= 0 or stamp in target:
                raise ValueError("Duplicate/nonpositive native header timestamp")
            target[stamp] = message
    stamps = select_roster(poses, points)
    if not stamps:
        raise SystemExit("No keyframes after native selection; do not fabricate an archive")
    native_to_original = exact_header_map(original_features)
    if not set(stamps).issubset(native_to_original):
        raise ValueError("Native keyframe missing exact forward identity in captured original features")
    original_to_native = {native_to_original[stamp]: stamp for stamp in stamps}
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "images").mkdir()
    (args.output_dir / "points").mkdir()
    stamp_to_id = {stamp: i for i, stamp in enumerate(stamps)}
    saved = {}
    bridge = CvBridge()
    if args.raw_image_topic is not None:
        if args.raw_index is None:
            parser.error("Raw AFRL images require their shared --raw-index")
        from run_loop_klt_export_v1 import CanonicalAFRLBag
        source = CanonicalAFRLBag(args.images_bag, args.raw_image_topic, args.raw_index)
    else:
        source = rosbag.Bag(str(args.images_bag), "r")
    image_source_hash = None
    selected_occurrence = None
    if args.export_receipt is not None:
        if args.raw_image_topic is None or args.raw_index is None:
            raise ValueError("Hash reuse requires the validated canonical raw index")
        exported = json.loads(args.export_receipt.read_text())
        if (exported.get("status") != "EXPORT_COMPLETE" or exported.get("probe") is not False
                or Path(exported["raw_bag"]).resolve() != args.images_bag.resolve()
                or exported["input_index_sha256"] != hash_file(args.raw_index)):
            raise ValueError("Export/raw-image identity mismatch")
        # CanonicalAFRLBag already checked original path,size,mtime and topic.
        image_source_hash = exported["raw_bag_sha256"]
        every_n, frame_offset = frozen_export_phase(exported)
        selected_occurrence = published_occurrences(
            source.rows, set(original_to_native), every_n, frame_offset)
    seen_occurrences = defaultdict(int)
    with source as bag:
        stream = (bag.read_messages(topics=[args.image_topic], selected_image_stamps=set(original_to_native))
                  if args.raw_image_topic is not None else bag.read_messages(topics=[args.image_topic]))
        for _, message, _ in stream:
            original_stamp = message.header.stamp.to_nsec()
            if original_stamp not in original_to_native:
                continue
            occurrence = seen_occurrences[original_stamp]
            seen_occurrences[original_stamp] += 1
            if selected_occurrence is not None and occurrence != selected_occurrence[original_stamp]:
                continue
            stamp = original_to_native[original_stamp]
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
            if args.image_pool is None:
                if not cv2.imwrite(str(path), image, [cv2.IMWRITE_PNG_COMPRESSION, 3]):
                    raise OSError("Failed to save keyframe PNG")
            else:
                args.image_pool.mkdir(parents=True, exist_ok=True)
                ok, encoded = cv2.imencode(".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 3])
                if not ok:
                    raise OSError("Failed to encode keyframe PNG")
                blob = encoded.tobytes()
                digest = hashlib.sha256(blob).hexdigest()
                pooled = args.image_pool / (digest + ".png")
                if pooled.exists():
                    if hash_file(pooled) != digest:
                        raise ValueError("Shared PNG content identity mismatch")
                else:
                    with pooled.open("xb") as f:
                        f.write(blob)
                os.link(pooled, path)  # Same filesystem; no copy or symlink fallback.
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
    mapping = args.output_dir / "header_identity.csv"
    with mapping.open("x", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["id", "original_feature_ns", "native_published_ns", "difference_ns"])
        writer.writerows([i, native_to_original[stamp], stamp, stamp - native_to_original[stamp]] for i, stamp in enumerate(stamps))
    receipt = {
        "schema": "aqua-fe-native-keyframe-archive-v1",
        "status": "COMPLETE",
        "pose_frame": "world_T_imu_body",
        "points_layout": "little-endian float32 rows: world_XYZ,norm_xy,pixel_uv,feature_id",
        "selection": "native first10 skip; skip_count0; distance strictly greater than0",
        "capture_bag_sha256": hash_file(args.capture_bag),
        "images_bag_sha256": image_source_hash or hash_file(args.images_bag),
        "raw_bag_hash_reused_under_validated_index_identity": image_source_hash is not None,
        "adapter_sha256": hash_file(Path(__file__)),
        "adapter_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "keyframes_csv_sha256": hash_file(manifest),
        "native_pose_messages": len(poses),
        "keyframes": len(stamps),
        "exact_image_join_missing": 0,
        "header_identity_csv_sha256": hash_file(mapping),
        "header_join": "unique exact forward ROS C++ double conversion from captured feature headers; no nearest neighbor or tolerance",
        "geometry_verified": "Not evaluated",
        "ground_truth_used": False,
        "raw_stream_input": args.raw_image_topic is not None,
        "duplicate_header_resolution": (
            "Unique published image index from frozen exporter every_n/frame_offset"
            if selected_occurrence is not None else "none; duplicate selected timestamps rejected"),
        "image_storage": "shared content-addressed hardlink" if args.image_pool else "independent PNG",
    }
    with (args.output_dir / "archive_receipt.json").open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
