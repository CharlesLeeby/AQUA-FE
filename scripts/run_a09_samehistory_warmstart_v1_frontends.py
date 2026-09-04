#!/usr/bin/env python3
"""Fail-closed A09 full-history KLT and causal XFeat frontend runner.

The two stages are deliberately separate and one-shot.  Each stage writes into
an unpublished staging directory, exposes only a temporary canonical symlink to
the child process, audits the complete result, then atomically replaces that
symlink with the accepted real directory.  No VINS backend is started here.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import io
import itertools
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from typing import Any, Iterable


ROOT = Path("/home/ma/AQUA-FE_WS")
EXP_ROOT = Path("/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1")
FRONTENDS = EXP_ROOT / "frontends"
RAW_BAG = EXP_ROOT / "raw/archaeo09_0000_4400.bag"
RAW_RECEIPT = EXP_ROOT / "raw/raw_materialization_receipt_v1.json"
RAW_ADDENDUM = EXP_ROOT / "raw/raw_materialization_canonicalization_addendum_v1.json"
RAW_FREEZE = ROOT / "papers/a09_samehistory_warmstart_v1_raw_materialization_freeze.json"
PROTOCOL = ROOT / "papers/a09_samehistory_warmstart_v1_frontends_protocol.md"

KLT_DIR = FRONTENDS / "klt_export"
KLT_STAGE = FRONTENDS / ".klt_export.stage_v1"
KLT_FAILURE = FRONTENDS / "klt_export_failed_v1"
KLT_TAG = "systemfair_a09_warmstart_v1_feed0000_4400_klt_export"
KLT_WORKSPACE = ROOT / f"logs/aqualoc_archaeo_vins/external_klt_every2_{KLT_TAG}"

AQUA_DIR = FRONTENDS / "aquafe_finalonline"
AQUA_STAGE = FRONTENDS / ".aquafe_finalonline.stage_v1"
AQUA_FAILURE = FRONTENDS / "aquafe_finalonline_failed_v1"

GLOBAL_FLOCK = EXP_ROOT / ".frontend_supervisor.flock"
SOURCE_ARCHIVE = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences/archaeo_sequence_9_raw_data.tar.gz"
)
GT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences/archaeo_groundtruth_files/"
    "new_archaeo_colmap_traj_sequence_09.txt"
)

KLT_PROFILE = ROOT / "scripts/run_paper_sidecar_profiles.sh"
AQUALOC_RUNNER = ROOT / "scripts/run_aqualoc_archaeo_vins_eval.sh"
EXPORTER = ROOT / "uw_frontend/ros/export_vins_features.py"
MIRROR_CONFIG = ROOT / "uw_frontend/configs/experiments/formal_loftr_mirror_contribution_v33_frontend.yaml"
XFEAT_NODE = ROOT / "uw_frontend/ros/xfeat_seed_sidecar_node.py"
LINEAGE_NODE = ROOT / "uw_frontend/ros/causal_lineage_shadow_node.py"
XFEAT_CONFIG = ROOT / "uw_frontend/configs/experiments/low_texture_lineage_safe_dense_start_frontend.yaml"
XFEAT_WEIGHTS = ROOT / "external_tools/accelerated_features/weights/xfeat.pt"

IDENTITIES = {
    RAW_BAG: (1_187_038_470, "a4a24bd0c2451f4996d39f635e55fd99730698bf704c4e7dc81729070d0dca97"),
    RAW_RECEIPT: (7_199, "b6f0ec00f04d5c62514b96b3ce591bc561221227ea05163793fc68d8c4d3cf91"),
    RAW_ADDENDUM: (2_717, "86e82d58dbd85f39907144aa1098352b97282c143fef5259cacd2974c4ca0956"),
    RAW_FREEZE: (2_422, "d72dcef75052194a8e48a8e14da5233412345b66a60b7c53e93e4650779cfa57"),
    SOURCE_ARCHIVE: (1_722_658_380, "4d20237571928067cfe4dbb813224cfd2277270c424a6ef97ef50d2933da2901"),
    GT: (45_197, "b732a68ec354cb66d36b1a9f708d614c70e884d4c167f8940f9601cfce69ac17"),
    KLT_PROFILE: (38_686, "266e3c6f0c57eaae0555e1918298d450d9452794569de83de83700f8bae87130"),
    AQUALOC_RUNNER: (53_928, "9da109074d559875434bc82e43febd7acf1e60c027f11bae31023e6d08198a9b"),
    EXPORTER: (437_542, "567ccc74989d7fb4ddcb38ac558fecea33033139a0b0db98e61124c6bac5a00d"),
    MIRROR_CONFIG: (447, "e50669deb51da948999aafa004ff6c5c7d355445847ef1db4252bad829bb15f4"),
    XFEAT_NODE: (41_561, "9afc6f7083f76bf1f7c6b7c19f79f02a98160663c945479b51492fa19cb3ace7"),
    LINEAGE_NODE: (16_891, "8856e0aff281ba30a31b2370ee2c6ff949f830c4230f3a2d358143f80628a727"),
    XFEAT_CONFIG: (778, "369120917878b55564d6d993670328738e5436beae92bee25e99dd86c3eb66a6"),
    XFEAT_WEIGHTS: (6_247_949, "0f5187fd7bedd26c7fe6acc9685444493a165a35ecc087b33c2db3627f3ea10b"),
}

FEATURE_TOPIC = "/feature_tracker/feature"
SIDECAR_TOPIC = "/feature_tracker/sidecar"
CAMERA_TOPIC = "/camera/image_raw"
IMU_TOPIC = "/rtimulib_node/imu"
GT_TOPIC = "/aqualoc/colmap_gt"
CHANNELS = (
    "id", "camera_id", "p_u", "p_v", "velocity_x", "velocity_y",
    "gx", "gy", "gz", "quality", "sigma", "source_code", "is_learned",
)
CAMERA_COUNT = 4401
FEATURE_COUNT = 2200
PREFIX_FEATURE_COUNT = 2000
SCORE_FEATURE_COUNT = 200
IMU_COUNT = 44025
GT_COUNT = 213
FEATURE_FIRST_NS = 1_542_888_746_121_190_768
FEATURE_LAST_NS = 1_542_888_965_985_217_392
SCORE_FEATURE_FIRST_NS = 1_542_888_946_088_258_928
SCORE_FEATURE_LAST_NS = FEATURE_LAST_NS
KLT_HEADER_SHA256 = "7afdc87e9515a88a83e4c7560042b3013f9dce303f77da2f40e6c6fcab846e83"
AQUA_HEADER_SHA256 = "f9ea50d9fb582d076bd22278d02111d021f73b1ebe346c5aadaaeaed2ca9fb36"
CAMERA_YAML_SHA256 = "045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5"


class FrontendError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise FrontendError(code)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, Any]:
    return {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256(path)}


def require_identity(path: Path, expected: tuple[int, str]) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"IDENTITY_NOT_REGULAR:{path}")
    actual = identity(path)
    require((actual["size_bytes"], actual["sha256"]) == expected, f"IDENTITY_DRIFT:{path}")
    return actual


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def exact_ns(stamp: Any) -> int:
    require(type(stamp.secs) is int and type(stamp.nsecs) is int, "STAMP_NOT_INTEGER")
    require(stamp.secs >= 0 and 0 <= stamp.nsecs < 1_000_000_000, "STAMP_RANGE")
    return stamp.secs * 1_000_000_000 + stamp.nsecs


def add_serialized(digest: Any, message: Any, record_stamp: Any) -> None:
    payload = io.BytesIO()
    message.serialize(payload)
    data = payload.getvalue()
    digest.update(exact_ns(record_stamp).to_bytes(8, "big"))
    digest.update(len(data).to_bytes(8, "big"))
    digest.update(data)


def rosbag_module() -> Any:
    ros_path = "/opt/ros/noetic/lib/python3/dist-packages"
    if ros_path not in sys.path:
        sys.path.insert(0, ros_path)
    import rosbag  # type: ignore
    return rosbag


def raw_contract() -> dict[str, Any]:
    rosbag = rosbag_module()
    cameras: list[int] = []
    counts = {CAMERA_TOPIC: 0, IMU_TOPIC: 0, GT_TOPIC: 0}
    digests = {IMU_TOPIC: hashlib.sha256(), GT_TOPIC: hashlib.sha256()}
    with rosbag.Bag(str(RAW_BAG), "r") as bag:
        for topic, message, record_stamp in bag.read_messages(
            topics=[CAMERA_TOPIC, IMU_TOPIC, GT_TOPIC]
        ):
            stamp = exact_ns(message.header.stamp)
            require(stamp == exact_ns(record_stamp), f"RAW_HEADER_RECORD_MISMATCH:{topic}")
            counts[topic] += 1
            if topic == CAMERA_TOPIC:
                cameras.append(stamp)
            else:
                add_serialized(digests[topic], message, record_stamp)
    require(counts == {CAMERA_TOPIC: CAMERA_COUNT, IMU_TOPIC: IMU_COUNT, GT_TOPIC: GT_COUNT}, "RAW_COUNTS_DRIFT")
    require(all(b > a for a, b in zip(cameras, cameras[1:])), "RAW_CAMERA_NOT_INCREASING")
    feature_stamps = cameras[1:4400:2]
    require(len(feature_stamps) == FEATURE_COUNT, "RAW_FEATURE_BINDING_COUNT")
    require(feature_stamps[0] == FEATURE_FIRST_NS and feature_stamps[-1] == FEATURE_LAST_NS, "RAW_FEATURE_ENDPOINT_DRIFT")
    require(feature_stamps[PREFIX_FEATURE_COUNT] == SCORE_FEATURE_FIRST_NS, "RAW_SCORE_FEATURE_FIRST_DRIFT")
    return {
        "counts": counts,
        "camera_stamps": cameras,
        "feature_stamps": feature_stamps,
        "stream_sha256": {topic: digest.hexdigest() for topic, digest in digests.items()},
    }


def channel_map(message: Any) -> dict[str, list[float]]:
    names = tuple(channel.name for channel in message.channels)
    require(names == CHANNELS, f"POINTCLOUD_CHANNEL_DRIFT:{names}")
    values = {channel.name: list(channel.values) for channel in message.channels}
    require(all(len(column) == len(message.points) for column in values.values()), "POINTCLOUD_CHANNEL_LENGTH")
    return values


def integral(value: float, code: str) -> int:
    require(math.isfinite(value), f"NONFINITE:{code}")
    rounded = round(value)
    require(abs(value - rounded) <= 1e-6, f"NONINTEGRAL:{code}:{value}")
    return int(rounded)


def audit_pointcloud_common(message: Any, expected_topic: str, *, base: bool) -> dict[str, list[float]]:
    require(message._type == "sensor_msgs/PointCloud", f"POINTCLOUD_TYPE:{expected_topic}")
    require(message._md5sum == "d8e9c3f5afbdd8a130fd1d2763945fca", f"POINTCLOUD_MD5:{expected_topic}")
    require(message.header.frame_id == "world" and message.header.seq == 0, f"POINTCLOUD_HEADER:{expected_topic}")
    channels = channel_map(message)
    for point in message.points:
        require(all(math.isfinite(v) for v in (point.x, point.y, point.z)), "POINT_NONFINITE")
        require(abs(point.z - 1.0) <= 1e-7, "POINT_Z_DRIFT")
    for name, values in channels.items():
        require(all(math.isfinite(value) for value in values), f"CHANNEL_NONFINITE:{name}")
    if base:
        require(len(message.points) == 350, "KLT_POINT_COUNT")
        ids = [integral(value, "id") for value in channels["id"]]
        require(len(set(ids)) == 350 and min(ids) >= 0 and max(ids) < 10_000_000, "KLT_ID_CONTRACT")
        require(all(integral(v, "camera_id") == 0 for v in channels["camera_id"]), "KLT_CAMERA_ID")
        require(all(integral(v, "source_code") in {1, 2} for v in channels["source_code"]), "KLT_SOURCE")
        require(all(integral(v, "is_learned") == 0 for v in channels["is_learned"]), "KLT_LEARNED_FLAG")
        for name in ("gx", "gy", "gz"):
            require(all(value == 0.0 for value in channels[name]), f"KLT_{name}_DRIFT")
        require(all(0.0 <= value < 968.0 for value in channels["p_u"]), "KLT_PU_RANGE")
        require(all(0.0 <= value < 608.0 for value in channels["p_v"]), "KLT_PV_RANGE")
        require(all(0.799999 <= value <= 1.000001 for value in channels["quality"]), "KLT_QUALITY_RANGE")
        for quality, sigma in zip(channels["quality"], channels["sigma"]):
            expected = 1.0 / math.sqrt(max(0.05, quality))
            require(abs(sigma - expected) <= 2e-5, "KLT_SIGMA_CONTRACT")
    return channels


def csv_header_sha(path: Path) -> str:
    first = path.read_bytes().splitlines()[0]
    return hashlib.sha256(first).hexdigest()


def audit_klt(raw: dict[str, Any]) -> dict[str, Any]:
    rosbag = rosbag_module()
    bag_path = KLT_DIR / "features.bag"
    csv_path = KLT_DIR / "frontend_metrics.csv"
    camera_path = KLT_DIR / "aqualoc_archaeo09_pinhole.yaml"
    require(bag_path.is_file() and csv_path.is_file() and camera_path.is_file(), "KLT_OUTPUT_MISSING")
    require(camera_path.stat().st_size == 357 and sha256(camera_path) == CAMERA_YAML_SHA256, "KLT_CAMERA_YAML_DRIFT")
    counts = {FEATURE_TOPIC: 0, IMU_TOPIC: 0, GT_TOPIC: 0}
    streams = {IMU_TOPIC: hashlib.sha256(), GT_TOPIC: hashlib.sha256()}
    feature_stamps: list[int] = []
    total_points = 0
    with rosbag.Bag(str(bag_path), "r") as bag:
        topics = bag.get_type_and_topic_info().topics
        require(set(topics) == {FEATURE_TOPIC, IMU_TOPIC, GT_TOPIC}, "KLT_TOPIC_SET")
        require(topics[FEATURE_TOPIC].msg_type == "sensor_msgs/PointCloud", "KLT_FEATURE_TYPE")
        for topic, message, record_stamp in bag.read_messages():
            stamp = exact_ns(message.header.stamp)
            require(stamp == exact_ns(record_stamp), f"KLT_HEADER_RECORD:{topic}")
            counts[topic] += 1
            if topic == FEATURE_TOPIC:
                audit_pointcloud_common(message, FEATURE_TOPIC, base=True)
                feature_stamps.append(stamp)
                total_points += len(message.points)
            else:
                add_serialized(streams[topic], message, record_stamp)
    require(counts == {FEATURE_TOPIC: FEATURE_COUNT, IMU_TOPIC: IMU_COUNT, GT_TOPIC: GT_COUNT}, "KLT_COUNTS")
    require(feature_stamps == raw["feature_stamps"], "KLT_RAW_ODD_FRAME_BINDING")
    require(total_points == 770_000, "KLT_TOTAL_POINTS")
    for topic in (IMU_TOPIC, GT_TOPIC):
        require(streams[topic].hexdigest() == raw["stream_sha256"][topic], f"KLT_COPIED_STREAM_DRIFT:{topic}")

    require(csv_header_sha(csv_path) == KLT_HEADER_SHA256, "KLT_CSV_HEADER_SHA")
    with csv_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames is not None and len(reader.fieldnames) == 141, "KLT_CSV_COLUMNS")
        rows = list(reader)
    require(len(rows) == FEATURE_COUNT, "KLT_CSV_ROWS")
    zero_columns = (
        "learned_candidate_count", "learned_confirmed_count", "learned_confirmed_xfeat_count",
        "exported_learned_features", "exported_xfeat_features", "exported_loftr_features",
        "exported_sp_lg_features", "source_provenance_learned_count", "source_provenance_xfeat_count",
    )
    for index, (row, stamp) in enumerate(zip(rows, feature_stamps)):
        stamp_secs, stamp_nsecs = divmod(stamp, 1_000_000_000)
        expected_timestamp = f"{stamp_secs + stamp_nsecs / 1_000_000_000.0:.9f}"
        require(int(row["frame_index"]) == 1 + 2 * index, f"KLT_CSV_FRAME:{index}")
        require(int(row["selected_feature_index"]) == index, f"KLT_CSV_SELECTED:{index}")
        require(row["timestamp"] == expected_timestamp, f"KLT_CSV_STAMP:{index}")
        require(row["num_features"] == "350" and row["exported_features"] == "350", f"KLT_CSV_COUNT:{index}")
        require(row["classical_track_count"] == "350", f"KLT_CSV_CLASSICAL:{index}")
        require(all(float(row[name]) == 0.0 for name in zero_columns), f"KLT_CSV_LEARNED_NONZERO:{index}")
    score_stamps = feature_stamps[PREFIX_FEATURE_COUNT:]
    require(len(score_stamps) == SCORE_FEATURE_COUNT, "KLT_SCORE_COUNT")
    require(score_stamps[0] == SCORE_FEATURE_FIRST_NS and score_stamps[-1] == SCORE_FEATURE_LAST_NS, "KLT_SCORE_ENDPOINT")
    return {
        "status": "PASS_KLT_FRONTEND_AUDIT",
        "topic_counts": counts,
        "feature_first_ns": feature_stamps[0],
        "feature_last_ns": feature_stamps[-1],
        "prefix_feature_count": PREFIX_FEATURE_COUNT,
        "score_feature_count": SCORE_FEATURE_COUNT,
        "score_feature_first_ns": score_stamps[0],
        "score_feature_last_ns": score_stamps[-1],
        "total_feature_points": total_points,
        "copied_stream_sha256": {topic: value.hexdigest() for topic, value in streams.items()},
        "csv_rows": len(rows),
        "csv_columns": len(reader.fieldnames or []),
        "csv_header_sha256": csv_header_sha(csv_path),
    }


def compare_base_and_merged(base_path: Path, merged_path: Path) -> tuple[list[tuple[int, int, int]], set[int]]:
    rosbag = rosbag_module()
    binding: list[tuple[int, int, int]] = []
    remapped_ids: set[int] = set()
    sentinel = object()
    with rosbag.Bag(str(base_path), "r") as base_bag, rosbag.Bag(str(merged_path), "r") as merged_bag:
        base_iter = base_bag.read_messages(topics=[FEATURE_TOPIC])
        merged_iter = merged_bag.read_messages(topics=[FEATURE_TOPIC])
        for index, pair in enumerate(itertools.zip_longest(base_iter, merged_iter, fillvalue=sentinel)):
            base_item, merged_item = pair
            require(base_item is not sentinel and merged_item is not sentinel, "AQUA_FEATURE_LENGTH_MISMATCH")
            _, base, base_record = base_item
            _, merged, merged_record = merged_item
            stamp = exact_ns(base.header.stamp)
            require(stamp == exact_ns(merged.header.stamp) == exact_ns(base_record) == exact_ns(merged_record), f"AQUA_FEATURE_STAMP:{index}")
            base_channels = channel_map(base)
            merged_channels = channel_map(merged)
            require(len(base.points) == 350 and len(merged.points) in {350, 351}, f"AQUA_POINT_COUNT:{index}")
            for left, right in zip(base.points, merged.points[:350]):
                require((left.x, left.y, left.z) == (right.x, right.y, right.z), f"AQUA_BASE_POINT_DRIFT:{index}")
            for name in CHANNELS:
                require(base_channels[name] == merged_channels[name][:350], f"AQUA_BASE_CHANNEL_DRIFT:{index}:{name}")
            added = len(merged.points) - 350
            binding.append((index, stamp, added))
            if added:
                require(added == 1, f"AQUA_EXTENSION_GT1:{index}")
                learned_id = integral(merged_channels["id"][-1], "aqua_id")
                require(learned_id >= 10_000_000, f"AQUA_REMAP_ID:{index}")
                require(integral(merged_channels["source_code"][-1], "aqua_source") == 20, f"AQUA_SOURCE:{index}")
                require(integral(merged_channels["is_learned"][-1], "aqua_learned") == 1, f"AQUA_FLAG:{index}")
                remapped_ids.add(learned_id)
    require(len(binding) == FEATURE_COUNT, "AQUA_BINDING_COUNT")
    require(len(remapped_ids) <= 1, "AQUA_MULTIPLE_LINEAGES")
    return binding, remapped_ids


def binding_digest(binding: Iterable[tuple[int, int, int]]) -> str:
    digest = hashlib.sha256()
    for index, stamp, count in binding:
        digest.update(f"{index},{stamp},{count}\n".encode())
    return digest.hexdigest()


def audit_aqua(klt_audit: dict[str, Any]) -> dict[str, Any]:
    del klt_audit
    rosbag = rosbag_module()
    base_path = KLT_DIR / "features.bag"
    merged_path = AQUA_DIR / "full_merged.bag"
    sidecar_path = AQUA_DIR / "sidecar.bag"
    stats_path = AQUA_DIR / "stats.csv"
    require(all(path.is_file() for path in (base_path, merged_path, sidecar_path, stats_path)), "AQUA_OUTPUT_MISSING")

    base_streams = {IMU_TOPIC: hashlib.sha256(), GT_TOPIC: hashlib.sha256()}
    with rosbag.Bag(str(base_path), "r") as bag:
        for topic, message, record_stamp in bag.read_messages(topics=[IMU_TOPIC, GT_TOPIC]):
            add_serialized(base_streams[topic], message, record_stamp)

    merged_counts = {FEATURE_TOPIC: 0, IMU_TOPIC: 0, GT_TOPIC: 0}
    merged_streams = {IMU_TOPIC: hashlib.sha256(), GT_TOPIC: hashlib.sha256()}
    merged_stamps: list[int] = []
    with rosbag.Bag(str(merged_path), "r") as bag:
        topics = bag.get_type_and_topic_info().topics
        require(set(topics) == {FEATURE_TOPIC, IMU_TOPIC, GT_TOPIC}, "AQUA_MERGED_TOPIC_SET")
        for topic, message, record_stamp in bag.read_messages():
            require(exact_ns(message.header.stamp) == exact_ns(record_stamp), f"AQUA_HEADER_RECORD:{topic}")
            merged_counts[topic] += 1
            if topic == FEATURE_TOPIC:
                require(len(message.points) in {350, 351}, "AQUA_MERGED_POINT_COUNT")
                audit_pointcloud_common(message, FEATURE_TOPIC, base=False)
                merged_stamps.append(exact_ns(record_stamp))
            else:
                add_serialized(merged_streams[topic], message, record_stamp)
    require(merged_counts == {FEATURE_TOPIC: FEATURE_COUNT, IMU_TOPIC: IMU_COUNT, GT_TOPIC: GT_COUNT}, "AQUA_MERGED_COUNTS")
    for topic in (IMU_TOPIC, GT_TOPIC):
        require(merged_streams[topic].hexdigest() == base_streams[topic].hexdigest(), f"AQUA_COPIED_STREAM:{topic}")

    binding, remapped_ids = compare_base_and_merged(base_path, merged_path)
    require([stamp for _, stamp, _ in binding] == merged_stamps, "AQUA_MERGED_BINDING_STAMPS")

    sidecar_stamps: list[int] = []
    sidecar_point_count = 0
    with rosbag.Bag(str(sidecar_path), "r") as bag:
        topics = bag.get_type_and_topic_info().topics
        require(set(topics) == {SIDECAR_TOPIC}, "AQUA_SIDECAR_TOPIC_SET")
        require(topics[SIDECAR_TOPIC].msg_type == "sensor_msgs/PointCloud", "AQUA_SIDECAR_TYPE")
        for topic, message, record_stamp in bag.read_messages():
            del topic
            require(exact_ns(message.header.stamp) == exact_ns(record_stamp), "AQUA_SIDECAR_HEADER_RECORD")
            require(0 <= len(message.points) <= 72, "AQUA_SIDECAR_POINT_COUNT")
            channels = audit_pointcloud_common(message, SIDECAR_TOPIC, base=False)
            ids = [integral(value, "sidecar_id") for value in channels["id"]]
            require(all(1_000_000 <= value < 10_000_000 for value in ids), "AQUA_SIDECAR_ID_RANGE")
            require(all(integral(value, "sidecar_source") == 20 for value in channels["source_code"]), "AQUA_SIDECAR_SOURCE")
            require(all(integral(value, "sidecar_learned") == 1 for value in channels["is_learned"]), "AQUA_SIDECAR_FLAG")
            sidecar_stamps.append(exact_ns(record_stamp))
            sidecar_point_count += len(message.points)
    require(sidecar_stamps == merged_stamps and len(sidecar_stamps) == FEATURE_COUNT, "AQUA_SIDECAR_TIMELINE")

    require(csv_header_sha(stats_path) == AQUA_HEADER_SHA256, "AQUA_STATS_HEADER_SHA")
    with stats_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames is not None and len(reader.fieldnames) == 31, "AQUA_STATS_COLUMNS")
        rows = list(reader)
    require(len(rows) == FEATURE_COUNT, "AQUA_STATS_ROWS")
    stats_binding: list[tuple[int, int, int]] = []
    trigger_frames = 0
    added_seeds = 0
    for index, (row, stamp) in enumerate(zip(rows, merged_stamps)):
        require(int(row["frame_index"]) == index == int(row["selector_frame_index"]), f"AQUA_STATS_INDEX:{index}")
        require(row["stamp"] == row["selector_stamp"], f"AQUA_STATS_STAMP_SPELLING:{index}")
        require(abs(float(row["stamp"]) - stamp / 1_000_000_000.0) <= 5e-7, f"AQUA_STATS_STAMP:{index}")
        injected = int(row["selector_injected_observations"])
        require(injected in {0, 1}, f"AQUA_STATS_INJECTED:{index}")
        stats_binding.append((index, stamp, injected))
        trigger_frames += int(row["triggered"])
        added_seeds += int(row["added_seeds"])
    require(stats_binding == binding, "AQUA_THREE_WAY_ACTION_BINDING")
    digest = binding_digest(binding)
    full_observations = sum(count for _, _, count in binding)
    prefix_observations = sum(count for index, _, count in binding if index < PREFIX_FEATURE_COUNT)
    score_observations = full_observations - prefix_observations
    prefix_frames = sum(count > 0 for index, _, count in binding if index < PREFIX_FEATURE_COUNT)
    score_frames = sum(count > 0 for index, _, count in binding if index >= PREFIX_FEATURE_COUNT)
    return {
        "status": "PASS_AQUAFE_FRONTEND_AUDIT",
        "merged_topic_counts": merged_counts,
        "sidecar_messages": len(sidecar_stamps),
        "sidecar_total_points": sidecar_point_count,
        "stats_rows": len(rows),
        "stats_columns": len(reader.fieldnames or []),
        "stats_header_sha256": csv_header_sha(stats_path),
        "action_binding_sha256": digest,
        "learned_action": {
            "full_observations": full_observations,
            "full_affected_frames": prefix_frames + score_frames,
            "prefix_observations": prefix_observations,
            "prefix_affected_frames": prefix_frames,
            "score_observations": score_observations,
            "score_affected_frames": score_frames,
            "remapped_lineage_ids": sorted(remapped_ids),
            "triggered_frames": trigger_frames,
            "added_seeds": added_seeds,
        },
        "copied_stream_sha256": {topic: value.hexdigest() for topic, value in merged_streams.items()},
    }


def frozen_inputs(stage: str) -> dict[str, Any]:
    paths = [RAW_BAG, RAW_RECEIPT, RAW_ADDENDUM, RAW_FREEZE, SOURCE_ARCHIVE, GT]
    paths += [KLT_PROFILE, AQUALOC_RUNNER, EXPORTER, MIRROR_CONFIG]
    if stage == "aquafe":
        paths += [XFEAT_NODE, LINEAGE_NODE, XFEAT_CONFIG, XFEAT_WEIGHTS]
    values = {str(path): require_identity(path, IDENTITIES[path]) for path in paths}
    require(PROTOCOL.is_file() and not PROTOCOL.is_symlink(), "PROTOCOL_NOT_REGULAR")
    values[str(PROTOCOL)] = identity(PROTOCOL)
    values[str(Path(__file__))] = identity(Path(__file__))
    return values


def output_identities(directory: Path, names: Iterable[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in names:
        path = directory / name
        require(path.is_file() and not path.is_symlink(), f"OUTPUT_NOT_REGULAR:{path}")
        result[name] = identity(path)
    return result


def klt_command() -> tuple[list[str], dict[str, str]]:
    command = [
        "/usr/bin/bash", str(KLT_PROFILE),
        "aqualoc_archaeo_loftr_mirror_klt", "9", "0", "4400",
    ]
    env = {
        "ROOT": str(ROOT),
        "VINS_WS": "/home/ma/SLAM/VINS-Fusion-origin",
        "AQUALOC_ROOT": str(SOURCE_ARCHIVE.parent),
        "RAW_TAR": str(SOURCE_ARCHIVE),
        "GT_TXT": str(GT),
        "RAW_BAG": str(RAW_BAG),
        "TAG": KLT_TAG,
        "RUN_VINS": "0",
        "FORCE_RAW": "0",
        "FORCE_EXPORT": "1",
        "LOFTR_MIRROR_CONFIG": str(MIRROR_CONFIG),
        "MEASUREMENT_SELECTION": "0",
        "EXPORT_MAX_FEATURES": "350",
        "FRAME_OFFSET": "1",
        "PROCESS_SKIPPED_FRAMES": "1",
        "INIT_PARALLAX_ADAPTIVE_SKIP": "0",
        "BACKEND_QUALITY_MODE": "source_aware",
        "BACKEND_QUALITY_ALPHA": "0.85",
        "BACKEND_QUALITY_FLOOR": "0.80",
        "OMP_NUM_THREADS": "2",
        "MKL_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "TMPDIR": str(KLT_STAGE),
    }
    return command, env


def aqua_command() -> tuple[list[str], dict[str, str]]:
    command = [
        "/usr/bin/python3.8", "-m", "uw_frontend.ros.xfeat_seed_sidecar_node", "bag",
        "--config", str(XFEAT_CONFIG),
        "--camera-config", str(KLT_DIR / "aqualoc_archaeo09_pinhole.yaml"),
        "--image-bag", str(RAW_BAG),
        "--base-bag", str(KLT_DIR / "features.bag"),
        "--output-bag", str(AQUA_DIR / "full_merged.bag"),
        "--sidecar-bag", str(AQUA_DIR / "sidecar.bag"),
        "--stats-csv", str(AQUA_DIR / "stats.csv"),
        "--image-topic", CAMERA_TOPIC,
        "--base-topic", FEATURE_TOPIC,
        "--sidecar-topic", SIDECAR_TOPIC,
        "--image-scale", "0.5", "--preprocess", "adaptive_clahe",
        "--trigger-warmup-frames", "0", "--trigger-cooldown-frames", "0",
        "--max-triggers", "3", "--trigger-degradation-min", "0.18",
        "--trigger-flat-region-min", "0.10", "--trigger-grid-texture-max", "0.90",
        "--trigger-base-tracks-max", "300", "--trigger-base-grid-max", "0.80",
        "--trigger-dropout-min", "0.18", "--trigger-long-track-ratio-max", "0.45",
        "--seed-max-per-trigger", "50", "--max-active-seeds", "72",
        "--seed-min-base-distance-px", "8", "--seed-min-active-distance-px", "10",
        "--seed-max-per-cell", "2", "--lk-fb-threshold", "1.20",
        "--lk-min-ncc", "0.42", "--min-observations", "10",
        "--rank-observations", "5", "--min-distance-px", "40",
        "--min-motion-ratio", "0.6", "--max-motion-ratio", "1.5",
        "--max-homography-residual-px", "0.75", "--max-lineages", "1",
        "--remap-id-base", "10000000", "--match-tolerance", "0.02",
    ]
    env = {
        "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0", "TMPDIR": str(AQUA_STAGE),
    }
    return command, env


def terminate_group(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    for sig, wait_seconds in ((signal.SIGINT, 10), (signal.SIGTERM, 10), (signal.SIGKILL, 2)):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=wait_seconds)
            return
        except subprocess.TimeoutExpired:
            continue


def run_child(command: list[str], env_updates: dict[str, str], log_path: Path, timeout: int) -> tuple[int, float]:
    started = time.monotonic()
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            command, cwd=str(ROOT), env={**os.environ, **env_updates},
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )
        try:
            return_code = process.wait(timeout=timeout)
        except BaseException:
            terminate_group(process)
            raise
    return return_code, time.monotonic() - started


def safe_unlink(path: Path) -> None:
    if path.is_symlink():
        path.unlink()


def stage_failure(stage: Path, canonical: Path, workspace: Path | None, failure: Path, error: BaseException) -> None:
    if workspace is not None:
        safe_unlink(workspace)
    safe_unlink(canonical)
    if stage.is_dir() and not stage.is_symlink():
        try:
            write_json(stage / "failure_receipt_v1.json", {
                "schema_version": "aqua-fe-a09-frontend-stage-failure-v1",
                "status": "FAILED_NO_AUTOMATIC_RETRY",
                "error_type": type(error).__name__,
                "error": str(error),
                "recorded_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            if not failure.exists() and not failure.is_symlink():
                stage.rename(failure)
        except OSError:
            pass


def preflight(stage_name: str) -> dict[str, Any]:
    require(shutil.disk_usage(EXP_ROOT).free >= 8_000_000_000, "INSUFFICIENT_MNT_DATA_SPACE")
    inputs = frozen_inputs(stage_name)
    raw = raw_contract()
    if stage_name == "klt":
        require(not KLT_DIR.exists() and not KLT_DIR.is_symlink(), "KLT_CANONICAL_ALREADY_EXISTS")
        require(not KLT_STAGE.exists() and not KLT_STAGE.is_symlink(), "KLT_STAGE_ALREADY_EXISTS")
        require(not KLT_FAILURE.exists() and not KLT_FAILURE.is_symlink(), "KLT_FAILURE_ALREADY_EXISTS")
        require(not KLT_WORKSPACE.exists() and not KLT_WORKSPACE.is_symlink(), "KLT_WORKSPACE_ALREADY_EXISTS")
        command, env = klt_command()
    else:
        require(KLT_DIR.is_dir() and not KLT_DIR.is_symlink(), "KLT_ACCEPTED_INPUT_MISSING")
        klt_audit = audit_klt(raw)
        inputs.update({str(KLT_DIR / name): identity(KLT_DIR / name) for name in (
            "features.bag", "frontend_metrics.csv", "aqualoc_archaeo09_pinhole.yaml",
            "formal_run_receipt_v1.json",
        )})
        require(not AQUA_DIR.exists() and not AQUA_DIR.is_symlink(), "AQUA_CANONICAL_ALREADY_EXISTS")
        require(not AQUA_STAGE.exists() and not AQUA_STAGE.is_symlink(), "AQUA_STAGE_ALREADY_EXISTS")
        require(not AQUA_FAILURE.exists() and not AQUA_FAILURE.is_symlink(), "AQUA_FAILURE_ALREADY_EXISTS")
        command, env = aqua_command()
        raw["klt_audit"] = klt_audit
    return {
        "status": f"READY_{stage_name.upper()}", "inputs": inputs,
        "raw_contract": raw, "command": command, "environment": env,
        "free_bytes": shutil.disk_usage(EXP_ROOT).free,
    }


def execute(stage_name: str) -> dict[str, Any]:
    FRONTENDS.mkdir(parents=True, exist_ok=True)
    GLOBAL_FLOCK.touch(exist_ok=True)
    with GLOBAL_FLOCK.open("r+") as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        ready = preflight(stage_name)
        if stage_name == "klt":
            stage, canonical, failure, workspace = KLT_STAGE, KLT_DIR, KLT_FAILURE, KLT_WORKSPACE
            output_names = ("features.bag", "frontend_metrics.csv", "aqualoc_archaeo09_pinhole.yaml", "supervisor_process.log")
            timeout = 9000
        else:
            stage, canonical, failure, workspace = AQUA_STAGE, AQUA_DIR, AQUA_FAILURE, None
            output_names = ("full_merged.bag", "sidecar.bag", "stats.csv", "supervisor_process.log")
            timeout = 3600
        stage.mkdir(mode=0o755)
        canonical.symlink_to(stage, target_is_directory=True)
        if workspace is not None:
            workspace.parent.mkdir(parents=True, exist_ok=True)
            workspace.symlink_to(canonical, target_is_directory=True)
        started = datetime.now(timezone.utc)
        claim = {
            "schema_version": "aqua-fe-a09-frontend-process-start-claim-v1",
            "stage": stage_name, "status": "CLAIMED_BEFORE_SINGLE_POPEN",
            "created_at_utc": started.isoformat(timespec="seconds"),
            "command": ready["command"], "environment": ready["environment"],
            "inputs": ready["inputs"], "no_automatic_retry": True,
        }
        write_json(stage / "process_start_claim_v1.json", claim)
        try:
            return_code, wall_time = run_child(
                ready["command"], ready["environment"], canonical / "supervisor_process.log", timeout,
            )
            require(return_code == 0, f"CHILD_RETURN_CODE:{return_code}")
            if stage_name == "klt":
                audit = audit_klt(ready["raw_contract"])
            else:
                audit = audit_aqua(ready["raw_contract"]["klt_audit"])
            outputs = output_identities(canonical, output_names)
            post_inputs = frozen_inputs(stage_name)
            if stage_name == "aquafe":
                post_inputs.update({str(KLT_DIR / name): identity(KLT_DIR / name) for name in (
                    "features.bag", "frontend_metrics.csv", "aqualoc_archaeo09_pinhole.yaml",
                    "formal_run_receipt_v1.json",
                )})
            require(set(ready["inputs"]) == set(post_inputs), "INPUT_SET_CHANGED_DURING_STAGE")
            require(
                {key: (value["size_bytes"], value["sha256"]) for key, value in ready["inputs"].items()}
                == {key: (value["size_bytes"], value["sha256"]) for key, value in post_inputs.items()},
                "INPUT_IDENTITY_CHANGED_DURING_STAGE",
            )
            ended = datetime.now(timezone.utc)
            receipt = {
                "schema_version": "aqua-fe-a09-samehistory-warmstart-frontend-receipt-v1",
                "status": "PASS_FRONTEND_STAGE_ACCEPTED",
                "stage": stage_name,
                "started_at_utc": started.isoformat(timespec="seconds"),
                "ended_at_utc": ended.isoformat(timespec="seconds"),
                "wall_time_seconds": wall_time,
                "terminal_process": {"return_code": return_code, "single_popen": True},
                "execution_integrity": {
                    "process_group_waited_to_terminal": True,
                    "ambient_desktop_allowed_by_user_development_waiver": True,
                    "no_runtime_benchmark_claim": True,
                    "no_automatic_retry": True,
                },
                "command": ready["command"], "environment": ready["environment"],
                "inputs_before": ready["inputs"], "inputs_after": post_inputs,
                "outputs": outputs, "artifact_audit": audit,
                "claim_boundary": {
                    "frontend_artifact_only": True,
                    "vins_or_slam_executed": False,
                    "trajectory_or_accuracy_result_available": False,
                    "formal_paper_accuracy_evidence_permitted": False,
                },
            }
            write_json(stage / "formal_run_receipt_v1.json", receipt)
            if workspace is not None:
                safe_unlink(workspace)
            safe_unlink(canonical)
            stage.rename(canonical)
            if workspace is not None:
                workspace.symlink_to(canonical, target_is_directory=True)
            return {
                "status": receipt["status"], "stage": stage_name,
                "output_dir": str(canonical), "artifact_audit": audit,
                "receipt": identity(canonical / "formal_run_receipt_v1.json"),
            }
        except BaseException as error:
            stage_failure(stage, canonical, workspace, failure, error)
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight-klt", "run-klt", "preflight-aquafe", "run-aquafe", "audit-all"))
    args = parser.parse_args()
    try:
        if args.command == "preflight-klt":
            result = preflight("klt")
        elif args.command == "run-klt":
            result = execute("klt")
        elif args.command == "preflight-aquafe":
            result = preflight("aquafe")
        elif args.command == "run-aquafe":
            result = execute("aquafe")
        else:
            raw = raw_contract()
            result = {"klt": audit_klt(raw), "aquafe": audit_aqua(audit_klt(raw)), "status": "PASS_ALL_FRONTENDS"}
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))
        return 0
    except (FrontendError, OSError, ValueError, csv.Error, subprocess.SubprocessError) as error:
        print(f"FRONTEND_ERROR:{type(error).__name__}:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
