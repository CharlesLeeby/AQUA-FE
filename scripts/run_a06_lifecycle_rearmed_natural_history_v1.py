#!/usr/bin/env python3
"""One-shot A06 natural-history XFeat lifecycle-rearm frontend probe.

This runner deliberately stops at the frontend action gate.  It never starts ROS,
VINS-Fusion, HFNet, an evaluator, or a trajectory-producing process.
"""

from __future__ import annotations

import argparse
import copy
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import io
from itertools import zip_longest
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
PROTOCOL = ROOT / "papers/a06_lifecycle_rearmed_natural_history_v1_protocol.md"
RUNNER = Path(__file__).resolve()
OUTPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/a06_lifecycle_rearmed_natural_history_v1"
)
LOCK_PATH = OUTPUT_ROOT / ".probe_supervisor.flock"

RAW_BAG = Path(
    "/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/raw/"
    "archaeo06_0000_2460.bag"
)
KLT_BAG = Path(
    "/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/"
    "external_klt/features.bag"
)
CAMERA_CONFIG = Path(
    "/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/"
    "external_klt/aqualoc_archaeo06_pinhole.yaml"
)
XFEAT_NODE = ROOT / "uw_frontend/ros/xfeat_seed_sidecar_node.py"
LINEAGE_NODE = ROOT / "uw_frontend/ros/causal_lineage_shadow_node.py"
XFEAT_CONFIG = (
    ROOT
    / "uw_frontend/configs/experiments/low_texture_lineage_safe_dense_start_frontend.yaml"
)
XFEAT_WEIGHTS = ROOT / "external_tools/accelerated_features/weights/xfeat.pt"
PREPARE_SCRIPT = ROOT / "scripts/prepare_causal_multilineage_bag.sh"
HISTORICAL_STATS = Path(
    "/mnt/data/AQUA-FE_WS/online_positive_search_20260721/"
    "a06_2210_2460/stats.csv"
)

CANDIDATE_DIR = OUTPUT_ROOT / "candidate_generator"
CANDIDATE_STAGE = OUTPUT_ROOT / ".candidate_generator.stage_v1"
CANDIDATE_FAILURE = OUTPUT_ROOT / "candidate_generator_failed_v1"
LIFECYCLE_DIR = OUTPUT_ROOT / "lifecycle_rearmed"
LIFECYCLE_STAGE = OUTPUT_ROOT / ".lifecycle_rearmed.stage_v1"
LIFECYCLE_FAILURE = OUTPUT_ROOT / "lifecycle_rearmed_failed_v1"
TERMINAL_RECEIPT = OUTPUT_ROOT / "terminal_probe_receipt_v1.json"

EXPECTED_IDENTITIES = {
    RAW_BAG: (
        573_420_704,
        "22cc3cff28dabc34de04c870eed5180ab76832c1f3c912da62d0268e9acb2e9a",
    ),
    KLT_BAG: (
        37_403_698,
        "0779bb8a71e4d81ddf02ba933b7428e548534ab580fd4483754f08e26e9bbeb6",
    ),
    CAMERA_CONFIG: (
        357,
        "045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5",
    ),
    XFEAT_NODE: (
        41_561,
        "9afc6f7083f76bf1f7c6b7c19f79f02a98160663c945479b51492fa19cb3ace7",
    ),
    LINEAGE_NODE: (
        16_891,
        "8856e0aff281ba30a31b2370ee2c6ff949f830c4230f3a2d358143f80628a727",
    ),
    XFEAT_CONFIG: (
        778,
        "369120917878b55564d6d993670328738e5436beae92bee25e99dd86c3eb66a6",
    ),
    XFEAT_WEIGHTS: (
        6_247_949,
        "0f5187fd7bedd26c7fe6acc9685444493a165a35ecc087b33c2db3627f3ea10b",
    ),
    PREPARE_SCRIPT: (
        2_814,
        "0b6d1d2d049732ce536ca478ae1a146f8ce78169a2a9fb1264307ffb3b0be549",
    ),
    HISTORICAL_STATS: (
        32_118,
        "f6c6041f61092407494434202f07a08d656771d1117109659f37f23dd13b0c5c",
    ),
}

CAMERA_TOPIC = "/camera/image_raw"
FEATURE_TOPIC = "/feature_tracker/feature"
SIDECAR_TOPIC = "/feature_tracker/sidecar"
IMU_TOPIC = "/rtimulib_node/imu"
GT_TOPIC = "/aqualoc/colmap_gt"

CAMERA_COUNT = 2461
FEATURE_COUNT = 1230
NORMAL_FEATURE_POINTS = 350
IMU_COUNT = 24649
GT_COUNT = 120
EVAL_FIRST_FEATURE = 930       # source 1861, evaluation interval 1860..2460
ACTION_FIRST_FEATURE = 1105    # source 2211, exact historical interval 2210..2460
ACTION_FEATURE_COUNT = 125
CHANNELS = (
    "id", "camera_id", "p_u", "p_v", "velocity_x", "velocity_y",
    "gx", "gy", "gz", "quality", "sigma", "source_code", "is_learned",
)
LEARNED_SOURCE_CODES = {10, 20, 30}


class ProbeError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ProbeError(code)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def require_identity(path: Path, expected: tuple[int, str]) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"INPUT_NOT_REGULAR:{path}")
    actual = identity(path)
    require(
        (actual["size_bytes"], actual["sha256"]) == expected,
        f"INPUT_IDENTITY_DRIFT:{path}",
    )
    return actual


def write_json(path: Path, value: Any) -> None:
    require(not path.exists() and not path.is_symlink(), f"REFUSE_OVERWRITE:{path}")
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def rosbag_module() -> Any:
    ros_path = "/opt/ros/noetic/lib/python3/dist-packages"
    if ros_path not in sys.path:
        sys.path.insert(0, ros_path)
    import rosbag  # type: ignore

    return rosbag


def exact_ns(stamp: Any) -> int:
    require(type(stamp.secs) is int and type(stamp.nsecs) is int, "STAMP_NOT_INTEGER")
    require(stamp.secs >= 0 and 0 <= stamp.nsecs < 1_000_000_000, "STAMP_RANGE")
    return stamp.secs * 1_000_000_000 + stamp.nsecs


def serialized(message: Any) -> bytes:
    payload = io.BytesIO()
    message.serialize(payload)
    return payload.getvalue()


def add_serialized(digest: Any, topic: str, message: Any, record_stamp: Any) -> None:
    topic_bytes = topic.encode("utf-8")
    payload = serialized(message)
    digest.update(len(topic_bytes).to_bytes(4, "big"))
    digest.update(topic_bytes)
    digest.update(exact_ns(record_stamp).to_bytes(8, "big"))
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)


def integral(value: float, code: str) -> int:
    require(math.isfinite(value), f"NONFINITE:{code}")
    rounded = round(value)
    require(abs(value - rounded) <= 1e-6, f"NONINTEGRAL:{code}:{value}")
    return int(rounded)


def channel_values(message: Any) -> dict[str, list[float]]:
    names = tuple(channel.name for channel in message.channels)
    require(names == CHANNELS, f"CHANNEL_ORDER:{names}")
    result = {channel.name: list(channel.values) for channel in message.channels}
    require(
        all(len(values) == len(message.points) for values in result.values()),
        "CHANNEL_LENGTH",
    )
    return result


def input_identities() -> dict[str, Any]:
    values = {
        str(path): require_identity(path, expected)
        for path, expected in EXPECTED_IDENTITIES.items()
    }
    for path in (PROTOCOL, RUNNER):
        require(path.is_file() and not path.is_symlink(), f"CONTROL_NOT_REGULAR:{path}")
        values[str(path)] = identity(path)
    return values


def refresh_identities(previous: dict[str, Any]) -> dict[str, Any]:
    """Re-hash exactly the paths claimed before a child was started."""
    result: dict[str, Any] = {}
    for raw_path in previous:
        path = Path(raw_path)
        require(path.is_file() and not path.is_symlink(), f"CLAIMED_INPUT_NOT_REGULAR:{path}")
        result[raw_path] = identity(path)
    return result


def historical_selection_contract() -> dict[str, Any]:
    with HISTORICAL_STATS.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    require(len(rows) == ACTION_FEATURE_COUNT, "HISTORICAL_ROWS")
    trigger_rows = [
        index for index, row in enumerate(rows) if integral(float(row["triggered"]), "hist_trigger")
    ]
    action = [
        integral(float(row["selector_injected_observations"]), "hist_injected")
        for row in rows
    ]
    action_rows = [index for index, count in enumerate(action) if count]
    require(trigger_rows == [1, 2, 3], "HISTORICAL_TRIGGER_PROVENANCE")
    require(sum(action) == 48, "HISTORICAL_ACTION_TOTAL")
    require(action_rows and action_rows[0] == 10 and action_rows[-1] == 57, "HISTORICAL_ACTION_RANGE")
    return {
        "role": "selection_provenance_only_not_runtime_input",
        "rows": len(rows),
        "trigger_rows": trigger_rows,
        "injected_observations": sum(action),
        "first_action_row": action_rows[0],
        "last_action_row": action_rows[-1],
    }


def raw_contract() -> dict[str, Any]:
    rosbag = rosbag_module()
    camera_stamps: list[int] = []
    gt_stamps: list[int] = []
    counts = {CAMERA_TOPIC: 0, IMU_TOPIC: 0, GT_TOPIC: 0}
    with rosbag.Bag(str(RAW_BAG), "r") as bag:
        for topic, message, record_stamp in bag.read_messages(
            topics=[CAMERA_TOPIC, IMU_TOPIC, GT_TOPIC]
        ):
            require(
                exact_ns(message.header.stamp) == exact_ns(record_stamp),
                f"RAW_HEADER_RECORD:{topic}",
            )
            counts[topic] += 1
            if topic == CAMERA_TOPIC:
                camera_stamps.append(exact_ns(message.header.stamp))
            elif topic == GT_TOPIC:
                gt_stamps.append(exact_ns(message.header.stamp))
    require(
        counts == {CAMERA_TOPIC: CAMERA_COUNT, IMU_TOPIC: IMU_COUNT, GT_TOPIC: GT_COUNT},
        f"RAW_COUNTS:{counts}",
    )
    require(all(b > a for a, b in zip(camera_stamps, camera_stamps[1:])), "CAMERA_ORDER")
    feature_stamps = camera_stamps[1:2460:2]
    require(len(feature_stamps) == FEATURE_COUNT, "RAW_FEATURE_BINDING_COUNT")
    action_start_ns = camera_stamps[2210]
    action_end_ns = camera_stamps[2460]
    eval_start_ns = camera_stamps[1860]
    eval_gt = [stamp for stamp in gt_stamps if eval_start_ns <= stamp <= action_end_ns]
    action_gt = [stamp for stamp in gt_stamps if action_start_ns <= stamp <= action_end_ns]
    require(len(eval_gt) == 30, f"EVAL_NATIVE_GT_COUNT:{len(eval_gt)}")
    require(len(action_gt) == 13, f"ACTION_NATIVE_GT_COUNT:{len(action_gt)}")
    require(feature_stamps[EVAL_FIRST_FEATURE] >= eval_start_ns, "EVAL_FEATURE_BOUNDARY")
    require(feature_stamps[ACTION_FIRST_FEATURE] >= action_start_ns, "ACTION_FEATURE_BOUNDARY")
    require(feature_stamps[ACTION_FIRST_FEATURE - 1] < action_start_ns, "ACTION_PRE_BOUNDARY")
    return {
        "counts": counts,
        "camera_first_ns": camera_stamps[0],
        "camera_last_ns": camera_stamps[-1],
        "feature_stamps": feature_stamps,
        "evaluation_window": {
            "source_indices_inclusive": [1860, 2460],
            "timestamp_ns_inclusive": [eval_start_ns, action_end_ns],
            "native_gt_messages": len(eval_gt),
            "feature_indices_inclusive": [EVAL_FIRST_FEATURE, FEATURE_COUNT - 1],
        },
        "historical_action_window": {
            "source_indices_inclusive": [2210, 2460],
            "timestamp_ns_inclusive": [action_start_ns, action_end_ns],
            "native_gt_messages": len(action_gt),
            "feature_indices_inclusive": [ACTION_FIRST_FEATURE, FEATURE_COUNT - 1],
        },
    }


def audit_klt(expected_stamps: list[int]) -> dict[str, Any]:
    rosbag = rosbag_module()
    counts: dict[str, int] = {}
    feature_stamps: list[int] = []
    feature_point_counts: list[int] = []
    stream = hashlib.sha256()
    with rosbag.Bag(str(KLT_BAG), "r") as bag:
        for topic, message, record_stamp in bag.read_messages():
            counts[topic] = counts.get(topic, 0) + 1
            add_serialized(stream, topic, message, record_stamp)
            if topic != FEATURE_TOPIC:
                continue
            require(message._type == "sensor_msgs/PointCloud", "KLT_FEATURE_TYPE")
            require(exact_ns(message.header.stamp) == exact_ns(record_stamp), "KLT_HEADER_RECORD")
            point_count = len(message.points)
            require(
                point_count in {335, NORMAL_FEATURE_POINTS},
                f"KLT_POINT_COUNT:{point_count}",
            )
            channels = channel_values(message)
            ids = [integral(value, "klt_id") for value in channels["id"]]
            require(len(set(ids)) == point_count, "KLT_ID_UNIQUENESS")
            require(max(ids) < 10_000_000 and min(ids) >= 0, "KLT_ID_RANGE")
            require(all(integral(v, "klt_learned") == 0 for v in channels["is_learned"]), "KLT_LEARNED")
            require(
                all(integral(v, "klt_source") not in LEARNED_SOURCE_CODES for v in channels["source_code"]),
                "KLT_SOURCE",
            )
            feature_stamps.append(exact_ns(message.header.stamp))
            feature_point_counts.append(point_count)
    require(
        counts == {GT_TOPIC: GT_COUNT, FEATURE_TOPIC: FEATURE_COUNT, IMU_TOPIC: IMU_COUNT},
        f"KLT_COUNTS:{counts}",
    )
    require(feature_stamps == expected_stamps, "KLT_RAW_FEATURE_STAMP_BINDING")
    short_rows = [
        index
        for index, count in enumerate(feature_point_counts)
        if count != NORMAL_FEATURE_POINTS
    ]
    require(short_rows == [1064], f"KLT_SHORT_ROW_BINDING:{short_rows}")
    require(feature_point_counts[1064] == 335, "KLT_SHORT_ROW_COUNT")
    return {
        "status": "PASS_KLT_INPUT_CONTRACT",
        "topic_counts": counts,
        "feature_point_count_histogram": {"335": 1, "350": 1229},
        "short_feature_message": {
            "feature_index": 1064,
            "points": 335,
            "timestamp_ns": feature_stamps[1064],
        },
        "ordered_stream_sha256": stream.hexdigest(),
        "feature_stamps": feature_stamps,
        "feature_point_counts": feature_point_counts,
    }


def candidate_command(stage: Path) -> list[str]:
    return [
        "/usr/bin/python3.8", "-m", "uw_frontend.ros.xfeat_seed_sidecar_node", "bag",
        "--config", str(XFEAT_CONFIG),
        "--camera-config", str(CAMERA_CONFIG),
        "--image-bag", str(RAW_BAG),
        "--base-bag", str(KLT_BAG),
        "--output-bag", str(stage / "dummy_merged.bag"),
        "--sidecar-bag", str(stage / "candidate_sidecar.bag"),
        "--stats-csv", str(stage / "candidate_stats.csv"),
        "--image-topic", CAMERA_TOPIC,
        "--base-topic", FEATURE_TOPIC,
        "--sidecar-topic", SIDECAR_TOPIC,
        "--image-scale", "0.5", "--preprocess", "adaptive_clahe",
        "--trigger-warmup-frames", "0", "--trigger-cooldown-frames", "12",
        "--max-triggers", "103", "--disable-seed-loss-rearm",
        "--trigger-degradation-min", "0.18",
        "--trigger-flat-region-min", "0.10", "--trigger-grid-texture-max", "0.90",
        "--trigger-base-tracks-max", "300", "--trigger-base-grid-max", "0.80",
        "--trigger-dropout-min", "0.18", "--trigger-long-track-ratio-max", "0.45",
        "--seed-max-per-trigger", "50", "--max-active-seeds", "72",
        "--seed-min-base-distance-px", "8", "--seed-min-active-distance-px", "10",
        "--seed-max-per-cell", "2", "--lk-fb-threshold", "1.20",
        "--lk-min-ncc", "0.42", "--min-observations", "10",
        "--rank-observations", "5", "--min-distance-px", "40",
        "--min-motion-ratio", "0.6", "--max-motion-ratio", "1.5",
        "--max-homography-residual-px", "0.75", "--max-lineages", "0",
        "--remap-id-base", "10000000", "--match-tolerance", "0.02",
    ]


def lifecycle_command(stage: Path) -> list[str]:
    return [
        "/usr/bin/bash", str(PREPARE_SCRIPT),
        str(KLT_BAG), str(CANDIDATE_DIR / "candidate_sidecar.bag"),
        str(stage), "1", "40", "0", "10", "10",
    ]


def child_environment(tmpdir: Path) -> dict[str, str]:
    return {
        "ROOT": str(ROOT),
        "OMP_NUM_THREADS": "2",
        "MKL_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "TMPDIR": str(tmpdir),
    }


def terminate_group(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    for sig, delay in ((signal.SIGINT, 10), (signal.SIGTERM, 10), (signal.SIGKILL, 2)):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=delay)
            return
        except subprocess.TimeoutExpired:
            continue


def run_child(
    command: list[str], environment: dict[str, str], log_path: Path, timeout: int
) -> tuple[int, float]:
    started = time.monotonic()
    with log_path.open("xb") as log:
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            env={**os.environ, **environment},
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            return_code = process.wait(timeout=timeout)
        except BaseException:
            terminate_group(process)
            raise
    return return_code, time.monotonic() - started


def compare_bags_exact(reference: Path, candidate: Path, code: str) -> dict[str, Any]:
    rosbag = rosbag_module()
    count = 0
    digest = hashlib.sha256()
    with rosbag.Bag(str(reference), "r") as left, rosbag.Bag(str(candidate), "r") as right:
        pairs = zip_longest(left.read_messages(), right.read_messages())
        for index, pair in enumerate(pairs):
            left_item, right_item = pair
            require(left_item is not None and right_item is not None, f"{code}_LENGTH:{index}")
            left_topic, left_message, left_stamp = left_item
            right_topic, right_message, right_stamp = right_item
            require(left_topic == right_topic, f"{code}_TOPIC:{index}")
            require(exact_ns(left_stamp) == exact_ns(right_stamp), f"{code}_STAMP:{index}")
            left_payload = serialized(left_message)
            right_payload = serialized(right_message)
            require(left_payload == right_payload, f"{code}_PAYLOAD:{index}")
            add_serialized(digest, left_topic, left_message, left_stamp)
            count += 1
    return {"messages": count, "ordered_stream_sha256": digest.hexdigest()}


def section_sums(values: list[int]) -> dict[str, int]:
    require(len(values) == FEATURE_COUNT, "SECTION_VALUE_COUNT")
    return {
        "full_history_0_2460": sum(values),
        "before_historical_window": sum(values[:ACTION_FIRST_FEATURE]),
        "evaluation_window_1860_2460": sum(values[EVAL_FIRST_FEATURE:]),
        "historical_window_2210_2460": sum(values[ACTION_FIRST_FEATURE:]),
    }


def read_csv(path: Path, expected_rows: int) -> tuple[list[dict[str, str]], list[str]]:
    require(path.is_file() and not path.is_symlink(), f"CSV_MISSING:{path}")
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    require(len(rows) == expected_rows, f"CSV_ROW_COUNT:{path}:{len(rows)}")
    return rows, fields


def audit_candidate(klt: dict[str, Any], directory: Path) -> dict[str, Any]:
    rosbag = rosbag_module()
    dummy = directory / "dummy_merged.bag"
    sidecar = directory / "candidate_sidecar.bag"
    stats = directory / "candidate_stats.csv"
    for path in (dummy, sidecar, stats, directory / "supervisor_process.log"):
        require(path.is_file() and not path.is_symlink(), f"CANDIDATE_OUTPUT_MISSING:{path}")
    parity = compare_bags_exact(KLT_BAG, dummy, "CANDIDATE_DUMMY_PARITY")
    require(
        parity["ordered_stream_sha256"] == klt["ordered_stream_sha256"],
        "CANDIDATE_DUMMY_DIGEST",
    )

    sidecar_stamps: list[int] = []
    candidate_counts: list[int] = []
    with rosbag.Bag(str(sidecar), "r") as bag:
        for topic, message, record_stamp in bag.read_messages():
            require(topic == SIDECAR_TOPIC, f"SIDECAR_TOPIC:{topic}")
            require(exact_ns(message.header.stamp) == exact_ns(record_stamp), "SIDECAR_HEADER_RECORD")
            channels = channel_values(message)
            count = len(message.points)
            for source, learned, raw_id in zip(
                channels["source_code"], channels["is_learned"], channels["id"]
            ):
                require(integral(source, "sidecar_source") == 20, "SIDECAR_SOURCE")
                require(integral(learned, "sidecar_learned") == 1, "SIDECAR_LEARNED")
                require(0 <= integral(raw_id, "sidecar_id") < 10_000_000, "SIDECAR_RAW_ID")
            sidecar_stamps.append(exact_ns(message.header.stamp))
            candidate_counts.append(count)
    require(sidecar_stamps == klt["feature_stamps"], "SIDECAR_STAMP_BINDING")

    rows, fields = read_csv(stats, FEATURE_COUNT)
    require("selector_injected_observations" in fields, "CANDIDATE_STATS_SCHEMA")
    trigger: list[int] = []
    added: list[int] = []
    injected: list[int] = []
    for index, row in enumerate(rows):
        require(integral(float(row["frame_index"]), "candidate_frame") == index, "CANDIDATE_FRAME_INDEX")
        require(
            abs(float(row["stamp"]) - klt["feature_stamps"][index] / 1e9) <= 2e-6,
            "CANDIDATE_STATS_STAMP",
        )
        trigger.append(integral(float(row["triggered"]), "candidate_trigger"))
        added.append(integral(float(row["added_seeds"]), "candidate_added"))
        injected.append(integral(float(row["selector_injected_observations"]), "candidate_injected"))
        for key in (
            "selector_selected_ids", "selector_active_ids", "selector_activated_ids"
        ):
            require(not row[key], f"CANDIDATE_SELECTOR_NONEMPTY:{key}:{index}")
    require(sum(injected) == 0, "CANDIDATE_STAGE_INJECTED_NONZERO")
    successful_trigger_rows = [index for index, value in enumerate(added) if value > 0]
    require(len(successful_trigger_rows) <= 103, "CANDIDATE_TRIGGER_BUDGET")
    require(
        all(
            b - a >= 12
            for a, b in zip(successful_trigger_rows, successful_trigger_rows[1:])
        ),
        "CANDIDATE_SUCCESS_COOLDOWN",
    )
    return {
        "status": "PASS_CANDIDATE_GENERATOR_AUDIT",
        "dummy_merged_exact_klt_parity": parity,
        "sidecar_messages": len(sidecar_stamps),
        "candidate_observations": section_sums(candidate_counts),
        "affected_candidate_frames": section_sums([int(value > 0) for value in candidate_counts]),
        "triggered_frames": section_sums(trigger),
        "added_seeds": section_sums(added),
        "successful_trigger_rows": successful_trigger_rows,
        "dummy_selector_injected_observations": section_sums(injected),
        "stats_columns": fields,
    }


def strip_learned(message: Any) -> tuple[Any, list[int]]:
    channels = channel_values(message)
    learned_indices: list[int] = []
    keep_indices: list[int] = []
    for index, (raw_id, source, learned) in enumerate(
        zip(channels["id"], channels["source_code"], channels["is_learned"])
    ):
        feature_id = integral(raw_id, "merged_id")
        source_code = integral(source, "merged_source")
        is_learned = integral(learned, "merged_learned")
        classified = is_learned == 1 or source_code in LEARNED_SOURCE_CODES or feature_id >= 10_000_000
        if classified:
            require(is_learned == 1, "MERGED_LEARNED_FLAG")
            require(source_code == 20, "MERGED_LEARNED_SOURCE")
            require(feature_id >= 10_000_000, "MERGED_LEARNED_REMAP")
            learned_indices.append(index)
        else:
            require(is_learned == 0, "MERGED_BASE_FLAG")
            require(source_code not in LEARNED_SOURCE_CODES, "MERGED_BASE_SOURCE")
            require(feature_id < 10_000_000, "MERGED_BASE_ID")
            keep_indices.append(index)
    recovered = copy.deepcopy(message)
    recovered.points = [recovered.points[index] for index in keep_indices]
    for channel in recovered.channels:
        channel.values = [channel.values[index] for index in keep_indices]
    return recovered, learned_indices


def audit_lifecycle(klt: dict[str, Any], candidate: dict[str, Any], directory: Path) -> dict[str, Any]:
    rosbag = rosbag_module()
    full = directory / "full_merged.bag"
    drop = directory / "drop_whole_lineage.bag"
    stats = directory / "lineage_selection.csv"
    for path in (
        full, drop, stats, directory / "drop_whole_lineage_stats.csv",
        directory / "manifest.txt", directory / "supervisor_process.log",
    ):
        require(path.is_file() and not path.is_symlink(), f"LIFECYCLE_OUTPUT_MISSING:{path}")
    drop_parity = compare_bags_exact(KLT_BAG, drop, "LIFECYCLE_DROP_PARITY")
    require(drop_parity["ordered_stream_sha256"] == klt["ordered_stream_sha256"], "DROP_DIGEST")

    injected_counts: list[int] = []
    affected_ids: set[int] = set()
    recovered_digest = hashlib.sha256()
    record_count = 0
    with rosbag.Bag(str(KLT_BAG), "r") as base, rosbag.Bag(str(full), "r") as merged:
        for index, pair in enumerate(zip_longest(base.read_messages(), merged.read_messages())):
            base_item, merged_item = pair
            require(base_item is not None and merged_item is not None, f"FULL_LENGTH:{index}")
            base_topic, base_message, base_stamp = base_item
            merged_topic, merged_message, merged_stamp = merged_item
            require(base_topic == merged_topic, f"FULL_TOPIC:{index}")
            require(exact_ns(base_stamp) == exact_ns(merged_stamp), f"FULL_STAMP:{index}")
            if base_topic != FEATURE_TOPIC:
                require(serialized(base_message) == serialized(merged_message), f"FULL_NONFEATURE:{index}")
                add_serialized(recovered_digest, base_topic, merged_message, merged_stamp)
            else:
                recovered, learned_indices = strip_learned(merged_message)
                require(len(learned_indices) <= 1, f"CONCURRENT_LINEAGE_CAP:{len(injected_counts)}")
                expected_base_count = klt["feature_point_counts"][len(injected_counts)]
                require(
                    len(recovered.points) == expected_base_count,
                    f"RECOVERED_FEATURE_COUNT:{len(injected_counts)}",
                )
                require(serialized(recovered) == serialized(base_message), f"FULL_RECOVERY:{len(injected_counts)}")
                merged_channels = channel_values(merged_message)
                for learned_index in learned_indices:
                    affected_ids.add(integral(merged_channels["id"][learned_index], "affected_id"))
                injected_counts.append(len(learned_indices))
                add_serialized(recovered_digest, base_topic, recovered, merged_stamp)
            record_count += 1
    require(len(injected_counts) == FEATURE_COUNT, "FULL_FEATURE_COUNT")
    require(recovered_digest.hexdigest() == klt["ordered_stream_sha256"], "FULL_RECOVERED_DIGEST")

    rows, fields = read_csv(stats, FEATURE_COUNT)
    csv_injected: list[int] = []
    activated_ids: set[int] = set()
    retired_ids: set[int] = set()
    selected_ids: set[int] = set()
    for index, row in enumerate(rows):
        require(integral(float(row["frame_index"]), "lifecycle_frame") == index, "LIFECYCLE_FRAME_INDEX")
        require(
            abs(float(row["stamp"]) - klt["feature_stamps"][index] / 1e9) <= 2e-6,
            "LIFECYCLE_STATS_STAMP",
        )
        csv_injected.append(integral(float(row["injected_observations"]), "lifecycle_injected"))
        for key, target in (
            ("activated_ids", activated_ids),
            ("retired_ids", retired_ids),
            ("selected_ids", selected_ids),
        ):
            for value in row[key].split(";") if row[key] else []:
                target.add(int(value))
    require(csv_injected == injected_counts, "CSV_BAG_INJECTION_BINDING")

    observation_sections = section_sums(injected_counts)
    affected_sections = section_sums([int(value > 0) for value in injected_counts])
    status = (
        "PASS_SCORE_ACTION_GATE_FRONTEND_ONLY"
        if observation_sections["historical_window_2210_2460"] > 0
        else "STOPPED_SCORE_ACTION_ZERO"
    )
    return {
        "status": status,
        "drop_bag_exact_klt_parity": drop_parity,
        "full_merged_records": record_count,
        "remove_learned_recovers_klt_exactly": True,
        "recovered_ordered_stream_sha256": recovered_digest.hexdigest(),
        "injected_observations": observation_sections,
        "affected_frames": affected_sections,
        "unique_raw_selected_lineages": sorted(selected_ids),
        "unique_raw_activated_lineages": sorted(activated_ids),
        "unique_raw_retired_lineages": sorted(retired_ids),
        "unique_remapped_affected_ids": sorted(affected_ids),
        "max_injected_observations_per_message": max(injected_counts, default=0),
        "csv_bag_injection_binding": True,
        "candidate_audit_status": candidate["status"],
        "stats_columns": fields,
        "gate": {
            "expression": "historical_window_2210_2460_injected_observations > 0",
            "value": observation_sections["historical_window_2210_2460"],
            "passed": observation_sections["historical_window_2210_2460"] > 0,
        },
    }


def output_identities(directory: Path, names: Iterable[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in names:
        path = directory / name
        require(path.is_file() and not path.is_symlink(), f"OUTPUT_NOT_REGULAR:{path}")
        result[name] = identity(path)
    return result


def preflight() -> dict[str, Any]:
    require(not OUTPUT_ROOT.exists() and not OUTPUT_ROOT.is_symlink(), "OUTPUT_ROOT_ALREADY_EXISTS")
    require(shutil.disk_usage(OUTPUT_ROOT.parent).free >= 8_000_000_000, "INSUFFICIENT_SPACE")
    require(Path("/usr/bin/python3.8").is_file(), "PYTHON38_MISSING")
    inputs = input_identities()
    selection = historical_selection_contract()
    raw = raw_contract()
    klt = audit_klt(raw["feature_stamps"])
    return {
        "status": "READY_ONE_SHOT_FRONTEND_PROBE",
        "inputs": inputs,
        "historical_selection": selection,
        "raw_contract": {key: value for key, value in raw.items() if key != "feature_stamps"},
        "klt_contract": {
            key: value
            for key, value in klt.items()
            if key not in {"feature_stamps", "feature_point_counts"}
        },
        "commands": {
            "candidate_generator": candidate_command(CANDIDATE_STAGE),
            "lifecycle_selector": lifecycle_command(LIFECYCLE_STAGE),
        },
        "no_automatic_retry": True,
        "backend_authorized_before_gate": False,
        "free_bytes": shutil.disk_usage(OUTPUT_ROOT.parent).free,
    }


def failure_stage(stage: Path, failure: Path, error: BaseException) -> None:
    if not stage.is_dir() or stage.is_symlink() or failure.exists() or failure.is_symlink():
        return
    try:
        write_json(stage / "failure_receipt_v1.json", {
            "status": "FAILED_NO_AUTOMATIC_RETRY",
            "error_type": type(error).__name__,
            "error": str(error),
            "recorded_at_utc": now(),
        })
        stage.rename(failure)
    except OSError:
        pass


def execute_stage(
    name: str,
    stage: Path,
    accepted: Path,
    failure: Path,
    command: list[str],
    timeout: int,
    inputs_before: dict[str, Any],
    audit_function: Any,
    audit_args: tuple[Any, ...],
    output_names: tuple[str, ...],
) -> dict[str, Any]:
    require(not stage.exists() and not stage.is_symlink(), f"STAGE_EXISTS:{stage}")
    require(not accepted.exists() and not accepted.is_symlink(), f"ACCEPTED_EXISTS:{accepted}")
    require(not failure.exists() and not failure.is_symlink(), f"FAILURE_EXISTS:{failure}")
    stage.mkdir(mode=0o755)
    environment = child_environment(stage)
    claim = {
        "schema_version": "a06-lifecycle-rearmed-process-start-claim-v1",
        "status": "CLAIMED_BEFORE_SINGLE_POPEN",
        "stage": name,
        "created_at_utc": now(),
        "command": command,
        "environment_updates": environment,
        "inputs": inputs_before,
        "no_automatic_retry": True,
    }
    write_json(stage / "process_start_claim_v1.json", claim)
    started = now()
    try:
        return_code, wall_time = run_child(
            command, environment, stage / "supervisor_process.log", timeout
        )
        require(return_code == 0, f"{name.upper()}_RETURN_CODE:{return_code}")
        audit = audit_function(*audit_args, stage)
        inputs_after = refresh_identities(inputs_before)
        require(
            {
                key: (value["size_bytes"], value["sha256"])
                for key, value in inputs_before.items()
            }
            == {
                key: (value["size_bytes"], value["sha256"])
                for key, value in inputs_after.items()
            },
            f"{name.upper()}_INPUT_IDENTITY_CHANGED",
        )
        outputs = output_identities(stage, output_names)
        receipt = {
            "schema_version": "a06-lifecycle-rearmed-frontend-stage-receipt-v1",
            "status": "PASS_STAGE_ACCEPTED",
            "stage": name,
            "started_at_utc": started,
            "ended_at_utc": now(),
            "terminal_process": {
                "return_code": return_code,
                "single_popen": True,
                "wall_time_seconds": wall_time,
            },
            "execution_integrity": {
                "no_automatic_retry": True,
                "ambient_desktop_and_unrelated_workloads_allowed": True,
                "runtime_or_realtime_claim_permitted": False,
            },
            "command": command,
            "environment_updates": environment,
            "inputs_before": inputs_before,
            "inputs_after": inputs_after,
            "outputs": outputs,
            "artifact_audit": audit,
            "claim_boundary": {
                "frontend_only": True,
                "vins_hfnet_or_evaluator_started": False,
                "trajectory_or_accuracy_claim_permitted": False,
            },
        }
        write_json(stage / "formal_run_receipt_v1.json", receipt)
        stage.rename(accepted)
        return receipt
    except BaseException as error:
        failure_stage(stage, failure, error)
        raise


def execute() -> dict[str, Any]:
    ready = preflight()
    OUTPUT_ROOT.mkdir(mode=0o755)
    LOCK_PATH.touch(exist_ok=False)
    with LOCK_PATH.open("r+") as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        raw = raw_contract()
        klt = audit_klt(raw["feature_stamps"])
        inputs = input_identities()
        candidate_receipt = execute_stage(
            "candidate_generator",
            CANDIDATE_STAGE,
            CANDIDATE_DIR,
            CANDIDATE_FAILURE,
            candidate_command(CANDIDATE_STAGE),
            7200,
            inputs,
            audit_candidate,
            (klt,),
            (
                "dummy_merged.bag", "candidate_sidecar.bag", "candidate_stats.csv",
                "supervisor_process.log", "process_start_claim_v1.json",
            ),
        )
        candidate_audit = candidate_receipt["artifact_audit"]
        lifecycle_inputs = input_identities()
        lifecycle_inputs[str(CANDIDATE_DIR / "candidate_sidecar.bag")] = identity(
            CANDIDATE_DIR / "candidate_sidecar.bag"
        )
        lifecycle_receipt = execute_stage(
            "lifecycle_selector",
            LIFECYCLE_STAGE,
            LIFECYCLE_DIR,
            LIFECYCLE_FAILURE,
            lifecycle_command(LIFECYCLE_STAGE),
            1800,
            lifecycle_inputs,
            audit_lifecycle,
            (klt, candidate_audit),
            (
                "drop_whole_lineage.bag", "drop_whole_lineage_stats.csv",
                "full_merged.bag", "lineage_selection.csv", "manifest.txt",
                "supervisor_process.log", "process_start_claim_v1.json",
            ),
        )
        # execute_stage re-hashes the candidate sidecar together with all common
        # frozen inputs, so the adopted candidate cannot change during selection.
        lifecycle_audit = lifecycle_receipt["artifact_audit"]
        terminal_status = lifecycle_audit["status"]
        terminal = {
            "schema_version": "a06-lifecycle-rearmed-natural-history-terminal-v1",
            "status": terminal_status,
            "recorded_at_utc": now(),
            "method_id": "AQUAFE_XFEAT_LIFECYCLE_REARMED_DIAGNOSTIC_V1",
            "natural_history_feed_source_indices_inclusive": [0, 2460],
            "historical_action_gate_source_indices_inclusive": [2210, 2460],
            "predeclared_later_accuracy_window_source_indices_inclusive": [1860, 2460],
            "candidate_receipt": identity(CANDIDATE_DIR / "formal_run_receipt_v1.json"),
            "lifecycle_receipt": identity(LIFECYCLE_DIR / "formal_run_receipt_v1.json"),
            "learned_action_gate": lifecycle_audit["gate"],
            "full_learned_action": {
                "observations": lifecycle_audit["injected_observations"],
                "affected_frames": lifecycle_audit["affected_frames"],
                "raw_selected_lineages": lifecycle_audit["unique_raw_selected_lineages"],
                "remapped_affected_ids": lifecycle_audit["unique_remapped_affected_ids"],
            },
            "decision": {
                "backend_may_be_prepared": terminal_status == "PASS_SCORE_ACTION_GATE_FRONTEND_ONLY",
                "backend_started_by_this_runner": False,
                "automatic_retry_permitted": False,
                "parameter_change_permitted_after_outcome": False,
            },
            "claim_boundary": {
                "frontend_action_evidence_only": True,
                "trajectory_accuracy_result_available": False,
                "system_ranking_or_superiority_claim_permitted": False,
                "original_final_online_identity_claim_permitted": False,
            },
        }
        write_json(TERMINAL_RECEIPT, terminal)
        return terminal


def audit_existing() -> dict[str, Any]:
    require(TERMINAL_RECEIPT.is_file() and not TERMINAL_RECEIPT.is_symlink(), "TERMINAL_MISSING")
    raw = raw_contract()
    klt = audit_klt(raw["feature_stamps"])
    candidate = audit_candidate(klt, CANDIDATE_DIR)
    lifecycle = audit_lifecycle(klt, candidate, LIFECYCLE_DIR)
    with TERMINAL_RECEIPT.open(encoding="utf-8") as stream:
        terminal = json.load(stream)
    require(terminal.get("status") == lifecycle["status"], "TERMINAL_STATUS_DRIFT")
    require(terminal.get("learned_action_gate") == lifecycle["gate"], "TERMINAL_GATE_DRIFT")
    return {
        "status": "PASS_EXISTING_PROBE_AUDIT",
        "terminal_status": terminal["status"],
        "candidate": candidate,
        "lifecycle": lifecycle,
        "terminal_receipt": identity(TERMINAL_RECEIPT),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "run", "audit"))
    args = parser.parse_args()
    try:
        if args.command == "preflight":
            result = preflight()
        elif args.command == "run":
            result = execute()
        else:
            result = audit_existing()
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))
        return 0
    except (
        ProbeError, OSError, ValueError, csv.Error, subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as error:
        print(f"A06_LIFECYCLE_PROBE_ERROR:{type(error).__name__}:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
