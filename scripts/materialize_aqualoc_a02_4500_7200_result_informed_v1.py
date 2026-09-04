#!/usr/bin/env python3
"""Materialize the frozen A02 4500..7200 result-informed source window.

``preflight`` is read-only.  ``export`` invokes the already frozen canonical
raw converter once, audits the complete result, and publishes the bag and its
manifest as a no-clobber hard-link pair with identity-aware rollback.  This
producer never starts a SLAM implementation and contains no retry path.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Iterable, Mapping, Sequence

from scripts import a02_hfnet_result_informed_extension_v1 as profile


ROOT = profile.ROOT
SCHEMA_VERSION = "aqua-fe-aqualoc-canonical-raw-window-result-informed-extension-v1"
STATUS = "PASS_RESULT_INFORMED_SOURCE_WINDOW_ONLY_NO_SLAM_STARTED"
ATTEMPT_SCHEMA = "aqua-fe-aqualoc-canonical-raw-window-result-informed-attempt-v1"
ATTEMPT_STATUS = "SOURCE_WINDOW_EXPORT_ATTEMPT_CLAIMED_NO_RETRY"

CAMERA_TOPIC = "/camera/image_raw"
IMU_TOPIC = "/rtimulib_node/imu"
GT_TOPIC = "/aqualoc/colmap_gt"
EXPECTED_TOPIC_COUNTS = {
    CAMERA_TOPIC: profile.FEED_COUNT,
    IMU_TOPIC: profile.CANONICAL_MARGIN_IMU_COUNT,
    GT_TOPIC: 136,
}
EXPECTED_TOPIC_TYPES = {
    CAMERA_TOPIC: "sensor_msgs/Image",
    IMU_TOPIC: "sensor_msgs/Imu",
    GT_TOPIC: "nav_msgs/Odometry",
}
EXPECTED_CAMERA_NS = {
    0: profile.CAMERA_FIRST_NS,
    profile.PRIOR_PREFIX_COUNT - 1: profile.CAMERA_PRIOR_LAST_NS,
    profile.FEED_COUNT - 1: profile.CAMERA_LAST_NS,
}


class ContractError(RuntimeError):
    pass


def converter_command(output: Path, *, python: str | None = None) -> list[str]:
    return [
        python or sys.executable,
        "-m",
        "uw_frontend.datasets.aqualoc_raw_to_rosbag",
        "--input",
        str(profile.RAW_TAR),
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
        str(profile.GT_PATH),
        "--start-index",
        str(profile.FEED_FIRST),
        "--end-index",
        str(profile.FEED_LAST),
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


def _stamp_ns(stamp: object) -> int:
    return int(getattr(stamp, "secs")) * 1_000_000_000 + int(getattr(stamp, "nsecs"))


def _finite(values: Iterable[float]) -> bool:
    return all(math.isfinite(float(value)) for value in values)


def audit_bag(path: Path) -> dict[str, object]:
    try:
        import rosbag
    except ImportError as error:
        raise ContractError("ROSBAG_IMPORT_FAILED") from error

    counts = {topic: 0 for topic in EXPECTED_TOPIC_COUNTS}
    first_ns: dict[str, int] = {}
    last_ns: dict[str, int] = {}
    previous_ns: dict[str, int] = {}
    camera_stamps: list[int] = []
    gt_stamps: list[int] = []
    with rosbag.Bag(str(path), "r") as bag:
        topic_info = bag.get_type_and_topic_info().topics
        observed_topics = set(topic_info)
        if observed_topics != set(EXPECTED_TOPIC_COUNTS):
            raise ContractError(f"TOPIC_SET_MISMATCH:{sorted(observed_topics)}")
        for topic, expected_type in EXPECTED_TOPIC_TYPES.items():
            if getattr(topic_info[topic], "msg_type", None) != expected_type:
                raise ContractError(f"TOPIC_TYPE_MISMATCH:{topic}")
        for topic, message, record_stamp in bag.read_messages():
            if topic not in counts:
                raise ContractError(f"UNEXPECTED_TOPIC:{topic}")
            if getattr(message, "_type", None) != EXPECTED_TOPIC_TYPES[topic]:
                raise ContractError(f"MESSAGE_TYPE_MISMATCH:{topic}")
            if not hasattr(message, "header"):
                raise ContractError(f"HEADER_MISSING:{topic}")
            header_ns = _stamp_ns(message.header.stamp)
            record_ns = _stamp_ns(record_stamp)
            if header_ns != record_ns:
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
                if message.header.frame_id != "aqualoc_imu" or not _finite(
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
                if (
                    message.header.frame_id != "aqualoc_world"
                    or message.child_frame_id != "aqualoc_camera"
                    or not _finite(
                        (
                            pose.position.x,
                            pose.position.y,
                            pose.position.z,
                            pose.orientation.x,
                            pose.orientation.y,
                            pose.orientation.z,
                            pose.orientation.w,
                        )
                    )
                ):
                    raise ContractError("GT_PAYLOAD_CONTRACT_MISMATCH")
                gt_stamps.append(header_ns)

    if counts != EXPECTED_TOPIC_COUNTS:
        raise ContractError(f"TOPIC_COUNT_MISMATCH:{counts}")
    for relative, expected in EXPECTED_CAMERA_NS.items():
        if camera_stamps[relative] != expected:
            raise ContractError(f"CAMERA_ENDPOINT_MISMATCH:{relative}")
    if (
        first_ns[IMU_TOPIC] != profile.CANONICAL_MARGIN_IMU_FIRST_NS
        or last_ns[IMU_TOPIC] != profile.CANONICAL_MARGIN_IMU_LAST_NS
    ):
        raise ContractError("IMU_ENDPOINT_MISMATCH")
    if gt_stamps != camera_stamps[0::20]:
        raise ContractError("GT_SCHEDULE_MISMATCH")
    return {
        "topic_counts": counts,
        "topic_first_header_ns": first_ns,
        "topic_last_header_ns": last_ns,
        "camera_prior_terminal_header_ns": camera_stamps[profile.PRIOR_PREFIX_COUNT - 1],
        "record_stamp_equals_header": True,
        "strictly_increasing_by_topic": True,
        "gt_matches_camera_every_20_global_frames": True,
    }


def build_manifest(
    artifact: Path,
    published_output: Path,
    command: Sequence[str],
    audit: Mapping[str, object],
    identities: Mapping[str, Mapping[str, object]],
    attempt_identity: Mapping[str, object],
) -> dict[str, object]:
    output = profile.identity(artifact, label="PARTIAL_WINDOW_BAG")
    output["path"] = str(published_output.resolve(strict=False))
    output["compression"] = "bz2"
    output.update(audit)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "scientific_role": profile.ROLE,
        "provenance": {
            "raw_tar": identities["raw_tar"],
            "gt": identities["ground_truth"],
            "converter": identities["converter"],
            "prior_hfnet_unusable_result": identities["prior_hfnet_unusable_result"],
            "attempt": dict(attempt_identity),
            "argv": list(command),
        },
        "selection": {
            "camera_global_start_index": profile.FEED_FIRST,
            "camera_global_end_index_inclusive": profile.FEED_LAST,
            "image_count_expected": profile.FEED_COUNT,
            "same_prefix_global_indices_inclusive": [profile.FEED_FIRST, profile.PRIOR_FEED_LAST],
            "new_global_indices_inclusive": [profile.PRIOR_FEED_LAST + 1, profile.FEED_LAST],
            "new_image_count": profile.NEW_CAMERA_COUNT,
            "score_global_indices_inclusive": [profile.SCORE_FIRST, profile.SCORE_LAST],
            "score_reference_count": profile.SCORE_REFERENCE_COUNT,
            "score_evaluation_grid_count": profile.SCORE_EVALUATION_GRID_COUNT,
            "imu_margin_ns": 250_000_000,
            "imu_rule_closed_interval": "[camera[4500]-250ms,camera[7200]+250ms]",
            "downstream_hfnet_inner_imu": {
                "count": profile.HFNET_INNER_IMU_COUNT,
                "global_indices_inclusive": [
                    profile.HFNET_INNER_IMU_GLOBAL_FIRST,
                    profile.HFNET_INNER_IMU_GLOBAL_LAST,
                ],
                "raw_header_endpoints_ns": [
                    profile.HFNET_INNER_IMU_FIRST_RAW_NS,
                    profile.HFNET_INNER_IMU_LAST_RAW_NS,
                ],
                "time_shift_ns": profile.IMU_SHIFT_NS,
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
            "gt_pose": "world_T_camera",
            "atlas_resume": False,
            "retry": False,
        },
        "output": output,
        "checks": {
            "canonical_inputs_exact": True,
            "converter_exact": True,
            "camera_count_and_endpoints_exact": True,
            "imu_count_and_endpoints_exact": True,
            "gt_count_and_schedule_exact": True,
            "record_header_stamps_exact": True,
            "payload_contract_exact": True,
            "no_slam_started": True,
        },
    }


def build_attempt_record(
    command: Sequence[str], identities: Mapping[str, Mapping[str, object]]
) -> dict[str, object]:
    return {
        "schema_version": ATTEMPT_SCHEMA,
        "status": ATTEMPT_STATUS,
        "scientific_role": profile.ROLE,
        "action": "source_window_export_once",
        "no_retry": True,
        "slam_started": False,
        "argv": list(command),
        "targets": {
            "bag": str(profile.NEW_WINDOW_BAG.resolve(strict=False)),
            "manifest": str(profile.NEW_WINDOW_MANIFEST.resolve(strict=False)),
        },
        "source_identities": {key: dict(value) for key, value in identities.items()},
    }


def _write_exclusive(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def publish_pair_no_clobber(
    partial_bag: Path,
    partial_manifest: Path,
    output_bag: Path,
    output_manifest: Path,
    *,
    link=os.link,
) -> None:
    for source, label in ((partial_bag, "PARTIAL_BAG"), (partial_manifest, "PARTIAL_MANIFEST")):
        if source.is_symlink() or not source.is_file():
            raise ContractError(f"{label}_MISSING_OR_NOT_REGULAR")
    if any(path.exists() or path.is_symlink() for path in (output_bag, output_manifest)):
        raise ContractError("RESERVED_OUTPUT_APPEARED_DURING_EXPORT")
    def same_inode(left: Path, right: Path) -> bool:
        try:
            left_stat, right_stat = left.stat(), right.stat()
        except OSError:
            return False
        return not right.is_symlink() and (left_stat.st_dev, left_stat.st_ino) == (right_stat.st_dev, right_stat.st_ino)

    bag_published = False
    manifest_published = False
    try:
        link(partial_bag, output_bag)
        bag_published = True
        link(partial_manifest, output_manifest)
        manifest_published = True
        if not same_inode(partial_bag, output_bag) or not same_inode(partial_manifest, output_manifest):
            raise ContractError("PUBLISHED_PAIR_IS_NOT_EXACT_HARD_LINK_IDENTITY")
    except BaseException:
        if manifest_published and same_inode(partial_manifest, output_manifest):
            output_manifest.unlink(missing_ok=True)
        if bag_published and same_inode(partial_bag, output_bag):
            output_bag.unlink(missing_ok=True)
        raise
    partial_bag.unlink()
    partial_manifest.unlink()


def _source_identities() -> Mapping[str, Mapping[str, object]]:
    rows = profile.expected_static_source_identities()
    return {
        "raw_tar": rows["raw_tar"],
        "ground_truth": rows["ground_truth"],
        "converter": rows["converter"],
        "prior_hfnet_unusable_result": rows["prior_hfnet_unusable_result"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    try:
        profile.audit_sealed_invocation_environment()
    except profile.ExtensionError as error:
        print(f"CONTRACT_BLOCKED:{error}", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("preflight", "export"), required=True)
    parser.add_argument("--output-bag", type=Path, default=profile.NEW_WINDOW_BAG)
    parser.add_argument("--manifest-json", type=Path, default=profile.NEW_WINDOW_MANIFEST)
    args = parser.parse_args(argv)
    try:
        output, manifest, attempt = args.output_bag, args.manifest_json, profile.NEW_WINDOW_ATTEMPT
        if output != profile.NEW_WINDOW_BAG or manifest != profile.NEW_WINDOW_MANIFEST:
            raise ContractError("FROZEN_OUTPUT_PATH_OVERRIDE_FORBIDDEN")
        if any(path.exists() or path.is_symlink() for path in (output, manifest, attempt)):
            raise ContractError("RESERVED_OUTPUT_OR_ATTEMPT_ALREADY_EXISTS")
        identities = _source_identities()
        partial = output.with_name(f".{output.name}.partial.{os.getpid()}")
        partial_manifest = manifest.with_name(f".{manifest.name}.partial.{os.getpid()}")
        command = converter_command(partial)
        if args.action == "preflight":
            print(json.dumps({"status": "PREFLIGHT_PASS_READ_ONLY", "scientific_role": profile.ROLE, "output": str(output), "manifest": str(manifest), "attempt": str(attempt), "argv": command}, sort_keys=True))
            return 0

        output.parent.mkdir(parents=True, exist_ok=True)
        if any(path.exists() or path.is_symlink() for path in (partial, partial_manifest)):
            raise ContractError("PARTIAL_OUTPUT_ALREADY_EXISTS")
        _write_exclusive(attempt, profile.canonical_json_bytes(build_attempt_record(command, identities)))
        attempt_identity = profile.identity(attempt, label="SOURCE_WINDOW_EXPORT_ATTEMPT")
        try:
            completed = subprocess.run(command, cwd=ROOT, check=False)
            if completed.returncode != 0:
                raise ContractError(f"CANONICAL_CONVERTER_RC:{completed.returncode}")
            audit = audit_bag(partial)
            manifest_value = build_manifest(partial, output, command, audit, identities, attempt_identity)
            _write_exclusive(partial_manifest, profile.canonical_json_bytes(manifest_value))
            publish_pair_no_clobber(partial, partial_manifest, output, manifest)
        finally:
            if partial.exists() and not partial.is_symlink():
                partial.unlink()
            if partial_manifest.exists() and not partial_manifest.is_symlink():
                partial_manifest.unlink()
        print(json.dumps({"status": STATUS, "bag": str(output), "manifest": str(manifest), "attempt": str(attempt)}, sort_keys=True))
        return 0
    except (ContractError, profile.ExtensionError, OSError) as error:
        print(f"CONTRACT_BLOCKED:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
