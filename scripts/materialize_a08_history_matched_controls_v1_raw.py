#!/usr/bin/env python3
"""Materialize the A08 source-0..4660 ROS bag for history-matched controls."""

from __future__ import annotations

import argparse
import ctypes
import csv
from datetime import datetime, timezone
import errno
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from typing import Any


ROOT = Path("/home/ma/AQUA-FE_WS")
PROTOCOL = ROOT / "papers/a08_hfnet_history_matched_support_extension_v1_protocol.md"
CONVERTER = ROOT / "uw_frontend/datasets/aqualoc_raw_to_rosbag.py"
SOURCE_ARCHIVE = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences/archaeo_sequence_8_raw_data.tar.gz"
)
GT = ROOT / (
    "datasets/full_downloads/aqualoc/Archaeological_site_sequences/"
    "archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_08.txt"
)
EXPERIMENT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1"
)
RAW_DIR = EXPERIMENT_ROOT / "raw"
RAW_BAG = RAW_DIR / "archaeo08_0000_4660.bag"
RECEIPT = RAW_DIR / "raw_materialization_receipt_v1.json"
CLAIM = EXPERIMENT_ROOT / "raw_materialization_process_start_claim_v1.json"
FAILURE_DIR = EXPERIMENT_ROOT / "raw_failed_v1"

IMAGE_CSV_MEMBER = "raw_data/img_sequence_8.csv"
IMU_CSV_MEMBER = "raw_data/imu_sequence_8.csv"
START_INDEX = 0
END_INDEX = 4660
IMU_MARGIN_NS = 250_000_000
START_NS = 1_542_884_961_144_554_192
SUPPORT_START_NS = 1_542_885_161_111_831_216
POSITIVE_START_NS = 1_542_885_186_107_583_632
END_NS = 1_542_885_194_106_222_672

SOURCE_EXPECTED = (
    2_316_571_070,
    "b45e4f6dbf852ff8d7e5c9386e3df2db4daa84d1841f1eafb01a4637d2fe9153",
)
CONVERTER_EXPECTED = (
    8_310,
    "b0c4b7ce7f3e29dcb18cb1604190cc8690cae370fc222246c8dfeb4fc79ffbec",
)
GT_EXPECTED = (
    54_593,
    "519d27750efd7e53c27a2bc3ff35bc9cf5c9fd2b888184eefea284bcfe8f2b6c",
)
IMAGE_CSV_EXPECTED = (
    338_102,
    "1137d5b60e618c5febfb62f6f89f0d261af206e2256d5bfac2bea6f0cbafe689",
)
IMU_CSV_EXPECTED = (
    10_495_986,
    "be4ce25d04d2a50b51474a072a14071f77e450dd78aff51e5ba8378f556c3643",
)
SOURCE_CAMERA_COUNT = 9_391
SOURCE_IMU_COUNT = 93_837


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
    result = identity(path)
    require((result["size_bytes"], result["sha256"]) == expected, f"{label}_IDENTITY_DRIFT")
    return result


def write_json_exclusive(path: Path, value: Any) -> None:
    payload = json.dumps(
        value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
    ) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        os.write(descriptor, payload.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def rename_noreplace(source: Path, destination: Path) -> None:
    """Atomically publish a directory without replacing competing data."""

    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    require(renameat2 is not None, "RENAMEAT2_UNAVAILABLE")
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise MaterializationError(f"DESTINATION_ALREADY_EXISTS_AT_PUBLISH:{destination}")
    raise OSError(error_number, os.strerror(error_number), str(destination))


def publish_directory_noreplace(
    source: Path, destination: Path, receipt_name: str
) -> None:
    """Publish a staged directory with an exclusive claim and receipt last."""

    try:
        rename_noreplace(source, destination)
        return
    except OSError as error:
        unsupported = {errno.EINVAL, errno.ENOSYS, errno.ENOTSUP}
        if hasattr(errno, "EOPNOTSUPP"):
            unsupported.add(errno.EOPNOTSUPP)
        if error.errno not in unsupported:
            raise

    require(source.is_dir() and not source.is_symlink(), "STAGE_NOT_REGULAR_DIRECTORY")
    os.mkdir(destination, 0o755)
    owner = os.lstat(destination)
    published: list[tuple[Path, tuple[int, int]]] = []
    try:
        children = list(source.iterdir())
        require(
            all(stat.S_ISREG(os.lstat(child).st_mode) and not child.is_symlink() for child in children),
            "STAGE_CONTAINS_NONREGULAR_ENTRY",
        )
        require(receipt_name in {child.name for child in children}, "STAGE_RECEIPT_MISSING")
        ordered = sorted(
            children,
            key=lambda child: (child.name == receipt_name, child.name),
        )
        require(ordered[-1].name == receipt_name, "RECEIPT_NOT_LAST")
        for child in ordered:
            target = destination / child.name
            os.link(child, target, follow_symlinks=False)
            metadata = os.lstat(target)
            published.append((target, (metadata.st_dev, metadata.st_ino)))
        descriptor = os.open(destination, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        shutil.rmtree(source)
    except BaseException:
        for target, inode in reversed(published):
            try:
                metadata = os.lstat(target)
                if (metadata.st_dev, metadata.st_ino) == inode:
                    target.unlink()
            except FileNotFoundError:
                pass
        try:
            metadata = os.lstat(destination)
            if (
                (metadata.st_dev, metadata.st_ino) == (owner.st_dev, owner.st_ino)
                and not any(destination.iterdir())
            ):
                destination.rmdir()
        except (FileNotFoundError, OSError):
            pass
        raise


def require_no_symlink_ancestors(path: Path) -> None:
    """Reject symlinks in already-existing publication ancestors."""

    absolute = path.absolute()
    for ancestor in (absolute.parent, *absolute.parent.parents):
        if ancestor.exists() or ancestor.is_symlink():
            require(not ancestor.is_symlink(), f"OUTPUT_ANCESTOR_SYMLINK:{ancestor}")


def exact_ns(stamp: Any) -> int:
    require(type(stamp.secs) is int and type(stamp.nsecs) is int, "ROS_STAMP_NOT_INTEGER")
    require(stamp.secs >= 0 and 0 <= stamp.nsecs < 1_000_000_000, "ROS_STAMP_RANGE")
    return stamp.secs * 1_000_000_000 + stamp.nsecs


def archive_payload(archive: tarfile.TarFile, member: str) -> bytes:
    extracted = archive.extractfile(member)
    require(extracted is not None, f"ARCHIVE_MEMBER_MISSING:{member}")
    return extracted.read()


def csv_rows(payload: bytes) -> list[list[str]]:
    return [
        row for row in csv.reader(io.StringIO(payload.decode("utf-8")))
        if row and not row[0].startswith("#")
    ]


def gt_indices() -> list[int]:
    result: list[int] = []
    for line_number, raw in enumerate(GT.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        fields = raw.split()
        require(len(fields) >= 8, f"GT_COLUMN_COUNT:{line_number}")
        value = float(fields[0])
        index = int(round(value))
        require(abs(value - index) <= 1e-9, f"GT_NONINTEGER_INDEX:{line_number}")
        result.append(index)
    require(all(right > left for left, right in zip(result, result[1:])), "GT_INDEX_ORDER")
    return result


def derive_contract() -> dict[str, Any]:
    with tarfile.open(SOURCE_ARCHIVE, "r:*") as archive:
        image_payload = archive_payload(archive, IMAGE_CSV_MEMBER)
        imu_payload = archive_payload(archive, IMU_CSV_MEMBER)
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
    require(all(right > left for left, right in zip(camera_ns, camera_ns[1:])), "CAMERA_TIME_ORDER")
    require(all(right > left for left, right in zip(imu_ns, imu_ns[1:])), "IMU_TIME_ORDER")
    require(camera_ns[0] == START_NS, "CAMERA_START_DRIFT")
    require(camera_ns[4000] == SUPPORT_START_NS, "SUPPORT_START_DRIFT")
    require(camera_ns[4500] == POSITIVE_START_NS, "POSITIVE_START_DRIFT")
    require(camera_ns[4660] == END_NS, "CAMERA_END_DRIFT")
    selected_camera = camera_ns[START_INDEX : END_INDEX + 1]
    selected_imu = [
        stamp for stamp in imu_ns
        if selected_camera[0] - IMU_MARGIN_NS <= stamp <= selected_camera[-1] + IMU_MARGIN_NS
    ]
    require(len(selected_camera) == 4661, "SELECTED_CAMERA_COUNT")
    require(len(selected_imu) > 46_000, "SELECTED_IMU_COUNT_IMPLAUSIBLE")
    require(selected_imu[0] <= selected_camera[0], "IMU_NO_START_MARGIN")
    require(selected_imu[-1] >= selected_camera[-1], "IMU_NO_END_MARGIN")
    selected_gt = [index for index in gt_indices() if START_INDEX <= index <= END_INDEX]
    support_gt = [index for index in selected_gt if 4000 <= index <= 4660]
    expected_support_gt = [
        index for index in range(4000, 4661, 20) if index not in (4400, 4640)
    ]
    require(support_gt == expected_support_gt, "SUPPORT_GT_INDEX_DRIFT")
    return {
        "source_camera_count": len(camera_ns),
        "source_imu_count": len(imu_ns),
        "selected_camera_count": len(selected_camera),
        "selected_imu_count": len(selected_imu),
        "selected_gt_count": len(selected_gt),
        "selected_camera_timestamps_ns": selected_camera,
        "selected_imu_timestamps_ns": selected_imu,
        "selected_gt_indices": selected_gt,
        "support_gt_indices": support_gt,
        "selected_camera_first_ns": selected_camera[0],
        "selected_camera_last_ns": selected_camera[-1],
        "selected_imu_first_ns": selected_imu[0],
        "selected_imu_last_ns": selected_imu[-1],
        "image_csv": {
            "member": IMAGE_CSV_MEMBER,
            "size_bytes": len(image_payload),
            "sha256": hashlib.sha256(image_payload).hexdigest(),
        },
        "imu_csv": {
            "member": IMU_CSV_MEMBER,
            "size_bytes": len(imu_payload),
            "sha256": hashlib.sha256(imu_payload).hexdigest(),
        },
    }


def converter_command(output_bag: Path) -> list[str]:
    return [
        "/usr/bin/python3", str(CONVERTER),
        "--input", str(SOURCE_ARCHIVE),
        "--output-bag", str(output_bag),
        "--sequence-name", "archaeo_sequence_08",
        "--raw-root", "raw_data",
        "--image-dir", "images_sequence_8",
        "--image-csv", "img_sequence_8.csv",
        "--imu-csv", "imu_sequence_8.csv",
        "--gt-txt", str(GT),
        "--start-index", str(START_INDEX),
        "--end-index", str(END_INDEX),
        "--imu-margin-s", "0.25",
    ]


def preflight() -> dict[str, Any]:
    require_no_symlink_ancestors(RAW_DIR)
    require_no_symlink_ancestors(FAILURE_DIR)
    require_no_symlink_ancestors(CLAIM)
    require(not RAW_DIR.exists() and not RAW_DIR.is_symlink(), "RAW_DIR_ALREADY_EXISTS")
    require(not FAILURE_DIR.exists() and not FAILURE_DIR.is_symlink(), "FAILURE_DIR_ALREADY_EXISTS")
    require(not CLAIM.exists() and not CLAIM.is_symlink(), "PROCESS_START_CLAIM_ALREADY_EXISTS")
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
    public_contract = {
        key: value for key, value in contract.items()
        if key not in ("selected_camera_timestamps_ns", "selected_imu_timestamps_ns")
    }
    return {
        "status": "READY_A08_RAW_MATERIALIZATION",
        "inputs": inputs,
        "free_bytes": free_bytes,
        "derived_contract": contract,
        "public_contract": public_contract,
        "command_template": converter_command(RAW_BAG),
        "slams_or_frontends_executed": False,
    }


def audit_bag(path: Path, contract: dict[str, Any]) -> dict[str, Any]:
    ros_path = "/opt/ros/noetic/lib/python3/dist-packages"
    if ros_path not in sys.path:
        sys.path.insert(0, ros_path)
    import rosbag  # type: ignore

    counts = {"camera": 0, "imu": 0, "gt": 0}
    camera_stamps: list[int] = []
    imu_stamps: list[int] = []
    gt_stamps: list[int] = []
    with rosbag.Bag(str(path), "r") as bag:
        topics = bag.get_type_and_topic_info().topics
        require(set(topics) == {"/camera/image_raw", "/rtimulib_node/imu", "/aqualoc/colmap_gt"}, "TOPIC_SET")
        require(topics["/camera/image_raw"].msg_type == "sensor_msgs/Image", "CAMERA_TYPE")
        require(topics["/rtimulib_node/imu"].msg_type == "sensor_msgs/Imu", "IMU_TYPE")
        require(topics["/aqualoc/colmap_gt"].msg_type == "nav_msgs/Odometry", "GT_TYPE")
        for topic, message, record_stamp in bag.read_messages():
            stamp = exact_ns(message.header.stamp)
            require(stamp == exact_ns(record_stamp), f"HEADER_RECORD_MISMATCH:{topic}")
            if topic == "/camera/image_raw":
                counts["camera"] += 1
                camera_stamps.append(stamp)
                require(message.header.frame_id == "aqualoc_camera", "CAMERA_FRAME")
                require(message.height == 608 and message.width == 968, "CAMERA_SHAPE")
                require(message.encoding == "mono8" and message.step == 968, "CAMERA_ENCODING")
                require(len(message.data) == 608 * 968, "CAMERA_PAYLOAD")
            elif topic == "/rtimulib_node/imu":
                counts["imu"] += 1
                imu_stamps.append(stamp)
                require(message.header.frame_id == "aqualoc_imu", "IMU_FRAME")
                values = (
                    message.angular_velocity.x, message.angular_velocity.y,
                    message.angular_velocity.z, message.linear_acceleration.x,
                    message.linear_acceleration.y, message.linear_acceleration.z,
                )
                require(all(math.isfinite(value) for value in values), "IMU_NONFINITE")
            else:
                counts["gt"] += 1
                gt_stamps.append(stamp)
                require(message.header.frame_id == "aqualoc_world", "GT_FRAME")
                require(message.child_frame_id == "aqualoc_camera", "GT_CHILD_FRAME")
    require(camera_stamps == contract["selected_camera_timestamps_ns"], "CAMERA_TIMELINE_DRIFT")
    require(imu_stamps == contract["selected_imu_timestamps_ns"], "IMU_TIMELINE_DRIFT")
    expected_gt_stamps = [camera_stamps[index] for index in contract["selected_gt_indices"]]
    require(gt_stamps == expected_gt_stamps, "GT_TIMELINE_DRIFT")
    return {
        "status": "PASS_COMPLETE_BAG_AUDIT",
        "counts": counts,
        "camera_timestamps_exact": True,
        "imu_timestamps_exact": True,
        "gt_bound_to_source_camera_timestamps": True,
        "camera_payload_schema_checked_for_all_messages": True,
        "support_source_indices_inclusive": [4000, 4660],
        "positive_subwindow_source_indices_inclusive": [4500, 4660],
    }


def run() -> dict[str, Any]:
    ready = preflight()
    EXPERIMENT_ROOT.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".a08_raw_v1.", dir=str(EXPERIMENT_ROOT)))
    stage_bag = stage / RAW_BAG.name
    command = converter_command(stage_bag)
    claim = {
        "schema_version": "aqua-fe-a08-history-matched-controls-raw-process-start-claim-v1",
        "status": "PROCESS_START_CLAIM_CONSUMES_SINGLE_MATERIALIZATION_ATTEMPT",
        "claimed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": ready["inputs"],
        "derived_contract": ready["public_contract"],
        "command": command,
        "automatic_retry_permitted": False,
        "slams_or_frontends_executed": False,
    }
    write_json_exclusive(CLAIM, claim)
    started = datetime.now(timezone.utc)
    try:
        process = subprocess.run(
            command,
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=7200,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "TMPDIR": str(stage)},
        )
        conversion_ended = datetime.now(timezone.utc)
        (stage / "converter.stdout.log").write_text(process.stdout, encoding="utf-8")
        require(process.returncode == 0, f"CONVERTER_RC:{process.returncode}")
        require(stage_bag.is_file() and not stage_bag.is_symlink(), "OUTPUT_BAG_NOT_REGULAR")
        bag_audit = audit_bag(stage_bag, ready["derived_contract"])
        audit_ended = datetime.now(timezone.utc)
        bag_identity = identity(stage_bag)
        require(bag_identity["size_bytes"] >= 900_000_000, "OUTPUT_BAG_SIZE_IMPLAUSIBLE")
        public_bag_identity = {**bag_identity, "path": str(RAW_BAG)}
        receipt = {
            "schema_version": "aqua-fe-a08-history-matched-controls-raw-materialization-receipt-v1",
            "status": "PASS_RAW_MATERIALIZED_AND_AUDITED",
            "started_at_utc": started.isoformat(timespec="seconds"),
            "conversion_ended_at_utc": conversion_ended.isoformat(timespec="seconds"),
            "ended_at_utc": audit_ended.isoformat(timespec="seconds"),
            "conversion_wall_time_seconds": (conversion_ended - started).total_seconds(),
            "conversion_and_audit_wall_time_seconds": (
                audit_ended - started
            ).total_seconds(),
            "inputs": ready["inputs"],
            "derived_contract": ready["public_contract"],
            "command": command,
            "raw_return_code": process.returncode,
            "output_bag": public_bag_identity,
            "bag_audit": bag_audit,
            "process_start_claim": identity(CLAIM),
            "claim_boundary": {
                "raw_materialization_only": True,
                "frontends_or_slams_executed": False,
                "ape_or_rpe_computed": False,
                "runtime_claim_permitted": False,
            },
        }
        (stage / RECEIPT.name).write_text(
            json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        publish_directory_noreplace(stage, RAW_DIR, RECEIPT.name)
        return {
            "status": receipt["status"],
            "raw_bag": public_bag_identity,
            "bag_audit": bag_audit,
            "receipt": str(RECEIPT),
        }
    except Exception:
        if stage.exists():
            try:
                rename_noreplace(stage, FAILURE_DIR)
            except Exception:
                # Preserve the original failure; never replace a competing
                # owner merely to publish this invocation's diagnostics.
                pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "run"))
    args = parser.parse_args()
    try:
        result = preflight() if args.command == "preflight" else run()
        if args.command == "preflight":
            result = {
                **result,
                "derived_contract": result["public_contract"],
            }
            result.pop("public_contract", None)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))
        return 0
    except (MaterializationError, OSError, ValueError, tarfile.TarError, subprocess.TimeoutExpired) as error:
        print(f"MATERIALIZATION_ERROR:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
