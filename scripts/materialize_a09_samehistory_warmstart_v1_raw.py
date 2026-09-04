#!/usr/bin/env python3
"""Materialize and audit the frozen A09 0..4400 same-history ROS bag.

This stage only converts pinned AQUALOC source data into a new ROS bag. It
does not start roscore, VINS, a frontend, HFNet, or any learned model.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Any


ROOT = Path("/home/ma/AQUA-FE_WS")
PROTOCOL = ROOT / "papers/a09_samehistory_warmstart_v1_raw_materialization_protocol.md"
CONVERTER = ROOT / "uw_frontend/datasets/aqualoc_raw_to_rosbag.py"
SOURCE_ARCHIVE = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences/archaeo_sequence_9_raw_data.tar.gz"
)
GT = ROOT / (
    "datasets/full_downloads/aqualoc/Archaeological_site_sequences/"
    "archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_09.txt"
)
EXPERIMENT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1"
)
RAW_RELATIVE = Path("raw/archaeo09_0000_4400.bag")
RECEIPT_RELATIVE = Path("raw/raw_materialization_receipt_v1.json")

IMAGE_CSV_MEMBER = "raw_data/img_sequence_9.csv"
IMU_CSV_MEMBER = "raw_data/imu_sequence_9.csv"
IMAGE_DIR = "images_sequence_9"
START_INDEX = 0
END_INDEX = 4400
IMU_MARGIN_NS = 250_000_000

SOURCE_EXPECTED = (
    1_722_658_380,
    "4d20237571928067cfe4dbb813224cfd2277270c424a6ef97ef50d2933da2901",
)
CONVERTER_EXPECTED = (
    8_310,
    "b0c4b7ce7f3e29dcb18cb1604190cc8690cae370fc222246c8dfeb4fc79ffbec",
)
GT_EXPECTED = (
    45_197,
    "b732a68ec354cb66d36b1a9f708d614c70e884d4c167f8940f9601cfce69ac17",
)
IMAGE_CSV_EXPECTED = (
    251_738,
    "29dc7cc3e67df003081070c6191107c8d8d6b5183fc62df965bd0fe5b685d03a",
)
IMU_CSV_EXPECTED = (
    7_806_649,
    "9334097f6311c5fcfe15dae581b18f479dbe9377f78da0b2ba08f4e5a36c83b3",
)
SOURCE_CAMERA_COUNT = 6992
SOURCE_IMU_COUNT = 69861
CAMERA_FIRST_NS = 1_542_888_746_071_008_208
CAMERA_LAST_NS = 1_542_889_095_563_440_368
SCORE_FIRST_NS = 1_542_888_946_038_630_384
SCORE_LAST_NS = 1_542_888_966_034_698_672


class MaterializationError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise MaterializationError(code)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, Any]:
    return {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256(path)}


def require_identity(path: Path, expected: tuple[int, str], label: str) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"{label}_NOT_REGULAR")
    actual = identity(path)
    require((actual["size_bytes"], actual["sha256"]) == expected, f"{label}_IDENTITY_DRIFT")
    return actual


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def exact_ns(stamp: Any) -> int:
    require(type(stamp.secs) is int and type(stamp.nsecs) is int, "ROS_STAMP_NOT_INTEGER")
    require(stamp.secs >= 0 and 0 <= stamp.nsecs < 1_000_000_000, "ROS_STAMP_RANGE")
    return stamp.secs * 1_000_000_000 + stamp.nsecs


def archive_member_payload(tar: tarfile.TarFile, name: str) -> bytes:
    extracted = tar.extractfile(name)
    require(extracted is not None, f"ARCHIVE_MEMBER_MISSING:{name}")
    return extracted.read()


def csv_rows(payload: bytes) -> list[list[str]]:
    text = io.StringIO(payload.decode("utf-8"))
    return [row for row in csv.reader(text) if row and not row[0].startswith("#")]


def derive_contract() -> dict[str, Any]:
    with tarfile.open(SOURCE_ARCHIVE, "r:*") as tar:
        image_payload = archive_member_payload(tar, IMAGE_CSV_MEMBER)
        imu_payload = archive_member_payload(tar, IMU_CSV_MEMBER)
    require(
        (len(image_payload), hashlib.sha256(image_payload).hexdigest()) == IMAGE_CSV_EXPECTED,
        "IMAGE_CSV_IDENTITY_DRIFT",
    )
    require(
        (len(imu_payload), hashlib.sha256(imu_payload).hexdigest()) == IMU_CSV_EXPECTED,
        "IMU_CSV_IDENTITY_DRIFT",
    )
    image_rows = csv_rows(image_payload)
    imu_rows = csv_rows(imu_payload)
    require(len(image_rows) == SOURCE_CAMERA_COUNT, "SOURCE_CAMERA_COUNT_DRIFT")
    require(len(imu_rows) == SOURCE_IMU_COUNT, "SOURCE_IMU_COUNT_DRIFT")
    camera_ns = [int(row[0]) for row in image_rows]
    imu_ns = [int(row[0]) for row in imu_rows]
    require(all(b > a for a, b in zip(camera_ns, camera_ns[1:])), "SOURCE_CAMERA_NOT_INCREASING")
    require(all(b > a for a, b in zip(imu_ns, imu_ns[1:])), "SOURCE_IMU_NOT_INCREASING")
    require(camera_ns[0] == CAMERA_FIRST_NS and camera_ns[-1] == CAMERA_LAST_NS, "SOURCE_CAMERA_ENDPOINT_DRIFT")
    require(camera_ns[4000] == SCORE_FIRST_NS and camera_ns[4400] == SCORE_LAST_NS, "SCORE_CAMERA_ENDPOINT_DRIFT")
    selected_camera = camera_ns[START_INDEX : END_INDEX + 1]
    selected_imu = [
        stamp for stamp in imu_ns
        if selected_camera[0] - IMU_MARGIN_NS <= stamp <= selected_camera[-1] + IMU_MARGIN_NS
    ]
    require(len(selected_camera) == 4401, "SELECTED_CAMERA_COUNT_DRIFT")
    require(len(selected_imu) > 40000, "SELECTED_IMU_COUNT_IMPLAUSIBLE")
    require(selected_imu[0] <= selected_camera[0] and selected_imu[-1] >= selected_camera[-1], "SELECTED_IMU_BOUNDARY_DRIFT")

    gt_indices: list[int] = []
    for raw in GT.read_text(encoding="utf-8").splitlines():
        if raw.strip() and not raw.lstrip().startswith("#"):
            fields = raw.split()
            if len(fields) >= 8:
                gt_indices.append(int(round(float(fields[0]))))
    selected_gt = [index for index in gt_indices if START_INDEX <= index <= END_INDEX]
    missing_gt = [1860, 1880, 1900, 1920, 1940, 3460, 3480, 3540]
    expected_gt = [index for index in range(0, 4401, 20) if index not in missing_gt]
    require(selected_gt == expected_gt, "GT_INDEX_SUPPORT_DRIFT")
    require(
        [index for index in selected_gt if 4000 <= index <= 4400]
        == list(range(4000, 4401, 20)),
        "SCORE_GT_SUPPORT_DRIFT",
    )
    return {
        "source_camera_count": len(camera_ns),
        "source_imu_count": len(imu_ns),
        "selected_camera_count": len(selected_camera),
        "selected_imu_count": len(selected_imu),
        "selected_gt_count": len(selected_gt),
        "selected_gt_indices": selected_gt,
        "missing_nominal_gt_indices": missing_gt,
        "selected_camera_first_ns": selected_camera[0],
        "selected_camera_last_ns": selected_camera[-1],
        "selected_imu_first_ns": selected_imu[0],
        "selected_imu_last_ns": selected_imu[-1],
        "score_camera_first_ns": camera_ns[4000],
        "score_camera_last_ns": camera_ns[4400],
        "image_csv": {"member": IMAGE_CSV_MEMBER, "size_bytes": len(image_payload), "sha256": hashlib.sha256(image_payload).hexdigest()},
        "imu_csv": {"member": IMU_CSV_MEMBER, "size_bytes": len(imu_payload), "sha256": hashlib.sha256(imu_payload).hexdigest()},
    }


def converter_command(output_bag: Path) -> list[str]:
    return [
        "/usr/bin/python3", str(CONVERTER),
        "--input", str(SOURCE_ARCHIVE),
        "--output-bag", str(output_bag),
        "--sequence-name", "archaeo_sequence_09",
        "--raw-root", "raw_data",
        "--image-dir", IMAGE_DIR,
        "--image-csv", "img_sequence_9.csv",
        "--imu-csv", "imu_sequence_9.csv",
        "--gt-txt", str(GT),
        "--start-index", str(START_INDEX),
        "--end-index", str(END_INDEX),
        "--imu-margin-s", "0.25",
    ]


def preflight() -> dict[str, Any]:
    require(not EXPERIMENT_ROOT.exists() and not EXPERIMENT_ROOT.is_symlink(), "EXPERIMENT_ROOT_ALREADY_EXISTS")
    require(PROTOCOL.is_file() and not PROTOCOL.is_symlink(), "PROTOCOL_NOT_REGULAR")
    inputs = {
        "source_archive": require_identity(SOURCE_ARCHIVE, SOURCE_EXPECTED, "SOURCE_ARCHIVE"),
        "converter": require_identity(CONVERTER, CONVERTER_EXPECTED, "CONVERTER"),
        "groundtruth": require_identity(GT, GT_EXPECTED, "GROUNDTRUTH"),
        "protocol": identity(PROTOCOL),
        "runner": identity(Path(__file__)),
    }
    free_bytes = shutil.disk_usage(EXPERIMENT_ROOT.parent).free
    require(free_bytes >= 8_000_000_000, "INSUFFICIENT_MNT_DATA_FREE_SPACE")
    contract = derive_contract()
    return {
        "status": "READY_RAW_MATERIALIZATION",
        "output_absent": True,
        "free_bytes": free_bytes,
        "inputs": inputs,
        "derived_contract": contract,
        "command": converter_command(EXPERIMENT_ROOT / RAW_RELATIVE),
    }


def audit_bag(path: Path, contract: dict[str, Any]) -> dict[str, Any]:
    ros_path = "/opt/ros/noetic/lib/python3/dist-packages"
    if ros_path not in sys.path:
        sys.path.insert(0, ros_path)
    import rosbag  # type: ignore

    counts = {"camera": 0, "imu": 0, "gt": 0}
    first: dict[str, int] = {}
    last: dict[str, int] = {}
    camera_stamps: list[int] = []
    gt_stamps: list[int] = []
    with rosbag.Bag(str(path), "r") as bag:
        info = bag.get_type_and_topic_info().topics
        require(set(info) == {"/camera/image_raw", "/rtimulib_node/imu", "/aqualoc/colmap_gt"}, "BAG_TOPIC_SET_DRIFT")
        require(info["/camera/image_raw"].msg_type == "sensor_msgs/Image", "CAMERA_TYPE_DRIFT")
        require(info["/rtimulib_node/imu"].msg_type == "sensor_msgs/Imu", "IMU_TYPE_DRIFT")
        require(info["/aqualoc/colmap_gt"].msg_type == "nav_msgs/Odometry", "GT_TYPE_DRIFT")
        for topic, message, record_stamp in bag.read_messages():
            stamp = exact_ns(message.header.stamp)
            require(stamp == exact_ns(record_stamp), f"HEADER_RECORD_STAMP_MISMATCH:{topic}")
            if topic == "/camera/image_raw":
                key = "camera"
                require(message.header.frame_id == "aqualoc_camera", "CAMERA_FRAME_DRIFT")
                require(message.height == 608 and message.width == 968, "CAMERA_SHAPE_DRIFT")
                require(message.encoding == "mono8" and message.step == 968, "CAMERA_ENCODING_DRIFT")
                require(len(message.data) == 608 * 968, "CAMERA_PAYLOAD_SIZE_DRIFT")
                camera_stamps.append(stamp)
            elif topic == "/rtimulib_node/imu":
                key = "imu"
                require(message.header.frame_id == "aqualoc_imu", "IMU_FRAME_DRIFT")
                values = [
                    message.angular_velocity.x, message.angular_velocity.y, message.angular_velocity.z,
                    message.linear_acceleration.x, message.linear_acceleration.y, message.linear_acceleration.z,
                ]
                require(all(math.isfinite(value) for value in values), "IMU_NONFINITE")
            else:
                key = "gt"
                require(message.header.frame_id == "aqualoc_world", "GT_FRAME_DRIFT")
                require(message.child_frame_id == "aqualoc_camera", "GT_CHILD_FRAME_DRIFT")
                gt_stamps.append(stamp)
            counts[key] += 1
            first.setdefault(key, stamp)
            last[key] = stamp
    require(counts["camera"] == contract["selected_camera_count"], "BAG_CAMERA_COUNT_DRIFT")
    require(counts["imu"] == contract["selected_imu_count"], "BAG_IMU_COUNT_DRIFT")
    require(counts["gt"] == contract["selected_gt_count"], "BAG_GT_COUNT_DRIFT")
    require(camera_stamps[0] == contract["selected_camera_first_ns"], "BAG_CAMERA_FIRST_DRIFT")
    require(camera_stamps[-1] == contract["selected_camera_last_ns"], "BAG_CAMERA_LAST_DRIFT")
    require(first["imu"] == contract["selected_imu_first_ns"], "BAG_IMU_FIRST_DRIFT")
    require(last["imu"] == contract["selected_imu_last_ns"], "BAG_IMU_LAST_DRIFT")
    require(
        gt_stamps == [camera_stamps[index] for index in contract["selected_gt_indices"]],
        "BAG_GT_CAMERA_STAMP_MAPPING_DRIFT",
    )
    require(all(b > a for a, b in zip(camera_stamps, camera_stamps[1:])), "BAG_CAMERA_NOT_INCREASING")
    return {
        "status": "PASS",
        "counts": counts,
        "first_stamp_ns": first,
        "last_stamp_ns": last,
        "score_camera_first_ns": camera_stamps[4000],
        "score_camera_last_ns": camera_stamps[4400],
        "gt_header_equals_every_20th_camera_header": True,
        "camera_payload_shape_and_encoding_validated_for_all_messages": True,
    }


def run() -> dict[str, Any]:
    ready = preflight()
    parent = EXPERIMENT_ROOT.parent
    staging = Path(tempfile.mkdtemp(prefix=".a09_samehistory_warmstart_v1.", dir=str(parent)))
    try:
        output_bag = staging / RAW_RELATIVE
        output_bag.parent.mkdir(parents=True, exist_ok=True)
        command = converter_command(output_bag)
        started = datetime.now(timezone.utc)
        process = subprocess.run(
            command, cwd=str(ROOT), text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=3600, check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "TMPDIR": str(staging)},
        )
        ended = datetime.now(timezone.utc)
        require(process.returncode == 0, f"CONVERTER_RC:{process.returncode}")
        require(output_bag.is_file() and not output_bag.is_symlink(), "OUTPUT_BAG_NOT_REGULAR")
        bag_audit = audit_bag(output_bag, ready["derived_contract"])
        bag_identity = identity(output_bag)
        require(bag_identity["size_bytes"] >= 500_000_000, "OUTPUT_BAG_SIZE_IMPLAUSIBLE")
        receipt = {
            "schema_version": "aqua-fe-a09-samehistory-warmstart-raw-materialization-receipt-v1",
            "status": "PASS_RAW_MATERIALIZED_AND_AUDITED",
            "started_at_utc": started.isoformat(timespec="seconds"),
            "ended_at_utc": ended.isoformat(timespec="seconds"),
            "wall_time_seconds": (ended - started).total_seconds(),
            "slams_or_frontends_executed": False,
            "inputs": ready["inputs"],
            "derived_contract": ready["derived_contract"],
            "command": command,
            "raw_return_code": process.returncode,
            "stdout": process.stdout,
            "output_bag": bag_identity,
            "bag_audit": bag_audit,
            "claim_boundary": {
                "raw_materialization_only": True,
                "trajectory_or_accuracy_result_available": False,
                "formal_paper_evidence_permitted": False,
            },
        }
        write_json(staging / RECEIPT_RELATIVE, receipt)
        require(not EXPERIMENT_ROOT.exists() and not EXPERIMENT_ROOT.is_symlink(), "EXPERIMENT_ROOT_APPEARED")
        staging.rename(EXPERIMENT_ROOT)
        return {
            "status": receipt["status"],
            "experiment_root": str(EXPERIMENT_ROOT),
            "output_bag": bag_identity,
            "bag_audit": bag_audit,
        }
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "run"))
    args = parser.parse_args()
    try:
        result = preflight() if args.command == "preflight" else run()
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))
        return 0
    except (MaterializationError, OSError, ValueError, tarfile.TarError, subprocess.TimeoutExpired) as error:
        print(f"MATERIALIZATION_ERROR:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
