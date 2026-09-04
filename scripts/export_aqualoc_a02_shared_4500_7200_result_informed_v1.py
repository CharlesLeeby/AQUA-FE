#!/usr/bin/env python3
"""Export the additive A02 4500..7200 HFNet shared input.

The first 1,801 camera frames are accepted only after a per-row comparison
against the immutable 4500..6300 shared manifest and its PNG payloads.  Those
bytes are hard-linked (or byte-copied if linking is unavailable); only global
6301..7200 are encoded.  Export reserves its final directory once; an
interruption leaves that namespace occupied and cannot become a retry.  No
SLAM process is started by this module.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

from scripts import a02_hfnet_result_informed_extension_v1 as profile
from scripts import export_aqualoc_a02_shared_4500_6300_v1 as prior
from scripts import materialize_aqualoc_a02_4500_7200_result_informed_v1 as materializer


SCHEMA_VERSION = "aqua-fe-a02-shared-4500-7200-result-informed-extension-v1"
STATUS_EXPORTED = "EXPORTED_RESULT_INFORMED_SHARED_INPUT_ONLY_NO_SLAM_STARTED"
ATTEMPT_SCHEMA = "aqua-fe-a02-shared-4500-7200-result-informed-export-attempt-v1"
ATTEMPT_STATUS = "SHARED_EXPORT_ATTEMPT_CLAIMED_NO_RETRY"

CAMERA_TOPIC = prior.CAMERA_TOPIC
IMU_TOPIC = prior.IMU_TOPIC
CAMERA_TYPE = prior.CAMERA_TYPE
IMU_TYPE = prior.IMU_TYPE
CAMERA_WIDTH = prior.CAMERA_WIDTH
CAMERA_HEIGHT = prior.CAMERA_HEIGHT
CAMERA_ENCODING = prior.CAMERA_ENCODING

GLOBAL_CAMERA_FIRST = profile.FEED_FIRST
GLOBAL_CAMERA_LAST = profile.FEED_LAST
CAMERA_COUNT = profile.FEED_COUNT
PREFIX_CAMERA_COUNT = profile.PRIOR_PREFIX_COUNT
SCORE_REFERENCE_INDICES = profile.SCORE_REFERENCE_INDICES
GLOBAL_IMU_FIRST = profile.HFNET_INNER_IMU_GLOBAL_FIRST
GLOBAL_IMU_LAST = profile.HFNET_INNER_IMU_GLOBAL_LAST
IMU_COUNT = profile.HFNET_INNER_IMU_COUNT
IMU_SHIFT_NS = profile.IMU_SHIFT_NS

DEFAULT_WINDOW_BAG = profile.NEW_WINDOW_BAG
DEFAULT_PROVENANCE = profile.NEW_WINDOW_MANIFEST
DEFAULT_PREFIX_ROOT = profile.OLD_SHARED_ROOT
DEFAULT_REFERENCE = profile.GT_PATH
DEFAULT_OUTPUT = profile.NEW_SHARED_ROOT


class ContractError(RuntimeError):
    pass


CameraSample = prior.CameraSample
ImuSample = prior.ImuSample
ReferencePose = prior.ReferencePose
Selection = prior.Selection
sha256_bytes = prior.sha256_bytes
sha256_file = prior.sha256_file
canonical_json_bytes = prior.canonical_json_bytes
encode_lossless_png = prior.encode_lossless_png
imu_csv_bytes = prior.imu_csv_bytes
reference_tum_bytes = prior.reference_tum_bytes
_link_or_copy = prior._link_or_copy
_topic_info = prior._topic_info
_stamp_ns = prior._stamp_ns
_finite_xyz = prior._finite_xyz


@contextmanager
def reserved_output_directory(target: Path):
    """Reserve the final name once; an interrupted export remains non-retryable."""
    if target.exists() or target.is_symlink():
        raise ContractError("OUTPUT_ALREADY_EXISTS")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.mkdir(exist_ok=False)
    except FileExistsError as error:
        raise ContractError("OUTPUT_APPEARED_DURING_RESERVATION") from error
    yield target


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


def _reject_symlinks_below(root: Path, label: str) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ContractError(f"{label}_ROOT_INVALID")
    for directory, names, files in os.walk(root, followlinks=False):
        parent = Path(directory)
        for name in [*names, *files]:
            if (parent / name).is_symlink():
                raise ContractError(f"{label}_SYMLINK_FORBIDDEN:{parent / name}")


def _regular_file_beneath(root: Path, relative: Path, label: str) -> Path:
    if relative.is_absolute() or not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
        raise ContractError(f"{label}_RELATIVE_PATH_INVALID")
    if root.is_symlink():
        raise ContractError(f"{label}_ROOT_MUST_NOT_BE_SYMLINK")
    canonical_root = root.resolve(strict=True)
    candidate = canonical_root
    for part in relative.parts:
        candidate /= part
        if candidate.is_symlink():
            raise ContractError(f"{label}_SYMLINK_COMPONENT_FORBIDDEN")
    resolved = _regular_file(candidate, label)
    try:
        resolved.relative_to(canonical_root)
    except ValueError as error:
        raise ContractError(f"{label}_PATH_ESCAPE") from error
    return resolved


def _regular_file(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ContractError(f"{label}_MUST_NOT_BE_SYMLINK")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ContractError(f"{label}_MISSING") from error
    if not resolved.is_file() or resolved.is_symlink():
        raise ContractError(f"{label}_NOT_REGULAR_FILE")
    return resolved


def _identity(path: Path) -> dict[str, object]:
    resolved = _regular_file(path, "IDENTITY_INPUT")
    return {"path": str(resolved), "size_bytes": resolved.stat().st_size, "sha256": sha256_file(resolved)}


def build_export_attempt_record() -> dict[str, object]:
    static = profile.expected_static_source_identities()
    return {
        "schema_version": ATTEMPT_SCHEMA,
        "status": ATTEMPT_STATUS,
        "scientific_role": profile.ROLE,
        "action": "shared_input_export_once",
        "no_retry": True,
        "slam_started": False,
        "argv": [profile.SEALED_PYTHON, "-B", "scripts/export_aqualoc_a02_shared_4500_7200_result_informed_v1.py", "--action", "export"],
        "targets": {"shared_root": str(profile.NEW_SHARED_ROOT.resolve(strict=False))},
        "inputs": {
            "window_bag": _identity(profile.NEW_WINDOW_BAG),
            "window_manifest": _identity(profile.NEW_WINDOW_MANIFEST),
            "window_export_attempt": _identity(profile.NEW_WINDOW_ATTEMPT),
            "prefix_manifest": static["prior_shared_manifest"],
            "ground_truth": static["ground_truth"],
            "prior_hfnet_unusable_result": static["prior_hfnet_unusable_result"],
        },
    }


def validate_export_attempt() -> dict[str, object]:
    path = _regular_file(profile.NEW_SHARED_ATTEMPT, "SHARED_EXPORT_ATTEMPT")
    payload = path.read_bytes()
    try:
        record = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ContractError("SHARED_EXPORT_ATTEMPT_INVALID_JSON") from error
    if payload != profile.canonical_json_bytes(record) or record != build_export_attempt_record():
        raise ContractError("SHARED_EXPORT_ATTEMPT_NOT_EXACT_CURRENT_CONTRACT")
    return _identity(path)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label}_NOT_OBJECT")
    return value


def validate_provenance(path: Path, window_bag: Path) -> dict[str, object]:
    resolved = _regular_file(path, "SOURCE_PROVENANCE")
    try:
        payload = resolved.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError("SOURCE_PROVENANCE_INVALID_JSON") from error
    if payload != profile.canonical_json_bytes(value):
        raise ContractError("SOURCE_PROVENANCE_NOT_CANONICAL_PRETTY_JSON")
    record = _mapping(value, "SOURCE_PROVENANCE")
    if record.get("schema_version") != "aqua-fe-aqualoc-canonical-raw-window-result-informed-extension-v1" or record.get("status") != "PASS_RESULT_INFORMED_SOURCE_WINDOW_ONLY_NO_SLAM_STARTED" or record.get("scientific_role") != profile.ROLE:
        raise ContractError("SOURCE_PROVENANCE_SCHEMA_STATUS_OR_ROLE_MISMATCH")
    provenance = _mapping(record.get("provenance"), "SOURCE_PROVENANCE_PROVENANCE")
    expected = profile.expected_static_source_identities()
    for key, expected_key in (("raw_tar", "raw_tar"), ("gt", "ground_truth"), ("converter", "converter"), ("prior_hfnet_unusable_result", "prior_hfnet_unusable_result")):
        if dict(_mapping(provenance.get(key), f"SOURCE_{key}")) != dict(expected[expected_key]):
            raise ContractError(f"SOURCE_PROVENANCE_IDENTITY_MISMATCH:{key}")
    argv = provenance.get("argv")
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        raise ContractError("SOURCE_PROVENANCE_ARGV_INVALID")
    try:
        candidate = Path(argv[argv.index("--output-bag") + 1])
    except (ValueError, IndexError) as error:
        raise ContractError("SOURCE_PROVENANCE_OUTPUT_ARG_MISSING") from error
    partial_prefix = f".{profile.NEW_WINDOW_BAG.name}.partial."
    suffix = candidate.name[len(partial_prefix) :] if candidate.name.startswith(partial_prefix) else ""
    if candidate.parent.resolve(strict=True) != profile.NEW_WINDOW_BAG.parent.resolve(strict=True) or not suffix.isdigit() or list(argv) != materializer.converter_command(candidate, python=profile.SEALED_PYTHON):
        raise ContractError("SOURCE_PROVENANCE_ARGV_MISMATCH")
    attempt_claim = dict(_mapping(provenance.get("attempt"), "SOURCE_WINDOW_EXPORT_ATTEMPT_IDENTITY"))
    attempt_path = _regular_file(profile.NEW_WINDOW_ATTEMPT, "SOURCE_WINDOW_EXPORT_ATTEMPT")
    attempt_payload = attempt_path.read_bytes()
    try:
        attempt_record = json.loads(attempt_payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ContractError("SOURCE_WINDOW_EXPORT_ATTEMPT_INVALID_JSON") from error
    source_subset = {
        "raw_tar": expected["raw_tar"],
        "ground_truth": expected["ground_truth"],
        "converter": expected["converter"],
        "prior_hfnet_unusable_result": expected["prior_hfnet_unusable_result"],
    }
    if attempt_payload != profile.canonical_json_bytes(attempt_record) or attempt_record != materializer.build_attempt_record(argv, source_subset) or attempt_claim != _identity(attempt_path):
        raise ContractError("SOURCE_WINDOW_EXPORT_ATTEMPT_MISMATCH")
    selection = _mapping(record.get("selection"), "SOURCE_SELECTION")
    expected_selection = {
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
    }
    if any(selection.get(key) != expected_value for key, expected_value in expected_selection.items()):
        raise ContractError("SOURCE_PROVENANCE_SELECTION_MISMATCH")
    semantics = _mapping(record.get("semantics"), "SOURCE_SEMANTICS")
    if semantics.get("header_stamp") != "raw_csv_integer_ns" or semantics.get("record_stamp_equals_header") is not True or semantics.get("no_time_shift") is not True or semantics.get("no_resampling") is not True or semantics.get("atlas_resume") is not False or semantics.get("retry") is not False:
        raise ContractError("SOURCE_PROVENANCE_SEMANTICS_MISMATCH")
    checks = _mapping(record.get("checks"), "SOURCE_CHECKS")
    if not checks or any(item is not True for item in checks.values()):
        raise ContractError("SOURCE_PROVENANCE_CHECKS_NOT_ALL_TRUE")
    output = _mapping(record.get("output"), "SOURCE_OUTPUT")
    bag = _regular_file(window_bag, "DERIVED_WINDOW_BAG")
    if output.get("path") != str(bag) or output.get("size_bytes") != bag.stat().st_size or output.get("sha256") != sha256_file(bag) or output.get("compression") != "bz2":
        raise ContractError("DERIVED_WINDOW_BAG_IDENTITY_MISMATCH")
    topic_counts = _mapping(output.get("topic_counts"), "SOURCE_TOPIC_COUNTS")
    expected_counts = {CAMERA_TOPIC: CAMERA_COUNT, IMU_TOPIC: profile.CANONICAL_MARGIN_IMU_COUNT, "/aqualoc/colmap_gt": 136}
    if dict(topic_counts) != expected_counts:
        raise ContractError("SOURCE_TOPIC_COUNTS_MISMATCH")
    expected_first = {CAMERA_TOPIC: profile.CAMERA_FIRST_NS, IMU_TOPIC: profile.CANONICAL_MARGIN_IMU_FIRST_NS, "/aqualoc/colmap_gt": profile.CAMERA_FIRST_NS}
    expected_last = {CAMERA_TOPIC: profile.CAMERA_LAST_NS, IMU_TOPIC: profile.CANONICAL_MARGIN_IMU_LAST_NS, "/aqualoc/colmap_gt": profile.CAMERA_LAST_NS}
    if dict(_mapping(output.get("topic_first_header_ns"), "SOURCE_TOPIC_FIRST")) != expected_first or dict(_mapping(output.get("topic_last_header_ns"), "SOURCE_TOPIC_LAST")) != expected_last or output.get("camera_prior_terminal_header_ns") != profile.CAMERA_PRIOR_LAST_NS or output.get("record_stamp_equals_header") is not True or output.get("strictly_increasing_by_topic") is not True or output.get("gt_matches_camera_every_20_global_frames") is not True:
        raise ContractError("SOURCE_OUTPUT_ENDPOINT_OR_AUDIT_MISMATCH")
    return {
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
        "producer_record": dict(record),
        "output_topic_counts": dict(topic_counts),
        "derived_window_bag": _identity(bag),
    }


def read_window_bag(path: Path, expected_topic_counts: Mapping[str, object]) -> tuple[tuple[CameraSample, ...], tuple[ImuSample, ...], dict[str, dict[str, object]]]:
    try:
        import rosbag
    except ImportError as error:
        raise ContractError("ROSBAG_IMPORT_FAILED") from error
    cameras: list[CameraSample] = []
    imus: list[ImuSample] = []
    with rosbag.Bag(str(path), "r") as bag:
        audit = _topic_info(bag)
        observed = {topic: int(row["message_count"]) for topic, row in audit.items()}
        if observed != {str(topic): int(count) for topic, count in expected_topic_counts.items()}:
            raise ContractError("DERIVED_BAG_TOPIC_COUNTS_DIFFER_FROM_PROVENANCE")
        for topic, expected_type in ((CAMERA_TOPIC, CAMERA_TYPE), (IMU_TOPIC, IMU_TYPE)):
            row = audit.get(topic)
            if row is None or row["message_type"] != expected_type:
                raise ContractError(f"REQUIRED_TOPIC_TYPE_MISMATCH:{topic}")
        for topic, message, record_stamp in bag.read_messages(topics=[CAMERA_TOPIC, IMU_TOPIC]):
            if topic == CAMERA_TOPIC:
                relative = len(cameras)
                header_ns = _stamp_ns(message.header.stamp, "CAMERA_HEADER")
                record_ns = _stamp_ns(record_stamp, "CAMERA_RECORD")
                pixels = bytes(message.data)
                if getattr(message, "_type", None) != CAMERA_TYPE or header_ns != record_ns or (int(message.width), int(message.height), str(message.encoding), int(message.step)) != (CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_ENCODING, CAMERA_WIDTH) or len(pixels) != CAMERA_WIDTH * CAMERA_HEIGHT:
                    raise ContractError("CAMERA_PAYLOAD_OR_STAMP_MISMATCH")
                cameras.append(CameraSample(relative, GLOBAL_CAMERA_FIRST + relative, header_ns, record_ns, CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_ENCODING, CAMERA_WIDTH, pixels, sha256_bytes(pixels)))
            else:
                raw_ns = _stamp_ns(message.header.stamp, "IMU_HEADER")
                record_ns = _stamp_ns(record_stamp, "IMU_RECORD")
                if getattr(message, "_type", None) != IMU_TYPE or raw_ns != record_ns:
                    raise ContractError("IMU_PAYLOAD_OR_STAMP_MISMATCH")
                imus.append(ImuSample(len(imus), -1, raw_ns, raw_ns + IMU_SHIFT_NS, record_ns, _finite_xyz(message.angular_velocity, "IMU_GYRO"), _finite_xyz(message.linear_acceleration, "IMU_ACCEL")))
    if len(cameras) != CAMERA_COUNT or len(imus) != profile.CANONICAL_MARGIN_IMU_COUNT:
        raise ContractError("DERIVED_BAG_SELECTED_COUNT_MISMATCH")
    first = [index for index, row in enumerate(imus) if row.raw_header_ns == profile.HFNET_INNER_IMU_FIRST_RAW_NS]
    last = [index for index, row in enumerate(imus) if row.raw_header_ns == profile.HFNET_INNER_IMU_LAST_RAW_NS]
    if len(first) != 1 or len(last) != 1 or last[0] - first[0] + 1 != IMU_COUNT:
        raise ContractError("HFNET_INNER_IMU_ENDPOINT_OR_COUNT_MISMATCH")
    selected = tuple(ImuSample(relative, GLOBAL_IMU_FIRST + relative, row.raw_header_ns, row.output_header_ns, row.record_ns, row.gyro_xyz, row.accel_xyz) for relative, row in enumerate(imus[first[0] : last[0] + 1]))
    stamps = [row.header_ns for row in cameras]
    if len(selected) != IMU_COUNT or any(right <= left for left, right in zip(stamps, stamps[1:])) or any(right.raw_header_ns <= left.raw_header_ns for left, right in zip(selected, selected[1:])):
        raise ContractError("SELECTED_TIMESTAMPS_NOT_STRICT")
    if (stamps[0], stamps[PREFIX_CAMERA_COUNT - 1], stamps[-1]) != (profile.CAMERA_FIRST_NS, profile.CAMERA_PRIOR_LAST_NS, profile.CAMERA_LAST_NS):
        raise ContractError("CAMERA_ENDPOINT_TIMESTAMP_MISMATCH")
    if (selected[0].raw_header_ns, selected[-1].raw_header_ns) != (profile.HFNET_INNER_IMU_FIRST_RAW_NS, profile.HFNET_INNER_IMU_LAST_RAW_NS) or not (selected[0].output_header_ns <= stamps[0] and selected[-1].output_header_ns >= stamps[-1]):
        raise ContractError("IMU_ENDPOINT_OR_BRACKET_MISMATCH")
    return tuple(cameras), selected, audit


def load_references(path: Path, cameras: Sequence[CameraSample]) -> tuple[ReferencePose, ...]:
    resolved = _regular_file(path, "REFERENCE_PROXY")
    if resolved.stat().st_size != profile.GT_SIZE or sha256_file(resolved) != profile.GT_SHA256:
        raise ContractError("REFERENCE_PROXY_IDENTITY_MISMATCH")
    wanted = set(SCORE_REFERENCE_INDICES)
    poses: dict[int, tuple[tuple[float, float, float], tuple[float, float, float, float]]] = {}
    with resolved.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            fields = line.split()
            if len(fields) != 8:
                raise ContractError(f"REFERENCE_COLUMN_COUNT_MISMATCH:{line_number}")
            try:
                index_float = float(fields[0])
                values = tuple(float(item) for item in fields[1:])
            except ValueError as error:
                raise ContractError(f"REFERENCE_NONNUMERIC:{line_number}") from error
            if not index_float.is_integer() or not all(math.isfinite(item) for item in values):
                raise ContractError(f"REFERENCE_INVALID_ROW:{line_number}")
            index = int(index_float)
            if index not in wanted:
                continue
            if index in poses or abs(math.sqrt(sum(item * item for item in values[3:7])) - 1.0) > 1e-6:
                raise ContractError("REFERENCE_DUPLICATE_OR_NONUNIT_QUATERNION")
            poses[index] = (values[0:3], values[3:7])  # type: ignore[assignment]
    if set(poses) != wanted:
        raise ContractError("REFERENCE_TARGET_GRID_INCOMPLETE")
    by_global = {row.global_index: row for row in cameras}
    return tuple(ReferencePose(index, by_global[index].header_ns, poses[index][0], poses[index][1]) for index in SCORE_REFERENCE_INDICES)


def validate_prefix_rows(
    prefix_root: Path,
    cameras: Sequence[CameraSample],
    *,
    manifest_sha256: str = profile.OLD_SHARED_MANIFEST_SHA256,
    expected_count: int = PREFIX_CAMERA_COUNT,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    manifest_path = _regular_file_beneath(prefix_root, Path("conversion_manifest.json"), "PREFIX_MANIFEST")
    if sha256_file(manifest_path) != manifest_sha256:
        raise ContractError("PREFIX_MANIFEST_IDENTITY_MISMATCH")
    try:
        payload = manifest_path.read_bytes()
        manifest = json.loads(payload.decode("utf-8"))
        rows = manifest["camera"]["images"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ContractError("PREFIX_MANIFEST_SCHEMA_INVALID") from error
    if payload != prior.canonical_json_bytes(manifest) or manifest.get("schema_version") != prior.SCHEMA_VERSION or manifest.get("status") != prior.STATUS_EXPORTED:
        raise ContractError("PREFIX_MANIFEST_CANONICAL_SCHEMA_OR_STATUS_MISMATCH")
    if not isinstance(rows, list) or len(rows) != expected_count or len(cameras) < expected_count:
        raise ContractError("PREFIX_CAMERA_COUNT_MISMATCH")
    validated: list[dict[str, object]] = []
    canonical_root = (prefix_root / "shared/cam0/data").resolve(strict=True)
    for relative, (raw_row, sample) in enumerate(zip(rows, cameras[:expected_count])):
        row = _mapping(raw_row, f"PREFIX_IMAGE_{relative}")
        if row.get("relative_index") != relative or row.get("global_source_index") != profile.FEED_FIRST + relative or row.get("raw_header_ns") != sample.header_ns or row.get("source_pixel_sha256") != sample.source_pixel_sha256:
            raise ContractError(f"PREFIX_SOURCE_IDENTITY_MISMATCH:{relative}")
        expected_relative = f"shared/cam0/data/{sample.header_ns}.png"
        if row.get("relative_path") != expected_relative:
            raise ContractError(f"PREFIX_RELATIVE_PATH_MISMATCH:{relative}")
        png = _regular_file_beneath(prefix_root, Path(expected_relative), "PREFIX_PNG")
        if png.parent.resolve(strict=True) != canonical_root:
            raise ContractError("PREFIX_PNG_PATH_ESCAPE")
        observed_hash = sha256_file(png)
        if observed_hash != row.get("png_sha256") or png.stat().st_size != row.get("png_size_bytes"):
            raise ContractError(f"PREFIX_PNG_IDENTITY_MISMATCH:{relative}")
        validated.append({"path": png, "png_sha256": observed_hash, "png_size_bytes": png.stat().st_size})
    return ({"root": str(prefix_root.resolve(strict=True)), "manifest": _identity(manifest_path), "camera_count": expected_count, "per_frame_source_pixel_and_png_identity_rehashed": True}, validated)


def write_artifact(output: Path, window_bag: Path, provenance_identity: Mapping[str, object], reference_path: Path, prefix_root: Path, selection: Selection, export_attempt_identity: Mapping[str, object]) -> dict[str, object]:
    if len(selection.cameras) != CAMERA_COUNT or len(selection.imus) != IMU_COUNT or len(selection.references) != profile.SCORE_REFERENCE_COUNT:
        raise ContractError("WRITE_SELECTION_COUNT_MISMATCH")
    prefix_identity, prefix_rows = validate_prefix_rows(prefix_root, selection.cameras)
    with reserved_output_directory(output) as staging:
        canonical_dir = staging / "shared/cam0/data"
        image_rows: list[dict[str, object]] = []
        for sample in selection.cameras:
            target = canonical_dir / f"{sample.header_ns}.png"
            if sample.relative_index < PREFIX_CAMERA_COUNT:
                old = prefix_rows[sample.relative_index]
                mode = _link_or_copy(old["path"], target)  # type: ignore[arg-type]
                png_hash, png_size = str(old["png_sha256"]), int(old["png_size_bytes"])
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                payload = encode_lossless_png(sample)
                target.write_bytes(payload)
                mode, png_hash, png_size = "encoded_new_lossless", sha256_bytes(payload), len(payload)
            if target.stat().st_size != png_size or sha256_file(target) != png_hash:
                raise ContractError("CANONICAL_PNG_POSTWRITE_IDENTITY_MISMATCH")
            image_rows.append({"relative_index": sample.relative_index, "global_source_index": sample.global_index, "raw_header_ns": sample.header_ns, "source_pixel_sha256": sample.source_pixel_sha256, "png_sha256": png_hash, "png_size_bytes": png_size, "materialization": mode, "relative_path": f"shared/cam0/data/{sample.header_ns}.png"})

        times_payload = ("\n".join(str(row["raw_header_ns"]) for row in image_rows) + "\n").encode("ascii")
        (staging / "shared/cam0_times.txt").write_bytes(times_payload)
        (staging / "shared/reference_proxy.tum").write_bytes(reference_tum_bytes(selection.references))
        mapping_rows = ["global_camera_index,header_ns,role"] + [f"{pose.global_camera_index},{pose.header_ns},SCORE" for pose in selection.references]
        (staging / "shared/reference_mapping.csv").write_text("\n".join(mapping_rows) + "\n", encoding="ascii")
        hf_cam = staging / "hfnet/mav0/cam0/data"
        link_modes: dict[str, int] = {}
        for row in image_rows:
            source = staging / str(row["relative_path"])
            mode = _link_or_copy(source, hf_cam / source.name)
            link_modes[mode] = link_modes.get(mode, 0) + 1
        camera_csv = ["#timestamp [ns],filename"] + [f"{row['raw_header_ns']},{row['raw_header_ns']}.png" for row in image_rows]
        (staging / "hfnet/mav0/cam0/data.csv").write_bytes("\n".join(camera_csv).encode("ascii"))
        imu_path = staging / "hfnet/mav0/imu0/data.csv"
        imu_path.parent.mkdir(parents=True, exist_ok=True)
        imu_path.write_bytes(imu_csv_bytes(selection.imus))
        (staging / "hfnet/cam0_times.txt").write_bytes(times_payload)
        manifest: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "status": STATUS_EXPORTED,
            "scientific_role": profile.ROLE,
            "source": {
                "export_attempt": dict(export_attempt_identity),
                "derived_window_bag": dict(provenance_identity.get("derived_window_bag") or _identity(window_bag)),
                "provenance": dict(provenance_identity),
                "canonical_raw_archive": {"size_bytes": profile.RAW_TAR_SIZE, "sha256": profile.RAW_TAR_SHA256, "converter_relative_path": "uw_frontend/datasets/aqualoc_raw_to_rosbag.py", "converter_sha256": profile.CONVERTER_SHA256},
                "prior_failed_hfnet": {"contract": profile.expected_static_source_identities()["prior_hfnet_contract"], "result": profile.expected_static_source_identities()["prior_hfnet_unusable_result"]},
            },
            "window": {"feed_global_camera_indices_inclusive": [profile.FEED_FIRST, profile.FEED_LAST], "camera_count": CAMERA_COUNT, "same_prefix_global_camera_indices_inclusive": [profile.FEED_FIRST, profile.PRIOR_FEED_LAST], "new_global_camera_indices_inclusive": [profile.PRIOR_FEED_LAST + 1, profile.FEED_LAST], "new_camera_count": profile.NEW_CAMERA_COUNT, "score_global_camera_indices_inclusive": [profile.SCORE_FIRST, profile.SCORE_LAST], "score_reference_global_indices": list(SCORE_REFERENCE_INDICES), "score_reference_count": profile.SCORE_REFERENCE_COUNT, "score_evaluation_grid_count": profile.SCORE_EVALUATION_GRID_COUNT},
            "camera": {"topic": CAMERA_TOPIC, "message_type": CAMERA_TYPE, "width": CAMERA_WIDTH, "height": CAMERA_HEIGHT, "encoding": CAMERA_ENCODING, "first_header_ns": selection.cameras[0].header_ns, "prior_terminal_header_ns": selection.cameras[PREFIX_CAMERA_COUNT - 1].header_ns, "last_header_ns": selection.cameras[-1].header_ns, "images": image_rows, "prefix_reuse": prefix_identity, "newly_encoded_relative_indices_inclusive": [PREFIX_CAMERA_COUNT, CAMERA_COUNT - 1]},
            "imu": {"topic": IMU_TOPIC, "message_type": IMU_TYPE, "global_indices_inclusive": [GLOBAL_IMU_FIRST, GLOBAL_IMU_LAST], "count": IMU_COUNT, "time_transform": f"output_ns=raw_header_ns+{IMU_SHIFT_NS}", "first_raw_header_ns": selection.imus[0].raw_header_ns, "last_raw_header_ns": selection.imus[-1].raw_header_ns, "first_output_header_ns": selection.imus[0].output_header_ns, "last_output_header_ns": selection.imus[-1].output_header_ns, "brackets_camera": True},
            "reference": {"identity": _identity(reference_path), "role": "same-image offline COLMAP, scale corrected with depth metadata; not sensor-independent ground truth", "pose_convention": "world_T_camera", "target_rows": len(selection.references), "evaluation_grid_count": profile.SCORE_EVALUATION_GRID_COUNT, "mapping": [{"global_camera_index": pose.global_camera_index, "header_ns": pose.header_ns} for pose in selection.references]},
            "views": {"canonical_png_root": "shared/cam0/data", "canonical_times": "shared/cam0_times.txt", "reference_tum": "shared/reference_proxy.tum", "hfnet_euroc_root": "hfnet", "hfnet_camera_link_modes": link_modes},
            "topic_audit": selection.topic_audit,
            "controls": {"replay_from_global_4500": True, "atlas_resume": False, "algorithm_or_threshold_modified": False, "retry": False, "extension_to_8100_after_failure": False},
            "claims": {"hfnet_started": False, "anyfeature_started": False, "aqua_fe_started": False, "official_source_modified": False, "accuracy_result_generated": False},
        }
        (staging / "conversion_manifest.json").write_bytes(canonical_json_bytes(manifest))
    return manifest


def _validate_png_pixels(path: Path, sample: CameraSample, label: str) -> None:
    try:
        import cv2
        import numpy as np
    except ImportError as error:
        raise ContractError("PNG_AUDIT_RUNTIME_IMPORT_FAILED") from error
    payload = path.read_bytes()
    decoded = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if decoded is None or decoded.dtype != np.uint8 or decoded.shape != (sample.height, sample.width):
        raise ContractError(f"{label}_DECODE_SCHEMA_MISMATCH")
    pixels = decoded.tobytes(order="C")
    if pixels != sample.pixels or sha256_bytes(pixels) != sample.source_pixel_sha256:
        raise ContractError(f"{label}_PIXELS_DIFFER_FROM_LOCKED_BAG")


def audit_exported_artifact(root: Path) -> dict[str, Any]:
    if root.is_symlink() or not root.is_dir():
        raise ContractError("SHARED_ROOT_NOT_NONSYMLINK_DIRECTORY")
    root = root.resolve(strict=True)
    _reject_symlinks_below(root, "SHARED_TREE")
    manifest_path = _regular_file_beneath(root, Path("conversion_manifest.json"), "SHARED_MANIFEST")
    payload = manifest_path.read_bytes()
    try:
        manifest = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ContractError("SHARED_MANIFEST_INVALID_JSON") from error
    if payload != canonical_json_bytes(manifest) or manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("status") != STATUS_EXPORTED or manifest.get("scientific_role") != profile.ROLE:
        raise ContractError("SHARED_MANIFEST_CANONICAL_SCHEMA_STATUS_OR_ROLE_MISMATCH")
    source = _mapping(manifest.get("source"), "SHARED_SOURCE")
    export_attempt_identity = validate_export_attempt()
    if dict(_mapping(source.get("export_attempt"), "SHARED_EXPORT_ATTEMPT_IDENTITY")) != export_attempt_identity:
        raise ContractError("SHARED_EXPORT_ATTEMPT_IDENTITY_MISMATCH")
    derived = dict(_mapping(source.get("derived_window_bag"), "SHARED_DERIVED_WINDOW_BAG"))
    provenance = dict(_mapping(source.get("provenance"), "SHARED_SOURCE_PROVENANCE"))
    if not isinstance(derived.get("path"), str) or _identity(Path(str(derived["path"]))) != derived or not isinstance(provenance.get("path"), str):
        raise ContractError("SHARED_SOURCE_PATH_OR_IDENTITY_INVALID")
    observed_provenance = validate_provenance(Path(str(provenance["path"])), Path(str(derived["path"])))
    if provenance != observed_provenance:
        raise ContractError("SHARED_SOURCE_PROVENANCE_MISMATCH")
    source_cameras, source_imus, source_topic_audit = read_window_bag(Path(str(derived["path"])), observed_provenance["output_topic_counts"])  # type: ignore[arg-type]
    source_references = load_references(profile.GT_PATH, source_cameras)
    expected_sources = profile.expected_static_source_identities()
    expected_raw = {"size_bytes": profile.RAW_TAR_SIZE, "sha256": profile.RAW_TAR_SHA256, "converter_relative_path": "uw_frontend/datasets/aqualoc_raw_to_rosbag.py", "converter_sha256": profile.CONVERTER_SHA256}
    expected_prior = {"contract": expected_sources["prior_hfnet_contract"], "result": expected_sources["prior_hfnet_unusable_result"]}
    if dict(_mapping(source.get("canonical_raw_archive"), "SHARED_CANONICAL_RAW")) != expected_raw or dict(_mapping(source.get("prior_failed_hfnet"), "SHARED_PRIOR_FAILED_HFNET")) != expected_prior:
        raise ContractError("SHARED_STATIC_SOURCE_IDENTITY_MISMATCH")
    window = _mapping(manifest.get("window"), "SHARED_WINDOW")
    expected_window = {"feed_global_camera_indices_inclusive": [profile.FEED_FIRST, profile.FEED_LAST], "camera_count": CAMERA_COUNT, "same_prefix_global_camera_indices_inclusive": [profile.FEED_FIRST, profile.PRIOR_FEED_LAST], "new_global_camera_indices_inclusive": [profile.PRIOR_FEED_LAST + 1, profile.FEED_LAST], "new_camera_count": profile.NEW_CAMERA_COUNT, "score_global_camera_indices_inclusive": [profile.SCORE_FIRST, profile.SCORE_LAST], "score_reference_global_indices": list(SCORE_REFERENCE_INDICES), "score_reference_count": profile.SCORE_REFERENCE_COUNT, "score_evaluation_grid_count": profile.SCORE_EVALUATION_GRID_COUNT}
    if any(window.get(key) != value for key, value in expected_window.items()):
        raise ContractError("SHARED_WINDOW_CONTRACT_MISMATCH")
    controls = _mapping(manifest.get("controls"), "SHARED_CONTROLS")
    expected_controls = {"replay_from_global_4500": True, "atlas_resume": False, "algorithm_or_threshold_modified": False, "retry": False, "extension_to_8100_after_failure": False}
    if any(controls.get(key) is not value for key, value in expected_controls.items()):
        raise ContractError("SHARED_CONTROLS_MISMATCH")
    claims = _mapping(manifest.get("claims"), "SHARED_CLAIMS")
    expected_claims = {"hfnet_started": False, "anyfeature_started": False, "aqua_fe_started": False, "official_source_modified": False, "accuracy_result_generated": False}
    if dict(claims) != expected_claims:
        raise ContractError("SHARED_CLAIMS_MISMATCH")
    topic_audit = _mapping(manifest.get("topic_audit"), "SHARED_TOPIC_AUDIT")
    expected_topic_audit = {
        CAMERA_TOPIC: {"message_type": CAMERA_TYPE, "message_count": CAMERA_COUNT},
        IMU_TOPIC: {"message_type": IMU_TYPE, "message_count": profile.CANONICAL_MARGIN_IMU_COUNT},
        "/aqualoc/colmap_gt": {"message_type": "nav_msgs/Odometry", "message_count": 136},
    }
    if dict(topic_audit) != expected_topic_audit or dict(topic_audit) != source_topic_audit:
        raise ContractError("SHARED_TOPIC_AUDIT_MISMATCH")
    camera = _mapping(manifest.get("camera"), "SHARED_CAMERA")
    images = camera.get("images")
    if not isinstance(images, list) or len(images) != CAMERA_COUNT or camera.get("first_header_ns") != profile.CAMERA_FIRST_NS or camera.get("prior_terminal_header_ns") != profile.CAMERA_PRIOR_LAST_NS or camera.get("last_header_ns") != profile.CAMERA_LAST_NS or camera.get("newly_encoded_relative_indices_inclusive") != [PREFIX_CAMERA_COUNT, CAMERA_COUNT - 1]:
        raise ContractError("SHARED_CAMERA_CONTRACT_MISMATCH")
    prefix = _mapping(camera.get("prefix_reuse"), "SHARED_PREFIX")
    prefix_manifest = _mapping(prefix.get("manifest"), "SHARED_PREFIX_MANIFEST")
    if prefix.get("camera_count") != PREFIX_CAMERA_COUNT or prefix.get("per_frame_source_pixel_and_png_identity_rehashed") is not True or prefix_manifest.get("sha256") != profile.OLD_SHARED_MANIFEST_SHA256:
        raise ContractError("SHARED_PREFIX_REUSE_MISMATCH")
    old_manifest_path = _regular_file_beneath(profile.OLD_SHARED_ROOT, Path("conversion_manifest.json"), "PRIOR_SHARED_MANIFEST")
    old_payload = old_manifest_path.read_bytes()
    try:
        old_manifest = json.loads(old_payload.decode("utf-8"))
        old_images = old_manifest["camera"]["images"]
    except (UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ContractError("PRIOR_SHARED_MANIFEST_SCHEMA_INVALID") from error
    if old_payload != prior.canonical_json_bytes(old_manifest) or sha256_bytes(old_payload) != profile.OLD_SHARED_MANIFEST_SHA256 or not isinstance(old_images, list) or len(old_images) != PREFIX_CAMERA_COUNT:
        raise ContractError("PRIOR_SHARED_MANIFEST_IDENTITY_OR_COUNT_MISMATCH")
    timestamps: list[int] = []
    aggregate = hashlib.sha256()
    expected_names: set[str] = set()
    for relative, raw_row in enumerate(images):
        row = _mapping(raw_row, f"SHARED_IMAGE_{relative}")
        source_sample = source_cameras[relative]
        stamp = row.get("raw_header_ns")
        expected_mode = {"hardlink", "copy"} if relative < PREFIX_CAMERA_COUNT else {"encoded_new_lossless"}
        if isinstance(stamp, bool) or not isinstance(stamp, int) or row.get("relative_index") != relative or row.get("global_source_index") != profile.FEED_FIRST + relative or row.get("materialization") not in expected_mode or row.get("relative_path") != f"shared/cam0/data/{stamp}.png":
            raise ContractError(f"SHARED_IMAGE_PROVENANCE_MISMATCH:{relative}")
        png_hash, png_size = row.get("png_sha256"), row.get("png_size_bytes")
        source_hash = row.get("source_pixel_sha256")
        if not isinstance(source_hash, str) or len(source_hash) != 64 or any(character not in "0123456789abcdef" for character in source_hash) or not isinstance(png_hash, str) or len(png_hash) != 64 or any(character not in "0123456789abcdef" for character in png_hash) or isinstance(png_size, bool) or not isinstance(png_size, int) or png_size <= 0:
            raise ContractError(f"SHARED_IMAGE_IDENTITY_INVALID:{relative}")
        if (stamp, row.get("global_source_index"), source_hash) != (source_sample.header_ns, source_sample.global_index, source_sample.source_pixel_sha256):
            raise ContractError(f"SHARED_IMAGE_DOES_NOT_BIND_LOCKED_BAG:{relative}")
        if relative < PREFIX_CAMERA_COUNT:
            old_row = _mapping(old_images[relative], f"PRIOR_SHARED_IMAGE_{relative}")
            for key in ("relative_index", "global_source_index", "raw_header_ns", "source_pixel_sha256", "png_sha256", "png_size_bytes", "relative_path"):
                if row.get(key) != old_row.get(key):
                    raise ContractError(f"SHARED_PREFIX_ROW_IDENTITY_MISMATCH:{relative}:{key}")
        canonical = _identity(root / str(row["relative_path"]))
        hfnet = _identity(root / f"hfnet/mav0/cam0/data/{stamp}.png")
        if canonical["sha256"] != png_hash or canonical["size_bytes"] != png_size or hfnet["sha256"] != png_hash or hfnet["size_bytes"] != png_size:
            raise ContractError(f"SHARED_OR_HFNET_PNG_IDENTITY_MISMATCH:{relative}")
        _validate_png_pixels(Path(str(canonical["path"])), source_sample, f"SHARED_IMAGE_{relative}")
        timestamps.append(stamp)
        expected_names.add(f"{stamp}.png")
        aggregate.update(f"{relative},{stamp},{png_hash},{png_size}\n".encode("ascii"))
    if any(right <= left for left, right in zip(timestamps, timestamps[1:])) or (timestamps[0], timestamps[PREFIX_CAMERA_COUNT - 1], timestamps[-1]) != (profile.CAMERA_FIRST_NS, profile.CAMERA_PRIOR_LAST_NS, profile.CAMERA_LAST_NS):
        raise ContractError("SHARED_CAMERA_TIMESTAMP_GATE_FAILED")
    for directory in (root / "shared/cam0/data", root / "hfnet/mav0/cam0/data"):
        if {path.name for path in directory.iterdir() if path.is_file()} != expected_names:
            raise ContractError("SHARED_CAMERA_DIRECTORY_FILESET_MISMATCH")
    times = ("\n".join(map(str, timestamps)) + "\n").encode("ascii")
    if (root / "shared/cam0_times.txt").read_bytes() != times or (root / "hfnet/cam0_times.txt").read_bytes() != times:
        raise ContractError("SHARED_OR_HFNET_TIMES_MISMATCH")
    camera_csv = ["#timestamp [ns],filename"] + [f"{stamp},{stamp}.png" for stamp in timestamps]
    if (root / "hfnet/mav0/cam0/data.csv").read_bytes() != "\n".join(camera_csv).encode("ascii"):
        raise ContractError("HFNET_CAMERA_CSV_MISMATCH")
    imu = _mapping(manifest.get("imu"), "SHARED_IMU")
    expected_imu = {"global_indices_inclusive": [GLOBAL_IMU_FIRST, GLOBAL_IMU_LAST], "count": IMU_COUNT, "time_transform": f"output_ns=raw_header_ns+{IMU_SHIFT_NS}", "first_raw_header_ns": profile.HFNET_INNER_IMU_FIRST_RAW_NS, "last_raw_header_ns": profile.HFNET_INNER_IMU_LAST_RAW_NS, "first_output_header_ns": profile.HFNET_INNER_IMU_FIRST_RAW_NS + IMU_SHIFT_NS, "last_output_header_ns": profile.HFNET_INNER_IMU_LAST_RAW_NS + IMU_SHIFT_NS, "brackets_camera": True}
    if any(imu.get(key) != value for key, value in expected_imu.items()):
        raise ContractError("SHARED_IMU_CONTRACT_MISMATCH")
    imu_payload = (root / "hfnet/mav0/imu0/data.csv").read_bytes()
    if imu_payload != imu_csv_bytes(source_imus):
        raise ContractError("HFNET_IMU_CSV_DIFFERS_FROM_LOCKED_BAG")
    imu_lines = imu_payload.decode("ascii").splitlines()
    if len(imu_lines) != IMU_COUNT + 1:
        raise ContractError("HFNET_IMU_CSV_COUNT_MISMATCH")
    imu_stamps = []
    for index, line in enumerate(imu_lines[1:]):
        fields = line.split(",")
        try:
            stamp, values = int(fields[0]), [float(item) for item in fields[1:]]
        except (ValueError, IndexError) as error:
            raise ContractError(f"HFNET_IMU_INVALID:{index}") from error
        if len(fields) != 7 or not all(math.isfinite(item) for item in values):
            raise ContractError(f"HFNET_IMU_INVALID:{index}")
        imu_stamps.append(stamp)
    if any(right <= left for left, right in zip(imu_stamps, imu_stamps[1:])) or imu_stamps[0] != expected_imu["first_output_header_ns"] or imu_stamps[-1] != expected_imu["last_output_header_ns"] or not (imu_stamps[0] <= timestamps[0] and imu_stamps[-1] >= timestamps[-1]):
        raise ContractError("HFNET_IMU_TIMESTAMP_GATE_FAILED")
    reference = _mapping(manifest.get("reference"), "SHARED_REFERENCE")
    if dict(_mapping(reference.get("identity"), "SHARED_REFERENCE_IDENTITY")) != expected_sources["ground_truth"] or reference.get("role") != "same-image offline COLMAP, scale corrected with depth metadata; not sensor-independent ground truth" or reference.get("pose_convention") != "world_T_camera":
        raise ContractError("SHARED_REFERENCE_IDENTITY_OR_SEMANTICS_MISMATCH")
    mapping = reference.get("mapping")
    expected_mapping = [{"global_camera_index": index, "header_ns": timestamps[index - profile.FEED_FIRST]} for index in SCORE_REFERENCE_INDICES]
    if mapping != expected_mapping or reference.get("target_rows") != profile.SCORE_REFERENCE_COUNT or reference.get("evaluation_grid_count") != profile.SCORE_EVALUATION_GRID_COUNT:
        raise ContractError("SHARED_REFERENCE_MAPPING_MISMATCH")
    mapping_payload = "global_camera_index,header_ns,role\n" + "".join(f"{row['global_camera_index']},{row['header_ns']},SCORE\n" for row in expected_mapping)
    if (root / "shared/reference_mapping.csv").read_text(encoding="ascii") != mapping_payload:
        raise ContractError("SHARED_REFERENCE_MAPPING_CSV_MISMATCH")
    reference_payload = (root / "shared/reference_proxy.tum").read_bytes()
    if reference_payload != reference_tum_bytes(source_references):
        raise ContractError("SHARED_REFERENCE_TUM_DIFFERS_FROM_LOCKED_GROUND_TRUTH")
    reference_lines = reference_payload.decode("ascii").splitlines()
    if len(reference_lines) != profile.SCORE_REFERENCE_COUNT:
        raise ContractError("SHARED_REFERENCE_TUM_COUNT_MISMATCH")
    for index, (line, expected) in enumerate(zip(reference_lines, expected_mapping)):
        fields = line.split()
        try:
            stamp_ns = int(Decimal(fields[0]) * Decimal(1_000_000_000))
            values = [float(item) for item in fields[1:]]
        except (InvalidOperation, ValueError) as error:
            raise ContractError(f"SHARED_REFERENCE_TUM_INVALID:{index}") from error
        if len(fields) != 8 or stamp_ns != expected["header_ns"] or not all(math.isfinite(item) for item in values):
            raise ContractError(f"SHARED_REFERENCE_TUM_INVALID:{index}")
    semantic = {name: _identity(root / relative) for name, relative in {"shared_times": "shared/cam0_times.txt", "hfnet_times": "hfnet/cam0_times.txt", "hfnet_camera_csv": "hfnet/mav0/cam0/data.csv", "hfnet_imu_csv": "hfnet/mav0/imu0/data.csv", "reference_tum": "shared/reference_proxy.tum", "reference_mapping": "shared/reference_mapping.csv"}.items()}
    return {"manifest": _identity(manifest_path), "semantic_files": semantic, "camera_count": CAMERA_COUNT, "camera_timestamps_ns": timestamps, "camera_first_ns": timestamps[0], "prior_terminal_ns": timestamps[PREFIX_CAMERA_COUNT - 1], "score_first_ns": timestamps[profile.SCORE_FIRST - profile.FEED_FIRST], "score_last_ns": timestamps[-1], "camera_last_ns": timestamps[-1], "imu_count": len(imu_stamps), "reference_count": len(reference_lines), "evaluation_grid_count": profile.SCORE_EVALUATION_GRID_COUNT, "image_aggregate_sha256": aggregate.hexdigest(), "views_rehashed": ["shared", "hfnet"]}


def prepare(window_bag: Path, provenance: Path, reference: Path) -> tuple[dict[str, object], Selection]:
    provenance_identity = validate_provenance(provenance, window_bag)
    cameras, imus, audit = read_window_bag(window_bag, provenance_identity["output_topic_counts"])  # type: ignore[arg-type]
    references = load_references(reference, cameras)
    return provenance_identity, Selection(cameras, imus, references, audit)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("preflight", "export", "audit"), default="preflight")
    parser.add_argument("--source-window-bag", type=Path, default=DEFAULT_WINDOW_BAG)
    parser.add_argument("--source-provenance", type=Path, default=DEFAULT_PROVENANCE)
    parser.add_argument("--prefix-root", type=Path, default=DEFAULT_PREFIX_ROOT)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        profile.audit_sealed_invocation_environment()
        expected_paths = (DEFAULT_WINDOW_BAG, DEFAULT_PROVENANCE, DEFAULT_PREFIX_ROOT, DEFAULT_REFERENCE, DEFAULT_OUTPUT)
        observed_paths = (args.source_window_bag, args.source_provenance, args.prefix_root, args.reference, args.output)
        if observed_paths != expected_paths:
            raise ContractError("FROZEN_INPUT_OR_OUTPUT_PATH_OVERRIDE_FORBIDDEN")
        if args.action == "audit":
            decision = audit_exported_artifact(args.output)
            print(json.dumps({"status": "AUDIT_PASS", **decision}, sort_keys=True))
            return 0
        if args.output.exists() or args.output.is_symlink() or profile.NEW_SHARED_ATTEMPT.exists() or profile.NEW_SHARED_ATTEMPT.is_symlink():
            raise ContractError("OUTPUT_OR_EXPORT_ATTEMPT_ALREADY_EXISTS")
        export_attempt_identity = None
        if args.action == "export":
            attempt_record = build_export_attempt_record()
            _write_exclusive(profile.NEW_SHARED_ATTEMPT, profile.canonical_json_bytes(attempt_record))
            export_attempt_identity = _identity(profile.NEW_SHARED_ATTEMPT)
        provenance, selection = prepare(args.source_window_bag, args.source_provenance, args.reference)
        validate_prefix_rows(args.prefix_root, selection.cameras)
        if args.action == "preflight":
            print(json.dumps({"status": "PREFLIGHT_PASSED_NO_OUTPUT_WRITTEN", "scientific_role": profile.ROLE, "camera_count": len(selection.cameras), "reused_camera_count": PREFIX_CAMERA_COUNT, "new_camera_count": profile.NEW_CAMERA_COUNT, "imu_count": len(selection.imus), "reference_count": len(selection.references), "evaluation_grid_count": profile.SCORE_EVALUATION_GRID_COUNT}, sort_keys=True))
            return 0
        if export_attempt_identity is None:
            raise ContractError("SHARED_EXPORT_ATTEMPT_WAS_NOT_CLAIMED")
        manifest = write_artifact(args.output, args.source_window_bag, provenance, args.reference, args.prefix_root, selection, export_attempt_identity)
        audit_exported_artifact(args.output)
        print(json.dumps({"status": manifest["status"], "output": str(args.output)}, sort_keys=True))
        return 0
    except (ContractError, profile.ExtensionError, prior.ContractError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(f"CONTRACT_BLOCKED:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
