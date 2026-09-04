#!/usr/bin/env python3
"""Fail-closed one-shot HFNet-SLAM A02 long1801 headless supervisor v4.

This supervisor does not modify the frozen v3 entrypoint or official HFNet-
SLAM.  It adds a strict audit for the shared 4500..6300 input, a unique
contract/evidence/result namespace, run-local TensorRT cache staging, and
score-window-aware trajectory/keyframe gates.  ``preflight`` is read-only,
``freeze`` only creates a no-clobber contract, and only ``run`` may start the
ELF (exactly once, with no retry).
"""

from __future__ import annotations

import argparse
import bisect
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import struct
import sys
from typing import Any, Callable, Mapping, Optional, Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts import export_aqualoc_a02_shared_4500_6300_v1 as shared
from scripts import run_hfnet_slam_a02_full901_headless_v3 as v3

ROOT = _ROOT
SCHEMA = "aqua-fe-hfnet-slam-a02-long1801-headless-contract-v4"
PROFILE_SCHEMA = "aqua-fe-hfnet-slam-a02-long1801-headless-profile-v4"
RESULT_SCHEMA = "aqua-fe-hfnet-slam-a02-long1801-headless-result-v4"
ROLE = "POST_STOP_EXPLORATORY_PUBLISHED_BASELINE_LONG_WINDOW_NOT_CONFIRMATORY"
RC_OK, RC_FAILED, RC_BLOCKED = 0, 1, 2

V3_RUNNER = ROOT / "scripts/run_hfnet_slam_a02_full901_headless_v3.py"
V3_RUNNER_SHA256 = "b5ad8731f7d50ed2dd5eb0e435f95ed2db9e854474c6d559ab6d21bcec4675a2"
SHARED_EXPORTER = ROOT / "scripts/export_aqualoc_a02_shared_4500_6300_v1.py"
SHARED_EXPORTER_SHA256 = "c3c79bef0e96a54dca7fe559e4f5a4d4646ad4e4e73828a13ca5aa603e5e361f"
BRIDGE = ROOT / "scripts/bridge_hfnet_world_body_to_vins_csv_v1.py"
BRIDGE_SHA256 = "5b14003204da7724f5a750bd0f6538575517aae7e21202c9b468a2716a84d2a1"
EVALUATION_CONFIG = ROOT / "configs/published_baselines/hfnet_aqualoc_a02_body_T_cam0_v1.yaml"
# Filled after the deliberately tiny frozen config is finalised.
EVALUATION_CONFIG_SHA256 = "a76c728b31d47c3a87f54c465fb581007ed2da2b7d7d84df81dbde93e9a886c1"

DEFAULT_SHARED_ROOT = Path("/mnt/data/AQUA-FE_WS/logs/published_shared_baselines_v1/a02_4500_6300_shared_r1")
DEFAULT_RESULT = ROOT / "logs/published_hfnet_slam_v4/post_stop_a02_long1801_headless/runs/aqualoc_a02_4500_6300_headless_r1"
DEFAULT_EVIDENCE = ROOT / "logs/published_hfnet_slam_v4/post_stop_a02_long1801_headless/drivers/aqualoc_a02_4500_6300_headless_r1"
DEFAULT_CONTRACT = ROOT / "papers/hfnet_slam_a02_long1801_headless_run_contract_v4.json"
DEFAULT_BRIDGE_OUTPUT = ROOT / "logs/published_hfnet_slam_v4/post_stop_a02_long1801_headless/bridges/aqualoc_a02_4500_6300_hfnet_world_T_body_v1.csv"

EXPECTED_CAMERA_COUNT = 1_801
EXPECTED_IMU_COUNT = 17_987
EXPECTED_REFERENCE_COUNT = 46
SCORE_GLOBAL_FIRST, SCORE_GLOBAL_LAST = 5_400, 6_300
MIN_TRAJECTORY_POSES = 30
MIN_TRAJECTORY_SCORE_POSES = 30
MIN_TRAJECTORY_SCORE_SPAN_S = 10.0
MIN_KEYFRAMES = 2
MIN_SCORE_KEYFRAMES = 1
MAX_HFNET_CAMERA_ASSOCIATION_ERROR_NS = 256


class ContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class Spec:
    official_root: Path = v3.DEFAULT_OFFICIAL_ROOT
    binary: Path = v3.DEFAULT_BINARY
    build_manifest: Path = v3.DEFAULT_BUILD_MANIFEST
    official_library: Path = v3.DEFAULT_LIBRARY
    official_entry: Path = v3.DEFAULT_ENTRY_SOURCE
    headless_source: Path = v3.DEFAULT_HARNESS_SOURCE
    config: Path = v3.DEFAULT_CONFIG
    onnx: Path = v3.DEFAULT_ONNX
    cache_seed: Path = v3.DEFAULT_CACHE_SEED
    shared_root: Path = DEFAULT_SHARED_ROOT
    result: Path = DEFAULT_RESULT
    evidence: Path = DEFAULT_EVIDENCE
    contract: Path = DEFAULT_CONTRACT
    bridge_output: Path = DEFAULT_BRIDGE_OUTPUT
    expected: Mapping[str, Mapping[str, object]] = field(default_factory=lambda: v3.EXPECTED)
    timeout_seconds: int = v3.prior.TIMEOUT_SECONDS

    @property
    def sequence(self) -> Path:
        return self.shared_root / "hfnet"


DEFAULT_SPEC = Spec()
Probe = Callable[[Sequence[str], Optional[Mapping[str, str]], Optional[Path]], v3.CommandResult]
Execute = Callable[[Sequence[str], Mapping[str, str], Optional[Path], int], v3.CommandResult]


def canonical_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"


def absolute(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def absent(path: Path) -> bool:
    return not path.exists() and not path.is_symlink()


def identity(path: Path) -> dict[str, object]:
    try:
        return v3.identity(path)
    except v3.ContractError as error:
        raise ContractError(str(error)) from error


def _require_identity(path: Path, expected_sha256: str, label: str) -> dict[str, object]:
    row = identity(path)
    if row["sha256"] != expected_sha256:
        raise ContractError(f"FROZEN_IDENTITY_MISMATCH:{label}")
    return row


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label}_NOT_OBJECT")
    return value


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ContractError(f"{label}_NOT_LIST")
    return value


def _png_header(path: Path) -> tuple[int, int, int, int]:
    with path.open("rb") as stream:
        header = stream.read(33)
    if len(header) != 33 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ContractError(f"INVALID_PNG_HEADER:{path}")
    width, height = struct.unpack(">II", header[16:24])
    return width, height, header[24], header[25]


def _load_shared_manifest(root: Path) -> tuple[Mapping[str, object], dict[str, object]]:
    path = root / "conversion_manifest.json"
    manifest_identity = identity(path)
    payload = path.read_bytes()
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ContractError("SHARED_MANIFEST_INVALID_JSON") from error
    if payload != shared.canonical_json_bytes(value):
        raise ContractError("SHARED_MANIFEST_NOT_CANONICAL")
    return _mapping(value, "SHARED_MANIFEST"), manifest_identity


def audit_shared_input(root: Path) -> dict[str, Any]:
    root = absolute(root)
    if not root.is_dir() or root.is_symlink():
        raise ContractError("SHARED_ROOT_NOT_NONSYMLINK_DIRECTORY")
    manifest, manifest_identity = _load_shared_manifest(root)
    if manifest.get("schema_version") != shared.SCHEMA_VERSION or manifest.get("status") != shared.STATUS_EXPORTED:
        raise ContractError("SHARED_MANIFEST_SCHEMA_OR_STATUS_MISMATCH")

    window = _mapping(manifest.get("window"), "SHARED_WINDOW")
    expected_window = {
        "feed_global_camera_indices_inclusive": [4_500, 6_300],
        "camera_count": EXPECTED_CAMERA_COUNT,
        "preroll_global_camera_indices_inclusive": [4_500, 5_399],
        "score_global_camera_indices_inclusive": [SCORE_GLOBAL_FIRST, SCORE_GLOBAL_LAST],
        "score_reference_global_indices": list(range(SCORE_GLOBAL_FIRST, SCORE_GLOBAL_LAST + 1, 20)),
        "score_reference_count": EXPECTED_REFERENCE_COUNT,
    }
    if any(window.get(key) != value for key, value in expected_window.items()):
        raise ContractError("SHARED_WINDOW_CONTRACT_MISMATCH")

    claims = _mapping(manifest.get("claims"), "SHARED_CLAIMS")
    expected_claims = {"hfnet_started": False, "anyfeature_started": False, "aqua_fe_started": False, "official_source_modified": False, "accuracy_result_generated": False}
    if any(claims.get(key) is not value for key, value in expected_claims.items()):
        raise ContractError("SHARED_CLAIMS_MISMATCH")
    views = _mapping(manifest.get("views"), "SHARED_VIEWS")
    if views.get("canonical_png_root") != "shared/cam0/data" or views.get("canonical_times") != "shared/cam0_times.txt" or views.get("reference_tum") != "shared/reference_proxy.tum" or views.get("hfnet_euroc_root") != "hfnet":
        raise ContractError("SHARED_VIEW_PATH_MISMATCH")

    source = _mapping(manifest.get("source"), "SHARED_SOURCE")
    raw = _mapping(source.get("canonical_raw_archive"), "SHARED_RAW")
    if raw.get("size_bytes") != shared.RAW_TAR_SIZE_BYTES or raw.get("sha256") != shared.RAW_TAR_SHA256 or raw.get("converter_relative_path") != shared.RAW_CONVERTER_RELATIVE or raw.get("converter_sha256") != shared.RAW_CONVERTER_SHA256:
        raise ContractError("SHARED_UPSTREAM_RAW_IDENTITY_MISMATCH")
    full_catalog = _mapping(source.get("known_full_bag_cross_source_catalog_not_producer_provenance"), "SHARED_FULL_BAG_CATALOG")
    if full_catalog.get("size_bytes") != shared.FULL_BAG_SIZE_BYTES or full_catalog.get("sha256") != shared.FULL_BAG_SHA256 or full_catalog.get("topic_counts") != shared.FULL_BAG_TOPIC_COUNTS:
        raise ContractError("SHARED_FULL_BAG_CROSS_SOURCE_CATALOG_MISMATCH")
    provenance = _mapping(source.get("provenance"), "SHARED_PROVENANCE")
    producer = _mapping(provenance.get("producer_record"), "SHARED_PRODUCER_RECORD")
    if producer.get("schema_version") != "aqua-fe-aqualoc-canonical-raw-window-bag-manifest-v1" or producer.get("status") != "PASS":
        raise ContractError("SHARED_PRODUCER_SCHEMA_OR_STATUS_MISMATCH")
    producer_provenance = _mapping(producer.get("provenance"), "SHARED_PRODUCER_PROVENANCE")
    producer_raw = _mapping(producer_provenance.get("raw_tar"), "SHARED_PRODUCER_RAW")
    producer_gt = _mapping(producer_provenance.get("gt"), "SHARED_PRODUCER_GT")
    producer_converter = _mapping(producer_provenance.get("converter"), "SHARED_PRODUCER_CONVERTER")
    if producer_raw.get("size", producer_raw.get("size_bytes")) != shared.RAW_TAR_SIZE_BYTES or producer_raw.get("sha", producer_raw.get("sha256")) != shared.RAW_TAR_SHA256:
        raise ContractError("SHARED_PRODUCER_RAW_IDENTITY_MISMATCH")
    if producer_gt.get("size", producer_gt.get("size_bytes")) != shared.REFERENCE_SIZE_BYTES or producer_gt.get("sha", producer_gt.get("sha256")) != shared.REFERENCE_SHA256:
        raise ContractError("SHARED_PRODUCER_GT_IDENTITY_MISMATCH")
    if producer_converter.get("sha", producer_converter.get("sha256")) != shared.RAW_CONVERTER_SHA256 or not str(producer_converter.get("path", "")).endswith(shared.RAW_CONVERTER_RELATIVE):
        raise ContractError("SHARED_PRODUCER_CONVERTER_IDENTITY_MISMATCH")
    producer_selection = _mapping(producer.get("selection"), "SHARED_PRODUCER_SELECTION")
    if producer_selection.get("camera_global_start_index") != 4_500 or producer_selection.get("camera_global_end_index_inclusive") != 6_300 or producer_selection.get("image_count_expected") != EXPECTED_CAMERA_COUNT or producer_selection.get("imu_margin_ns") != 250_000_000 or "imu_rule_closed_interval" not in producer_selection:
        raise ContractError("SHARED_PRODUCER_SELECTION_MISMATCH")
    producer_semantics = _mapping(producer.get("semantics"), "SHARED_PRODUCER_SEMANTICS")
    if producer_semantics.get("header_stamp") != "raw_csv_integer_ns" or producer_semantics.get("record_stamp_equals_header") is not True or producer_semantics.get("no_time_shift") is not True or producer_semantics.get("image_encoding") != "mono8" or producer_semantics.get("gt_pose") != "world_T_camera":
        raise ContractError("SHARED_PRODUCER_SEMANTICS_MISMATCH")
    producer_output = _mapping(producer.get("output"), "SHARED_PRODUCER_OUTPUT")
    producer_topic_counts = _mapping(producer_output.get("topic_counts"), "SHARED_PRODUCER_TOPIC_COUNTS")
    if producer_output.get("compression") != "bz2" or producer_topic_counts.get(shared.CAMERA_TOPIC) != EXPECTED_CAMERA_COUNT or not isinstance(producer_topic_counts.get(shared.IMU_TOPIC), int) or producer_topic_counts.get(shared.IMU_TOPIC) < EXPECTED_IMU_COUNT:
        raise ContractError("SHARED_PRODUCER_OUTPUT_MISMATCH")
    checks = _mapping(producer.get("checks"), "SHARED_PRODUCER_CHECKS")
    if not checks or any(value is not True for value in checks.values()):
        raise ContractError("SHARED_PRODUCER_CHECKS_NOT_ALL_TRUE")
    derived = _mapping(source.get("derived_window_bag"), "SHARED_DERIVED_WINDOW_BAG")
    provenance_derived = _mapping(provenance.get("derived_window_bag"), "SHARED_PROVENANCE_DERIVED_WINDOW_BAG")
    if dict(derived) != dict(provenance_derived) or provenance.get("output_topic_counts") != producer_topic_counts:
        raise ContractError("SHARED_DERIVED_WINDOW_PROVENANCE_MISMATCH")
    reference = _mapping(manifest.get("reference"), "SHARED_REFERENCE")
    reference_identity = _mapping(reference.get("identity"), "SHARED_REFERENCE_IDENTITY")
    if reference_identity.get("size_bytes") != shared.REFERENCE_SIZE_BYTES or reference_identity.get("sha256") != shared.REFERENCE_SHA256 or reference.get("pose_convention") != "world_T_camera" or reference.get("target_rows") != EXPECTED_REFERENCE_COUNT:
        raise ContractError("SHARED_REFERENCE_CONTRACT_MISMATCH")
    topic_audit = _mapping(manifest.get("topic_audit"), "SHARED_TOPIC_AUDIT")
    camera_topic_audit = _mapping(topic_audit.get(shared.CAMERA_TOPIC), "SHARED_CAMERA_TOPIC_AUDIT")
    imu_topic_audit = _mapping(topic_audit.get(shared.IMU_TOPIC), "SHARED_IMU_TOPIC_AUDIT")
    if camera_topic_audit.get("message_type") != shared.CAMERA_TYPE or camera_topic_audit.get("message_count") != EXPECTED_CAMERA_COUNT or imu_topic_audit.get("message_type") != shared.IMU_TYPE or not isinstance(imu_topic_audit.get("message_count"), int) or imu_topic_audit.get("message_count") < EXPECTED_IMU_COUNT:
        raise ContractError("SHARED_TOPIC_AUDIT_MISMATCH")

    camera = _mapping(manifest.get("camera"), "SHARED_CAMERA")
    images = _list(camera.get("images"), "SHARED_IMAGES")
    expected_camera_metadata = {"topic": shared.CAMERA_TOPIC, "message_type": shared.CAMERA_TYPE, "width": shared.CAMERA_WIDTH, "height": shared.CAMERA_HEIGHT, "encoding": shared.CAMERA_ENCODING, "first_header_ns": shared.EXPECTED_FIRST_CAMERA_NS, "boundary_header_ns": shared.EXPECTED_BOUNDARY_CAMERA_NS, "last_header_ns": shared.EXPECTED_LAST_CAMERA_NS, "newly_encoded_relative_indices_inclusive": [901, 1800]}
    if len(images) != EXPECTED_CAMERA_COUNT or any(camera.get(key) != value for key, value in expected_camera_metadata.items()):
        raise ContractError("SHARED_CAMERA_CONTRACT_MISMATCH")
    prefix = _mapping(camera.get("prefix_reuse"), "SHARED_PREFIX_REUSE")
    if prefix.get("manifest_sha256") != shared.PREFIX_MANIFEST_SHA256 or prefix.get("camera_count") != shared.PREFIX_CAMERA_COUNT:
        raise ContractError("SHARED_PREFIX_REUSE_CONTRACT_MISMATCH")
    link_modes = _mapping(views.get("hfnet_camera_link_modes"), "SHARED_HFNET_LINK_MODES")
    if set(link_modes) - {"hardlink", "copy"} or not link_modes or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in link_modes.values()) or sum(link_modes.values()) != EXPECTED_CAMERA_COUNT:
        raise ContractError("SHARED_HFNET_LINK_MODES_MISMATCH")

    timestamps: list[int] = []
    canonical_names: set[str] = set()
    hfnet_names: set[str] = set()
    aggregate = hashlib.sha256()
    for relative, raw_row in enumerate(images):
        row = _mapping(raw_row, f"SHARED_IMAGE_{relative}")
        stamp = row.get("raw_header_ns")
        if isinstance(stamp, bool) or not isinstance(stamp, int):
            raise ContractError(f"SHARED_IMAGE_INVALID_STAMP:{relative}")
        if row.get("relative_index") != relative or row.get("global_source_index") != 4_500 + relative:
            raise ContractError(f"SHARED_IMAGE_INDEX_MISMATCH:{relative}")
        source_hash = row.get("source_pixel_sha256")
        expected_modes = {"hardlink", "copy"} if relative < shared.PREFIX_CAMERA_COUNT else {"encoded_new_lossless"}
        if not isinstance(source_hash, str) or len(source_hash) != 64 or any(character not in "0123456789abcdef" for character in source_hash) or row.get("materialization") not in expected_modes:
            raise ContractError(f"SHARED_IMAGE_PROVENANCE_MISMATCH:{relative}")
        relative_path = f"shared/cam0/data/{stamp}.png"
        if row.get("relative_path") != relative_path:
            raise ContractError(f"SHARED_IMAGE_PATH_MISMATCH:{relative}")
        png_hash, png_size = row.get("png_sha256"), row.get("png_size_bytes")
        if not isinstance(png_hash, str) or len(png_hash) != 64 or isinstance(png_size, bool) or not isinstance(png_size, int) or png_size <= 0:
            raise ContractError(f"SHARED_IMAGE_IDENTITY_INVALID:{relative}")
        canonical_path = root / relative_path
        hfnet_path = root / "hfnet/mav0/cam0/data" / f"{stamp}.png"
        canonical_identity, hfnet_identity = identity(canonical_path), identity(hfnet_path)
        if canonical_identity["sha256"] != png_hash or canonical_identity["size_bytes"] != png_size or hfnet_identity["sha256"] != png_hash or hfnet_identity["size_bytes"] != png_size:
            raise ContractError(f"SHARED_OR_HFNET_PNG_IDENTITY_MISMATCH:{relative}")
        if _png_header(canonical_path) != (shared.CAMERA_WIDTH, shared.CAMERA_HEIGHT, 8, 0) or _png_header(hfnet_path) != (shared.CAMERA_WIDTH, shared.CAMERA_HEIGHT, 8, 0):
            raise ContractError(f"SHARED_OR_HFNET_PNG_SCHEMA_MISMATCH:{relative}")
        name = f"{stamp}.png"
        canonical_names.add(name)
        hfnet_names.add(name)
        timestamps.append(stamp)
        aggregate.update(f"{relative},{stamp},{png_hash},{png_size}\n".encode("ascii"))
    if any(right <= left for left, right in zip(timestamps, timestamps[1:])) or timestamps != [int(_mapping(row, "IMAGE").get("raw_header_ns")) for row in images]:
        raise ContractError("SHARED_CAMERA_TIMESTAMPS_NOT_STRICT")
    if timestamps[0] != shared.EXPECTED_FIRST_CAMERA_NS or timestamps[900] != shared.EXPECTED_BOUNDARY_CAMERA_NS or timestamps[-1] != shared.EXPECTED_LAST_CAMERA_NS:
        raise ContractError("SHARED_CAMERA_TIMESTAMP_ENDPOINT_MISMATCH")
    canonical_observed = {path.name for path in (root / "shared/cam0/data").iterdir() if path.is_file()}
    hfnet_observed = {path.name for path in (root / "hfnet/mav0/cam0/data").iterdir() if path.is_file()}
    if canonical_observed != canonical_names or hfnet_observed != hfnet_names:
        raise ContractError("SHARED_CAMERA_DIRECTORY_FILESET_MISMATCH")

    shared_times_path, hfnet_times_path = root / "shared/cam0_times.txt", root / "hfnet/cam0_times.txt"
    camera_csv_path, imu_csv_path = root / "hfnet/mav0/cam0/data.csv", root / "hfnet/mav0/imu0/data.csv"
    reference_tum_path, reference_mapping_path = root / "shared/reference_proxy.tum", root / "shared/reference_mapping.csv"
    semantic_paths = {"shared_times": shared_times_path, "hfnet_times": hfnet_times_path, "hfnet_camera_csv": camera_csv_path, "hfnet_imu_csv": imu_csv_path, "reference_tum": reference_tum_path, "reference_mapping": reference_mapping_path}
    semantic_identities = {name: identity(path) for name, path in semantic_paths.items()}
    times_payload = ("\n".join(map(str, timestamps)) + "\n").encode("ascii")
    if shared_times_path.read_bytes() != times_payload or hfnet_times_path.read_bytes() != times_payload:
        raise ContractError("SHARED_OR_HFNET_TIMES_PAYLOAD_MISMATCH")
    camera_csv = ["#timestamp [ns],filename"] + [f"{stamp},{stamp}.png" for stamp in timestamps]
    if camera_csv_path.read_bytes() != "\n".join(camera_csv).encode("ascii"):
        raise ContractError("HFNET_CAMERA_CSV_MISMATCH")

    imu = _mapping(manifest.get("imu"), "SHARED_IMU")
    expected_imu = {"topic": shared.IMU_TOPIC, "message_type": shared.IMU_TYPE, "global_indices_inclusive": [shared.GLOBAL_IMU_FIRST, shared.GLOBAL_IMU_LAST], "count": EXPECTED_IMU_COUNT, "time_transform": f"output_ns=raw_header_ns+{shared.IMU_SHIFT_NS}", "first_raw_header_ns": shared.EXPECTED_FIRST_IMU_RAW_NS, "last_raw_header_ns": shared.EXPECTED_LAST_IMU_RAW_NS, "first_output_header_ns": shared.EXPECTED_FIRST_IMU_RAW_NS + shared.IMU_SHIFT_NS, "last_output_header_ns": shared.EXPECTED_LAST_IMU_RAW_NS + shared.IMU_SHIFT_NS, "brackets_camera": True}
    if any(imu.get(key) != value for key, value in expected_imu.items()):
        raise ContractError("SHARED_IMU_CONTRACT_MISMATCH")
    imu_lines = imu_csv_path.read_text(encoding="ascii").splitlines()
    expected_header = "#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],w_RS_S_z [rad s^-1],a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],a_RS_S_z [m s^-2]"
    if len(imu_lines) != EXPECTED_IMU_COUNT + 1 or imu_lines[0] != expected_header:
        raise ContractError("HFNET_IMU_CSV_COUNT_OR_HEADER_MISMATCH")
    imu_stamps: list[int] = []
    for index, line in enumerate(imu_lines[1:]):
        fields = line.split(",")
        if len(fields) != 7:
            raise ContractError(f"HFNET_IMU_FIELD_COUNT_MISMATCH:{index}")
        try:
            stamp = int(fields[0])
            values = [float(value) for value in fields[1:]]
        except ValueError as error:
            raise ContractError(f"HFNET_IMU_NONNUMERIC:{index}") from error
        if str(stamp) != fields[0] or not all(math.isfinite(value) for value in values):
            raise ContractError(f"HFNET_IMU_INVALID_VALUE:{index}")
        imu_stamps.append(stamp)
    if any(right <= left for left, right in zip(imu_stamps, imu_stamps[1:])) or imu_stamps[0] != expected_imu["first_output_header_ns"] or imu_stamps[-1] != expected_imu["last_output_header_ns"] or not (imu_stamps[0] <= timestamps[0] and imu_stamps[-1] >= timestamps[-1]):
        raise ContractError("HFNET_IMU_TIMESTAMP_GATE_FAILED")

    mapping = _list(reference.get("mapping"), "SHARED_REFERENCE_MAPPING")
    expected_indices = list(range(SCORE_GLOBAL_FIRST, SCORE_GLOBAL_LAST + 1, 20))
    expected_mapping = [{"global_camera_index": index, "header_ns": timestamps[index - 4_500]} for index in expected_indices]
    if mapping != expected_mapping:
        raise ContractError("SHARED_REFERENCE_MAPPING_MISMATCH")
    expected_mapping_csv = "global_camera_index,header_ns,role\n" + "".join(f"{row['global_camera_index']},{row['header_ns']},SCORE\n" for row in expected_mapping)
    if reference_mapping_path.read_text(encoding="ascii") != expected_mapping_csv:
        raise ContractError("SHARED_REFERENCE_MAPPING_CSV_MISMATCH")
    reference_lines = reference_tum_path.read_text(encoding="ascii").splitlines()
    if len(reference_lines) != EXPECTED_REFERENCE_COUNT:
        raise ContractError("SHARED_REFERENCE_TUM_COUNT_MISMATCH")
    for index, (line, expected) in enumerate(zip(reference_lines, expected_mapping)):
        fields = line.split()
        try:
            stamp_ns = int(Decimal(fields[0]) * Decimal(1_000_000_000))
            values = [float(value) for value in fields[1:]]
        except (InvalidOperation, ValueError) as error:
            raise ContractError(f"SHARED_REFERENCE_TUM_INVALID:{index}") from error
        if len(fields) != 8 or stamp_ns != expected["header_ns"] or not all(math.isfinite(value) for value in values) or not 0.99 <= math.sqrt(sum(value * value for value in values[3:7])) <= 1.01:
            raise ContractError(f"SHARED_REFERENCE_TUM_GATE_FAILED:{index}")

    return {"manifest": manifest_identity, "semantic_files": semantic_identities, "camera_count": len(timestamps), "camera_timestamps_ns": timestamps, "camera_first_ns": timestamps[0], "score_first_ns": timestamps[900], "score_last_ns": timestamps[-1], "camera_last_ns": timestamps[-1], "imu_count": len(imu_stamps), "reference_count": len(reference_lines), "image_aggregate_sha256": aggregate.hexdigest(), "views_rehashed": ["shared", "hfnet"]}


def audit_official_stack(spec: Spec, probe: Probe = v3.default_probe) -> dict[str, Any]:
    paths = {"binary": spec.binary, "build_manifest": spec.build_manifest, "official_library": spec.official_library, "config": spec.config, "onnx": spec.onnx, "cache_seed": spec.cache_seed, "official_entry": spec.official_entry, "headless_source": spec.headless_source}
    identities = {name: identity(path) for name, path in paths.items()}
    for name, expected in spec.expected.items():
        if any(identities[name].get(key) != value for key, value in expected.items()):
            raise ContractError(f"FROZEN_IDENTITY_MISMATCH:{name}")
    if not (spec.binary.stat().st_mode & stat.S_IXUSR) or spec.binary.read_bytes()[:4] != b"\x7fELF":
        raise ContractError("HEADLESS_BINARY_NOT_EXECUTABLE_ELF")
    git_commands = {"commit": ["git", "-C", str(spec.official_root), "rev-parse", "HEAD^{commit}"], "tree": ["git", "-C", str(spec.official_root), "rev-parse", "HEAD^{tree}"], "origin": ["git", "-C", str(spec.official_root), "remote", "get-url", "origin"], "status": ["git", "-C", str(spec.official_root), "status", "--porcelain=v1", "--untracked-files=no"]}
    git = {name: probe(command, None, None) for name, command in git_commands.items()}
    if any(row.returncode != 0 or row.timed_out for row in git.values()) or git["commit"].stdout.strip() != v3.COMMIT or git["tree"].stdout.strip() != v3.TREE or git["origin"].stdout.strip() != v3.ORIGIN or git["status"].stdout.strip():
        raise ContractError("OFFICIAL_SOURCE_IDENTITY_OR_CLEANLINESS_MISMATCH")
    harness = spec.headless_source.read_text(encoding="utf-8")
    if any(token not in harness for token in (": System(settings_file, sensor, false, init_frame)", f'#include "{absolute(spec.official_entry)}"', "#define System HeadlessSystem")) or "TrackMonocular(" in harness:
        raise ContractError("HEADLESS_SINGLE_DELTA_STATIC_AUDIT_FAILED")
    config = spec.config.read_text(encoding="utf-8")
    tokens = ('Extractor.type: "HFNetRT"', "Extractor.scaleFactor: 1.2", "Extractor.nLevels: 4", "Extractor.nFeatures: 675", "Extractor.threshold: 0.01", "loopClosing: 1", f'Extractor.modelPath: "{absolute(spec.onnx.parent)}/"')
    if any(config.count(token) != 1 for token in tokens):
        raise ContractError("FROZEN_CONFIG_TOKEN_MISMATCH")
    build = json.loads(spec.build_manifest.read_text(encoding="utf-8"))
    if build.get("semantic_delta") != {"all_other_entry_logic": "included_from_frozen_official_source", "system_constructor_bUseViewer": False}:
        raise ContractError("BUILD_MANIFEST_SEMANTIC_DELTA_MISMATCH")
    ldd = probe(["ldd", str(absolute(spec.binary))], v3.runtime_environment(spec), None)
    resolved, missing = v3._parse_ldd(ldd.stdout)
    hfnet = [absolute(Path(path)) for name, path in resolved.items() if name.startswith("libHFNet_SLAM.so")]
    if ldd.returncode != 0 or missing or hfnet != [absolute(spec.official_library)]:
        raise ContractError("HEADLESS_BINARY_LINKAGE_MISMATCH")
    support = {"v4_runner": identity(Path(__file__)), "v3_runner": _require_identity(V3_RUNNER, V3_RUNNER_SHA256, "v3_runner"), "shared_exporter": _require_identity(SHARED_EXPORTER, SHARED_EXPORTER_SHA256, "shared_exporter"), "world_body_bridge": _require_identity(BRIDGE, BRIDGE_SHA256, "world_body_bridge"), "evaluation_config": _require_identity(EVALUATION_CONFIG, EVALUATION_CONFIG_SHA256, "evaluation_config")}
    return {"baseline": {"commit": v3.COMMIT, "tree": v3.TREE, "origin": v3.ORIGIN}, "identities": identities, "support_identities": support, "headless_boundary": {"viewer_enabled": False, "official_entry_included": True, "algorithm_or_threshold_modified": False}, "runtime_cache_policy": {"seed": identities["cache_seed"], "run_local_copy_required": True, "shared_cache_writeback_forbidden": True}, "runtime": {"display_required": False, "official_library_resolved": str(hfnet[0])}}


def audit_profile(spec: Spec, probe: Probe = v3.default_probe) -> dict[str, Any]:
    return {"schema_version": PROFILE_SCHEMA, "scientific_role": ROLE, "official": audit_official_stack(spec, probe), "input": audit_shared_input(spec.shared_root), "score_gate": {"global_camera_indices_inclusive": [SCORE_GLOBAL_FIRST, SCORE_GLOBAL_LAST], "hfnet_double_timestamp_camera_association_max_abs_error_ns": MAX_HFNET_CAMERA_ASSOCIATION_ERROR_NS, "association_policy": "unique nearest frozen shared camera timestamp; associated relative indices strictly increasing; score membership by associated global camera index", "output_timestamps_or_poses_modified": False, "minimum_trajectory_score_poses": MIN_TRAJECTORY_SCORE_POSES, "minimum_trajectory_score_span_s": MIN_TRAJECTORY_SCORE_SPAN_S, "minimum_keyframes": MIN_KEYFRAMES, "minimum_score_keyframes": MIN_SCORE_KEYFRAMES}}


def preflight(spec: Spec = DEFAULT_SPEC, *, probe: Probe = v3.default_probe) -> dict[str, Any]:
    errors: list[str] = []
    profile = None
    try:
        profile = audit_profile(spec, probe)
    except (ContractError, v3.ContractError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        errors.append(str(error))
    reservations = {"contract_absent": absent(spec.contract), "evidence_absent": absent(spec.evidence), "result_absent": absent(spec.result), "bridge_output_absent": absent(spec.bridge_output), "bridge_manifest_absent": absent(Path(str(spec.bridge_output) + ".manifest.json"))}
    if not all(reservations.values()):
        errors.append("OUTPUT_RESERVATION_NOT_EMPTY")
    return {"schema_version": PROFILE_SCHEMA, "status": "PREFLIGHT_READY" if not errors else "PREFLIGHT_BLOCKED", "ready": not errors, "errors": errors, "profile": profile, "reservations": reservations, "claims": {"slam_started": False, "filesystem_writes": False}}


def build_contract(profile: Mapping[str, Any], spec: Spec) -> dict[str, Any]:
    return {"schema_version": SCHEMA, "scientific_role": ROLE, "frozen_profile": dict(profile), "frozen_profile_sha256": hashlib.sha256(canonical_json(profile).encode()).hexdigest(), "execution_policy": {"maximum_process_starts": 1, "retry": False, "viewer": False, "official_algorithm_or_source_modification": False, "cache": "copy seed to run-local model directory; record pre/post SHA; never write back", "trajectory_gate": "RC0 plus valid world_T_body trajectory and keyframe files with frozen score-window support"}, "paths": {"contract": str(absolute(spec.contract)), "evidence": str(absolute(spec.evidence)), "result": str(absolute(spec.result)), "raw_trajectory": str(absolute(spec.result / "trajectory.txt")), "raw_keyframes": str(absolute(spec.result / "trajectory_keyframe.txt")), "reserved_vins_csv_bridge_output": str(absolute(spec.bridge_output)), "reserved_vins_csv_bridge_manifest": str(absolute(Path(str(spec.bridge_output) + ".manifest.json")))}}


def freeze(spec: Spec = DEFAULT_SPEC, *, probe: Probe = v3.default_probe) -> dict[str, Any]:
    decision = preflight(spec, probe=probe)
    if not decision["ready"]:
        return {**decision, "return_code": RC_BLOCKED, "status": "FREEZE_BLOCKED"}
    try:
        v3.write_exclusive(spec.contract, canonical_json(build_contract(decision["profile"], spec)).encode())
    except (OSError, FileExistsError) as error:
        return {**decision, "return_code": RC_BLOCKED, "status": "FREEZE_BLOCKED", "errors": [*decision["errors"], str(error)]}
    return {"schema_version": SCHEMA, "status": "CONTRACT_FROZEN_NO_RUN_STARTED", "return_code": RC_OK, "contract": identity(spec.contract), "slam_started": False}


def _parse_trajectory(path: Path, camera_timestamps_ns: Sequence[int], *, keyframes: bool) -> dict[str, Any]:
    result: dict[str, Any] = {"exists": False, "identity": None, "pose_count": 0, "score_pose_count": 0, "strictly_increasing_timestamps": False, "finite_valid_world_T_body_rows": False, "all_rows_uniquely_associated_to_camera": False, "association_max_abs_error_ns": None, "associated_first_relative_camera_index": None, "associated_last_relative_camera_index": None, "associated_max_camera_index_gap": None, "associated_skipped_camera_count": None, "span_seconds": None, "score_span_seconds": None, "gate_pass": False, "errors": []}
    if len(camera_timestamps_ns) != EXPECTED_CAMERA_COUNT or any(right <= left for left, right in zip(camera_timestamps_ns, camera_timestamps_ns[1:])):
        result["errors"] = ["invalid_frozen_camera_timestamp_grid"]
        return result
    try:
        resolved_path = path.expanduser().resolve(strict=True)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(resolved_path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise ContractError("TRAJECTORY_NOT_REGULAR_FILE")
            payload = stream.read()
        path_identity = {"path": str(resolved_path), "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        lines = payload.decode("ascii").splitlines()
        result["exists"] = True
        result["identity"] = path_identity
    except (ContractError, OSError, UnicodeError) as error:
        result["errors"] = [str(error)]
        return result
    if not lines or any(not line.strip() for line in lines):
        result["errors"] = ["empty_or_blank_row"]
        return result
    stamps: list[int] = []
    errors: list[str] = []
    for index, line in enumerate(lines):
        fields = line.split()
        if len(fields) != 8:
            errors.append(f"row_{index}_field_count")
            continue
        try:
            raw_stamp = Decimal(fields[0])
            values = [float(value) for value in fields[1:]]
        except (InvalidOperation, ValueError):
            errors.append(f"row_{index}_nonnumeric")
            continue
        if not raw_stamp.is_finite() or raw_stamp != raw_stamp.to_integral_value() or not all(math.isfinite(value) for value in values):
            errors.append(f"row_{index}_nonfinite_or_noninteger_stamp")
            continue
        norm = math.sqrt(sum(value * value for value in values[3:7]))
        if not 0.99 <= norm <= 1.01:
            errors.append(f"row_{index}_invalid_quaternion")
            continue
        stamps.append(int(raw_stamp))
    pose_rows_valid = not errors and len(stamps) == len(lines)
    strict = pose_rows_valid and all(right > left for left, right in zip(stamps, stamps[1:]))
    associations: list[int] = []
    association_errors: list[int] = []
    for row_index, stamp in enumerate(stamps):
        insertion = bisect.bisect_left(camera_timestamps_ns, stamp)
        candidates = [index for index in (insertion - 1, insertion) if 0 <= index < len(camera_timestamps_ns)]
        if not candidates:
            errors.append(f"row_{row_index}_no_camera_candidate")
            associations.append(-1)
            continue
        nearest = min(candidates, key=lambda index: (abs(camera_timestamps_ns[index] - stamp), index))
        error = abs(camera_timestamps_ns[nearest] - stamp)
        if error > MAX_HFNET_CAMERA_ASSOCIATION_ERROR_NS:
            errors.append(f"row_{row_index}_camera_association_error_gt_{MAX_HFNET_CAMERA_ASSOCIATION_ERROR_NS}ns")
            associations.append(-1)
            continue
        associations.append(nearest)
        association_errors.append(error)
    association_strict = len(associations) == len(stamps) and all(index >= 0 for index in associations) and all(right > left for left, right in zip(associations, associations[1:]))
    if all(index >= 0 for index in associations) and len(set(associations)) != len(associations):
        association_strict = False
        errors.append("camera_association_not_unique")
    if associations and not association_strict:
        errors.append("associated_camera_indices_not_strictly_increasing")
    score_rows = [(stamp, associated) for stamp, associated in zip(stamps, associations) if associated >= SCORE_GLOBAL_FIRST - shared.GLOBAL_CAMERA_FIRST]
    score_stamps = [stamp for stamp, _ in score_rows]
    gaps = [right - left for left, right in zip(associations, associations[1:])] if association_strict else []
    result.update({"pose_count": len(stamps), "score_pose_count": len(score_stamps), "strictly_increasing_timestamps": strict, "finite_valid_world_T_body_rows": pose_rows_valid, "all_rows_uniquely_associated_to_camera": association_strict, "association_max_abs_error_ns": max(association_errors) if association_errors else None, "associated_first_relative_camera_index": associations[0] if associations and associations[0] >= 0 else None, "associated_last_relative_camera_index": associations[-1] if associations and associations[-1] >= 0 else None, "associated_max_camera_index_gap": max(gaps) if gaps else 0, "associated_skipped_camera_count": sum(gap - 1 for gap in gaps) if gaps else 0, "span_seconds": (stamps[-1] - stamps[0]) / 1e9 if strict else None, "score_span_seconds": (score_stamps[-1] - score_stamps[0]) / 1e9 if len(score_stamps) >= 2 else 0.0, "errors": errors})
    if keyframes:
        result["gate_pass"] = bool(result["finite_valid_world_T_body_rows"] and strict and association_strict and len(stamps) >= MIN_KEYFRAMES and len(score_stamps) >= MIN_SCORE_KEYFRAMES)
    else:
        result["gate_pass"] = bool(result["finite_valid_world_T_body_rows"] and strict and association_strict and len(stamps) >= MIN_TRAJECTORY_POSES and len(score_stamps) >= MIN_TRAJECTORY_SCORE_POSES and result["score_span_seconds"] >= MIN_TRAJECTORY_SCORE_SPAN_S)
    return result


def run(spec: Spec = DEFAULT_SPEC, *, probe: Probe = v3.default_probe, execute: Execute = v3.default_execute) -> dict[str, Any]:
    try:
        frozen = json.loads(spec.contract.read_text(encoding="utf-8"))
        profile = audit_profile(spec, probe)
        if frozen != build_contract(profile, spec):
            raise ContractError("FROZEN_CONTRACT_OR_PROFILE_MISMATCH")
        if not all(absent(path) for path in (spec.evidence, spec.result, spec.bridge_output, Path(str(spec.bridge_output) + ".manifest.json"))):
            raise ContractError("RUN_OUTPUT_NO_CLOBBER")
        spec.evidence.mkdir(parents=True, exist_ok=False)
        v3.write_exclusive(spec.evidence / "frozen_contract.snapshot.json", canonical_json(frozen).encode())
        shared_cache_pre = identity(spec.cache_seed)
        staged = v3.stage_run_local_model(spec)
    except (ContractError, v3.ContractError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        return {"schema_version": RESULT_SCHEMA, "status": "CONTRACT_BLOCKED", "return_code": RC_BLOCKED, "evaluable": False, "errors": [str(error)], "execution": {"command_started": False, "process_start_count": 0}}

    command = v3.command_argv(spec, Path(staged["derived_config"]["path"]))
    execution = execute(command, v3.runtime_environment(spec), spec.evidence, spec.timeout_seconds)
    v3.write_exclusive(spec.evidence / "headless.stdout.log", execution.stdout.encode(errors="replace"))
    v3.write_exclusive(spec.evidence / "headless.stderr.log", execution.stderr.encode(errors="replace"))
    input_profile = profile["input"]
    trajectory = _parse_trajectory(spec.result / "trajectory.txt", input_profile["camera_timestamps_ns"], keyframes=False)
    keyframes = _parse_trajectory(spec.result / "trajectory_keyframe.txt", input_profile["camera_timestamps_ns"], keyframes=True)
    cache_errors: list[str] = []
    try:
        cache_post = identity(Path(staged["model_dir"]) / "HF-Net.cache")
        shared_cache_post = identity(spec.cache_seed)
        shared_unchanged = shared_cache_pre == shared_cache_post
    except (ContractError, OSError, v3.ContractError) as error:
        cache_post, shared_cache_post, shared_unchanged = None, None, False
        cache_errors.append(f"CACHE_POST_AUDIT_FAILED:{error}")
    passed = execution.returncode == 0 and not execution.timed_out and trajectory["gate_pass"] is True and keyframes["gate_pass"] is True and shared_unchanged
    errors = cache_errors + ([] if shared_unchanged else ["SHARED_CACHE_WAS_MODIFIED_OR_UNREADABLE"])
    result = {"schema_version": RESULT_SCHEMA, "scientific_role": ROLE, "status": "PASS_LONG1801_HEADLESS_SCORE_TRAJECTORY_GATE" if passed else "HEADLESS_RUN_FAILED_OR_UNUSABLE", "return_code": RC_OK if passed else RC_FAILED, "evaluable": passed, "errors": errors, "command_argv": command, "execution": {"command_started": True, "process_start_count": 1, "raw_returncode": execution.returncode, "timed_out": execution.timed_out}, "cache": {"shared_pre": shared_cache_pre, "shared_post": shared_cache_post, "shared_unchanged": shared_unchanged, "run_local_pre": staged["cache_pre"], "run_local_post": cache_post, "writeback_performed": False}, "immutables": {"profile_sha256": frozen["frozen_profile_sha256"], "run_local_onnx": staged["onnx"], "derived_config": staged["derived_config"]}, "gate": {"return_code_zero": execution.returncode == 0, "trajectory": trajectory, "keyframe_trajectory": keyframes}, "supervision": {"viewer_enabled": False, "algorithm_or_official_source_modified": False, "retry_performed": False}}
    v3.write_exclusive(spec.evidence / "run_result.json", canonical_json(result).encode())
    return result


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--action", choices=("preflight", "freeze", "run"), default="preflight")
    value.add_argument("--shared-root", type=Path, default=DEFAULT_SHARED_ROOT)
    value.add_argument("--result-directory", type=Path, default=DEFAULT_RESULT)
    value.add_argument("--evidence-directory", type=Path, default=DEFAULT_EVIDENCE)
    value.add_argument("--contract-json", type=Path, default=DEFAULT_CONTRACT)
    value.add_argument("--bridge-output", type=Path, default=DEFAULT_BRIDGE_OUTPUT)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    spec = replace(DEFAULT_SPEC, shared_root=args.shared_root, result=args.result_directory, evidence=args.evidence_directory, contract=args.contract_json, bridge_output=args.bridge_output)
    decision = preflight(spec) if args.action == "preflight" else freeze(spec) if args.action == "freeze" else run(spec)
    if args.action == "preflight":
        decision["return_code"] = RC_OK if decision["ready"] else RC_BLOCKED
    sys.stdout.write(canonical_json(decision))
    return int(decision["return_code"])


if __name__ == "__main__":
    raise SystemExit(main())
