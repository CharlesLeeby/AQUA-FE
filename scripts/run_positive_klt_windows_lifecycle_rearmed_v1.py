#!/usr/bin/env python3
"""One-shot A10/A09 natural-history lifecycle-rearmed frontend probes.

The fixed execution order is A10 then A09.  This runner never starts ROS,
VINS-Fusion, HFNet, an evaluator, or a trajectory-producing process.
"""

from __future__ import annotations

import argparse
import copy
import csv
from dataclasses import dataclass
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
PROTOCOL = ROOT / "papers/positive_klt_windows_lifecycle_rearmed_v1_protocol.md"
RUNNER = Path(__file__).resolve()
OUTPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/positive_klt_windows_lifecycle_rearmed_v1"
)
LOCK_PATH = OUTPUT_ROOT / ".frontend_supervisor.flock"
MULTIWINDOW_RECEIPT = OUTPUT_ROOT / "multiwindow_terminal_receipt_v1.json"

XFEAT_NODE = ROOT / "uw_frontend/ros/xfeat_seed_sidecar_node.py"
LINEAGE_NODE = ROOT / "uw_frontend/ros/causal_lineage_shadow_node.py"
XFEAT_CONFIG = (
    ROOT
    / "uw_frontend/configs/experiments/low_texture_lineage_safe_dense_start_frontend.yaml"
)
XFEAT_WEIGHTS = ROOT / "external_tools/accelerated_features/weights/xfeat.pt"
PREPARE_SCRIPT = ROOT / "scripts/prepare_causal_multilineage_bag.sh"

CAMERA_TOPIC = "/camera/image_raw"
FEATURE_TOPIC = "/feature_tracker/feature"
SIDECAR_TOPIC = "/feature_tracker/sidecar"
IMU_TOPIC = "/rtimulib_node/imu"
GT_TOPIC = "/aqualoc/colmap_gt"
CHANNELS = (
    "id", "camera_id", "p_u", "p_v", "velocity_x", "velocity_y",
    "gx", "gy", "gz", "quality", "sigma", "source_code", "is_learned",
)
LEARNED_SOURCE_CODES = {10, 20, 30}
NORMAL_FEATURE_POINTS = 350


@dataclass(frozen=True)
class WindowSpec:
    key: str
    sequence: str
    raw_bag: Path
    klt_bag: Path
    camera_config: Path
    raw_identity: tuple[int, str]
    klt_identity: tuple[int, str]
    camera_count: int
    feature_count: int
    imu_count: int
    gt_count: int
    feed_end: int
    score_start: int
    max_triggers: int

    @property
    def output(self) -> Path:
        return OUTPUT_ROOT / self.key

    @property
    def score_first_feature(self) -> int:
        return self.score_start // 2

    @property
    def score_feature_count(self) -> int:
        return self.feature_count - self.score_first_feature


WINDOWS = (
    WindowSpec(
        key="a10",
        sequence="AQUALOC_ARCHAEO_10",
        raw_bag=Path(
            "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v1/raw/"
            "archaeo10_0000_2800.bag"
        ),
        klt_bag=Path(
            "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v3_recovery/"
            "frontends/klt_input_adoption/features.bag"
        ),
        camera_config=Path(
            "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v3_recovery/"
            "frontends/klt_input_adoption/aqualoc_archaeo10_pinhole.yaml"
        ),
        raw_identity=(
            765_976_943,
            "49864715ec19005daa3492fa043fe87204fb6f8cc802b6b98cba55a8ab4fe87e",
        ),
        klt_identity=(
            42_576_500,
            "34e7ea87dd5706c58e666341776107570cc3351794b92da541f7eb8ec0d04b1f",
        ),
        camera_count=2801,
        feature_count=1400,
        imu_count=28064,
        gt_count=139,
        feed_end=2800,
        score_start=2400,
        max_triggers=117,
    ),
    WindowSpec(
        key="a09",
        sequence="AQUALOC_ARCHAEO_09",
        raw_bag=Path(
            "/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1/"
            "raw/archaeo09_0000_4400.bag"
        ),
        klt_bag=Path(
            "/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1/"
            "frontends/klt_export/features.bag"
        ),
        camera_config=Path(
            "/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1/"
            "frontends/klt_export/aqualoc_archaeo09_pinhole.yaml"
        ),
        raw_identity=(
            1_187_038_470,
            "a4a24bd0c2451f4996d39f635e55fd99730698bf704c4e7dc81729070d0dca97",
        ),
        klt_identity=(
            66_859_585,
            "cce64be73ddd545ad469e42adddf9cf8f9592f8316adda69399ec27d0b71494f",
        ),
        camera_count=4401,
        feature_count=2200,
        imu_count=44025,
        gt_count=213,
        feed_end=4400,
        score_start=4000,
        max_triggers=184,
    ),
)

CAMERA_IDENTITY = (
    357,
    "045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5",
)
COMMON_IDENTITIES = {
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
}


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


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


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


def input_identities(spec: WindowSpec) -> dict[str, Any]:
    expected = {
        spec.raw_bag: spec.raw_identity,
        spec.klt_bag: spec.klt_identity,
        spec.camera_config: CAMERA_IDENTITY,
        **COMMON_IDENTITIES,
    }
    values = {
        str(path): require_identity(path, frozen)
        for path, frozen in expected.items()
    }
    for path in (PROTOCOL, RUNNER):
        require(path.is_file() and not path.is_symlink(), f"CONTROL_NOT_REGULAR:{path}")
        values[str(path)] = identity(path)
    return values


def refresh_identities(previous: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw_path in previous:
        path = Path(raw_path)
        require(path.is_file() and not path.is_symlink(), f"CLAIMED_INPUT_NOT_REGULAR:{path}")
        result[raw_path] = identity(path)
    return result


def raw_contract(spec: WindowSpec) -> dict[str, Any]:
    rosbag = rosbag_module()
    camera_stamps: list[int] = []
    gt_stamps: list[int] = []
    counts = {CAMERA_TOPIC: 0, IMU_TOPIC: 0, GT_TOPIC: 0}
    with rosbag.Bag(str(spec.raw_bag), "r") as bag:
        for topic, message, record_stamp in bag.read_messages(
            topics=[CAMERA_TOPIC, IMU_TOPIC, GT_TOPIC]
        ):
            require(
                exact_ns(message.header.stamp) == exact_ns(record_stamp),
                f"{spec.key}:RAW_HEADER_RECORD:{topic}",
            )
            counts[topic] += 1
            if topic == CAMERA_TOPIC:
                camera_stamps.append(exact_ns(message.header.stamp))
            elif topic == GT_TOPIC:
                gt_stamps.append(exact_ns(message.header.stamp))
    expected_counts = {
        CAMERA_TOPIC: spec.camera_count,
        IMU_TOPIC: spec.imu_count,
        GT_TOPIC: spec.gt_count,
    }
    require(counts == expected_counts, f"{spec.key}:RAW_COUNTS:{counts}")
    require(
        all(b > a for a, b in zip(camera_stamps, camera_stamps[1:])),
        f"{spec.key}:CAMERA_ORDER",
    )
    require(spec.camera_count == spec.feed_end + 1, f"{spec.key}:FEED_CAMERA_BINDING")
    feature_stamps = camera_stamps[1:spec.feed_end:2]
    require(len(feature_stamps) == spec.feature_count, f"{spec.key}:FEATURE_BINDING_COUNT")
    require(
        spec.max_triggers == math.ceil(spec.feature_count / 12),
        f"{spec.key}:TRIGGER_FORMULA",
    )
    require(spec.score_start % 2 == 0, f"{spec.key}:SCORE_START_PARITY")
    require(spec.score_feature_count == 200, f"{spec.key}:SCORE_FEATURE_COUNT")
    score_start_ns = camera_stamps[spec.score_start]
    score_end_ns = camera_stamps[spec.feed_end]
    score_gt = [stamp for stamp in gt_stamps if score_start_ns <= stamp <= score_end_ns]
    first = spec.score_first_feature
    require(feature_stamps[first] >= score_start_ns, f"{spec.key}:SCORE_FEATURE_BOUNDARY")
    require(feature_stamps[first - 1] < score_start_ns, f"{spec.key}:SCORE_PRE_BOUNDARY")
    return {
        "counts": counts,
        "camera_first_ns": camera_stamps[0],
        "camera_last_ns": camera_stamps[-1],
        "feature_stamps": feature_stamps,
        "natural_history_feed_source_indices_inclusive": [0, spec.feed_end],
        "score_gate": {
            "source_indices_inclusive": [spec.score_start, spec.feed_end],
            "timestamp_ns_inclusive": [score_start_ns, score_end_ns],
            "feature_indices_inclusive": [first, spec.feature_count - 1],
            "feature_messages": spec.score_feature_count,
            "native_gt_messages": len(score_gt),
        },
    }


def audit_klt(spec: WindowSpec, expected_stamps: list[int]) -> dict[str, Any]:
    rosbag = rosbag_module()
    counts: dict[str, int] = {}
    feature_stamps: list[int] = []
    feature_point_counts: list[int] = []
    stream = hashlib.sha256()
    with rosbag.Bag(str(spec.klt_bag), "r") as bag:
        for topic, message, record_stamp in bag.read_messages():
            counts[topic] = counts.get(topic, 0) + 1
            add_serialized(stream, topic, message, record_stamp)
            require(
                exact_ns(message.header.stamp) == exact_ns(record_stamp),
                f"{spec.key}:KLT_HEADER_RECORD:{topic}",
            )
            if topic != FEATURE_TOPIC:
                continue
            require(message._type == "sensor_msgs/PointCloud", f"{spec.key}:KLT_FEATURE_TYPE")
            point_count = len(message.points)
            require(point_count == NORMAL_FEATURE_POINTS, f"{spec.key}:KLT_POINT_COUNT:{point_count}")
            channels = channel_values(message)
            ids = [integral(value, "klt_id") for value in channels["id"]]
            require(len(set(ids)) == point_count, f"{spec.key}:KLT_ID_UNIQUENESS")
            require(max(ids) < 10_000_000 and min(ids) >= 0, f"{spec.key}:KLT_ID_RANGE")
            require(
                all(integral(v, "klt_learned") == 0 for v in channels["is_learned"]),
                f"{spec.key}:KLT_LEARNED",
            )
            require(
                all(
                    integral(v, "klt_source") not in LEARNED_SOURCE_CODES
                    for v in channels["source_code"]
                ),
                f"{spec.key}:KLT_SOURCE",
            )
            feature_stamps.append(exact_ns(message.header.stamp))
            feature_point_counts.append(point_count)
    expected_counts = {
        GT_TOPIC: spec.gt_count,
        FEATURE_TOPIC: spec.feature_count,
        IMU_TOPIC: spec.imu_count,
    }
    require(counts == expected_counts, f"{spec.key}:KLT_COUNTS:{counts}")
    require(feature_stamps == expected_stamps, f"{spec.key}:KLT_RAW_FEATURE_STAMP_BINDING")
    return {
        "status": "PASS_KLT_INPUT_CONTRACT",
        "topic_counts": counts,
        "feature_point_count_histogram": {str(NORMAL_FEATURE_POINTS): spec.feature_count},
        "ordered_stream_sha256": stream.hexdigest(),
        "feature_stamps": feature_stamps,
        "feature_point_counts": feature_point_counts,
    }


def paths(spec: WindowSpec) -> dict[str, Path]:
    return {
        "candidate": spec.output / "candidate_generator",
        "candidate_stage": spec.output / ".candidate_generator.stage_v1",
        "candidate_failure": spec.output / "candidate_generator_failed_v1",
        "lifecycle": spec.output / "lifecycle_rearmed",
        "lifecycle_stage": spec.output / ".lifecycle_rearmed.stage_v1",
        "lifecycle_failure": spec.output / "lifecycle_rearmed_failed_v1",
        "terminal": spec.output / "terminal_probe_receipt_v1.json",
    }


def candidate_command(spec: WindowSpec, stage: Path) -> list[str]:
    return [
        "/usr/bin/python3.8", "-m", "uw_frontend.ros.xfeat_seed_sidecar_node", "bag",
        "--config", str(XFEAT_CONFIG),
        "--camera-config", str(spec.camera_config),
        "--image-bag", str(spec.raw_bag),
        "--base-bag", str(spec.klt_bag),
        "--output-bag", str(stage / "dummy_merged.bag"),
        "--sidecar-bag", str(stage / "candidate_sidecar.bag"),
        "--stats-csv", str(stage / "candidate_stats.csv"),
        "--image-topic", CAMERA_TOPIC,
        "--base-topic", FEATURE_TOPIC,
        "--sidecar-topic", SIDECAR_TOPIC,
        "--image-scale", "0.5", "--preprocess", "adaptive_clahe",
        "--trigger-warmup-frames", "0", "--trigger-cooldown-frames", "12",
        "--max-triggers", str(spec.max_triggers), "--disable-seed-loss-rearm",
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


def lifecycle_command(spec: WindowSpec, stage: Path) -> list[str]:
    candidate = paths(spec)["candidate"]
    return [
        "/usr/bin/bash", str(PREPARE_SCRIPT),
        str(spec.klt_bag), str(candidate / "candidate_sidecar.bag"),
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
        for index, pair in enumerate(zip_longest(left.read_messages(), right.read_messages())):
            left_item, right_item = pair
            require(left_item is not None and right_item is not None, f"{code}_LENGTH:{index}")
            left_topic, left_message, left_stamp = left_item
            right_topic, right_message, right_stamp = right_item
            require(left_topic == right_topic, f"{code}_TOPIC:{index}")
            require(exact_ns(left_stamp) == exact_ns(right_stamp), f"{code}_STAMP:{index}")
            require(serialized(left_message) == serialized(right_message), f"{code}_PAYLOAD:{index}")
            add_serialized(digest, left_topic, left_message, left_stamp)
            count += 1
    return {"messages": count, "ordered_stream_sha256": digest.hexdigest()}


def section_sums(spec: WindowSpec, values: list[int]) -> dict[str, int]:
    require(len(values) == spec.feature_count, f"{spec.key}:SECTION_VALUE_COUNT")
    first = spec.score_first_feature
    return {
        "full_history": sum(values),
        "before_score_gate": sum(values[:first]),
        "score_gate": sum(values[first:]),
    }


def read_csv(path: Path, expected_rows: int) -> tuple[list[dict[str, str]], list[str]]:
    require(path.is_file() and not path.is_symlink(), f"CSV_MISSING:{path}")
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    require(len(rows) == expected_rows, f"CSV_ROW_COUNT:{path}:{len(rows)}")
    return rows, fields


def audit_candidate(
    spec: WindowSpec, klt: dict[str, Any], directory: Path
) -> dict[str, Any]:
    rosbag = rosbag_module()
    dummy = directory / "dummy_merged.bag"
    sidecar = directory / "candidate_sidecar.bag"
    stats = directory / "candidate_stats.csv"
    for path in (dummy, sidecar, stats, directory / "supervisor_process.log"):
        require(path.is_file() and not path.is_symlink(), f"CANDIDATE_OUTPUT_MISSING:{path}")
    parity = compare_bags_exact(spec.klt_bag, dummy, f"{spec.key}:CANDIDATE_DUMMY_PARITY")
    require(parity["ordered_stream_sha256"] == klt["ordered_stream_sha256"], f"{spec.key}:DUMMY_DIGEST")

    sidecar_stamps: list[int] = []
    candidate_counts: list[int] = []
    with rosbag.Bag(str(sidecar), "r") as bag:
        for topic, message, record_stamp in bag.read_messages():
            require(topic == SIDECAR_TOPIC, f"{spec.key}:SIDECAR_TOPIC:{topic}")
            require(exact_ns(message.header.stamp) == exact_ns(record_stamp), f"{spec.key}:SIDECAR_HEADER_RECORD")
            channels = channel_values(message)
            for source, learned, raw_id in zip(
                channels["source_code"], channels["is_learned"], channels["id"]
            ):
                require(integral(source, "sidecar_source") == 20, f"{spec.key}:SIDECAR_SOURCE")
                require(integral(learned, "sidecar_learned") == 1, f"{spec.key}:SIDECAR_LEARNED")
                require(0 <= integral(raw_id, "sidecar_id") < 10_000_000, f"{spec.key}:SIDECAR_RAW_ID")
            sidecar_stamps.append(exact_ns(message.header.stamp))
            candidate_counts.append(len(message.points))
    require(sidecar_stamps == klt["feature_stamps"], f"{spec.key}:SIDECAR_STAMP_BINDING")

    rows, fields = read_csv(stats, spec.feature_count)
    require("selector_injected_observations" in fields, f"{spec.key}:CANDIDATE_STATS_SCHEMA")
    trigger: list[int] = []
    added: list[int] = []
    injected: list[int] = []
    for index, row in enumerate(rows):
        require(integral(float(row["frame_index"]), "candidate_frame") == index, f"{spec.key}:CANDIDATE_FRAME_INDEX")
        require(
            abs(float(row["stamp"]) - klt["feature_stamps"][index] / 1e9) <= 2e-6,
            f"{spec.key}:CANDIDATE_STATS_STAMP",
        )
        trigger.append(integral(float(row["triggered"]), "candidate_trigger"))
        added.append(integral(float(row["added_seeds"]), "candidate_added"))
        injected.append(integral(float(row["selector_injected_observations"]), "candidate_injected"))
        for key in ("selector_selected_ids", "selector_active_ids", "selector_activated_ids"):
            require(not row[key], f"{spec.key}:CANDIDATE_SELECTOR_NONEMPTY:{key}:{index}")
    require(sum(injected) == 0, f"{spec.key}:CANDIDATE_STAGE_INJECTED_NONZERO")
    successful = [index for index, value in enumerate(added) if value > 0]
    require(len(successful) <= spec.max_triggers, f"{spec.key}:CANDIDATE_TRIGGER_BUDGET")
    require(
        all(b - a >= 12 for a, b in zip(successful, successful[1:])),
        f"{spec.key}:CANDIDATE_SUCCESS_COOLDOWN",
    )
    return {
        "status": "PASS_CANDIDATE_GENERATOR_AUDIT",
        "dummy_merged_exact_klt_parity": parity,
        "sidecar_messages": len(sidecar_stamps),
        "candidate_observations": section_sums(spec, candidate_counts),
        "affected_candidate_frames": section_sums(spec, [int(value > 0) for value in candidate_counts]),
        "triggered_frames": section_sums(spec, trigger),
        "added_seeds": section_sums(spec, added),
        "successful_trigger_rows": successful,
        "max_triggers": spec.max_triggers,
        "max_triggers_formula": "ceil(feature_count / 12)",
        "dummy_selector_injected_observations": section_sums(spec, injected),
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


def audit_lifecycle(
    spec: WindowSpec,
    klt: dict[str, Any],
    candidate: dict[str, Any],
    directory: Path,
) -> dict[str, Any]:
    rosbag = rosbag_module()
    full = directory / "full_merged.bag"
    drop = directory / "drop_whole_lineage.bag"
    stats = directory / "lineage_selection.csv"
    for path in (
        full, drop, stats, directory / "drop_whole_lineage_stats.csv",
        directory / "manifest.txt", directory / "supervisor_process.log",
    ):
        require(path.is_file() and not path.is_symlink(), f"LIFECYCLE_OUTPUT_MISSING:{path}")
    drop_parity = compare_bags_exact(spec.klt_bag, drop, f"{spec.key}:LIFECYCLE_DROP_PARITY")
    require(drop_parity["ordered_stream_sha256"] == klt["ordered_stream_sha256"], f"{spec.key}:DROP_DIGEST")

    injected_counts: list[int] = []
    affected_ids: set[int] = set()
    recovered_digest = hashlib.sha256()
    record_count = 0
    with rosbag.Bag(str(spec.klt_bag), "r") as base, rosbag.Bag(str(full), "r") as merged:
        for index, pair in enumerate(zip_longest(base.read_messages(), merged.read_messages())):
            base_item, merged_item = pair
            require(base_item is not None and merged_item is not None, f"{spec.key}:FULL_LENGTH:{index}")
            base_topic, base_message, base_stamp = base_item
            merged_topic, merged_message, merged_stamp = merged_item
            require(base_topic == merged_topic, f"{spec.key}:FULL_TOPIC:{index}")
            require(exact_ns(base_stamp) == exact_ns(merged_stamp), f"{spec.key}:FULL_STAMP:{index}")
            if base_topic != FEATURE_TOPIC:
                require(serialized(base_message) == serialized(merged_message), f"{spec.key}:FULL_NONFEATURE:{index}")
                add_serialized(recovered_digest, base_topic, merged_message, merged_stamp)
            else:
                recovered, learned_indices = strip_learned(merged_message)
                require(len(learned_indices) <= 1, f"{spec.key}:CONCURRENT_LINEAGE_CAP:{len(injected_counts)}")
                expected_base_count = klt["feature_point_counts"][len(injected_counts)]
                require(len(recovered.points) == expected_base_count, f"{spec.key}:RECOVERED_FEATURE_COUNT:{len(injected_counts)}")
                require(serialized(recovered) == serialized(base_message), f"{spec.key}:FULL_RECOVERY:{len(injected_counts)}")
                merged_channels = channel_values(merged_message)
                for learned_index in learned_indices:
                    affected_ids.add(integral(merged_channels["id"][learned_index], "affected_id"))
                injected_counts.append(len(learned_indices))
                add_serialized(recovered_digest, base_topic, recovered, merged_stamp)
            record_count += 1
    require(len(injected_counts) == spec.feature_count, f"{spec.key}:FULL_FEATURE_COUNT")
    require(recovered_digest.hexdigest() == klt["ordered_stream_sha256"], f"{spec.key}:FULL_RECOVERED_DIGEST")

    rows, fields = read_csv(stats, spec.feature_count)
    csv_injected: list[int] = []
    activated_ids: set[int] = set()
    retired_ids: set[int] = set()
    selected_ids: set[int] = set()
    for index, row in enumerate(rows):
        require(integral(float(row["frame_index"]), "lifecycle_frame") == index, f"{spec.key}:LIFECYCLE_FRAME_INDEX")
        require(
            abs(float(row["stamp"]) - klt["feature_stamps"][index] / 1e9) <= 2e-6,
            f"{spec.key}:LIFECYCLE_STATS_STAMP",
        )
        csv_injected.append(integral(float(row["injected_observations"]), "lifecycle_injected"))
        for key, target in (
            ("activated_ids", activated_ids),
            ("retired_ids", retired_ids),
            ("selected_ids", selected_ids),
        ):
            for value in row[key].split(";") if row[key] else []:
                target.add(int(value))
    require(csv_injected == injected_counts, f"{spec.key}:CSV_BAG_INJECTION_BINDING")

    observation_sections = section_sums(spec, injected_counts)
    affected_sections = section_sums(spec, [int(value > 0) for value in injected_counts])
    gate_value = observation_sections["score_gate"]
    status = (
        "PASS_SCORE_ACTION_GATE_FRONTEND_ONLY"
        if gate_value > 0
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
            "expression": "score_gate_injected_observations > 0",
            "source_indices_inclusive": [spec.score_start, spec.feed_end],
            "feature_indices_inclusive": [spec.score_first_feature, spec.feature_count - 1],
            "value": gate_value,
            "passed": gate_value > 0,
        },
    }


def output_identities(directory: Path, names: Iterable[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in names:
        path = directory / name
        require(path.is_file() and not path.is_symlink(), f"OUTPUT_NOT_REGULAR:{path}")
        result[name] = identity(path)
    return result


def output_state(spec: WindowSpec) -> str:
    window_paths = paths(spec)
    terminal = window_paths["terminal"]
    if not spec.output.exists() and not spec.output.is_symlink():
        return "NOT_STARTED"
    require(spec.output.is_dir() and not spec.output.is_symlink(), f"{spec.key}:OUTPUT_NOT_DIRECTORY")
    if terminal.is_file() and not terminal.is_symlink():
        return "TERMINAL_RETAINED_NO_RERUN"
    return "BLOCKED_PARTIAL_NO_RETRY"


def preflight() -> dict[str, Any]:
    require(Path("/usr/bin/python3.8").is_file(), "PYTHON38_MISSING")
    require(OUTPUT_ROOT.parent.is_dir(), "OUTPUT_PARENT_MISSING")
    require(shutil.disk_usage(OUTPUT_ROOT.parent).free >= 12_000_000_000, "INSUFFICIENT_SPACE")
    window_results: dict[str, Any] = {}
    for spec in WINDOWS:
        state = output_state(spec)
        require(state != "BLOCKED_PARTIAL_NO_RETRY", f"{spec.key}:PARTIAL_OUTPUT_BLOCKS_RETRY")
        inputs = input_identities(spec)
        raw = raw_contract(spec)
        klt = audit_klt(spec, raw["feature_stamps"])
        window_results[spec.key] = {
            "state": state,
            "inputs": inputs,
            "raw_contract": {key: value for key, value in raw.items() if key != "feature_stamps"},
            "klt_contract": {
                key: value
                for key, value in klt.items()
                if key not in {"feature_stamps", "feature_point_counts"}
            },
            "candidate_command": candidate_command(spec, paths(spec)["candidate_stage"]),
            "lifecycle_command": lifecycle_command(spec, paths(spec)["lifecycle_stage"]),
        }
    return {
        "status": "READY_FIXED_ORDER_ONE_SHOT_FRONTEND_PROBES",
        "method_id": "AQUAFE_XFEAT_LIFECYCLE_REARMED_DIAGNOSTIC_V1",
        "fixed_order": [spec.key for spec in WINDOWS],
        "windows": window_results,
        "historical_selection_artifacts_read": False,
        "historical_selection_role": "roster_provenance_only_not_runtime_input",
        "max_triggers_rule": "ceil(feature_count / 12)",
        "no_automatic_retry": True,
        "zero_action_retained": True,
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
    spec: WindowSpec,
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
    require(not stage.exists() and not stage.is_symlink(), f"{spec.key}:STAGE_EXISTS:{stage}")
    require(not accepted.exists() and not accepted.is_symlink(), f"{spec.key}:ACCEPTED_EXISTS:{accepted}")
    require(not failure.exists() and not failure.is_symlink(), f"{spec.key}:FAILURE_EXISTS:{failure}")
    stage.mkdir(mode=0o755)
    environment = child_environment(stage)
    write_json(stage / "process_start_claim_v1.json", {
        "schema_version": "positive-klt-lifecycle-rearmed-process-start-claim-v1",
        "status": "CLAIMED_BEFORE_SINGLE_POPEN",
        "window": spec.key,
        "stage": name,
        "created_at_utc": now(),
        "command": command,
        "environment_updates": environment,
        "inputs": inputs_before,
        "no_automatic_retry": True,
    })
    started = now()
    try:
        return_code, wall_time = run_child(command, environment, stage / "supervisor_process.log", timeout)
        require(return_code == 0, f"{spec.key}:{name.upper()}_RETURN_CODE:{return_code}")
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
            f"{spec.key}:{name.upper()}_INPUT_IDENTITY_CHANGED",
        )
        outputs = output_identities(stage, output_names)
        receipt = {
            "schema_version": "positive-klt-lifecycle-rearmed-frontend-stage-receipt-v1",
            "status": "PASS_STAGE_ACCEPTED",
            "window": spec.key,
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


def execute_window(spec: WindowSpec) -> dict[str, Any]:
    require(output_state(spec) == "NOT_STARTED", f"{spec.key}:REFUSE_WINDOW_RERUN")
    spec.output.mkdir(mode=0o755)
    window_paths = paths(spec)
    try:
        raw = raw_contract(spec)
        klt = audit_klt(spec, raw["feature_stamps"])
        inputs = input_identities(spec)
        candidate_receipt = execute_stage(
            spec,
            "candidate_generator",
            window_paths["candidate_stage"],
            window_paths["candidate"],
            window_paths["candidate_failure"],
            candidate_command(spec, window_paths["candidate_stage"]),
            10_800,
            inputs,
            audit_candidate,
            (spec, klt),
            (
                "dummy_merged.bag", "candidate_sidecar.bag", "candidate_stats.csv",
                "supervisor_process.log", "process_start_claim_v1.json",
            ),
        )
        candidate_audit = candidate_receipt["artifact_audit"]
        lifecycle_inputs = input_identities(spec)
        sidecar_path = window_paths["candidate"] / "candidate_sidecar.bag"
        lifecycle_inputs[str(sidecar_path)] = identity(sidecar_path)
        lifecycle_receipt = execute_stage(
            spec,
            "lifecycle_selector",
            window_paths["lifecycle_stage"],
            window_paths["lifecycle"],
            window_paths["lifecycle_failure"],
            lifecycle_command(spec, window_paths["lifecycle_stage"]),
            3600,
            lifecycle_inputs,
            audit_lifecycle,
            (spec, klt, candidate_audit),
            (
                "drop_whole_lineage.bag", "drop_whole_lineage_stats.csv",
                "full_merged.bag", "lineage_selection.csv", "manifest.txt",
                "supervisor_process.log", "process_start_claim_v1.json",
            ),
        )
        lifecycle_audit = lifecycle_receipt["artifact_audit"]
        terminal_status = lifecycle_audit["status"]
        terminal = {
            "schema_version": "positive-klt-lifecycle-rearmed-window-terminal-v1",
            "status": terminal_status,
            "window": spec.key,
            "sequence": spec.sequence,
            "recorded_at_utc": now(),
            "method_id": "AQUAFE_XFEAT_LIFECYCLE_REARMED_DIAGNOSTIC_V1",
            "natural_history_feed_source_indices_inclusive": [0, spec.feed_end],
            "score_gate_source_indices_inclusive": [spec.score_start, spec.feed_end],
            "candidate_receipt": identity(window_paths["candidate"] / "formal_run_receipt_v1.json"),
            "lifecycle_receipt": identity(window_paths["lifecycle"] / "formal_run_receipt_v1.json"),
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
        write_json(window_paths["terminal"], terminal)
        return terminal
    except Exception as error:
        failure_receipts = []
        for key in ("candidate_failure", "lifecycle_failure"):
            failure = window_paths[key] / "failure_receipt_v1.json"
            if failure.is_file() and not failure.is_symlink():
                failure_receipts.append(identity(failure))
        terminal = {
            "schema_version": "positive-klt-lifecycle-rearmed-window-terminal-v1",
            "status": "FAILED_NO_AUTOMATIC_RETRY",
            "window": spec.key,
            "sequence": spec.sequence,
            "recorded_at_utc": now(),
            "method_id": "AQUAFE_XFEAT_LIFECYCLE_REARMED_DIAGNOSTIC_V1",
            "error_type": type(error).__name__,
            "error": str(error),
            "failure_receipts": failure_receipts,
            "decision": {
                "backend_may_be_prepared": False,
                "backend_started_by_this_runner": False,
                "automatic_retry_permitted": False,
                "parameter_change_permitted_after_outcome": False,
            },
            "claim_boundary": {
                "frontend_action_evidence_only": False,
                "trajectory_accuracy_result_available": False,
                "system_ranking_or_superiority_claim_permitted": False,
            },
        }
        write_json(window_paths["terminal"], terminal)
        return terminal


def audit_window(spec: WindowSpec) -> dict[str, Any]:
    window_paths = paths(spec)
    terminal_path = window_paths["terminal"]
    require(terminal_path.is_file() and not terminal_path.is_symlink(), f"{spec.key}:TERMINAL_MISSING")
    terminal = read_json(terminal_path)
    require(terminal.get("window") == spec.key, f"{spec.key}:TERMINAL_WINDOW_DRIFT")
    require(
        terminal.get("method_id") == "AQUAFE_XFEAT_LIFECYCLE_REARMED_DIAGNOSTIC_V1",
        f"{spec.key}:METHOD_DRIFT",
    )
    if terminal.get("status") == "FAILED_NO_AUTOMATIC_RETRY":
        receipts = terminal.get("failure_receipts") or []
        for claimed in receipts:
            actual = identity(Path(claimed["path"]))
            require(
                (actual["size_bytes"], actual["sha256"])
                == (claimed["size_bytes"], claimed["sha256"]),
                f"{spec.key}:FAILURE_RECEIPT_DRIFT",
            )
        return {
            "status": "PASS_RETAINED_FAILURE_AUDIT",
            "terminal_status": terminal["status"],
            "failure_receipts": receipts,
            "terminal_receipt": identity(terminal_path),
        }

    raw = raw_contract(spec)
    klt = audit_klt(spec, raw["feature_stamps"])
    candidate = audit_candidate(spec, klt, window_paths["candidate"])
    lifecycle = audit_lifecycle(spec, klt, candidate, window_paths["lifecycle"])
    require(terminal.get("status") == lifecycle["status"], f"{spec.key}:TERMINAL_STATUS_DRIFT")
    require(terminal.get("learned_action_gate") == lifecycle["gate"], f"{spec.key}:TERMINAL_GATE_DRIFT")
    return {
        "status": "PASS_EXISTING_WINDOW_AUDIT",
        "terminal_status": terminal["status"],
        "candidate": candidate,
        "lifecycle": lifecycle,
        "terminal_receipt": identity(terminal_path),
    }


def aggregate_status(terminals: dict[str, dict[str, Any]]) -> str:
    statuses = [terminals[spec.key]["status"] for spec in WINDOWS]
    complete = {"PASS_SCORE_ACTION_GATE_FRONTEND_ONLY", "STOPPED_SCORE_ACTION_ZERO"}
    return (
        "PASS_ALL_WINDOWS_TERMINAL_ACTION_GATES_EVALUATED"
        if all(status in complete for status in statuses)
        else "COMPLETE_WITH_RETAINED_FAILURE_NO_RETRY"
    )


def finalize_multiwindow(terminals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    require(not MULTIWINDOW_RECEIPT.exists(), "MULTIWINDOW_RECEIPT_ALREADY_EXISTS")
    result = {
        "schema_version": "positive-klt-lifecycle-rearmed-multiwindow-terminal-v1",
        "status": aggregate_status(terminals),
        "recorded_at_utc": now(),
        "method_id": "AQUAFE_XFEAT_LIFECYCLE_REARMED_DIAGNOSTIC_V1",
        "fixed_order": [spec.key for spec in WINDOWS],
        "windows": {
            spec.key: {
                "status": terminals[spec.key]["status"],
                "terminal_receipt": identity(paths(spec)["terminal"]),
                "score_gate": terminals[spec.key].get("learned_action_gate"),
                "backend_may_be_prepared": (
                    (terminals[spec.key].get("decision") or {}).get("backend_may_be_prepared")
                    is True
                ),
            }
            for spec in WINDOWS
        },
        "a06_handling": {
            "role": "separate_frozen_receipt_to_be_adopted_by_later_three_window_summary",
            "rerun_by_this_runner": False,
            "expected_terminal_sha256": "4dd554b066bb67112c792f2e1c5c83a9a57601c941cfc56f6e7094161e33b705",
        },
        "historical_selection_artifacts_read": False,
        "no_automatic_retry": True,
        "zero_action_retained": True,
        "claim_boundary": {
            "frontend_action_only": True,
            "backend_or_evaluator_started": False,
            "trajectory_accuracy_result_available": False,
            "system_ranking_or_superiority_claim_permitted": False,
        },
    }
    write_json(MULTIWINDOW_RECEIPT, result)
    return result


def execute_all() -> dict[str, Any]:
    ready = preflight()
    if MULTIWINDOW_RECEIPT.is_file() and not MULTIWINDOW_RECEIPT.is_symlink():
        existing = audit_existing()
        return {
            "status": "ADOPTED_EXISTING_TERMINALS_NO_RERUN",
            "preflight": ready["status"],
            "audit": existing,
        }
    if not OUTPUT_ROOT.exists():
        OUTPUT_ROOT.mkdir(mode=0o755)
    require(OUTPUT_ROOT.is_dir() and not OUTPUT_ROOT.is_symlink(), "OUTPUT_ROOT_NOT_DIRECTORY")
    if not LOCK_PATH.exists():
        LOCK_PATH.touch(exist_ok=False)
    require(LOCK_PATH.is_file() and not LOCK_PATH.is_symlink(), "LOCK_NOT_REGULAR")
    terminals: dict[str, dict[str, Any]] = {}
    with LOCK_PATH.open("r+") as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        for spec in WINDOWS:
            state = output_state(spec)
            if state == "TERMINAL_RETAINED_NO_RERUN":
                audit_window(spec)
                terminals[spec.key] = read_json(paths(spec)["terminal"])
            else:
                require(state == "NOT_STARTED", f"{spec.key}:PARTIAL_OUTPUT_BLOCKS_RETRY")
                terminals[spec.key] = execute_window(spec)
        return finalize_multiwindow(terminals)


def audit_existing() -> dict[str, Any]:
    audits = {spec.key: audit_window(spec) for spec in WINDOWS}
    terminals = {spec.key: read_json(paths(spec)["terminal"]) for spec in WINDOWS}
    require(MULTIWINDOW_RECEIPT.is_file() and not MULTIWINDOW_RECEIPT.is_symlink(), "MULTIWINDOW_TERMINAL_MISSING")
    aggregate = read_json(MULTIWINDOW_RECEIPT)
    require(aggregate.get("status") == aggregate_status(terminals), "AGGREGATE_STATUS_DRIFT")
    for spec in WINDOWS:
        claimed = aggregate["windows"][spec.key]["terminal_receipt"]
        actual = identity(paths(spec)["terminal"])
        require(
            (actual["size_bytes"], actual["sha256"])
            == (claimed["size_bytes"], claimed["sha256"]),
            f"{spec.key}:AGGREGATE_TERMINAL_IDENTITY_DRIFT",
        )
    return {
        "status": "PASS_EXISTING_MULTIWINDOW_AUDIT",
        "aggregate_status": aggregate["status"],
        "windows": audits,
        "multiwindow_terminal_receipt": identity(MULTIWINDOW_RECEIPT),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "run", "audit"))
    args = parser.parse_args()
    try:
        if args.command == "preflight":
            result = preflight()
        elif args.command == "run":
            result = execute_all()
        else:
            result = audit_existing()
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))
        if result.get("status") == "COMPLETE_WITH_RETAINED_FAILURE_NO_RETRY":
            return 2
        return 0
    except (
        ProbeError, OSError, ValueError, csv.Error, subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as error:
        print(
            f"POSITIVE_KLT_LIFECYCLE_PROBE_ERROR:{type(error).__name__}:{error}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
