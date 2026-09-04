#!/usr/bin/env python3
"""Materialize and seal the canonical A02 camera-index 4500..6300 ROS bag.

This is a high-level, no-clobber wrapper around the existing canonical
``uw_frontend.datasets.aqualoc_raw_to_rosbag`` converter.  It changes no
sensor value or timestamp.  A candidate bag is written under a unique partial
name, audited against the frozen A02 contract, and only then published with an
adjacent provenance manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "aqua-fe-aqualoc-canonical-raw-window-bag-manifest-v1"
STATUS = "PASS"

RAW_TAR = ROOT / (
    "datasets/full_downloads/aqualoc/Archaeological_site_sequences/"
    "archaeo_sequence_2_raw_data.tar.gz"
)
GT_PATH = ROOT / (
    "datasets/full_downloads/aqualoc/Archaeological_site_sequences/"
    "archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_02.txt"
)
CONVERTER = ROOT / "uw_frontend/datasets/aqualoc_raw_to_rosbag.py"
DEFAULT_OUTPUT = ROOT / "datasets/aqualoc/rosbags/archaeo02_4500_6300.bag"

RAW_TAR_SIZE = 2_195_786_266
RAW_TAR_SHA256 = "8f6203e0b46068a9d237f03e469acecb5f51eedbd6b7c1dc7c1f980ea6ea6d69"
GT_SIZE = 64_318
GT_SHA256 = "1122b753372545966026df10f1899e751cdaa3359a6938be251cd8e22b6e4379"
CONVERTER_SHA256 = "b0c4b7ce7f3e29dcb18cb1604190cc8690cae370fc222246c8dfeb4fc79ffbec"

CAMERA_TOPIC = "/camera/image_raw"
IMU_TOPIC = "/rtimulib_node/imu"
GT_TOPIC = "/aqualoc/colmap_gt"
# The canonical compact bag retains the converter's full +/-0.25 s IMU
# margin.  The shared HFNet adapter later selects a strictly smaller 17,987
# sample subsequence; those two counts must never be conflated.
EXPECTED_TOPIC_COUNTS = {CAMERA_TOPIC: 1_801, IMU_TOPIC: 18_084, GT_TOPIC: 91}
EXPECTED_CAMERA_NS = {
    0: 1_542_829_016_700_435_392,
    900: 1_542_829_061_692_686_528,
    1800: 1_542_829_106_687_510_592,
}
EXPECTED_IMU_FIRST_NS = 1_542_829_016_456_083_680
EXPECTED_IMU_LAST_NS = 1_542_829_106_933_121_504
HFNET_INNER_IMU_COUNT = 17_987
HFNET_INNER_IMU_GLOBAL_INDICES = [44_954, 62_940]
HFNET_INNER_IMU_ENDPOINTS_NS = [
    1_542_829_016_645_312_000,
    1_542_829_106_638_112_448,
]


class ContractError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path, size: int, digest: str, label: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"{label}_MISSING_OR_NOT_REGULAR")
    observed_size = path.stat().st_size
    observed_digest = sha256_file(path)
    if observed_size != size or observed_digest != digest:
        raise ContractError(f"{label}_IDENTITY_MISMATCH")
    return {"path": str(path.resolve()), "size_bytes": observed_size, "sha256": observed_digest}


def converter_command(output: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "uw_frontend.datasets.aqualoc_raw_to_rosbag",
        "--input",
        str(RAW_TAR),
        "--output-bag",
        str(output),
        "--sequence-name",
        "archaeo_sequence_2",
        "--raw-root",
        "raw_data",
        "--image-dir",
        "images_sequence_2",
        "--image-csv",
        "img_sequence_2.csv",
        "--imu-csv",
        "imu_sequence_2.csv",
        "--gt-txt",
        str(GT_PATH),
        "--start-index",
        "4500",
        "--end-index",
        "6300",
        "--image-topic",
        CAMERA_TOPIC,
        "--imu-topic",
        IMU_TOPIC,
        "--gt-topic",
        GT_TOPIC,
        "--camera-frame-id",
        "aqualoc_camera",
        "--imu-frame-id",
        "aqualoc_imu",
        "--gt-frame-id",
        "aqualoc_world",
        "--imu-margin-s",
        "0.25",
    ]


def stamp_ns(stamp: object) -> int:
    return int(getattr(stamp, "secs")) * 1_000_000_000 + int(getattr(stamp, "nsecs"))


def finite(values: Iterable[float]) -> bool:
    return all(math.isfinite(float(value)) for value in values)


def audit_bag(path: Path) -> dict[str, object]:
    import rosbag

    counts = {topic: 0 for topic in EXPECTED_TOPIC_COUNTS}
    first_ns: dict[str, int] = {}
    last_ns: dict[str, int] = {}
    previous_ns: dict[str, int] = {}
    camera_stamps: list[int] = []
    gt_stamps: list[int] = []

    with rosbag.Bag(str(path), "r") as bag:
        info = bag.get_type_and_topic_info().topics
        observed_topics = set(info)
        if observed_topics != set(EXPECTED_TOPIC_COUNTS):
            raise ContractError(f"TOPIC_SET_MISMATCH:{sorted(observed_topics)}")
        for topic, message, record_stamp in bag.read_messages():
            if topic not in counts:
                raise ContractError(f"UNEXPECTED_TOPIC:{topic}")
            header = getattr(message, "header", None)
            if header is None:
                raise ContractError(f"HEADER_MISSING:{topic}")
            header_ns = stamp_ns(header.stamp)
            record_ns = stamp_ns(record_stamp)
            if record_ns != header_ns:
                raise ContractError(f"RECORD_HEADER_STAMP_MISMATCH:{topic}")
            if topic in previous_ns and header_ns <= previous_ns[topic]:
                raise ContractError(f"NON_MONOTONIC_TOPIC:{topic}")
            previous_ns[topic] = header_ns
            first_ns.setdefault(topic, header_ns)
            last_ns[topic] = header_ns
            counts[topic] += 1

            if topic == CAMERA_TOPIC:
                if (
                    int(message.width) != 968
                    or int(message.height) != 608
                    or message.encoding != "mono8"
                    or int(message.step) != 968
                    or len(message.data) != 968 * 608
                    or message.header.frame_id != "aqualoc_camera"
                ):
                    raise ContractError("CAMERA_PAYLOAD_CONTRACT_MISMATCH")
                camera_stamps.append(header_ns)
            elif topic == IMU_TOPIC:
                if message.header.frame_id != "aqualoc_imu" or not finite(
                    (
                        message.angular_velocity.x,
                        message.angular_velocity.y,
                        message.angular_velocity.z,
                        message.linear_acceleration.x,
                        message.linear_acceleration.y,
                        message.linear_acceleration.z,
                    )
                ):
                    raise ContractError("IMU_PAYLOAD_CONTRACT_MISMATCH")
            else:
                pose = message.pose.pose
                if message.header.frame_id != "aqualoc_world" or message.child_frame_id != "aqualoc_camera":
                    raise ContractError("GT_FRAME_CONTRACT_MISMATCH")
                if not finite(
                    (
                        pose.position.x,
                        pose.position.y,
                        pose.position.z,
                        pose.orientation.x,
                        pose.orientation.y,
                        pose.orientation.z,
                        pose.orientation.w,
                    )
                ):
                    raise ContractError("GT_NONFINITE")
                gt_stamps.append(header_ns)

    if counts != EXPECTED_TOPIC_COUNTS:
        raise ContractError(f"TOPIC_COUNT_MISMATCH:{counts}")
    for relative_index, expected in EXPECTED_CAMERA_NS.items():
        if camera_stamps[relative_index] != expected:
            raise ContractError(f"CAMERA_ENDPOINT_MISMATCH:{relative_index}")
    if first_ns[IMU_TOPIC] != EXPECTED_IMU_FIRST_NS or last_ns[IMU_TOPIC] != EXPECTED_IMU_LAST_NS:
        raise ContractError("IMU_ENDPOINT_MISMATCH")
    expected_gt_stamps = camera_stamps[0::20]
    if gt_stamps != expected_gt_stamps:
        raise ContractError("GT_SCHEDULE_MISMATCH")

    return {
        "topic_counts": counts,
        "topic_first_header_ns": first_ns,
        "topic_last_header_ns": last_ns,
        "camera_boundary_header_ns": camera_stamps[900],
        "record_stamp_equals_header": True,
        "strictly_increasing_by_topic": True,
        "gt_matches_camera_every_20_global_frames": True,
    }


def build_manifest(
    artifact: Path,
    published_output: Path,
    command: list[str],
    audit: Mapping[str, object],
    identities: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    reserved_output_keys = {"path", "size_bytes", "sha256", "compression"}
    overlap = reserved_output_keys.intersection(audit)
    if overlap:
        raise ContractError(f"AUDIT_OUTPUT_KEY_COLLISION:{sorted(overlap)}")
    output_record: dict[str, object] = {
        "path": str(published_output.resolve()),
        "size_bytes": artifact.stat().st_size,
        "sha256": sha256_file(artifact),
        "compression": "bz2",
    }
    output_record.update(audit)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "provenance": {
            "raw_tar": identities["raw_tar"],
            "gt": identities["gt"],
            "converter": identities["converter"],
            "argv": command,
        },
        "selection": {
            "camera_global_start_index": 4500,
            "camera_global_end_index_inclusive": 6300,
            "image_count_expected": 1801,
            "preroll_global_indices_inclusive": [4500, 5399],
            "score_global_indices_inclusive": [5400, 6300],
            "imu_margin_ns": 250_000_000,
            "imu_rule_closed_interval": "[camera[4500]-250ms,camera[6300]+250ms]",
            "downstream_hfnet_inner_imu": {
                "count": HFNET_INNER_IMU_COUNT,
                "global_indices_inclusive": HFNET_INNER_IMU_GLOBAL_INDICES,
                "raw_header_endpoints_ns": HFNET_INNER_IMU_ENDPOINTS_NS,
                "role": "strict downstream subsequence; not the canonical raw-window bag count",
            },
        },
        "semantics": {
            "header_stamp": "raw_csv_integer_ns",
            "record_stamp_equals_header": True,
            "no_time_shift": True,
            "no_resampling": True,
            "image_encoding": "mono8",
            "image_pixels": "lossless_decode_of_canonical_raw_archive_frame",
            "imu_preserved_fields": ["angular_velocity", "linear_acceleration"],
            "imu_fields_absent_from_raw_csv": "ROS_message_defaults",
            "gt_pose": "world_T_camera",
        },
        "output": output_record,
        "checks": {
            "canonical_inputs_exact": True,
            "converter_exact": True,
            "camera_count_exact": True,
            "imu_count_exact": True,
            "gt_count_and_schedule_exact": True,
            "camera_endpoints_exact": True,
            "imu_endpoints_exact": True,
            "record_header_stamps_exact": True,
            "payload_contract_exact": True,
        },
    }


def write_exclusive(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def publish_pair_no_clobber(
    partial_bag: Path,
    partial_manifest: Path,
    output_bag: Path,
    output_manifest: Path,
    *,
    link=os.link,
) -> None:
    """Publish a bag/manifest pair, rolling back the bag if link two fails."""

    for source, label in ((partial_bag, "PARTIAL_BAG"), (partial_manifest, "PARTIAL_MANIFEST")):
        if source.is_symlink() or not source.is_file():
            raise ContractError(f"{label}_MISSING_OR_NOT_REGULAR")
    if (
        output_bag.exists()
        or output_bag.is_symlink()
        or output_manifest.exists()
        or output_manifest.is_symlink()
    ):
        raise ContractError("RESERVED_OUTPUT_APPEARED_DURING_EXPORT")

    linked_bag = False
    try:
        link(partial_bag, output_bag)
        linked_bag = True
        link(partial_manifest, output_manifest)
    except BaseException:
        if linked_bag:
            try:
                output_bag.unlink()
            except FileNotFoundError:
                pass
        raise
    partial_bag.unlink()
    partial_manifest.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("preflight", "export"), required=True)
    parser.add_argument("--output-bag", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--manifest-json")
    args = parser.parse_args()

    output = Path(args.output_bag)
    manifest = Path(args.manifest_json) if args.manifest_json else Path(str(output) + ".manifest.json")
    if output.exists() or output.is_symlink() or manifest.exists() or manifest.is_symlink():
        raise ContractError("RESERVED_OUTPUT_ALREADY_EXISTS")
    output.parent.mkdir(parents=True, exist_ok=True)

    identities = {
        "raw_tar": identity(RAW_TAR, RAW_TAR_SIZE, RAW_TAR_SHA256, "RAW_TAR"),
        "gt": identity(GT_PATH, GT_SIZE, GT_SHA256, "GT"),
        "converter": identity(CONVERTER, CONVERTER.stat().st_size, CONVERTER_SHA256, "CONVERTER"),
    }
    partial = output.with_name(f".{output.name}.partial.{os.getpid()}")
    partial_manifest = manifest.with_name(f".{manifest.name}.partial.{os.getpid()}")
    command = converter_command(partial)
    if args.action == "preflight":
        print(json.dumps({"status": "PREFLIGHT_PASS", "output": str(output), "manifest": str(manifest), "argv": command}, sort_keys=True))
        return 0

    if partial.exists() or partial.is_symlink() or partial_manifest.exists() or partial_manifest.is_symlink():
        raise ContractError("PARTIAL_OUTPUT_ALREADY_EXISTS")
    try:
        subprocess.run(command, cwd=ROOT, check=True)
        audit = audit_bag(partial)
        payload = build_manifest(partial, output, command, audit, identities)
        write_exclusive(
            partial_manifest,
            (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"),
        )
        publish_pair_no_clobber(partial, partial_manifest, output, manifest)
    finally:
        if partial.exists() and not partial.is_symlink():
            partial.unlink()
        if partial_manifest.exists() and not partial_manifest.is_symlink():
            partial_manifest.unlink()
    print(f"bag={output}")
    print(f"manifest={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
