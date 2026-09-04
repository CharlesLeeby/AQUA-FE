#!/usr/bin/env python3
"""Build the outcome-blind plan for the 20 frozen P07 B0 play inputs.

The plan does not run a converter and does not authorize VINS.  It binds each
B0 window to either a canonical raw bag, an already materialized immutable
window bag, or an exact AQUALOC archive-to-window reconstruction recipe.  A
future explicit executor produces the runtime ``b0_play_inputs`` contract.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import io
import json
import os
import re
import shutil
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from scripts import build_p07_backend_replay_queue_v1 as queue_builder
    from scripts import p07_backend_replay_common_v1 as common
    from scripts import validate_p07_backend_replay_queue_v1 as queue_validator
except ModuleNotFoundError:  # Direct execution.
    import build_p07_backend_replay_queue_v1 as queue_builder  # type: ignore
    import p07_backend_replay_common_v1 as common  # type: ignore
    import validate_p07_backend_replay_queue_v1 as queue_validator  # type: ignore


ROOT = queue_builder.ROOT
P07 = queue_builder.P07
OUTPUT = P07 / "backend_b0_materialization_lock_v1.json"
INTENT = P07 / "backend_b0_materialization_intent_v1.json"
FINAL_OUTPUT = P07 / "backend_b0_play_inputs_v1.json"
RECEIPT = P07 / "backend_b0_materialization_receipt_v1.json"
SCHEMA = "isj-p07-backend-b0-materialization-lock-v1"
STATUS = "FROZEN_READY_FOR_EXPLICIT_B0_MATERIALIZATION"
SELF_HASH = "materialization_lock_hash"
OUTCOME_BOUNDARY = "B0_INPUT_PREPARATION_ONLY_NO_VINS_APE_RPE_TRAJECTORY"
CAPACITY_RESERVE_BYTES = 2 * 1024**3
CAMERA_TOPICS = {
    "aqualoc_archaeology": "/camera/image_raw",
    "aqualoc_harbor": "/camera/image_raw",
    "ntnu": "/alphasense_driver_ros/cam0",
    "afrl": "/camera/image_raw",
}
RECEIPT_DIRECTORY = P07 / "raw_cache_reclamation"
Q55_LOCK = ROOT / queue_builder.frontend_provenance.Q55_LOCK
Q55_CLOSEOUT = ROOT / queue_builder.frontend_provenance.Q55_CLOSEOUT
Q55_MATERIALIZATION = (
    P07
    / "frontend_attempts"
    / "queue_055_isj_p07_aqualoc_archaeology_a04_0002_p_attempt02"
    / "raw_materialization_v1.json"
)
_SHA = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_LIVE_ARTIFACT_PATHS = {
    queue_builder.BACKEND_QUEUE.relative_to(ROOT).as_posix(),
    queue_builder.BACKEND_ALLOCATION.relative_to(ROOT).as_posix(),
    queue_builder.BACKEND_QUEUE_LOCK.relative_to(ROOT).as_posix(),
    queue_builder.ARM_ORDER.relative_to(ROOT).as_posix(),
    queue_builder.MANIFEST.relative_to(ROOT).as_posix(),
    "papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv",
    "papers/ieee_sensors_journal_experiments/dataset_checksum_manifest.txt",
    "scripts/build_p07_backend_b0_materialization_lock_v1.py",
    "scripts/run_p07_backend_b0_materialization_v1.py",
    "scripts/tests/test_p07_backend_b0_materialization_v1.py",
    "scripts/p07_backend_replay_common_v1.py",
    "scripts/p07_g0_publisher_v1.py",
    "scripts/p07_backend_formal_io_v1.py",
    "uw_frontend/datasets/aqualoc_raw_to_rosbag.py",
}


class B0MaterializationError(RuntimeError):
    """The B0 materialization plan is incomplete, drifted, or unsafe."""


def document_hash(payload: Mapping[str, object], field: str) -> str:
    clone = dict(payload)
    clone.pop(field, None)
    return queue_builder.sha256_bytes(
        queue_builder.canonical_json(clone).encode("utf-8")
    )


def _record(path: Path, *, root: Path = ROOT) -> dict[str, object]:
    try:
        _content, record = queue_builder.rooted_io.read_bytes_and_record_bound_input_rooted(
            root, path, label="B0 governed artifact"
        )
        return dict(record)
    except (
        FileNotFoundError,
        ValueError,
        queue_builder.formal_io.FormalIOError,
        queue_builder.rooted_io.gov.G0GovernanceError,
    ) as error:
        raise B0MaterializationError(f"missing/out-of-root B0 artifact: {path}") from error


def _snapshot(
    path: Path, *, root: Path = ROOT, label: str
) -> tuple[bytes, dict[str, object]]:
    try:
        content, record = queue_builder.rooted_io.read_bytes_and_record_bound_input_rooted(
            root, path, label=label
        )
    except (OSError, queue_builder.rooted_io.gov.G0GovernanceError) as error:
        raise B0MaterializationError(f"cannot read {label}: {path}") from error
    return content, dict(record)


def _json_snapshot(
    path: Path, *, root: Path = ROOT, label: str = "B0 JSON evidence"
) -> tuple[dict[str, Any], dict[str, object]]:
    content, record = _snapshot(path, root=root, label=label)
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise B0MaterializationError(f"invalid B0 JSON evidence: {path}") from error
    if not isinstance(payload, dict):
        raise B0MaterializationError(f"B0 JSON evidence is not an object: {path}")
    return payload, record


def _json(path: Path, *, root: Path = ROOT) -> dict[str, Any]:
    payload, _record_value = _json_snapshot(path, root=root)
    return payload


def _checksum_manifest_snapshot(
    path: Path, *, root: Path = ROOT
) -> tuple[dict[str, str], dict[str, object]]:
    content, record = _snapshot(path, root=root, label="dataset checksum manifest")
    result: dict[str, str] = {}
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise B0MaterializationError("invalid dataset checksum manifest encoding") from error
    for line in lines:
        if not line.strip():
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2 or not _SHA.fullmatch(parts[0]) or parts[1] in result:
            raise B0MaterializationError("invalid dataset checksum manifest")
        result[parts[1]] = parts[0]
    return result, record


def _checksum_manifest(path: Path, *, root: Path = ROOT) -> dict[str, str]:
    result, _record_value = _checksum_manifest_snapshot(path, root=root)
    return result


def _hash_manifest_entry(
    *, root: Path, record: Mapping[str, object], expected_path: str
) -> str:
    """Return one exact output-manifest hash without interpreting bag contents."""

    relative = str(record.get("path", ""))
    manifest = root / relative
    content, observed = _snapshot(
        manifest, root=root, label="AFRL output hash manifest"
    )
    if any(
        observed.get(key) != record.get(key)
        for key in ("path", "sha256", "size_bytes")
    ):
        raise B0MaterializationError("AFRL output-manifest record drift")
    matches: list[str] = []
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise B0MaterializationError("invalid AFRL output hash manifest") from error
    for line in lines:
        parts = line.split("  ", 1)
        if len(parts) != 2 or not _SHA.fullmatch(parts[0]) or not parts[1]:
            raise B0MaterializationError("invalid AFRL output hash manifest")
        if parts[1] == expected_path:
            matches.append(parts[0])
    if len(matches) != 1:
        raise B0MaterializationError("AFRL short bag lacks one exact manifest entry")
    return matches[0]


def _bag_input_contract_bytes(content: bytes, camera_topic: str) -> dict[str, object]:
    """Read ROS bag metadata and camera stamps only; never trajectory values."""

    try:
        import rosbag  # type: ignore
    except ModuleNotFoundError as error:
        raise B0MaterializationError("rosbag is unavailable for B0 input freeze") from error
    required_os = ("memfd_create", "MFD_ALLOW_SEALING")
    required_fcntl = (
        "F_ADD_SEALS",
        "F_GET_SEALS",
        "F_SEAL_SEAL",
        "F_SEAL_SHRINK",
        "F_SEAL_GROW",
        "F_SEAL_WRITE",
    )
    if any(not hasattr(os, name) for name in required_os) or any(
        not hasattr(fcntl, name) for name in required_fcntl
    ):
        raise B0MaterializationError("platform lacks sealed B0 bag snapshot support")
    descriptor = os.memfd_create("p07-b0-bag", os.MFD_ALLOW_SEALING)
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise B0MaterializationError("short write to sealed B0 bag snapshot")
            view = view[written:]
        os.fsync(descriptor)
        seals = (
            fcntl.F_SEAL_SHRINK
            | fcntl.F_SEAL_GROW
            | fcntl.F_SEAL_WRITE
            | fcntl.F_SEAL_SEAL
        )
        fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, seals)
        if fcntl.fcntl(descriptor, fcntl.F_GET_SEALS) != seals:
            raise B0MaterializationError("B0 bag snapshot seals differ")
        os.lseek(descriptor, 0, os.SEEK_SET)
        bag_path = f"/proc/self/fd/{descriptor}"
        counts: dict[str, int]
        first: int | None = None
        last: int | None = None
        previous = -1
        with rosbag.Bag(bag_path, "r") as bag:
            counts = {
                str(topic): int(info.message_count)
                for topic, info in bag.get_type_and_topic_info().topics.items()
            }
            for _topic, message, _record_stamp in bag.read_messages(topics=[camera_topic]):
                stamp = getattr(getattr(message, "header", None), "stamp", None)
                if stamp is None or not hasattr(stamp, "to_nsec"):
                    raise B0MaterializationError("AFRL source camera lacks header stamp")
                stamp_ns = int(stamp.to_nsec())
                if stamp_ns <= previous:
                    raise B0MaterializationError("AFRL source camera stamps are not increasing")
                first = stamp_ns if first is None else first
                last = stamp_ns
                previous = stamp_ns
    finally:
        os.close(descriptor)
    if first is None or last is None or last <= first:
        raise B0MaterializationError("AFRL source camera window is incomplete")
    try:
        common.validate_absolute_ros_epoch_window(
            first, last, label="AFRL B0 source camera window"
        )
    except common.BackendReplayViolation as error:
        raise B0MaterializationError(
            "AFRL source camera stamps are not absolute epoch ns"
        ) from error
    return {
        "topic_counts": dict(sorted(counts.items())),
        "camera_stamp_range_ns": {"first": first, "last": last},
        "camera_stamp_source": "sensor_msgs/Image.header.stamp",
        "trajectory_values_interpreted": False,
    }


def _eligibility_rows_snapshot(
    path: Path, *, root: Path = ROOT
) -> tuple[dict[tuple[str, str], dict[str, str]], dict[str, object]]:
    content, record = _snapshot(path, root=root, label="data eligibility manifest")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise B0MaterializationError("invalid data eligibility encoding") from error
    rows = list(csv.DictReader(io.StringIO(text, newline="")))
    result = {(row["dataset_family"], row["sequence"]): row for row in rows}
    if len(result) != len(rows):
        raise B0MaterializationError("duplicate data-eligibility identity")
    return result, record


def _eligibility_rows(path: Path, *, root: Path = ROOT) -> dict[tuple[str, str], dict[str, str]]:
    result, _record_value = _eligibility_rows_snapshot(path, root=root)
    return result


def _read_backend_inputs(
    *, root: Path = ROOT
) -> tuple[
    list[dict[str, str]],
    dict[str, Any],
    dict[str, dict[str, object]],
]:
    queue_path = root / queue_builder.BACKEND_QUEUE.relative_to(ROOT)
    allocation_path = root / queue_builder.BACKEND_ALLOCATION.relative_to(ROOT)
    lock_path = root / queue_builder.BACKEND_QUEUE_LOCK.relative_to(ROOT)
    queue_content, queue_record = _snapshot(
        queue_path, root=root, label="backend replay queue"
    )
    allocation_content, allocation_record = _snapshot(
        allocation_path, root=root, label="backend allocation"
    )
    lock, lock_record = _json_snapshot(
        lock_path, root=root, label="backend queue lock"
    )
    arm_order_path = root / queue_builder.ARM_ORDER.relative_to(ROOT)
    arm_order_content, arm_order_record = _snapshot(
        arm_order_path, root=root, label="backend arm order"
    )
    queue_fields, rows = queue_validator.parse_csv(queue_content)
    allocation_fields, allocations = queue_validator.parse_csv(allocation_content)
    _arm_fields, arm_order_rows = queue_builder._parse_csv_content(
        arm_order_path, arm_order_content
    )
    if queue_fields != queue_builder.QUEUE_FIELDS or allocation_fields != queue_builder.ALLOCATION_FIELDS:
        raise B0MaterializationError("backend queue/allocation header drift")
    issues = queue_validator.validate_artifacts(
        queue_content=queue_content,
        allocation_content=allocation_content,
        lock_payload=lock,
        arm_order_rows=arm_order_rows,
        root=root,
    )
    if issues:
        raise B0MaterializationError(f"backend queue is not a frozen PASS: {issues}")
    return rows, lock, {
        "backend_queue": queue_record,
        "backend_allocation": allocation_record,
        "backend_queue_lock": lock_record,
        "arm_order": arm_order_record,
    }


def _source_by_window(lock: Mapping[str, Any], arm: str) -> dict[str, Mapping[str, Any]]:
    result = {
        str(item["window_id"]): item
        for item in lock.get("source_evidence", [])
        if isinstance(item, dict) and item.get("arm") == arm
    }
    if len(result) != 20:
        raise B0MaterializationError(f"backend queue lock lacks 20 {arm} sources")
    return result


def _receipt_by_window(root: Path) -> dict[str, tuple[dict[str, Any], dict[str, object]]]:
    directory = root / RECEIPT_DIRECTORY.relative_to(ROOT)
    result: dict[str, tuple[dict[str, Any], dict[str, object]]] = {}
    probe = (RECEIPT_DIRECTORY / ".receipt-probe").relative_to(ROOT).as_posix()
    try:
        with queue_builder.formal_io._parent_dirfd(root, probe) as (parent_fd, _name):
            names = sorted(
                name
                for name in os.listdir(parent_fd)
                if re.fullmatch(r"receipt-[A-Za-z0-9._-]+\.json", name)
            )
    except queue_builder.formal_io.FormalIOError as error:
        raise B0MaterializationError("raw-cache receipt directory is unsafe") from error
    for name in names:
        path = directory / name
        payload, receipt_record = _json_snapshot(
            path, root=root, label="raw-cache reclamation receipt"
        )
        window_id = str(payload.get("window_id", ""))
        if not window_id:
            continue
        if window_id in result:
            raise B0MaterializationError(f"duplicate raw-cache receipt: {window_id}")
        if (
            payload.get("schema_version") != "isj-p07-raw-cache-reclamation-v1"
            or payload.get("status") != "AUTHORIZED_BEFORE_UNLINK"
            or payload.get("held_out_trajectory_outcome_read") is not False
            or not _SHA.fullmatch(str(payload.get("raw_cache_sha256", "")))
            or not _SHA.fullmatch(str(payload.get("source_archive_sha256", "")))
        ):
            raise B0MaterializationError(f"invalid raw-cache receipt: {path}")
        result[window_id] = (payload, receipt_record)
    return result


def _aqualoc_expected_topics(
    window: Mapping[str, str], b1_source: Mapping[str, Any], *, root: Path
) -> dict[str, int]:
    audit_path = root / str(b1_source["input_audit_path"])
    audit, audit_record = _json_snapshot(
        audit_path, root=root, label="B1 frontend audit"
    )
    expected_audit_hash = b1_source.get("input_audit_sha256")
    if expected_audit_hash and expected_audit_hash != audit_record["sha256"]:
        raise B0MaterializationError(
            f"B1 audit hash drift: {window['window_id']}"
        )
    feature = audit.get("feature_bag")
    counts = feature.get("topic_counts") if isinstance(feature, dict) else None
    if not isinstance(counts, dict):
        raise B0MaterializationError(f"B1 audit lacks topic counts: {window['window_id']}")
    result = {CAMERA_TOPICS[str(window["dataset_family"])]: int(window["input_frame_count"]) + 1}
    for topic in ("/rtimulib_node/imu", "/aqualoc/colmap_gt"):
        if topic not in counts:
            raise B0MaterializationError(f"B1 audit lacks {topic}: {window['window_id']}")
        result[topic] = int(counts[topic])
    return result


def _bound_file_snapshot_or_absent(
    root: Path, relative: str, *, label: str
) -> tuple[bytes, dict[str, object]] | None:
    path = root / relative
    try:
        state = queue_builder.rooted_io.path_state_bound_input_rooted(
            root, path, label=label
        )
    except queue_builder.rooted_io.gov.G0GovernanceError as error:
        raise B0MaterializationError(f"unsafe {label}: {relative}") from error
    if state == "ABSENT":
        return None
    if state != "FILE":
        raise B0MaterializationError(f"{label} is not a direct file: {relative}")
    return _snapshot(path, root=root, label=label)


def _bound_file_record_or_absent(
    root: Path, relative: str, *, label: str
) -> dict[str, object] | None:
    path = root / relative
    try:
        state = queue_builder.rooted_io.path_state_bound_input_rooted(
            root, path, label=label
        )
        if state == "ABSENT":
            return None
        if state != "FILE":
            raise B0MaterializationError(f"{label} is not a direct file: {relative}")
        return dict(
            queue_builder.rooted_io.direct_file_record_bound_input_rooted(
                root, path, label=label
            )
        )
    except queue_builder.rooted_io.gov.G0GovernanceError as error:
        raise B0MaterializationError(f"unsafe {label}: {relative}") from error


def _capture_source_identity(
    *,
    root: Path,
    relative: str,
    expected_sha256: str,
    expected_record: Mapping[str, object],
) -> dict[str, Any]:
    try:
        identity = common.capture_canonical_input_identity(
            root,
            relative,
            expected_sha256=expected_sha256,
            verify_sha256=True,
        )
    except common.BackendReplayViolation as error:
        raise B0MaterializationError(
            f"B0 source path/link/target drift: {relative}"
        ) from error
    final_record = _record(root / relative, root=root)
    if any(
        final_record.get(key) != expected_record.get(key)
        for key in ("path", "sha256", "size_bytes")
    ):
        raise B0MaterializationError(
            f"B0 source changed across identity capture: {relative}"
        )
    return identity


def _aqualoc_recipe(
    window: Mapping[str, str],
    b1_source: Mapping[str, Any],
    eligibility: Mapping[str, str],
    checksums: Mapping[str, str],
    receipts: Mapping[str, tuple[dict[str, Any], dict[str, object]]],
    *,
    root: Path,
) -> dict[str, object]:
    family = str(window["dataset_family"])
    sequence = str(window["sequence"])
    number = int(sequence[1:])
    pad = f"{number:02d}"
    start = round(float(window["window_start_s"]) * 20.0)
    end = round(float(window["window_end_s"]) * 20.0)
    prefix = "archaeo" if family == "aqualoc_archaeology" else "harbor"
    target = f"datasets/aqualoc/rosbags/{prefix}{pad}_{start}_{end}.bag"
    receipt_item = receipts.get(str(window["window_id"]))
    if receipt_item is not None:
        receipt, receipt_record = receipt_item
        if receipt.get("raw_cache_path") != target:
            raise B0MaterializationError(f"raw-cache target mismatch: {window['window_id']}")
        expected_sha = str(receipt["raw_cache_sha256"])
        expected_size = int(receipt["raw_cache_size_bytes"])
        source_path = str(receipt["source_archive_path"])
        source_sha = str(receipt["source_archive_sha256"])
        disposition = "REBUILD_REQUIRED_OR_EXACT_RECONCILE"
        evidence = [receipt_record]
    else:
        target_record = _bound_file_record_or_absent(
            root, target, label="AQUALOC retained B0 target"
        )
        if target_record is None:
            raise B0MaterializationError(
                f"AQUALOC target has neither receipt nor retained file: {target}"
            )
        expected_sha = str(target_record["sha256"])
        expected_size = int(target_record["size_bytes"])
        source_path = str(eligibility["raw_input_path"])
        source_sha = str(checksums.get(source_path, ""))
        disposition = "PREMATERIALIZED_EXACT_REUSE"
        evidence = []
    if checksums.get(source_path) != source_sha:
        raise B0MaterializationError(f"AQUALOC archive checksum mismatch: {source_path}")
    source_record = _bound_file_record_or_absent(
        root, source_path, label="AQUALOC source archive"
    )
    if source_record is None:
        raise B0MaterializationError(f"AQUALOC archive missing/hash drift: {source_path}")
    if source_record["sha256"] != source_sha:
        raise B0MaterializationError(f"AQUALOC archive missing/hash drift: {source_path}")
    source_identity = _capture_source_identity(
        root=root,
        relative=source_path,
        expected_sha256=source_sha,
        expected_record=source_record,
    )
    gt = str(eligibility["reference_path"])
    raw_root = "." if sequence == "A04" else ""
    if family == "aqualoc_archaeology" and sequence != "A04":
        raw_root = "raw_data"
    if family == "aqualoc_archaeology":
        argv = [
            "python3", "-m", "uw_frontend.datasets.aqualoc_raw_to_rosbag",
            "--input", source_path, "--output-bag", "{OUTPUT}",
            "--sequence-name", f"archaeo_sequence_{number}",
            "--raw-root", raw_root,
            "--image-dir", f"images_sequence_{number}",
            "--image-csv", f"img_sequence_{number}.csv",
            "--imu-csv", f"imu_sequence_{number}.csv",
            "--gt-txt", gt,
        ]
    else:
        argv = [
            "python3", "-m", "uw_frontend.datasets.aqualoc_raw_to_rosbag",
            "--input", source_path, "--output-bag", "{OUTPUT}",
            "--sequence-name", f"harbor_sequence_{pad}",
            "--image-dir", f"harbor_images_sequence_{pad}",
            "--image-csv", f"harbor_img_sequence_{pad}.csv",
            "--imu-csv", f"harbor_imu_sequence_{pad}.csv",
            "--gt-txt", gt,
        ]
    argv.extend([
        "--start-index", str(start), "--end-index", str(end),
        "--image-topic", "/camera/image_raw",
        "--imu-topic", "/rtimulib_node/imu",
        "--gt-topic", "/aqualoc/colmap_gt",
    ])
    recipe: dict[str, object] = {
        "window_id": window["window_id"],
        "dataset_family": family,
        "sequence": sequence,
        "runner_start": str(start),
        "runner_end_or_duration": str(end),
        "runner_unit": "frame",
        "target_path": target,
        "expected_sha256": expected_sha,
        "expected_size_bytes": expected_size,
        "expected_topic_counts": _aqualoc_expected_topics(window, b1_source, root=root),
        "camera_topic": "/camera/image_raw",
        "disposition": disposition,
        "derivation_kind": "PREMATERIALIZED_WINDOW_BAG",
        "source_raw_path": source_path,
        "source_raw_sha256": source_sha,
        "source_path_identity": source_identity,
        "converter_argv_template": argv,
        "evidence": evidence,
        "held_out_trajectory_outcome_read": False,
    }
    if str(window["window_id"]) == "aqualoc_archaeology:A04:0002":
        q55_materialization, q55_materialization_record = _json_snapshot(
            root / Q55_MATERIALIZATION.relative_to(ROOT),
            root=root,
            label="q55 raw materialization evidence",
        )
        q55_counts = q55_materialization.get("expected_topic_counts")
        if (
            raw_root != "."
            or q55_materialization.get("raw_bag", {}).get("sha256") != expected_sha
            or q55_counts != recipe["expected_topic_counts"]
        ):
            raise B0MaterializationError("A04 q55 archive-root/topic/hash contract drift")
        recipe["a04_layout_recovery"] = {
            "execution_raw_root_argument": ".",
            "q55_frozen_raw_root_argument": "",
            "semantic_equivalence": (
                "BOUND_CONVERTER_MEMBER_PATH_IGNORES_EMPTY_AND_DOT_COMPONENTS"
            ),
            "expected_topic_counts": q55_counts,
            "q55_recovery_lock": _record(root / Q55_LOCK.relative_to(ROOT), root=root),
            "q55_recovery_closeout": _record(root / Q55_CLOSEOUT.relative_to(ROOT), root=root),
            "raw_materialization": q55_materialization_record,
        }
    recipe["recipe_hash"] = document_hash(recipe, "recipe_hash")
    return recipe


def _direct_recipe(
    window: Mapping[str, str],
    eligibility: Mapping[str, str],
    checksums: Mapping[str, str],
    *,
    root: Path,
) -> dict[str, object]:
    family = str(window["dataset_family"])
    raw = str(eligibility["raw_input_path"])
    expected = str(checksums.get(raw, ""))
    raw_record = _bound_file_record_or_absent(
        root, raw, label="direct B0 raw input"
    )
    if not _SHA.fullmatch(expected) or raw_record is None:
        raise B0MaterializationError(f"direct B0 raw input unavailable: {raw}")
    if (
        raw_record["size_bytes"] != int(eligibility["raw_size_bytes"])
        or raw_record["sha256"] != expected
    ):
        raise B0MaterializationError(f"direct B0 raw input unavailable: {raw}")
    recipe: dict[str, object] = {
        "window_id": window["window_id"],
        "dataset_family": family,
        "sequence": window["sequence"],
        "runner_start": queue_builder.number(window["window_start_s"]),
        "runner_end_or_duration": queue_builder.number(
            float(window["window_end_s"]) - float(window["window_start_s"])
        ),
        "runner_unit": "second",
        "target_path": raw,
        "expected_sha256": expected,
        "expected_size_bytes": int(eligibility["raw_size_bytes"]),
        "expected_topic_counts": None,
        "camera_topic": CAMERA_TOPICS[family],
        "disposition": "DIRECT_RAW_WINDOW_PLAYBACK",
        "derivation_kind": "DIRECT_RAW_WINDOW_PLAYBACK",
        "source_raw_path": raw,
        "source_raw_sha256": expected,
        "source_path_identity": _capture_source_identity(
            root=root,
            relative=raw,
            expected_sha256=expected,
            expected_record=raw_record,
        ),
        "converter_argv_template": None,
        "evidence": [],
        "held_out_trajectory_outcome_read": False,
    }
    recipe["recipe_hash"] = document_hash(recipe, "recipe_hash")
    return recipe


def build_plan_payload(
    *,
    frozen_at: str,
    queue_rows: Sequence[Mapping[str, str]],
    queue_lock: Mapping[str, Any],
    manifest_rows: Sequence[Mapping[str, str]],
    eligibility_rows: Mapping[tuple[str, str], Mapping[str, str]],
    checksums: Mapping[str, str],
    receipts: Mapping[str, tuple[dict[str, Any], dict[str, object]]],
    root: Path = ROOT,
    include_code_records: bool = True,
    base_artifacts: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    queue_builder.allocation_stamp(frozen_at)
    windows = {str(row["window_id"]): dict(row) for row in manifest_rows}
    if len(windows) != 20:
        raise B0MaterializationError("B0 plan requires exactly 20 manifest windows")
    b0_sources = _source_by_window(queue_lock, queue_builder.B0)
    b1_sources = _source_by_window(queue_lock, queue_builder.B1)
    b0_rows = [dict(row) for row in queue_rows if row["arm"] == queue_builder.B0]
    if len(b0_rows) != 60:
        raise B0MaterializationError("B0 plan requires exactly 60 B0 replay rows")
    recipes: list[dict[str, object]] = []
    for window_id, window in sorted(windows.items()):
        key = (window["dataset_family"], window["sequence"])
        eligibility = eligibility_rows.get(key)
        if eligibility is None:
            raise B0MaterializationError(f"missing B0 data eligibility: {key}")
        if window["dataset_family"].startswith("aqualoc_"):
            recipe = _aqualoc_recipe(
                window, b1_sources[window_id], eligibility, checksums, receipts, root=root
            )
        elif window["dataset_family"] == "ntnu":
            recipe = _direct_recipe(window, eligibility, checksums, root=root)
        elif window["dataset_family"] == "afrl":
            # Copy the corrected, hash-bound short bag into a dedicated B0 cache;
            # backend replay must never consume a frontend attempt directory.
            audit_path = root / str(b1_sources[window_id]["input_audit_path"])
            audit, observed_audit = _json_snapshot(
                audit_path, root=root, label="AFRL B1 audit"
            )
            expected_audit = b1_sources[window_id].get("input_audit_sha256")
            if expected_audit and expected_audit != observed_audit["sha256"]:
                raise B0MaterializationError("AFRL B1 audit hash drift")
            manifests = audit.get("afrl_replay_manifest")
            if not isinstance(manifests, list) or len(manifests) != 1:
                raise B0MaterializationError("AFRL audit lacks one replay manifest")
            source_path = (
                "logs/afrl_cave_v31/external_klt_every2_"
                "isj_p07_afrl_bus_outside_0001_b1_attempt01/cave_gennie_short.bag"
            )
            target = "datasets/p07_backend_b0_inputs/afrl/bus_outside_0001.bag"
            provenance = b1_sources[window_id].get("source_provenance")
            if not isinstance(provenance, dict):
                raise B0MaterializationError("AFRL source provenance is absent")
            output_record = provenance.get("output_hash_manifest")
            audit_record = provenance.get("audit")
            if not isinstance(output_record, dict) or not isinstance(audit_record, dict):
                raise B0MaterializationError("AFRL source manifest/audit record is absent")
            expected = _hash_manifest_entry(
                root=root, record=output_record, expected_path=source_path
            )
            source_snapshot = _bound_file_snapshot_or_absent(
                root, source_path, label="AFRL frozen short bag"
            )
            if source_snapshot is None:
                raise B0MaterializationError("AFRL short bag hash/manifest drift")
            source_content, source_record = source_snapshot
            if source_record["sha256"] != expected:
                raise B0MaterializationError("AFRL short bag hash/manifest drift")
            source_contract = _bag_input_contract_bytes(
                source_content, "/camera/image_raw"
            )
            source_identity = _capture_source_identity(
                root=root,
                relative=source_path,
                expected_sha256=expected,
                expected_record=source_record,
            )
            recipe = {
                "window_id": window["window_id"],
                "dataset_family": "afrl",
                "sequence": window["sequence"],
                "runner_start": queue_builder.number(window["window_start_s"]),
                "runner_end_or_duration": queue_builder.number(
                    float(window["window_end_s"]) - float(window["window_start_s"])
                ),
                "runner_unit": "second",
                "target_path": target,
                "expected_sha256": expected,
                "expected_size_bytes": source_record["size_bytes"],
                "expected_topic_counts": source_contract["topic_counts"],
                "expected_camera_stamp_range_ns": source_contract[
                    "camera_stamp_range_ns"
                ],
                "camera_topic": "/camera/image_raw",
                "disposition": "EXACT_COPY_REQUIRED_OR_RECONCILE",
                "derivation_kind": "PREMATERIALIZED_WINDOW_BAG",
                "source_raw_path": source_path,
                "source_raw_sha256": expected,
                "source_path_identity": source_identity,
                "converter_argv_template": [
                    "INTERNAL_EXACT_COPY_NOREPLACE",
                    source_path,
                    "{OUTPUT}",
                ],
                "source_input_contract": source_contract,
                "evidence": [
                    dict(audit_record),
                    dict(output_record),
                    dict(manifests[0]),
                ],
                "held_out_trajectory_outcome_read": False,
            }
            recipe["recipe_hash"] = document_hash(recipe, "recipe_hash")
        else:
            raise B0MaterializationError(f"unsupported B0 dataset family: {key[0]}")
        recipe["source_provenance_hash"] = b0_sources[window_id][
            "source_provenance_hash"
        ]
        recipe["recipe_hash"] = document_hash(recipe, "recipe_hash")
        recipes.append(recipe)
    bindings = [
        {
            "queue_index": int(row["queue_index"]),
            "run_id": row["run_id"],
            "window_id": row["window_id"],
            "arm": row["arm"],
            "dataset_family": row["dataset_family"],
            "sequence": row["sequence"],
            "runner_start": row["runner_start"],
            "runner_end_or_duration": row["runner_end_or_duration"],
            "runner_unit": row["runner_unit"],
            "source_run_id": row["source_run_id"],
            "source_provenance_kind": row["source_provenance_kind"],
            "source_provenance_hash": row["source_provenance_hash"],
        }
        for row in b0_rows
    ]
    missing_bytes = 0
    for item in recipes:
        if item["disposition"] not in {
            "REBUILD_REQUIRED_OR_EXACT_RECONCILE",
            "EXACT_COPY_REQUIRED_OR_RECONCILE",
        }:
            continue
        if _bound_file_record_or_absent(
            root,
            str(item["target_path"]),
            label="B0 materialization target capacity probe",
        ) is None:
            missing_bytes += int(item["expected_size_bytes"])
    artifacts = (
        [dict(item) for item in base_artifacts]
        if base_artifacts is not None
        else [
            _record(root / queue_builder.BACKEND_QUEUE.relative_to(ROOT), root=root),
            _record(root / queue_builder.BACKEND_QUEUE_LOCK.relative_to(ROOT), root=root),
            _record(root / queue_builder.MANIFEST.relative_to(ROOT), root=root),
        ]
    )
    if include_code_records:
        for relative in (
            "scripts/build_p07_backend_b0_materialization_lock_v1.py",
            "scripts/run_p07_backend_b0_materialization_v1.py",
            "scripts/tests/test_p07_backend_b0_materialization_v1.py",
            "scripts/p07_backend_replay_common_v1.py",
            "scripts/p07_g0_publisher_v1.py",
            "scripts/p07_backend_formal_io_v1.py",
            "uw_frontend/datasets/aqualoc_raw_to_rosbag.py",
        ):
            artifacts.append(_record(root / relative, root=root))
    payload: dict[str, object] = {
        "schema_version": SCHEMA,
        "status": STATUS,
        "frozen_at": frozen_at,
        "backend_queue_lock_hash": queue_lock["backend_queue_lock_hash"],
        "window_count": 20,
        "b0_replay_binding_count": 60,
        "recipes": recipes,
        "queue_bindings": bindings,
        "capacity": {
            "missing_materialization_bytes": missing_bytes,
            "reserve_bytes": CAPACITY_RESERVE_BYTES,
            "required_free_bytes": missing_bytes + CAPACITY_RESERVE_BYTES,
        },
        "artifacts": artifacts,
        "policy": {
            "explicit_execute_required": True,
            "durable_intent_before_first_target_mutation": True,
            "no_clobber_targets": True,
            "exact_hash_reconcile_only": True,
            "all_topic_counts_verified_before_commit": True,
            "absolute_camera_stamp_window_required": True,
            "one_materializer_process": True,
            "vins_execution_allowed": False,
        },
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": OUTCOME_BOUNDARY,
    }
    payload[SELF_HASH] = document_hash(payload, SELF_HASH)
    return payload


def validate_plan_payload(
    payload: Mapping[str, Any],
    *,
    require_live_artifacts: bool = False,
    root: Path = ROOT,
) -> None:
    if set(payload) != {
        "schema_version",
        "status",
        "frozen_at",
        "backend_queue_lock_hash",
        "window_count",
        "b0_replay_binding_count",
        "recipes",
        "queue_bindings",
        "capacity",
        "artifacts",
        "policy",
        "held_out_trajectory_outcome_read",
        "outcome_boundary",
        SELF_HASH,
    }:
        raise B0MaterializationError("B0 plan top-level schema expansion/drift")
    if (
        payload.get("schema_version") != SCHEMA
        or payload.get("status") != STATUS
        or payload.get(SELF_HASH) != document_hash(payload, SELF_HASH)
        or int(payload.get("window_count", -1)) != 20
        or int(payload.get("b0_replay_binding_count", -1)) != 60
        or payload.get("held_out_trajectory_outcome_read") is not False
        or payload.get("outcome_boundary") != OUTCOME_BOUNDARY
    ):
        raise B0MaterializationError("B0 plan schema/status/count/hash mismatch")
    recipes = payload.get("recipes")
    bindings = payload.get("queue_bindings")
    if not isinstance(recipes, list) or not isinstance(bindings, list):
        raise B0MaterializationError("B0 plan lacks recipes/bindings")
    if len(recipes) != 20 or len(bindings) != 60:
        raise B0MaterializationError("B0 plan coverage mismatch")
    policy = payload.get("policy")
    capacity = payload.get("capacity")
    if (
        not isinstance(policy, dict)
        or set(policy)
        != {
            "explicit_execute_required",
            "durable_intent_before_first_target_mutation",
            "no_clobber_targets",
            "exact_hash_reconcile_only",
            "all_topic_counts_verified_before_commit",
            "absolute_camera_stamp_window_required",
            "one_materializer_process",
            "vins_execution_allowed",
        }
        or any(
            policy.get(key) is not True
            for key in (
                "explicit_execute_required",
                "durable_intent_before_first_target_mutation",
                "no_clobber_targets",
                "exact_hash_reconcile_only",
                "all_topic_counts_verified_before_commit",
                "absolute_camera_stamp_window_required",
                "one_materializer_process",
            )
        )
        or policy.get("vins_execution_allowed") is not False
        or not isinstance(capacity, dict)
        or set(capacity)
        != {
            "missing_materialization_bytes",
            "reserve_bytes",
            "required_free_bytes",
        }
        or int(capacity.get("missing_materialization_bytes", -1)) < 0
        or int(capacity.get("reserve_bytes", -1)) != CAPACITY_RESERVE_BYTES
        or int(capacity.get("required_free_bytes", -1))
        != int(capacity.get("missing_materialization_bytes", -2))
        + CAPACITY_RESERVE_BYTES
    ):
        raise B0MaterializationError("B0 plan policy/capacity drift")
    seen: set[str] = set()
    base_recipe_keys = {
        "window_id",
        "dataset_family",
        "sequence",
        "runner_start",
        "runner_end_or_duration",
        "runner_unit",
        "target_path",
        "expected_sha256",
        "expected_size_bytes",
        "expected_topic_counts",
        "camera_topic",
        "disposition",
        "derivation_kind",
        "source_raw_path",
        "source_raw_sha256",
        "source_path_identity",
        "converter_argv_template",
        "evidence",
        "held_out_trajectory_outcome_read",
        "source_provenance_hash",
        "recipe_hash",
    }
    for recipe in recipes:
        if not isinstance(recipe, dict):
            raise B0MaterializationError("invalid B0 materialization recipe")
        expected_counts = recipe.get("expected_topic_counts")
        source_identity = recipe.get("source_path_identity")
        disposition = recipe.get("disposition")
        template = recipe.get("converter_argv_template")
        expected_recipe_keys = set(base_recipe_keys)
        if recipe.get("window_id") == "aqualoc_archaeology:A04:0002":
            expected_recipe_keys.add("a04_layout_recovery")
        if recipe.get("window_id") == "afrl:bus_outside:0001":
            expected_recipe_keys.update(
                {"expected_camera_stamp_range_ns", "source_input_contract"}
            )
        if (
            set(recipe) != expected_recipe_keys
            or
            str(recipe.get("window_id", "")) in seen
            or recipe.get("recipe_hash") != document_hash(recipe, "recipe_hash")
            or not _SHA.fullmatch(str(recipe.get("expected_sha256", "")))
            or not _SHA.fullmatch(str(recipe.get("source_raw_sha256", "")))
            or not _SHA.fullmatch(str(recipe.get("source_provenance_hash", "")))
            or recipe.get("held_out_trajectory_outcome_read") is not False
            or not isinstance(source_identity, dict)
            or not isinstance(recipe.get("target_path"), str)
            or not isinstance(recipe.get("source_raw_path"), str)
            or int(recipe.get("expected_size_bytes", 0)) <= 0
            or disposition
            not in {
                "DIRECT_RAW_WINDOW_PLAYBACK",
                "PREMATERIALIZED_EXACT_REUSE",
                "REBUILD_REQUIRED_OR_EXACT_RECONCILE",
                "EXACT_COPY_REQUIRED_OR_RECONCILE",
            }
            or (
                expected_counts is not None
                and (
                    not isinstance(expected_counts, dict)
                    or not expected_counts
                    or any(
                        not isinstance(topic, str)
                        or not topic.startswith("/")
                        or not isinstance(count, int)
                        or count <= 0
                        for topic, count in expected_counts.items()
                    )
                )
            )
        ):
            raise B0MaterializationError("invalid B0 materialization recipe")
        try:
            common.validate_canonical_input_identity_shape(source_identity)
        except common.BackendReplayViolation as error:
            raise B0MaterializationError("invalid B0 source path identity") from error
        if source_identity.get("expected_sha256") != recipe["source_raw_sha256"]:
            raise B0MaterializationError("B0 source path identity/hash drift")
        seen.add(str(recipe["window_id"]))
        if disposition in {
            "REBUILD_REQUIRED_OR_EXACT_RECONCILE",
            "PREMATERIALIZED_EXACT_REUSE",
        }:
            if (
                not isinstance(template, list)
                or template.count("{OUTPUT}") != 1
                or template[:3]
                != ["python3", "-m", "uw_frontend.datasets.aqualoc_raw_to_rosbag"]
            ):
                raise B0MaterializationError("invalid AQUALOC converter recipe")
        elif disposition == "EXACT_COPY_REQUIRED_OR_RECONCILE":
            if template != [
                "INTERNAL_EXACT_COPY_NOREPLACE",
                recipe["source_raw_path"],
                "{OUTPUT}",
            ]:
                raise B0MaterializationError("invalid B0 exact-copy recipe")
        elif template is not None:
            raise B0MaterializationError("direct B0 recipe has converter argv")
        if recipe["window_id"] == "aqualoc_archaeology:A04:0002":
            recovery = recipe.get("a04_layout_recovery")
            if (
                not isinstance(recovery, dict)
                or recovery.get("execution_raw_root_argument") != "."
                or recovery.get("q55_frozen_raw_root_argument") != ""
                or recovery.get("expected_topic_counts")
                != {"/camera/image_raw": 901, "/rtimulib_node/imu": 9091, "/aqualoc/colmap_gt": 44}
            ):
                raise B0MaterializationError("A04 special archive-root contract missing")
            template = recipe["converter_argv_template"]
            try:
                raw_root = template[template.index("--raw-root") + 1]
            except (ValueError, IndexError) as error:
                raise B0MaterializationError("A04 converter lacks --raw-root") from error
            if raw_root != ".":
                raise B0MaterializationError("A04 converter raw-root argument drift")
        if recipe["window_id"] == "afrl:bus_outside:0001":
            source_contract = recipe.get("source_input_contract")
            if (
                recipe.get("target_path")
                != "datasets/p07_backend_b0_inputs/afrl/bus_outside_0001.bag"
                or recipe.get("disposition") != "EXACT_COPY_REQUIRED_OR_RECONCILE"
                or not isinstance(source_contract, dict)
                or source_contract.get("topic_counts") != recipe.get(
                    "expected_topic_counts"
                )
                or source_contract.get("camera_stamp_range_ns")
                != recipe.get("expected_camera_stamp_range_ns")
                or source_contract.get("trajectory_values_interpreted") is not False
            ):
                raise B0MaterializationError("AFRL dedicated B0 cache contract missing")
    bound: set[tuple[int, str]] = set()
    per_window: dict[str, int] = {window_id: 0 for window_id in seen}
    for binding in bindings:
        if not isinstance(binding, dict):
            raise B0MaterializationError("invalid B0 queue binding")
        if set(binding) != {
            "queue_index",
            "run_id",
            "window_id",
            "arm",
            "dataset_family",
            "sequence",
            "runner_start",
            "runner_end_or_duration",
            "runner_unit",
            "source_run_id",
            "source_provenance_kind",
            "source_provenance_hash",
        }:
            raise B0MaterializationError("B0 queue binding schema expansion/drift")
        try:
            key = (int(binding["queue_index"]), str(binding["run_id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise B0MaterializationError("malformed B0 queue binding") from error
        window_id = str(binding.get("window_id", ""))
        if (
            key in bound
            or window_id not in seen
            or binding.get("arm") != queue_builder.B0
            or binding.get("source_run_id") != f"B0_NATIVE_DATA:{window_id}"
            or binding.get("source_provenance_kind")
            != "B0_NATIVE_DATA_IDENTITY_V1"
            or not _SHA.fullmatch(str(binding.get("source_provenance_hash", "")))
        ):
            raise B0MaterializationError("B0 queue binding identity/provenance drift")
        bound.add(key)
        per_window[window_id] += 1
        recipe = next(item for item in recipes if item["window_id"] == window_id)
        if binding["source_provenance_hash"] != recipe["source_provenance_hash"]:
            raise B0MaterializationError("B0 recipe/binding provenance hash drift")
    if set(per_window.values()) != {3}:
        raise B0MaterializationError("B0 queue bindings are not three-per-window")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise B0MaterializationError("B0 plan lacks artifact bindings")
    artifact_paths: set[str] = set()
    for record in artifacts:
        if (
            not isinstance(record, dict)
            or set(record) != {"path", "sha256", "size_bytes"}
            or not isinstance(record.get("path"), str)
            or not _SHA.fullmatch(str(record.get("sha256", "")))
            or not isinstance(record.get("size_bytes"), int)
            or int(record["size_bytes"]) <= 0
            or record["path"] in artifact_paths
        ):
            raise B0MaterializationError("invalid/duplicate B0 artifact binding")
        artifact_paths.add(str(record["path"]))
    if require_live_artifacts and artifact_paths != REQUIRED_LIVE_ARTIFACT_PATHS:
        raise B0MaterializationError("B0 live artifact path set drift")
    if require_live_artifacts:
        frozen_at = payload.get("frozen_at")
        if not isinstance(frozen_at, str):
            raise B0MaterializationError("B0 frozen_at is invalid")
        rebuilt = _assemble_live_payload(frozen_at=frozen_at, root=root)
        if queue_builder.canonical_json(dict(payload)) != queue_builder.canonical_json(
            rebuilt
        ):
            raise B0MaterializationError(
                "B0 plan differs from deterministic live-input rebuild"
            )


def _assemble_live_payload(
    *, frozen_at: str, root: Path = ROOT
) -> dict[str, object]:
    rows, lock, backend_records = _read_backend_inputs(root=root)
    manifest_path = root / queue_builder.MANIFEST.relative_to(ROOT)
    manifest_content, manifest_record = _snapshot(
        manifest_path, root=root, label="B0 dataset manifest"
    )
    _manifest_fields, manifest = queue_builder._parse_csv_content(
        manifest_path, manifest_content
    )
    eligibility_path = (
        root / "papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv"
    )
    eligibility, eligibility_record = _eligibility_rows_snapshot(
        eligibility_path, root=root
    )
    checksum_path = (
        root / "papers/ieee_sensors_journal_experiments/dataset_checksum_manifest.txt"
    )
    checksums, checksum_record = _checksum_manifest_snapshot(
        checksum_path, root=root
    )
    base_artifacts = [
        backend_records["backend_queue"],
        backend_records["backend_allocation"],
        backend_records["backend_queue_lock"],
        backend_records["arm_order"],
        manifest_record,
        eligibility_record,
        checksum_record,
    ]
    payload = build_plan_payload(
        frozen_at=frozen_at,
        queue_rows=rows,
        queue_lock=lock,
        manifest_rows=manifest,
        eligibility_rows=eligibility,
        checksums=checksums,
        receipts=_receipt_by_window(root),
        root=root,
        base_artifacts=base_artifacts,
    )
    return payload


def build_live_plan(*, frozen_at: str, root: Path = ROOT) -> dict[str, object]:
    payload = _assemble_live_payload(frozen_at=frozen_at, root=root)
    validate_plan_payload(payload, require_live_artifacts=True, root=root)
    for path in (OUTPUT, INTENT, FINAL_OUTPUT, RECEIPT):
        relative = path.relative_to(ROOT).as_posix()
        if queue_builder.formal_io.destination_exists(root, relative):
            raise FileExistsError(root / relative)
    capacity_path = queue_builder.rooted_io.SANCTIONED_INPUT_ROOT_TARGETS.get(
        "datasets", root / "datasets"
    )
    free = shutil.disk_usage(capacity_path).free
    if free < int(payload["capacity"]["required_free_bytes"]):
        raise B0MaterializationError("insufficient capacity for B0 materialization")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen-at", required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    payload = build_live_plan(frozen_at=args.frozen_at)
    if not args.write:
        print(json.dumps({
            "status": "READY",
            "window_count": payload["window_count"],
            "missing_materialization_bytes": payload["capacity"]["missing_materialization_bytes"],
            SELF_HASH: payload[SELF_HASH],
            "held_out_trajectory_outcome_read": False,
        }, indent=2, sort_keys=True))
        return 0
    queue_builder.formal_io.publish_json_no_clobber(
        ROOT, OUTPUT.relative_to(ROOT).as_posix(), payload
    )
    print(f"P07_B0_MATERIALIZATION_PLAN_FROZEN hash={payload[SELF_HASH]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
