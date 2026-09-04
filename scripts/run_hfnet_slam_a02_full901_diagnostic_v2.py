#!/usr/bin/env python3
"""Freeze and supervise one post-STOP HFNet-SLAM A02 full901 diagnostic.

This runner does not repair, patch, tune, or wrap any HFNet-SLAM algorithmic
call.  It validates a separately exported EuRoC-style input, freezes every
immutable identity and the exact official command, and then (only for the
``run`` action) starts the unchanged official executable once as a child
process.  Child-process isolation keeps the official empty-map
``SaveTrajectoryEuRoC`` SIGSEGV from killing the evidence writer; the raw
signal remains a failed, non-evaluable result.

The sealed prefix200 STOP remains a distinct historical result.  This full
window is a post-STOP diagnostic requested to determine whether the official
initialization guard can be satisfied later in the same frozen A02 stream.  It
cannot replace or backfill the prefix result.

Return codes:

* 0: profile/freeze succeeded, or the unique official run passed every gate;
* 1: the official child started but the run was unusable or failed a gate;
* 2: a no-clobber, provenance, identity, runtime, or contract gate blocked it.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import stat
import struct
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

_IMPORT_ROOT = Path(__file__).resolve().parents[1]
if str(_IMPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(_IMPORT_ROOT))

from scripts import export_aqualoc_to_hfnet_euroc_full_v2 as exporter


ROOT = Path(__file__).resolve().parents[1]

SCHEMA_VERSION = "aqua-fe-hfnet-a02-full901-post-stop-diagnostic-contract-r2"
RESULT_SCHEMA_VERSION = "aqua-fe-hfnet-a02-full901-post-stop-diagnostic-result-r2"
PROFILE_SCHEMA_VERSION = "aqua-fe-hfnet-a02-full901-post-stop-profile-r2"
SCIENTIFIC_ROLE = "POST_STOP_DIAGNOSTIC_NOT_REPLACEMENT_FOR_PREFIX_R1_STOP"
OFFICIAL_REPOSITORY = "https://github.com/LiuLimingCode/HFNet_SLAM.git"
PUBLISHED_DOI = "10.3390/s23042113"
EXECUTION_COMMIT = "c354c72588a97bb6f6a9c7c8317530795956ec80"
EXECUTION_TREE = "6619814aed4cd0e4baa2501341a48f753f8ba196"

DEFAULT_OFFICIAL_ROOT = Path("/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1")
DEFAULT_BINARY = (
    DEFAULT_OFFICIAL_ROOT
    / "Examples/Monocular-Inertial/mono_inertial_euroc"
)
DEFAULT_CONFIG = ROOT / "configs/published_baselines/hfnet_slam_aqualoc_a02_0005.yaml"
DEFAULT_MODEL_DIRECTORY = Path(
    "/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT"
)
DEFAULT_ONNX_MODEL = DEFAULT_MODEL_DIRECTORY / "HF-Net.onnx"
DEFAULT_MODEL_CACHE = DEFAULT_MODEL_DIRECTORY / "HF-Net.cache"
DEFAULT_RUNTIME_ROOT = Path("/home/ma/opt/hfnet_cuda116_trt851_r1")
DEFAULT_PANGOLIN_ROOT = Path("/home/ma/SLAM/aqua_deps/install")
DEFAULT_SEQUENCE_ROOT = (
    ROOT
    / "logs/hfnet_slam_adapter/aqualoc_a02_0005_full901_euroc_diag_r2"
)
DEFAULT_RESULT_DIRECTORY = (
    ROOT
    / "logs/published_hfnet_slam_v2/post_stop_full901/runs"
    / "aqualoc_a02_0005_full901_diag_r2"
)
DEFAULT_EVIDENCE_DIRECTORY = (
    ROOT
    / "logs/published_hfnet_slam_v2/post_stop_full901/drivers"
    / "aqualoc_a02_0005_full901_diag_r2"
)
DEFAULT_CONTRACT_JSON = (
    ROOT / "papers/hfnet_slam_a02_full901_diagnostic_run_contract_r2.json"
)
DEFAULT_PREFIX_RESULT = ROOT / "papers/hfnet_slam_a02_prefix200_result_r1.json"
DEFAULT_PREFIX_CONTRACT = ROOT / "papers/hfnet_slam_a02_prefix200_run_contract_r1.json"

EXPECTED_IDENTITIES: Mapping[str, Mapping[str, object]] = {
    "binary": {
        "sha256": "4029c6ba8ecdc76c98f2c190c1a1151493ed2553da087c1a4f077fc036e143a3",
        "size_bytes": 122_352,
    },
    "config": {
        "sha256": "7e6482653e55b2fcf86a9e5418fd87747677a88eb9c06443d505cda311b80569",
        "size_bytes": 1_807,
    },
    "onnx_model": {
        "sha256": "354a23f9c28b75ea9056a8eb5586e3b13191426521fd3f5556e5bfd670fc39b5",
        "size_bytes": 132_238_602,
    },
    "model_cache": {
        "sha256": "a687454ce7dd12cdf73dab66a8e295ee21eb4827f8f7b1f9ca96e7ceef8342bc",
        "size_bytes": 853_319,
    },
    "prefix_result": {
        "sha256": "9e42c9e1f9b2848b45ff90d1a1bc581ba42752a91dcf07a0ac5bdecfa8d3a4c4",
        "size_bytes": 3_421,
    },
    "prefix_contract": {
        "sha256": "5c23bd2d519a76912c69d88cc7b8117b3532f2c70238b7ca59314eae4b4b0639",
        "size_bytes": 2_194,
    },
}

OFFICIAL_SOURCE_FILES = (
    "Examples/Monocular-Inertial/mono_inertial_euroc.cc",
    "src/LocalMapping.cc",
    "src/System.cc",
    "src/Tracking.cc",
)

GPU_INDEX = "0"
GPU_NAME_TOKEN = "GTX 1650"
TIMEOUT_SECONDS = 1_800
MINIMUM_POSE_COUNT = 30
MINIMUM_TIMESTAMP_SPAN_SECONDS = 3.0

RC_PASS = 0
RC_EXECUTION_FAILED = 1
RC_CONTRACT_BLOCKED = 2


class ContractError(RuntimeError):
    """A fail-closed experiment contract violation."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


@dataclass(frozen=True)
class RunSpec:
    official_root: Path = DEFAULT_OFFICIAL_ROOT
    binary: Path = DEFAULT_BINARY
    config: Path = DEFAULT_CONFIG
    onnx_model: Path = DEFAULT_ONNX_MODEL
    model_cache: Path = DEFAULT_MODEL_CACHE
    runtime_root: Path = DEFAULT_RUNTIME_ROOT
    pangolin_root: Path = DEFAULT_PANGOLIN_ROOT
    sequence_root: Path = DEFAULT_SEQUENCE_ROOT
    result_directory: Path = DEFAULT_RESULT_DIRECTORY
    evidence_directory: Path = DEFAULT_EVIDENCE_DIRECTORY
    contract_json: Path = DEFAULT_CONTRACT_JSON
    prefix_result: Path = DEFAULT_PREFIX_RESULT
    prefix_contract: Path = DEFAULT_PREFIX_CONTRACT
    expected_commit: str = EXECUTION_COMMIT
    expected_tree: str = EXECUTION_TREE
    expected_origin: str = OFFICIAL_REPOSITORY
    expected_identities: Mapping[str, Mapping[str, object]] = field(
        default_factory=lambda: EXPECTED_IDENTITIES
    )
    expected_camera_count: int = 901
    expected_source_imu_count: int = 9_091
    expected_imu_count: int = 8_994
    expected_camera_indices: tuple[int, int] = (0, 900)
    expected_imu_indices: tuple[int, int] = (38, 9_031)
    expected_first_camera_ns: int = 1_542_829_016_700_435_392
    expected_last_camera_ns: int = 1_542_829_061_692_686_528
    expected_first_imu_raw_ns: int = 1_542_829_016_645_312_000
    expected_last_imu_raw_ns: int = 1_542_829_061_641_706_560
    expected_imu_shift_ns: int = 53_694_112
    timeout_seconds: int = TIMEOUT_SECONDS


DEFAULT_SPEC = RunSpec()

ProbeRunner = Callable[
    [Sequence[str], Optional[Mapping[str, str]], Optional[Path]], CommandResult
]
ExecuteRunner = Callable[
    [Sequence[str], Mapping[str, str], Optional[Path], int], CommandResult
]
ProfileCollector = Callable[[RunSpec, ProbeRunner], Dict[str, Any]]
RuntimeChecker = Callable[
    [RunSpec, ProbeRunner, Mapping[str, str]], Dict[str, Any]
]


def canonical_json(value: object) -> str:
    return json.dumps(
        value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
    ) + "\n"


def _absolute(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _is_within(path: Path, root: Path) -> bool:
    try:
        _absolute(path).relative_to(_absolute(root))
    except (OSError, ValueError):
        return False
    return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _bytes_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _identity(path: Path) -> dict[str, object]:
    path = _absolute(path)
    if not path.is_file() or path.is_symlink():
        raise ContractError(f"NOT_REGULAR_NONSYMLINK_FILE:{path}")
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _identity_matches(
    observed: Mapping[str, object], expected: Mapping[str, object]
) -> bool:
    return all(observed.get(key) == value for key, value in expected.items())


def _aggregate_rows(rows: Sequence[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for name, file_hash in rows:
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _write_exclusive(path: Path, payload: bytes, mode: int = 0o444) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    os.chmod(path, mode)


def _load_canonical_json(path: Path) -> object:
    try:
        payload = path.read_text(encoding="utf-8")
        value = json.loads(payload)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(
            f"CANONICAL_JSON_UNREADABLE:{path}:{type(error).__name__}:{error}"
        ) from error
    if payload != canonical_json(value):
        raise ContractError(f"JSON_NOT_CANONICAL:{path}")
    return value


def _png_header(path: Path) -> dict[str, int]:
    with path.open("rb") as stream:
        header = stream.read(33)
    if (
        len(header) != 33
        or header[:8] != b"\x89PNG\r\n\x1a\n"
        or struct.unpack(">I", header[8:12])[0] != 13
        or header[12:16] != b"IHDR"
    ):
        raise ContractError(f"INVALID_PNG_HEADER:{path}")
    width, height = struct.unpack(">II", header[16:24])
    return {
        "bit_depth": header[24],
        "color_type": header[25],
        "height": height,
        "width": width,
    }


def _strict_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{label}_NOT_INTEGER")
    return value


def _dict(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label}_NOT_OBJECT")
    return value


def _list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError(f"{label}_NOT_ARRAY")
    return value


def validate_prefix_runtime_continuity(
    spec: RunSpec, identities: Mapping[str, Mapping[str, object]]
) -> dict[str, Any]:
    """Prove that the full track reuses the sealed prefix post-run cache.

    ``HF-Net.cache`` is a TensorRT timing/engine cache produced by the already
    sealed official prefix run.  It is not an ONNX weight file or an extractor
    parameter.  This check prevents silently choosing either the prefix
    contract's pre-run cache or an unrelated later cache.
    """

    try:
        prefix_value = json.loads(spec.prefix_result.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"PREFIX_RESULT_UNREADABLE:{type(error).__name__}:{error}") from error
    # The legacy file predates this runner's recursively sorted serializer; its
    # exact bytes are already protected by EXPECTED_IDENTITIES.
    prefix = _dict(prefix_value, "PREFIX_RESULT")
    runtime = _dict(prefix.get("runtime"), "PREFIX_RUNTIME")
    prefix_identity = _dict(prefix.get("identity"), "PREFIX_IDENTITY")
    expected_cache_sha = str(
        spec.expected_identities.get("model_cache", {}).get("sha256", "")
    )
    observed_cache_sha = str(identities.get("model_cache", {}).get("sha256", ""))
    cache_after_sha = runtime.get("cache_after_sha256")
    if not expected_cache_sha or not (
        cache_after_sha == expected_cache_sha == observed_cache_sha
    ):
        raise ContractError("PREFIX_POST_RUN_CACHE_CONTINUITY_MISMATCH")
    if runtime.get("cache_before_sha256") == cache_after_sha:
        raise ContractError("PREFIX_CACHE_TRANSITION_NOT_RECORDED")
    if prefix_identity.get("onnx_sha256") != identities["onnx_model"].get("sha256"):
        raise ContractError("PREFIX_ONNX_CONTINUITY_MISMATCH")
    if prefix_identity.get("config_sha256") != identities["config"].get("sha256"):
        raise ContractError("PREFIX_CONFIG_CONTINUITY_MISMATCH")
    decision = _dict(prefix.get("decision"), "PREFIX_DECISION")
    if decision.get("status") != "STOP" or decision.get("full_window_allowed") is not False:
        raise ContractError("PREFIX_STOP_DECISION_DRIFT")

    config_text = _absolute(spec.config).read_text(encoding="utf-8")
    expected_config_lines = (
        'Extractor.type: "HFNetRT"',
        "Extractor.scaleFactor: 1.2",
        "Extractor.nLevels: 4",
        "Extractor.nFeatures: 675",
        "Extractor.threshold: 0.01",
    )
    if any(line not in config_text for line in expected_config_lines):
        raise ContractError("FROZEN_EXTRACTOR_PARAMETER_TEXT_MISMATCH")
    return {
        "cache_after_prefix_sha256": cache_after_sha,
        "cache_before_prefix_sha256": runtime.get("cache_before_sha256"),
        "classification": "TensorRT_runtime_timing_cache_not_model_weights_or_thresholds",
        "config_unchanged_from_prefix": True,
        "extractor_parameters": {
            "nFeatures": 675,
            "nLevels": 4,
            "scaleFactor": 1.2,
            "threshold": 0.01,
            "type": "HFNetRT",
        },
        "onnx_unchanged_from_prefix": True,
        "source": "sealed_prefix_r1_official_run_cache_after",
    }


def audit_input(spec: RunSpec) -> dict[str, Any]:
    """Rehash and validate the exact full EuRoC-style input tree."""

    root = _absolute(spec.sequence_root)
    if not root.is_dir() or root.is_symlink():
        raise ContractError(f"INPUT_ROOT_NOT_DIRECTORY:{root}")
    manifest_path = root / "conversion_manifest.json"
    manifest = _dict(_load_canonical_json(manifest_path), "INPUT_MANIFEST")
    if manifest.get("adapter_version") != exporter.ADAPTER_VERSION:
        raise ContractError("INPUT_ADAPTER_VERSION_MISMATCH")
    if manifest.get("artifact_scope") != exporter.ARTIFACT_SCOPE:
        raise ContractError("INPUT_ARTIFACT_SCOPE_MISMATCH")
    if manifest.get("scientific_role") != exporter.SCIENTIFIC_ROLE:
        raise ContractError("INPUT_SCIENTIFIC_ROLE_MISMATCH")
    if manifest.get("status") != exporter.STATUS_EXPORTED:
        raise ContractError("INPUT_NOT_EXPORTED")
    claims = _dict(manifest.get("claims"), "INPUT_CLAIMS")
    required_claims = {
        "full_a02_window_exported": True,
        "hfnet_source_modified": False,
        "hfnet_started": False,
        "prefix_r1_result_replaced": False,
        "trajectory_produced": False,
    }
    if any(claims.get(key) != value for key, value in required_claims.items()):
        raise ContractError("INPUT_CLAIMS_MISMATCH")

    contract = _dict(manifest.get("contract"), "INPUT_CONTRACT")
    expected_contract_values = {
        "expected_total_images": spec.expected_camera_count,
        "image_first_index": spec.expected_camera_indices[0],
        "image_last_index": spec.expected_camera_indices[1],
        "expected_total_imus": spec.expected_source_imu_count,
        "imu_first_index": spec.expected_imu_indices[0],
        "imu_last_index": spec.expected_imu_indices[1],
        "expected_first_image_stamp_ns": spec.expected_first_camera_ns,
        "expected_last_image_stamp_ns": spec.expected_last_camera_ns,
        "expected_first_imu_raw_stamp_ns": spec.expected_first_imu_raw_ns,
        "expected_last_imu_raw_stamp_ns": spec.expected_last_imu_raw_ns,
        "imu_shift_ns": spec.expected_imu_shift_ns,
    }
    for key, expected in expected_contract_values.items():
        if contract.get(key) != expected:
            raise ContractError(f"INPUT_CONTRACT_MISMATCH:{key}")
    if contract.get("imu_time_transform") != (
        f"output_ns=raw_header_ns+{spec.expected_imu_shift_ns}"
    ):
        raise ContractError("INPUT_IMU_TIME_TRANSFORM_MISMATCH")

    camera = _dict(manifest.get("camera"), "INPUT_CAMERA")
    images = _list(camera.get("images"), "INPUT_IMAGES")
    if camera.get("count") != spec.expected_camera_count:
        raise ContractError("INPUT_CAMERA_COUNT_MISMATCH")
    if len(images) != spec.expected_camera_count:
        raise ContractError("INPUT_IMAGE_MANIFEST_COUNT_MISMATCH")
    if camera.get("source_indices_inclusive") != list(spec.expected_camera_indices):
        raise ContractError("INPUT_CAMERA_INDICES_MISMATCH")
    if camera.get("first_raw_header_ns") != spec.expected_first_camera_ns:
        raise ContractError("INPUT_FIRST_CAMERA_STAMP_MISMATCH")
    if camera.get("last_raw_header_ns") != spec.expected_last_camera_ns:
        raise ContractError("INPUT_LAST_CAMERA_STAMP_MISMATCH")
    if camera.get("strictly_monotonic") is not True:
        raise ContractError("INPUT_CAMERA_NOT_DECLARED_MONOTONIC")
    schema = _dict(camera.get("schema"), "INPUT_CAMERA_SCHEMA")
    expected_png = {
        "bit_depth": 8,
        "color_type": 0,
        "height": _strict_int(schema.get("height"), "INPUT_HEIGHT"),
        "width": _strict_int(schema.get("width"), "INPUT_WIDTH"),
    }
    if schema.get("encoding") != "mono8" or schema.get("step") != expected_png["width"]:
        raise ContractError("INPUT_CAMERA_SCHEMA_MISMATCH")

    timestamps: list[int] = []
    aggregate_rows: list[tuple[str, str]] = []
    allowed_files = {
        "conversion_manifest.json",
        "cam0_times.txt",
        "mav0/imu0/data.csv",
    }
    for offset, raw_row in enumerate(images):
        row = _dict(raw_row, f"INPUT_IMAGE_ROW_{offset}")
        timestamp = _strict_int(row.get("raw_header_ns"), "INPUT_IMAGE_STAMP")
        if row.get("source_index") != spec.expected_camera_indices[0] + offset:
            raise ContractError(f"INPUT_IMAGE_SOURCE_INDEX_MISMATCH:{offset}")
        filename = f"{timestamp}.png"
        if row.get("filename") != filename:
            raise ContractError(f"INPUT_IMAGE_FILENAME_MISMATCH:{offset}")
        if row.get("pixel_identity_verified") is not True:
            raise ContractError(f"INPUT_IMAGE_PIXEL_IDENTITY_UNVERIFIED:{offset}")
        relative = f"mav0/cam0/data/{filename}"
        path = root / relative
        identity = _identity(path)
        if identity["sha256"] != row.get("png_sha256"):
            raise ContractError(f"INPUT_IMAGE_HASH_MISMATCH:{offset}")
        if _png_header(path) != expected_png:
            raise ContractError(f"INPUT_IMAGE_PNG_SCHEMA_MISMATCH:{offset}")
        timestamps.append(timestamp)
        aggregate_rows.append((relative, str(identity["sha256"])))
        allowed_files.add(relative)
    if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
        raise ContractError("INPUT_IMAGE_STAMPS_NOT_STRICT")
    if timestamps[0] != spec.expected_first_camera_ns or timestamps[-1] != spec.expected_last_camera_ns:
        raise ContractError("INPUT_IMAGE_ENDPOINT_MISMATCH")

    times_path = root / "cam0_times.txt"
    times_payload = times_path.read_bytes()
    expected_times_payload = (
        "\n".join(str(value) for value in timestamps) + "\n"
    ).encode("ascii")
    if times_payload != expected_times_payload:
        raise ContractError("INPUT_TIMES_PAYLOAD_MISMATCH")
    times_info = _dict(camera.get("times_file"), "INPUT_TIMES_INFO")
    times_hash = _bytes_sha256(times_payload)
    if (
        times_info.get("path") != "cam0_times.txt"
        or times_info.get("line_count") != spec.expected_camera_count
        or times_info.get("final_newline") is not True
        or times_info.get("sha256") != times_hash
    ):
        raise ContractError("INPUT_TIMES_MANIFEST_MISMATCH")
    aggregate_rows.append(("cam0_times.txt", times_hash))

    imu = _dict(manifest.get("imu"), "INPUT_IMU")
    csv_info = _dict(imu.get("csv"), "INPUT_IMU_CSV")
    if imu.get("count") != spec.expected_imu_count:
        raise ContractError("INPUT_IMU_COUNT_MISMATCH")
    if imu.get("source_indices_inclusive") != list(spec.expected_imu_indices):
        raise ContractError("INPUT_IMU_INDICES_MISMATCH")
    if imu.get("first_raw_header_ns") != spec.expected_first_imu_raw_ns:
        raise ContractError("INPUT_FIRST_IMU_RAW_MISMATCH")
    if imu.get("last_raw_header_ns") != spec.expected_last_imu_raw_ns:
        raise ContractError("INPUT_LAST_IMU_RAW_MISMATCH")
    expected_first_output = spec.expected_first_imu_raw_ns + spec.expected_imu_shift_ns
    expected_last_output = spec.expected_last_imu_raw_ns + spec.expected_imu_shift_ns
    if imu.get("first_output_header_ns") != expected_first_output:
        raise ContractError("INPUT_FIRST_IMU_OUTPUT_MISMATCH")
    if imu.get("last_output_header_ns") != expected_last_output:
        raise ContractError("INPUT_LAST_IMU_OUTPUT_MISMATCH")
    if imu.get("brackets_camera_full_window") is not True:
        raise ContractError("INPUT_IMU_BRACKET_DECLARATION_MISSING")

    csv_path = root / "mav0/imu0/data.csv"
    csv_payload = csv_path.read_bytes()
    if csv_payload.endswith(b"\n") or not csv_payload.isascii():
        raise ContractError("INPUT_IMU_CSV_SERIALIZATION_MISMATCH")
    try:
        csv_text = csv_payload.decode("ascii")
        rows = list(csv.reader(csv_text.splitlines()))
    except (UnicodeError, csv.Error) as error:
        raise ContractError(f"INPUT_IMU_CSV_PARSE_ERROR:{error}") from error
    if not rows or ",".join(rows[0]) != exporter.base.CSV_HEADER:
        raise ContractError("INPUT_IMU_CSV_HEADER_MISMATCH")
    data_rows = rows[1:]
    if len(data_rows) != spec.expected_imu_count:
        raise ContractError("INPUT_IMU_CSV_COUNT_MISMATCH")
    imu_timestamps: list[int] = []
    for index, fields in enumerate(data_rows):
        if len(fields) != 7 or not fields[0].isdigit():
            raise ContractError(f"INPUT_IMU_CSV_ROW_SCHEMA:{index}")
        timestamp = int(fields[0])
        try:
            numeric = [float(value) for value in fields[1:]]
        except ValueError as error:
            raise ContractError(f"INPUT_IMU_CSV_NONNUMERIC:{index}") from error
        if any(not math.isfinite(value) for value in numeric):
            raise ContractError(f"INPUT_IMU_CSV_NONFINITE:{index}")
        if any(value != value.strip() or not value for value in fields):
            raise ContractError(f"INPUT_IMU_CSV_WHITESPACE:{index}")
        imu_timestamps.append(timestamp)
    if any(right <= left for left, right in zip(imu_timestamps, imu_timestamps[1:])):
        raise ContractError("INPUT_IMU_STAMPS_NOT_STRICT")
    if imu_timestamps[0] != expected_first_output or imu_timestamps[-1] != expected_last_output:
        raise ContractError("INPUT_IMU_OUTPUT_ENDPOINT_MISMATCH")
    if not (imu_timestamps[0] <= timestamps[0] and imu_timestamps[-1] >= timestamps[-1]):
        raise ContractError("INPUT_IMU_DOES_NOT_BRACKET_CAMERA")
    csv_hash = _bytes_sha256(csv_payload)
    if (
        csv_info.get("path") != "mav0/imu0/data.csv"
        or csv_info.get("header") != exporter.base.CSV_HEADER
        or csv_info.get("data_row_count") != spec.expected_imu_count
        or csv_info.get("final_newline") is not False
        or csv_info.get("sha256") != csv_hash
    ):
        raise ContractError("INPUT_IMU_CSV_MANIFEST_MISMATCH")
    aggregate_rows.append(("mav0/imu0/data.csv", csv_hash))

    observed_files: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ContractError(f"INPUT_SYMLINK_FORBIDDEN:{path}")
        if path.is_file():
            observed_files.add(path.relative_to(root).as_posix())
    if observed_files != allowed_files:
        extra = sorted(observed_files - allowed_files)
        missing = sorted(allowed_files - observed_files)
        raise ContractError(f"INPUT_FILE_TREE_MISMATCH:extra={extra}:missing={missing}")
    payload_tree = _aggregate_rows(sorted(aggregate_rows))
    if manifest.get("payload_tree_sha256_excluding_manifest") != payload_tree:
        raise ContractError("INPUT_PAYLOAD_TREE_HASH_MISMATCH")

    return {
        "adapter_version": exporter.ADAPTER_VERSION,
        "artifact_scope": exporter.ARTIFACT_SCOPE,
        "camera_count": len(timestamps),
        "camera_ns_inclusive": [timestamps[0], timestamps[-1]],
        "file_count_including_manifest": len(observed_files),
        "imu_count": len(imu_timestamps),
        "imu_output_ns_inclusive": [imu_timestamps[0], imu_timestamps[-1]],
        "manifest": _identity(manifest_path),
        "payload_tree_sha256_excluding_manifest": payload_tree,
        "root": str(root),
        "scientific_role": exporter.SCIENTIFIC_ROLE,
    }


def _default_probe(
    command: Sequence[str],
    environment: Optional[Mapping[str, str]],
    cwd: Optional[Path],
) -> CommandResult:
    env = dict(os.environ)
    if environment is not None:
        env.update(environment)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        completed = subprocess.run(
            list(command),
            cwd=str(cwd) if cwd is not None else None,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=60,
        )
    except FileNotFoundError as error:
        return CommandResult(127, "", f"{type(error).__name__}:{error}")
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout if isinstance(error.stdout, str) else ""
        stderr = error.stderr if isinstance(error.stderr, str) else ""
        return CommandResult(124, stdout, stderr, True)
    except OSError as error:
        return CommandResult(126, "", f"{type(error).__name__}:{error}")
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _default_execute(
    command: Sequence[str],
    environment: Mapping[str, str],
    cwd: Optional[Path],
    timeout_seconds: int,
) -> CommandResult:
    try:
        completed = subprocess.run(
            list(command),
            cwd=str(cwd) if cwd is not None else None,
            env=dict(environment),
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout_seconds,
        )
    except FileNotFoundError as error:
        return CommandResult(127, "", f"{type(error).__name__}:{error}")
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout if isinstance(error.stdout, str) else ""
        stderr = error.stderr if isinstance(error.stderr, str) else ""
        return CommandResult(124, stdout, stderr, True)
    except OSError as error:
        return CommandResult(126, "", f"{type(error).__name__}:{error}")
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _runtime_library_paths(spec: RunSpec) -> tuple[Path, ...]:
    return (
        spec.official_root / "lib",
        spec.official_root / "Thirdparty/g2o/lib",
        spec.pangolin_root / "lib",
        spec.runtime_root / "usr/lib/x86_64-linux-gnu",
        spec.runtime_root / "usr/local/cuda-11.6/lib64",
        spec.runtime_root / "usr/local/cuda-11.6/targets/x86_64-linux/lib",
        spec.runtime_root / "usr/local/cuda-11.8/lib64",
        spec.runtime_root / "usr/local/cuda-11.8/targets/x86_64-linux/lib",
    )


def runtime_environment(spec: RunSpec) -> dict[str, str]:
    preserved = (
        "DBUS_SESSION_BUS_ADDRESS",
        "DISPLAY",
        "HOME",
        "PATH",
        "TMPDIR",
        "USER",
        "XAUTHORITY",
        "XDG_RUNTIME_DIR",
    )
    environment = {
        name: os.environ[name] for name in preserved if name in os.environ
    }
    environment.setdefault(
        "PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    )
    environment["CUDA_VISIBLE_DEVICES"] = GPU_INDEX
    environment["LANG"] = "C"
    environment["LC_ALL"] = "C"
    environment["LD_LIBRARY_PATH"] = ":".join(
        str(_absolute(path)) for path in _runtime_library_paths(spec)
    )
    return environment


def collect_profile(
    spec: RunSpec, probe_runner: ProbeRunner = _default_probe
) -> dict[str, Any]:
    """Collect only stable identities; fail if any frozen identity drifted."""

    named_paths = {
        "binary": spec.binary,
        "config": spec.config,
        "model_cache": spec.model_cache,
        "onnx_model": spec.onnx_model,
        "prefix_contract": spec.prefix_contract,
        "prefix_result": spec.prefix_result,
    }
    identities = {name: _identity(path) for name, path in named_paths.items()}
    for name, expected in spec.expected_identities.items():
        observed = identities.get(name)
        if observed is None or not _identity_matches(observed, expected):
            raise ContractError(f"FROZEN_IDENTITY_MISMATCH:{name}")
    binary_mode = _absolute(spec.binary).stat().st_mode
    if not binary_mode & stat.S_IXUSR:
        raise ContractError("BINARY_NOT_EXECUTABLE")
    if _absolute(spec.binary).read_bytes()[:4] != b"\x7fELF":
        raise ContractError("BINARY_NOT_ELF")

    git_commands = {
        "commit": ["git", "-C", str(spec.official_root), "rev-parse", "HEAD^{commit}"],
        "tree": ["git", "-C", str(spec.official_root), "rev-parse", "HEAD^{tree}"],
        "origin": ["git", "-C", str(spec.official_root), "remote", "get-url", "origin"],
        "tracked_status": [
            "git",
            "-C",
            str(spec.official_root),
            "status",
            "--porcelain=v1",
            "--untracked-files=no",
        ],
    }
    git = {
        name: probe_runner(command, None, None)
        for name, command in git_commands.items()
    }
    if any(result.returncode != 0 or result.timed_out for result in git.values()):
        raise ContractError("OFFICIAL_GIT_PROBE_FAILED")
    commit = git["commit"].stdout.strip()
    tree = git["tree"].stdout.strip()
    origin = git["origin"].stdout.strip()
    tracked_status = git["tracked_status"].stdout
    if commit != spec.expected_commit:
        raise ContractError("OFFICIAL_COMMIT_MISMATCH")
    if tree != spec.expected_tree:
        raise ContractError("OFFICIAL_TREE_MISMATCH")
    if origin != spec.expected_origin:
        raise ContractError("OFFICIAL_ORIGIN_MISMATCH")
    if tracked_status.strip():
        raise ContractError("OFFICIAL_TRACKED_WORKTREE_DIRTY")

    source_files = {
        relative: _identity(spec.official_root / relative)
        for relative in OFFICIAL_SOURCE_FILES
    }
    runner_identity = _identity(Path(__file__))
    exporter_identity = _identity(Path(exporter.__file__))
    input_profile = audit_input(spec)
    prefix_runtime_continuity = validate_prefix_runtime_continuity(
        spec, identities
    )
    command = command_argv(spec)
    return {
        "baseline": {
            "implementation": "author_official_HFNet_SLAM",
            "official_repository": OFFICIAL_REPOSITORY,
            "paper_doi": PUBLISHED_DOI,
            "source_commit": commit,
            "source_tree": tree,
        },
        "command_argv": command,
        "exporter": exporter_identity,
        "identities": identities,
        "input": input_profile,
        "official_source": {
            "commit": commit,
            "files": source_files,
            "origin": origin,
            "root": str(_absolute(spec.official_root)),
            "tracked_worktree_clean": True,
            "tree": tree,
        },
        "prefix_runtime_continuity": prefix_runtime_continuity,
        "profile_schema": PROFILE_SCHEMA_VERSION,
        "runner": runner_identity,
        "scientific_role": SCIENTIFIC_ROLE,
    }


def _parse_ldd(payload: str) -> tuple[dict[str, str], list[str]]:
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for raw_line in payload.splitlines():
        line = raw_line.strip()
        if "=> not found" in line:
            missing.append(line.split("=>", 1)[0].strip())
        elif "=>" in line:
            name, remainder = line.split("=>", 1)
            resolved[name.strip()] = remainder.strip().split(" ", 1)[0]
    return resolved, missing


def check_runtime(
    spec: RunSpec,
    probe_runner: ProbeRunner = _default_probe,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    environment = dict(environment or runtime_environment(spec))
    checks: dict[str, Any] = {}

    display = environment.get("DISPLAY", "").strip()
    checks["viewer_display_declared"] = {
        "ok": bool(display),
        "observed": display or None,
    }
    gpu = probe_runner(
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
        environment,
        None,
    )
    gpu_names = [line.strip() for line in gpu.stdout.splitlines() if line.strip()]
    checks["gpu_zero_identity"] = {
        "ok": (
            gpu.returncode == 0
            and not gpu.timed_out
            and bool(gpu_names)
            and GPU_NAME_TOKEN in gpu_names[0]
        ),
        "observed": {"names": gpu_names, "returncode": gpu.returncode},
    }
    ldd = probe_runner(["ldd", str(_absolute(spec.binary))], environment, None)
    resolved, missing = _parse_ldd(ldd.stdout)
    groups = {
        "hfnet": any(name.startswith("libHFNet_SLAM.so") for name in resolved),
        "pangolin": any(
            name.startswith("libpango_") or name.startswith("libpangolin.so")
            for name in resolved
        ),
        "tensorrt": any(name.startswith("libnvinfer.so") for name in resolved),
        "cuda": any(name.startswith("libcudart.so") for name in resolved),
        "cudnn": any(name.startswith("libcudnn.so") for name in resolved),
    }
    hfnet_paths = [
        Path(path)
        for name, path in resolved.items()
        if name.startswith("libHFNet_SLAM.so")
    ]
    hfnet_ok = bool(hfnet_paths) and all(
        _is_within(path, spec.official_root / "lib") for path in hfnet_paths
    )
    checks["binary_linkage"] = {
        "ok": (
            ldd.returncode == 0
            and not ldd.timed_out
            and not missing
            and all(groups.values())
            and hfnet_ok
        ),
        "observed": {
            "groups": groups,
            "hfnet_paths": [str(path) for path in hfnet_paths],
            "missing": missing,
            "returncode": ldd.returncode,
        },
    }
    required_runtime = (
        "usr/local/cuda-11.6/lib64/libcudart.so.11.0",
        "usr/local/cuda-11.8/lib64/libcublas.so.11",
        "usr/local/cuda-11.8/lib64/libcublasLt.so.11",
        "usr/lib/x86_64-linux-gnu/libnvinfer.so.8.5.1",
        "usr/lib/x86_64-linux-gnu/libnvinfer_plugin.so.8.5.1",
        "usr/lib/x86_64-linux-gnu/libnvonnxparser.so.8.5.1",
        "usr/lib/x86_64-linux-gnu/libcudnn.so.8.4.1",
    )
    missing_runtime = [
        relative
        for relative in required_runtime
        if not (spec.runtime_root / relative).exists()
    ]
    checks["isolated_runtime_layout"] = {
        "ok": not missing_runtime,
        "observed": {"missing": missing_runtime},
    }
    checks["pangolin_layout"] = {
        "ok": (spec.pangolin_root / "lib").is_dir(),
        "observed": str(_absolute(spec.pangolin_root / "lib")),
    }
    return {
        "checks": checks,
        "ok": all(bool(row.get("ok")) for row in checks.values()),
    }


def command_argv(spec: RunSpec) -> list[str]:
    result_argument = str(_absolute(spec.result_directory)).rstrip("/") + "/"
    return [
        str(_absolute(spec.binary)),
        str(_absolute(spec.config)),
        result_argument,
        str(_absolute(spec.sequence_root)),
        str(_absolute(spec.sequence_root / "cam0_times.txt")),
    ]


def build_contract(profile: Mapping[str, Any], spec: RunSpec) -> dict[str, Any]:
    profile_payload = canonical_json(profile).encode("utf-8")
    return {
        "baseline": {
            "implementation": "author_official_HFNet_SLAM",
            "official_repository": OFFICIAL_REPOSITORY,
            "paper_doi": PUBLISHED_DOI,
            "source_commit": spec.expected_commit,
            "source_tree": spec.expected_tree,
        },
        "command_argv": command_argv(spec),
        "execution_policy": {
            "accuracy_dependent_retry": False,
            "algorithm_or_official_source_modification": False,
            "config_or_threshold_modification": False,
            "empty_map_save_sigsegv_policy": (
                "retain raw child signal; classify as a secondary exit bug; "
                "never promote an empty trajectory to success"
            ),
            "maximum_official_process_starts": 1,
            "supervision_boundary": "unchanged official executable as child process",
            "timeout_seconds": spec.timeout_seconds,
            "tuning_after_freeze": False,
        },
        "frozen_profile": dict(profile),
        "frozen_profile_sha256": _bytes_sha256(profile_payload),
        "legacy_prefix_r1": {
            "decision": "STOP",
            "preserved": True,
            "replacement_by_this_track": False,
            "run_contract": profile["identities"]["prefix_contract"],
            "run_result": profile["identities"]["prefix_result"],
        },
        "output": {
            "contract_json": str(_absolute(spec.contract_json)),
            "evidence_directory": str(_absolute(spec.evidence_directory)),
            "official_result_directory": str(_absolute(spec.result_directory)),
        },
        "prefix_runtime_continuity": profile["prefix_runtime_continuity"],
        "schema_version": SCHEMA_VERSION,
        "scientific_gate": {
            "finite_eight_field_poses_only": True,
            "keyframe_trajectory_nonempty": True,
            "minimum_pose_count": MINIMUM_POSE_COUNT,
            "minimum_timestamp_span_seconds": MINIMUM_TIMESTAMP_SPAN_SECONDS,
            "official_child_return_code_zero": True,
            "strictly_increasing_timestamps": True,
        },
        "scientific_role": SCIENTIFIC_ROLE,
    }


def profile_decision(
    spec: RunSpec = DEFAULT_SPEC,
    *,
    probe_runner: ProbeRunner = _default_probe,
    profile_collector: ProfileCollector = collect_profile,
    runtime_checker: RuntimeChecker = check_runtime,
) -> dict[str, Any]:
    errors: list[str] = []
    profile: dict[str, Any] | None = None
    try:
        profile = profile_collector(spec, probe_runner)
    except (ContractError, OSError, ValueError) as error:
        errors.append(str(error))
    environment = runtime_environment(spec)
    runtime = runtime_checker(spec, probe_runner, environment)
    if not runtime.get("ok"):
        errors.append("RUNTIME_NOT_READY")
    reservations = {
        "contract_json_absent": not spec.contract_json.exists() and not spec.contract_json.is_symlink(),
        "evidence_directory_absent": not spec.evidence_directory.exists() and not spec.evidence_directory.is_symlink(),
        "result_directory_absent": not spec.result_directory.exists() and not spec.result_directory.is_symlink(),
    }
    if not all(reservations.values()):
        errors.append("OUTPUT_RESERVATION_NOT_EMPTY")
    return {
        "claims": {
            "hfnet_started": False,
            "legacy_prefix_r1_replaced": False,
            "official_source_or_config_modified": False,
            "trajectory_produced": False,
        },
        "errors": errors,
        "profile": profile,
        "ready": not errors,
        "reservations": reservations,
        "runtime": runtime,
        "schema_version": PROFILE_SCHEMA_VERSION,
        "scientific_role": SCIENTIFIC_ROLE,
        "status": "PROFILE_READY" if not errors else "PROFILE_BLOCKED",
    }


def freeze_contract(
    spec: RunSpec = DEFAULT_SPEC,
    *,
    probe_runner: ProbeRunner = _default_probe,
    profile_collector: ProfileCollector = collect_profile,
    runtime_checker: RuntimeChecker = check_runtime,
) -> dict[str, Any]:
    decision = profile_decision(
        spec,
        probe_runner=probe_runner,
        profile_collector=profile_collector,
        runtime_checker=runtime_checker,
    )
    if not decision["ready"]:
        return {
            **decision,
            "return_code": RC_CONTRACT_BLOCKED,
            "status": "FREEZE_BLOCKED",
        }
    profile = decision["profile"]
    assert isinstance(profile, dict)
    contract = build_contract(profile, spec)
    try:
        _write_exclusive(
            _absolute(spec.contract_json), canonical_json(contract).encode("utf-8")
        )
    except FileExistsError:
        return {
            **decision,
            "errors": [*decision["errors"], "CONTRACT_NO_CLOBBER"],
            "return_code": RC_CONTRACT_BLOCKED,
            "status": "FREEZE_BLOCKED",
        }
    return {
        "claims": decision["claims"],
        "contract": _identity(spec.contract_json),
        "frozen_profile_sha256": contract["frozen_profile_sha256"],
        "ready_for_unique_run": True,
        "return_code": RC_PASS,
        "schema_version": PROFILE_SCHEMA_VERSION,
        "scientific_role": SCIENTIFIC_ROLE,
        "status": "CONTRACT_FROZEN_NO_RUN_STARTED",
    }


def audit_trajectory(path: Path, minimum_pose_count: int = MINIMUM_POSE_COUNT) -> dict[str, Any]:
    result: dict[str, Any] = {
        "exists": path.is_file() and not path.is_symlink(),
        "finite_eight_field_rows": False,
        "pose_count": 0,
        "span_seconds": None,
        "strictly_increasing_timestamps": False,
        "syntax_errors": [],
    }
    if not result["exists"]:
        return result
    try:
        payload = path.read_text(encoding="ascii")
    except (OSError, UnicodeError) as error:
        result["syntax_errors"] = [f"{type(error).__name__}:{error}"]
        return result
    lines = payload.splitlines()
    if not lines or any(not line.strip() for line in lines):
        result["syntax_errors"] = ["empty_or_blank_line"]
        return result
    timestamps: list[float] = []
    errors: list[str] = []
    for index, line in enumerate(lines):
        fields = line.split()
        if len(fields) != 8:
            errors.append(f"row_{index}_field_count")
            continue
        try:
            values = [float(field) for field in fields]
        except ValueError:
            errors.append(f"row_{index}_nonnumeric")
            continue
        if any(not math.isfinite(value) for value in values):
            errors.append(f"row_{index}_nonfinite")
            continue
        timestamps.append(values[0])
    result["pose_count"] = len(lines)
    result["syntax_errors"] = errors
    result["finite_eight_field_rows"] = not errors and len(timestamps) == len(lines)
    if timestamps:
        strict = all(right > left for left, right in zip(timestamps, timestamps[1:]))
        result["strictly_increasing_timestamps"] = strict
        if strict:
            result["span_seconds"] = (timestamps[-1] - timestamps[0]) / 1e9
    result["gate_pass"] = bool(
        result["finite_eight_field_rows"]
        and result["strictly_increasing_timestamps"]
        and result["pose_count"] >= minimum_pose_count
        and isinstance(result["span_seconds"], float)
        and result["span_seconds"] >= MINIMUM_TIMESTAMP_SPAN_SECONDS
    )
    return result


def is_empty_map_save_exit_bug(execution: CommandResult) -> bool:
    if execution.returncode not in (-11, 139):
        return False
    if "Saving trajectory" not in execution.stdout:
        return False
    map_rows = re.findall(r"^\s*Map\s+\d+\s+has\s+(\d+)\s+KFs\s*$", execution.stdout, re.MULTILINE)
    return bool(map_rows) and all(int(value) == 0 for value in map_rows)


def classify_execution(
    execution: CommandResult,
    trajectory: Mapping[str, Any],
    keyframe_trajectory: Mapping[str, Any],
) -> tuple[str, bool, int]:
    keyframe_nonempty = bool(keyframe_trajectory.get("pose_count", 0))
    passed = bool(
        execution.returncode == 0
        and not execution.timed_out
        and trajectory.get("gate_pass") is True
        and keyframe_nonempty
        and keyframe_trajectory.get("finite_eight_field_rows") is True
        and keyframe_trajectory.get("strictly_increasing_timestamps") is True
    )
    if passed:
        return "PASS_FULL901_DIAGNOSTIC_TRAJECTORY_GATE", True, RC_PASS
    if is_empty_map_save_exit_bug(execution):
        return (
            "EMPTY_MAP_SAVE_EXIT_BUG_AFTER_ALGORITHM_FAILURE",
            False,
            RC_EXECUTION_FAILED,
        )
    if execution.timed_out:
        return "OFFICIAL_CHILD_TIMEOUT_UNUSABLE", False, RC_EXECUTION_FAILED
    if not trajectory.get("exists") or not trajectory.get("pose_count"):
        return "ALGORITHM_INITIALIZATION_FAILED_EMPTY_TRAJECTORY", False, RC_EXECUTION_FAILED
    return "FULL901_DIAGNOSTIC_TRAJECTORY_GATE_FAILED", False, RC_EXECUTION_FAILED


def _tree_identity(root: Path) -> dict[str, Any]:
    root = _absolute(root)
    if not root.is_dir() or root.is_symlink():
        return {"exists": False, "files": {}, "tree_sha256": None}
    rows: list[tuple[str, str]] = []
    files: dict[str, Any] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ContractError(f"OUTPUT_SYMLINK_FORBIDDEN:{path}")
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            identity = _identity(path)
            files[relative] = {
                "sha256": identity["sha256"],
                "size_bytes": identity["size_bytes"],
            }
            rows.append((relative, str(identity["sha256"])))
    return {
        "exists": True,
        "files": files,
        "tree_sha256": _aggregate_rows(rows),
    }


def _blocked_result(error: str) -> dict[str, Any]:
    return {
        "evaluable": False,
        "errors": [error],
        "execution": {"command_started": False, "returncode": None},
        "return_code": RC_CONTRACT_BLOCKED,
        "schema_version": RESULT_SCHEMA_VERSION,
        "scientific_role": SCIENTIFIC_ROLE,
        "status": "CONTRACT_BLOCKED",
    }


def run_diagnostic(
    spec: RunSpec = DEFAULT_SPEC,
    *,
    probe_runner: ProbeRunner = _default_probe,
    execute_runner: ExecuteRunner = _default_execute,
    profile_collector: ProfileCollector = collect_profile,
    runtime_checker: RuntimeChecker = check_runtime,
) -> dict[str, Any]:
    """Start the unchanged official executable at most once after exact freeze."""

    try:
        frozen = _dict(_load_canonical_json(spec.contract_json), "FROZEN_CONTRACT")
        current_profile = profile_collector(spec, probe_runner)
        expected_contract = build_contract(current_profile, spec)
        if frozen != expected_contract:
            raise ContractError("FROZEN_CONTRACT_OR_PROFILE_MISMATCH")
        runtime = runtime_checker(spec, probe_runner, runtime_environment(spec))
        if not runtime.get("ok"):
            raise ContractError("RUNTIME_NOT_READY")
        if spec.evidence_directory.exists() or spec.evidence_directory.is_symlink():
            raise ContractError("EVIDENCE_DIRECTORY_NO_CLOBBER")
        if spec.result_directory.exists() or spec.result_directory.is_symlink():
            raise ContractError("RESULT_DIRECTORY_NO_CLOBBER")
        spec.evidence_directory.parent.mkdir(parents=True, exist_ok=True)
        spec.result_directory.parent.mkdir(parents=True, exist_ok=True)
        spec.evidence_directory.mkdir(mode=0o755, parents=False, exist_ok=False)
        _write_exclusive(
            spec.evidence_directory / "frozen_contract.snapshot.json",
            canonical_json(frozen).encode("utf-8"),
        )
    except (ContractError, OSError, ValueError) as error:
        return _blocked_result(str(error))

    environment = runtime_environment(spec)
    command = command_argv(spec)
    # This is the only call site that can start the official process.  There is
    # intentionally no retry loop or alternate command path.
    execution = execute_runner(
        command, environment, spec.evidence_directory, spec.timeout_seconds
    )
    _write_exclusive(
        spec.evidence_directory / "official.stdout.log",
        execution.stdout.encode("utf-8", errors="replace"),
    )
    _write_exclusive(
        spec.evidence_directory / "official.stderr.log",
        execution.stderr.encode("utf-8", errors="replace"),
    )

    post_errors: list[str] = []
    try:
        post_profile = profile_collector(spec, probe_runner)
        if post_profile != current_profile:
            post_errors.append("IMMUTABLE_PROFILE_DRIFT_DURING_EXECUTION")
    except (ContractError, OSError, ValueError) as error:
        post_errors.append(f"POST_PROFILE_ERROR:{error}")

    trajectory = audit_trajectory(spec.result_directory / "trajectory.txt")
    keyframes = audit_trajectory(
        spec.result_directory / "trajectory_keyframe.txt", minimum_pose_count=1
    )
    status, evaluable, wrapper_rc = classify_execution(
        execution, trajectory, keyframes
    )
    if post_errors:
        status = "IMMUTABLE_PROFILE_DRIFT_RUN_INVALID"
        evaluable = False
        wrapper_rc = RC_CONTRACT_BLOCKED
    result_tree = _tree_identity(spec.result_directory)
    evidence_tree_before_manifest = _tree_identity(spec.evidence_directory)
    raw_signal = None
    if execution.returncode < 0:
        raw_signal = -execution.returncode
    elif execution.returncode == 139:
        raw_signal = 11
    result = {
        "artifacts": {
            "evidence_tree_before_manifest": evidence_tree_before_manifest,
            "official_result_tree": result_tree,
        },
        "command_argv": command,
        "contract": _identity(spec.contract_json),
        "evaluable": evaluable,
        "errors": post_errors,
        "execution": {
            "command_started": True,
            "official_process_start_count": 1,
            "raw_returncode": execution.returncode,
            "raw_signal_number": raw_signal,
            "timed_out": execution.timed_out,
        },
        "gate": {
            "keyframe_trajectory": keyframes,
            "official_child_return_code_zero": execution.returncode == 0,
            "trajectory": trajectory,
        },
        "legacy_prefix_r1_replaced": False,
        "return_code": wrapper_rc,
        "runtime_preflight": runtime,
        "schema_version": RESULT_SCHEMA_VERSION,
        "scientific_role": SCIENTIFIC_ROLE,
        "status": status,
        "supervision": {
            "algorithm_or_official_source_modified": False,
            "empty_map_save_exit_bug_detected": is_empty_map_save_exit_bug(execution),
            "raw_child_failure_rewritten_as_success": False,
            "retry_performed": False,
        },
    }
    try:
        _write_exclusive(
            spec.evidence_directory / "run_result.json",
            canonical_json(result).encode("utf-8"),
        )
    except FileExistsError:
        result["errors"].append("RUN_RESULT_NO_CLOBBER")
        result["status"] = "EVIDENCE_WRITE_FAILED"
        result["evaluable"] = False
        result["return_code"] = RC_CONTRACT_BLOCKED
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("profile", "freeze", "run"), default="profile")
    parser.add_argument("--sequence-root", type=Path, default=DEFAULT_SEQUENCE_ROOT)
    parser.add_argument("--result-directory", type=Path, default=DEFAULT_RESULT_DIRECTORY)
    parser.add_argument("--evidence-directory", type=Path, default=DEFAULT_EVIDENCE_DIRECTORY)
    parser.add_argument("--contract-json", type=Path, default=DEFAULT_CONTRACT_JSON)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    spec = replace(
        DEFAULT_SPEC,
        sequence_root=args.sequence_root,
        result_directory=args.result_directory,
        evidence_directory=args.evidence_directory,
        contract_json=args.contract_json,
    )
    if args.action == "profile":
        decision = profile_decision(spec)
        decision["return_code"] = RC_PASS if decision["ready"] else RC_CONTRACT_BLOCKED
    elif args.action == "freeze":
        decision = freeze_contract(spec)
    else:
        decision = run_diagnostic(spec)
    sys.stdout.write(canonical_json(decision))
    return int(decision["return_code"])


if __name__ == "__main__":
    raise SystemExit(main())
