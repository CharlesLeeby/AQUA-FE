#!/usr/bin/env python3
"""Frozen historical KLT with canonical AFRL image conversion streamed in RAM.

Only input serialization changes: no whole converted-image bag is materialized.
Header ordering matches a conventional converted ROS bag, including ties. The
original KLT package and export CLI come from the registered Git commit.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import time

import cv2
import numpy as np
import rosbag
import rospy
from cv_bridge import CvBridge
from std_msgs.msg import Header

from learned_loop_encoder_v1 import guard, sha

KLT_COMMIT = "3c50b742d6e0c69796a69813e42823e9895ed684"
EXPORT_SHA = "bb4e50d8b9777e76aee558d94ec0597461e9dcad4ff9c9486875b46a7c714d1d"
REAL_BAG = rosbag.Bag


def snapshot(root: Path) -> None:
    export = root / "uw_frontend/ros/export_vins_features.py"
    if root.exists():
        if sha(export) != EXPORT_SHA:
            raise ValueError("Existing KLT snapshot differs from frozen exporter")
        identity = json.loads((root / "snapshot_identity.json").read_text())
        for name, expected in identity["files"].items():
            if name == "snapshot_identity.json":
                continue  # Early preparation receipt included its empty self; never a source dependency.
            if sha(root / name) != expected:
                raise ValueError("Frozen KLT dependency changed: " + name)
        return
    payload = subprocess.check_output(["git", "archive", KLT_COMMIT, "uw_frontend",
        "scripts/learned_seedchain_env.sh", "scripts/run_afrl_cave_vins_eval.sh"])
    root.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        for member in archive.getmembers():
            p = Path(member.name)
            if p.is_absolute() or ".." in p.parts or member.issym() or member.islnk():
                raise ValueError("Unsafe Git source archive member")
        archive.extractall(root)
    if sha(export) != EXPORT_SHA:
        raise ValueError("KLT exporter does not match original frozen identity")
    identity = dict(commit=KLT_COMMIT, files={str(p.relative_to(root)): sha(p)
        for p in root.rglob("*") if p.is_file()})
    with (root / "snapshot_identity.json").open("x") as f:
        json.dump(identity, f, indent=2)


def canonical_image(msg):
    image = cv2.imdecode(np.frombuffer(msg.data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Undecodable original image: cannot claim complete input")
    h, w = image.shape[:2]
    image = cv2.resize(image, (max(1, round(w * .5)), max(1, round(h * .5))), interpolation=cv2.INTER_AREA)
    image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if image.shape != (600, 800):
        raise ValueError("Unexpected calibrated half-resolution dimensions")
    return image


class CanonicalAFRLBag:
    def __init__(self, raw: Path, image_topic: str, index: Path):
        self.raw = Path(raw)
        self.image_topic = image_topic
        self.bag = REAL_BAG(str(raw), "r")
        if index.exists():
            with np.load(index, allow_pickle=False) as data:
                if str(data["raw_path"].item()) != str(self.raw.resolve()) or int(data["raw_size"]) != self.raw.stat().st_size:
                    raise ValueError("Raw input index identity mismatch")
                if int(data["raw_mtime_ns"]) != self.raw.stat().st_mtime_ns or str(data["image_topic"].item()) != image_topic:
                    raise ValueError("Raw input changed after indexing")
                self.rows = data["rows"].copy()
        else:
            guard(index.parent, 32 * 1024**2)
            rows, connection_order = [], {}
            for ordinal, (topic, msg, stamp) in enumerate(self.bag.read_messages(topics=[image_topic, "/imu/imu"], raw=True)):
                datatype, data, _, position, _ = msg
                wanted = "sensor_msgs/CompressedImage" if topic == image_topic else "sensor_msgs/Imu"
                if datatype != wanted:
                    raise ValueError("Unexpected raw sensor schema")
                _, sec, nsec = struct.unpack_from("<III", data)
                ns = sec * 1000000000 + nsec
                if ns == 0:
                    ns = stamp.to_nsec()  # Exact existing converter fallback.
                rank = connection_order.setdefault(topic, len(connection_order))
                rows.append((ns, rank, ordinal, position[0], position[1], int(topic == image_topic)))
            # A converted bag's heapq.merge tie order is the order in which its
            # topic connections were first written, then their stable row order.
            rows.sort(key=lambda r: (r[0], r[1], r[2]))
            self.rows = np.asarray(rows, dtype=np.int64).reshape(-1, 6)
            if not len(rows):
                raise ValueError("Empty full sensor input")
            with index.open("xb") as f:
                np.savez(f, rows=self.rows, raw_path=str(self.raw.resolve()), raw_size=self.raw.stat().st_size,
                    raw_mtime_ns=self.raw.stat().st_mtime_ns, image_topic=image_topic)
        self.bridge = CvBridge()

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.bag.close()

    def get_start_time(self):
        return rospy.Time(int(self.rows[0, 0]) // 1000000000, int(self.rows[0, 0]) % 1000000000).to_sec()

    def get_end_time(self):
        return rospy.Time(int(self.rows[-1, 0]) // 1000000000, int(self.rows[-1, 0]) % 1000000000).to_sec()

    def read_messages(self, topics=None, selected_image_stamps=None):
        for ns, _, _, chunk, offset, is_image in self.rows:
            topic = "/camera/image_raw" if is_image else "/imu/imu"
            if topics is not None and topic not in topics:
                continue
            if is_image and selected_image_stamps is not None and int(ns) not in selected_image_stamps:
                continue
            _, msg, _ = self.bag._reader.seek_and_read_message_data_record((int(chunk), int(offset)), False)
            stamp = rospy.Time(int(ns) // 1000000000, int(ns) % 1000000000)
            if is_image:
                msg = self.bridge.cv2_to_imgmsg(canonical_image(msg), encoding="mono8")
                msg.header = Header(stamp=stamp, frame_id="afrl_camera")
            else:
                msg.header.stamp = stamp
            yield topic, msg, stamp


def frozen_arguments(root: Path, raw: Path, camera: Path, output: Path) -> list[str]:
    source = (root / "scripts/run_afrl_cave_vins_eval.sh").read_text()
    prefix = source[:source.index('mkdir -p "$RUN_DIR" "$VINS_OUTPUT"')]
    begin = source.index("    EXPORT_ARGS=(")
    end = source.index('    "${PYTHON_COMMAND[@]}" -m uw_frontend.ros.export_vins_features', begin)
    fragment = 'source "$ROOT/scripts/learned_seedchain_env.sh"\n' + prefix + "\n" + source[begin:end] + '\nprintf "%s\\0" "${EXPORT_ARGS[@]}"\n'
    env = dict(PATH="/usr/local/bin:/usr/bin:/bin", ROOT=str(root.resolve()),
        AQUAFE_SEEDCHAIN_PROFILE="lineage_early_seed_coverage_monotone_v2", RUN_DIR=str(output.resolve()),
        SHORT_BAG=str(raw.resolve()), CAMERA_CONFIG=str(camera.resolve()),
        MEASUREMENT_SELECTION="0", EXPORT_MAX_FEATURES="350", VINS_MAX_CNT="350",
        VINS_SAFE_SOURCE_SELECTION="0", FORMAL_THREE_LAYER_EXPORT="0", PROCESS_SKIPPED_FRAMES="1",
        PREPROCESS="adaptive_clahe", SEMIDENSE_FALLBACK_METHOD="none", BACKEND_QUALITY_MODE="vins_safe",
        BACKEND_QUALITY_ALPHA="0.65", BACKEND_QUALITY_FLOOR="0.80", FRAME_OFFSET="0")
    result = subprocess.check_output(["bash", "-c", fragment, "frozen-args", "external", "klt", "0", "0", "2"], env=env)
    args = result.decode().rstrip("\0").split("\0")
    # References are evaluation-only. Removing their copy request does not touch
    # an image, IMU, feature, quality value or the original export gates.
    i = args.index("/afrl/colmap_gt")
    assert args[i - 1] == "--copy-topic"
    del args[i - 1:i + 1]
    return args


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-bag", type=Path, required=True)
    parser.add_argument("--raw-image-topic", required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--camera-config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--probe-max-frames", type=int)
    args = parser.parse_args()
    guard(args.output_dir, 256 * 1024**2)
    if args.output_dir.exists():
        raise FileExistsError("Preserve previous export attempt")
    args.output_dir.mkdir(parents=True)
    snapshot(args.snapshot)
    argv = frozen_arguments(args.snapshot, args.raw_bag, args.camera_config, args.output_dir)
    if args.probe_max_frames is not None:
        argv += ["--max-frames", str(args.probe_max_frames)]
    identity = dict(status="REGISTERED_BEFORE_EXPORT", source_commit=KLT_COMMIT,
        exporter_sha256=EXPORT_SHA, argv=argv, raw_bag=str(args.raw_bag.resolve()),
        camera_sha256=sha(args.camera_config), input_adapter="canonical AFRL decode-half-gray/header-sorted stream; no GT", independent_vio=False)
    with (args.output_dir / "input_lock.json").open("x") as f:
        json.dump(identity, f, indent=2)
    canonical = CanonicalAFRLBag(args.raw_bag, args.raw_image_topic, args.index)
    source_counts = dict(images=int(canonical.rows[:, 5].sum()), imu=int((canonical.rows[:, 5] == 0).sum()))
    if args.probe_max_frames is not None:
        # A small, explicitly labeled prefix probe, never a formal local repeat.
        positions = np.flatnonzero(canonical.rows[:, 5])
        stop = positions[min(len(positions), args.probe_max_frames * 2) - 1] + 1
        canonical.rows = canonical.rows[:stop]
    raw_path = args.raw_bag.resolve()
    def bag_factory(path, mode="r", *more, **kwargs):
        if mode == "r" and Path(path).resolve() == raw_path:
            return canonical
        guard(args.output_dir)
        return REAL_BAG(path, mode, *more, **kwargs)
    sys.path.insert(0, str(args.snapshot.resolve()))
    from uw_frontend.ros import export_vins_features as exporter
    assert sha(Path(exporter.__file__)) == EXPORT_SHA
    exporter.rosbag.Bag = bag_factory
    sys.argv = [str(exporter.__file__), *argv]
    started = time.monotonic()
    exporter.main()
    identity.update(status="EXPORT_COMPLETE", wall_s=time.monotonic() - started,
        feature_bag_sha256=sha(args.output_dir / "features.bag"), raw_bag_sha256=sha(args.raw_bag),
        input_index_sha256=sha(args.index), full_source_counts=source_counts,
        actual_input_image_messages=int(canonical.rows[:, 5].sum()),
        actual_input_imu_messages=int((canonical.rows[:, 5] == 0).sum()),
        probe=args.probe_max_frames is not None)
    with (args.output_dir / "export_receipt.json").open("x") as f:
        json.dump(identity, f, indent=2)
    print(json.dumps(identity))


if __name__ == "__main__":
    main()
