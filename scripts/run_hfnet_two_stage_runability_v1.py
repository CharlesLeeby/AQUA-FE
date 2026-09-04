#!/usr/bin/env python3
"""Fail-closed Phase-D HFNet-SLAM runability supervisor for EuRoC MH01.

The runner has four explicit actions:

``preflight``
    Read-only audit of the frozen official stack and the already materialized
    EuRoC ``MH_01_easy`` input.
``prepare``
    Create the fresh attempt namespace, copy ONNX and TensorRT timing-cache
    seed to a run-local directory, and derive a settings file whose only
    difference from the official EuRoC settings is ``Extractor.modelPath``.
``check``
    Read-only re-audit of the prepared namespace.  It never starts HFNet.
``run``
    One-shot execution.  It requires an exact authorization token and writes
    a no-clobber process-start claim before invoking the frozen headless ELF.

This module does not download or extract EuRoC, never modifies the official
HFNet-SLAM checkout, and does not treat Phase-D output as an underwater or
accuracy result.
"""

from __future__ import annotations

import argparse
import bisect
import csv
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]

PREFLIGHT_SCHEMA = "aqua-fe-hfnet-phase-d-mh01-preflight-v1"
PREPARED_SCHEMA = "aqua-fe-hfnet-phase-d-mh01-prepared-v1"
CHECK_SCHEMA = "aqua-fe-hfnet-phase-d-mh01-check-v1"
START_CLAIM_SCHEMA = "aqua-fe-hfnet-phase-d-mh01-process-start-claim-v1"
RESULT_SCHEMA = "aqua-fe-hfnet-phase-d-mh01-run-result-v1"
ROLE = "PHASE_D_OFFICIAL_EUROC_MH01_DEVELOPMENT_RUNABILITY_ONLY"

OFFICIAL_COMMIT = "c354c72588a97bb6f6a9c7c8317530795956ec80"
OFFICIAL_TREE = "6619814aed4cd0e4baa2501341a48f753f8ba196"
OFFICIAL_ORIGIN = "https://github.com/LiuLimingCode/HFNet_SLAM.git"

EXPECTED_CAMERA_COUNT = 3_682
EXPECTED_WIDTH = 752
EXPECTED_HEIGHT = 480
MAX_CAMERA_ASSOCIATION_ERROR_NS = 256
QUATERNION_NORM_TOLERANCE = 0.001
MIN_TRAJECTORY_ROWS = 2_578
MIN_TRAJECTORY_SPAN_SECONDS = 120.0
MIN_LAST_INPUT_FRACTION = 0.9
MIN_KEYFRAMES = 20
TIMEOUT_SECONDS = 900

RUN_AUTHORIZATION_TOKEN = "PHASE_D_MH01_ATTEMPT_001_START_ONCE"

RC_OK = 0
RC_FAILED = 1
RC_BLOCKED = 2

DEFAULT_OFFICIAL_ROOT = Path("/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1")
DEFAULT_BINARY = ROOT / "build/published_baselines/hfnet_slam_headless_entry_v3/mono_inertial_euroc_headless_v3"
DEFAULT_BUILD_MANIFEST = DEFAULT_BINARY.parent / "build_manifest.json"
DEFAULT_LIBRARY = DEFAULT_OFFICIAL_ROOT / "lib/libHFNet_SLAM.so"
DEFAULT_ENTRY_SOURCE = DEFAULT_OFFICIAL_ROOT / "Examples/Monocular-Inertial/mono_inertial_euroc.cc"
DEFAULT_HARNESS_SOURCE = ROOT / "scripts/harnesses/hfnet_slam_mono_inertial_euroc_headless_v3.cc"
DEFAULT_OFFICIAL_CONFIG = DEFAULT_OFFICIAL_ROOT / "Examples/Monocular-Inertial/EuRoC.yaml"
DEFAULT_TIMESTAMPS = DEFAULT_OFFICIAL_ROOT / "Examples/Monocular-Inertial/EuRoC_TimeStamps/MH01.txt"
DEFAULT_SHARED_MODEL_DIR = Path("/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT")
DEFAULT_ONNX = DEFAULT_SHARED_MODEL_DIR / "HF-Net.onnx"
DEFAULT_CACHE_SEED = DEFAULT_SHARED_MODEL_DIR / "HF-Net.cache"
DEFAULT_RUNTIME_ROOT = Path("/home/ma/opt/hfnet_cuda116_trt851_r1")
DEFAULT_PANGOLIN_ROOT = Path("/home/ma/SLAM/aqua_deps/install")
DEFAULT_DATASET = Path("/mnt/data/AQUA-FE_WS/datasets/official_euroc_v1/MH01/MH_01_easy")
DEFAULT_ARCHIVE = Path("/mnt/data/AQUA-FE_WS/datasets/official_euroc_v1/downloads/MH_01_easy.zip")
DEFAULT_DOWNLOAD_MANIFEST = DEFAULT_ARCHIVE.parent / "MH_01_easy_download_manifest_v1.json"
DEFAULT_FREEZE = ROOT / "papers/hfnet_v6_two_stage_runability_freeze_v1.json"
DEFAULT_ADOPTION = ROOT / "papers/hfnet_v6_mh01_input_adoption_v1.json"
DEFAULT_PRESTART_INCIDENT = ROOT / "papers/hfnet_v6_attempt_001_prestart_incident_v1.json"
DEFAULT_EXECUTION_LOCK = ROOT / "papers/hfnet_v6_attempt_001_execution_lock_v1.json"
DEFAULT_INPUT_INVENTORY = DEFAULT_DATASET.parent / "MH_01_easy_input_inventory_v1.json"
DEFAULT_ATTEMPT = Path("/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/dev_euroc_mh01/attempt_001")

OFFICIAL_MODEL_PATH_LINE = 'Extractor.modelPath: "/home/llm/ROS/HFNet_SLAM/model/HFNet-RT/"'

EXPECTED_IDENTITIES: Mapping[str, Mapping[str, object]] = {
    "freeze": {"sha256": "46d599746696ce492bb7029db82778f1bf0d59b803939ec61f54db8a847dae30", "size_bytes": 4_621},
    "binary": {"sha256": "4d17eecc74ec8f4bcbe4381d579d2bb48160cf63f6dc948f7857d92e681affeb", "size_bytes": 118_280},
    "build_manifest": {"sha256": "dc01d34652afbeb9dfd8b64e96b7d3ecdd8a09522796b73207a05e295ca4f8e9", "size_bytes": 1_748},
    "official_library": {"sha256": "a56dfd1b48dee4af5be4e55b076d32eac2cf8fb463da8ab943b690377f193717", "size_bytes": 4_807_712},
    "official_entry": {"sha256": "fa3effb0c2b99bc4dd83abda443180cf2f017f61710e02fa6b3f9278cc774d39", "size_bytes": 10_201},
    "headless_source": {"sha256": "303947840bdc5377656554560c6785b3218a52e034862a63d5d6da0036b81d90", "size_bytes": 1_112},
    "official_config": {"sha256": "9bbf682649b32ab2292979c7bf63b9fe12787948e74811838259aa723ab8ed01", "size_bytes": 2_613},
    "timestamps": {"sha256": "9354db11b423f7169eda7a3048d9594ee14572c6017e1439dee7861261b065fb", "size_bytes": 73_640},
    "onnx": {"sha256": "354a23f9c28b75ea9056a8eb5586e3b13191426521fd3f5556e5bfd670fc39b5", "size_bytes": 132_238_602},
    "cache_seed": {"sha256": "6798ef896e4f503d4d81827a81fc9dad99d40c5e10352abbe974ed309bd0c0e7", "size_bytes": 853_319},
    "archive": {"sha256": "5f4ecbc563e7bf04950efab76fc3b14e126d4c91a1dd1134c33124fe18a4bfc6", "size_bytes": 1_571_292_346},
    "download_manifest": {"sha256": "3cbf9f91c286fee760eb620cb6ee97f6461e5df5a7f1700a6c17514a0ea71d4b", "size_bytes": 726},
    "adoption": {"sha256": "cd45e7c39f322bc60d840ae18816584fce024d8220e89ef0698915af51c4437d", "size_bytes": 6_622},
    "input_inventory": {"sha256": "a6009f56146fc675131f44fd2d355092b37035958e6d1e73b87ce21130427ff6", "size_bytes": 664_378},
    "prestart_incident": {"sha256": "cdc691643bec2b1c849d8e12a237411f8c19a4041d772a52ca4e0b694941a6ac", "size_bytes": 3_211},
}

EXPECTED_IMAGE_PAYLOAD_TREE_SHA256 = "89ff5551c437eba2c0ef349ee8d64d6e4cc83637858f290994e3f0188cf6ef53"
EXPECTED_IMAGE_TOTAL_BYTES = 1_333_002_361
EXPECTED_EXTRACTED_TREE_SHA256 = "e6033bcf32b182eafad64c68cc634dbce896b5e33caef99bee6840d3c1590a08"
EXPECTED_EXTRACTED_FILE_COUNT = 3_689
EXPECTED_EXTRACTED_TOTAL_BYTES = 1_344_612_193
EXPECTED_DATASET_METADATA: Mapping[str, Mapping[str, object]] = {
    "camera_csv": {"sha256": "62db628a8e6358f43df81e66ddb4597ab40b19a10f3d6cd80cc04d590b5adb12", "size_bytes": 165_716},
    "camera_sensor": {"sha256": "191748edddda5d1368188f5b0a3c4bed6c48842c178ef9d83c50cba17d66e819", "size_bytes": 683},
    "imu_csv": {"sha256": "226470999dc8ba758c838982fd7eb2bc9f3f2b489e85a38d0ecf8b9d40785a5b", "size_bytes": 5_210_832},
    "imu_sensor": {"sha256": "91e6c408416f549f87e7405830b83849cca10521f3d3fc8bb3de862c2bc882d0", "size_bytes": 695},
    "groundtruth_csv": {"sha256": "aae2d7c5684724c8afe364d2fd8499a6ed77a9169adf03736531f67d8e7b2117", "size_bytes": 6_225_269},
    "groundtruth_sensor": {"sha256": "e02cacbad1b654908f1fad9f8997672a2928ec348840225919259f73f1084a95", "size_bytes": 489},
}


class ContractError(RuntimeError):
    """A frozen identity, input, staging, or one-shot contract was violated."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    duration_seconds: float = 0.0


@dataclass(frozen=True)
class Spec:
    official_root: Path = DEFAULT_OFFICIAL_ROOT
    binary: Path = DEFAULT_BINARY
    build_manifest: Path = DEFAULT_BUILD_MANIFEST
    official_library: Path = DEFAULT_LIBRARY
    official_entry: Path = DEFAULT_ENTRY_SOURCE
    headless_source: Path = DEFAULT_HARNESS_SOURCE
    official_config: Path = DEFAULT_OFFICIAL_CONFIG
    timestamps: Path = DEFAULT_TIMESTAMPS
    onnx: Path = DEFAULT_ONNX
    cache_seed: Path = DEFAULT_CACHE_SEED
    runtime_root: Path = DEFAULT_RUNTIME_ROOT
    pangolin_root: Path = DEFAULT_PANGOLIN_ROOT
    dataset: Path = DEFAULT_DATASET
    archive: Path = DEFAULT_ARCHIVE
    download_manifest: Path = DEFAULT_DOWNLOAD_MANIFEST
    freeze: Path = DEFAULT_FREEZE
    adoption: Path = DEFAULT_ADOPTION
    prestart_incident: Path = DEFAULT_PRESTART_INCIDENT
    execution_lock: Path = DEFAULT_EXECUTION_LOCK
    input_inventory: Path = DEFAULT_INPUT_INVENTORY
    attempt: Path = DEFAULT_ATTEMPT
    timeout_seconds: int = TIMEOUT_SECONDS
    governance_records_required: bool = True
    expected: Mapping[str, Mapping[str, object]] = field(default_factory=lambda: EXPECTED_IDENTITIES)

    @property
    def model_dir(self) -> Path:
        return self.attempt / "run_local_model/HFNet-RT"

    @property
    def derived_config(self) -> Path:
        return self.attempt / "runtime_config_model_path_only.yaml"

    @property
    def prepared_manifest(self) -> Path:
        return self.attempt / "prepared_manifest.json"

    @property
    def result_dir(self) -> Path:
        return self.attempt / "result"

    @property
    def start_claim(self) -> Path:
        return self.attempt / "process_start_claim.json"

    @property
    def stdout_log(self) -> Path:
        return self.attempt / "headless.stdout.log"

    @property
    def stderr_log(self) -> Path:
        return self.attempt / "headless.stderr.log"

    @property
    def run_result(self) -> Path:
        return self.attempt / "run_result.json"


DEFAULT_SPEC = Spec()
Probe = Callable[[Sequence[str], Optional[Mapping[str, str]], Optional[Path]], CommandResult]
Execute = Callable[[Sequence[str], Mapping[str, str], Optional[Path], int], CommandResult]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"


def absolute(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path, *, recorded_path: Optional[Path] = None) -> dict[str, object]:
    lexical = path.expanduser()
    metadata = lexical.lstat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ContractError(f"NOT_REGULAR_NONSYMLINK_FILE:{lexical}")
    return {
        "path": str(absolute(recorded_path or lexical)),
        "sha256": sha256(lexical),
        "size_bytes": metadata.st_size,
    }


def require_identity(path: Path, expected: Mapping[str, object], label: str) -> dict[str, object]:
    observed = identity(path)
    if any(observed.get(key) != value for key, value in expected.items()):
        raise ContractError(f"FROZEN_IDENTITY_MISMATCH:{label}")
    return observed


def write_exclusive(path: Path, payload: bytes, mode: int = 0o444) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    os.chmod(path, mode)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read_canonical_json(path: Path) -> object:
    payload = path.read_text(encoding="utf-8")
    value = json.loads(payload)
    if payload != canonical_json(value):
        raise ContractError(f"JSON_NOT_CANONICAL:{path}")
    return value


def default_probe(command: Sequence[str], environment: Optional[Mapping[str, str]], cwd: Optional[Path]) -> CommandResult:
    env = dict(os.environ)
    if environment:
        env.update(environment)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    started = time.monotonic()
    try:
        done = subprocess.run(
            list(command),
            cwd=str(cwd) if cwd else None,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=60,
        )
        return CommandResult(done.returncode, done.stdout, done.stderr, False, time.monotonic() - started)
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else error.stdout or ""
        stderr = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr or ""
        return CommandResult(124, stdout, stderr, True, time.monotonic() - started)
    except OSError as error:
        return CommandResult(126, "", f"{type(error).__name__}:{error}", False, time.monotonic() - started)


def default_execute(command: Sequence[str], environment: Mapping[str, str], cwd: Optional[Path], timeout: int) -> CommandResult:
    started = time.monotonic()
    try:
        done = subprocess.run(
            list(command),
            cwd=str(cwd) if cwd else None,
            env=dict(environment),
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
        return CommandResult(done.returncode, done.stdout, done.stderr, False, time.monotonic() - started)
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else error.stdout or ""
        stderr = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr or ""
        return CommandResult(124, stdout, stderr, True, time.monotonic() - started)
    except OSError as error:
        return CommandResult(126, "", f"{type(error).__name__}:{error}", False, time.monotonic() - started)


def runtime_library_paths(spec: Spec) -> tuple[Path, ...]:
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


def runtime_environment(spec: Spec) -> dict[str, str]:
    environment = {
        "PATH": os.environ.get("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"),
        "HOME": os.environ.get("HOME", "/home/ma"),
        "USER": os.environ.get("USER", "ma"),
        "CUDA_VISIBLE_DEVICES": "0",
        "LANG": "C",
        "LC_ALL": "C",
        "LD_LIBRARY_PATH": ":".join(str(absolute(path)) for path in runtime_library_paths(spec)),
    }
    if os.environ.get("TMPDIR"):
        environment["TMPDIR"] = os.environ["TMPDIR"]
    return environment


def command_argv(spec: Spec) -> list[str]:
    return [
        str(absolute(spec.binary)),
        str(absolute(spec.derived_config)),
        str(absolute(spec.result_dir)).rstrip("/") + "/",
        str(absolute(spec.dataset)),
        str(absolute(spec.timestamps)),
    ]


def parse_timestamps(path: Path) -> list[int]:
    payload = path.read_text(encoding="ascii")
    if not payload.endswith("\n"):
        raise ContractError("TIMESTAMPS_FINAL_NEWLINE_MISSING")
    lines = payload.splitlines()
    if len(lines) != EXPECTED_CAMERA_COUNT:
        raise ContractError(f"TIMESTAMP_COUNT_MISMATCH:{len(lines)}")
    try:
        stamps = [int(line) for line in lines]
    except ValueError as error:
        raise ContractError(f"TIMESTAMPS_NONINTEGER:{error}") from error
    if any(str(stamp) != line for stamp, line in zip(stamps, lines)):
        raise ContractError("TIMESTAMPS_NONCANONICAL")
    if any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise ContractError("TIMESTAMPS_NOT_STRICT")
    return stamps


def png_header(path: Path) -> dict[str, int]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(str(path), flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ContractError(f"IMAGE_NOT_REGULAR:{path}")
        header = os.read(descriptor, 33)
    finally:
        os.close(descriptor)
    if (
        len(header) != 33
        or header[:8] != b"\x89PNG\r\n\x1a\n"
        or struct.unpack(">I", header[8:12])[0] != 13
        or header[12:16] != b"IHDR"
    ):
        raise ContractError(f"INVALID_PNG_HEADER:{path}")
    width, height = struct.unpack(">II", header[16:24])
    return {"width": width, "height": height, "bit_depth": header[24], "color_type": header[25]}


def audit_dataset(spec: Spec) -> dict[str, Any]:
    root = spec.dataset.expanduser()
    root_metadata = root.lstat()
    if not stat.S_ISDIR(root_metadata.st_mode) or stat.S_ISLNK(root_metadata.st_mode):
        raise ContractError(f"DATASET_NOT_REAL_DIRECTORY:{root}")
    stamps = parse_timestamps(spec.timestamps)
    cam0 = root / "mav0/cam0"
    image_root = cam0 / "data"
    camera_csv = cam0 / "data.csv"
    imu_csv = root / "mav0/imu0/data.csv"
    gt_csv = root / "mav0/state_groundtruth_estimate0/data.csv"
    semantic_paths = {
        "camera_csv": camera_csv,
        "camera_sensor": cam0 / "sensor.yaml",
        "imu_csv": imu_csv,
        "imu_sensor": root / "mav0/imu0/sensor.yaml",
        "groundtruth_csv": gt_csv,
        "groundtruth_sensor": root / "mav0/state_groundtruth_estimate0/sensor.yaml",
    }
    inventory_identity = require_identity(spec.input_inventory, spec.expected["input_inventory"], "input_inventory")
    inventory = read_canonical_json(spec.input_inventory)
    if not isinstance(inventory, dict):
        raise ContractError("INPUT_INVENTORY_NOT_OBJECT")
    inventory_records = inventory.get("files")
    if (
        inventory.get("schema_version") != "aqua-fe-official-euroc-mh01-selected-input-inventory-v1"
        or inventory.get("root") != str(absolute(root))
        or inventory.get("digest_algorithm") != "sha256_of_inventory_record_order_relpath_NUL_decimal_size_NUL_lowercase_hex_sha256_newline"
        or inventory.get("file_count") != EXPECTED_EXTRACTED_FILE_COUNT
        or inventory.get("total_bytes") != EXPECTED_EXTRACTED_TOTAL_BYTES
        or inventory.get("tree_sha256") != EXPECTED_EXTRACTED_TREE_SHA256
        or not isinstance(inventory_records, list)
        or len(inventory_records) != EXPECTED_EXTRACTED_FILE_COUNT
    ):
        raise ContractError("INPUT_INVENTORY_SEMANTICS_MISMATCH")
    inventory_by_path: dict[str, Mapping[str, object]] = {}
    for record in inventory_records:
        if (
            not isinstance(record, dict)
            or set(record) != {"path", "sha256", "size_bytes"}
            or not isinstance(record.get("path"), str)
            or record["path"] in inventory_by_path
        ):
            raise ContractError("INPUT_INVENTORY_RECORD_INVALID_OR_DUPLICATE")
        inventory_by_path[record["path"]] = record
    observed_files: list[str] = []
    for path in root.rglob("*"):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ContractError(f"DATASET_SYMLINKS_FORBIDDEN:{path}")
        if stat.S_ISREG(metadata.st_mode):
            observed_files.append(path.relative_to(root).as_posix())
        elif not stat.S_ISDIR(metadata.st_mode):
            raise ContractError(f"DATASET_SPECIAL_FILE_FORBIDDEN:{path}")
    if len(observed_files) != len(inventory_by_path) or set(observed_files) != set(inventory_by_path):
        raise ContractError("DATASET_EXACT_FILE_INVENTORY_MISMATCH")

    audited_records: dict[str, dict[str, object]] = {}

    def audit_file(path: Path) -> dict[str, object]:
        observed = identity(path)
        relative = path.relative_to(root).as_posix()
        record = {
            "path": relative,
            "sha256": observed["sha256"],
            "size_bytes": observed["size_bytes"],
        }
        if record != inventory_by_path.get(relative):
            raise ContractError(f"DATASET_FILE_INVENTORY_IDENTITY_DRIFT:{relative}")
        audited_records[relative] = record
        return observed

    for path in semantic_paths.values():
        if not path.is_file() or path.is_symlink():
            raise ContractError(f"DATASET_SEMANTIC_FILE_MISSING_OR_SYMLINK:{path}")
    if not image_root.is_dir() or image_root.is_symlink():
        raise ContractError("CAMERA_IMAGE_ROOT_MISSING_OR_SYMLINK")

    expected_names = [f"{stamp}.png" for stamp in stamps]
    observed_names = sorted(path.name for path in image_root.iterdir())
    if observed_names != sorted(expected_names):
        raise ContractError("CAMERA_IMAGE_FILENAME_SET_MISMATCH")

    with camera_csv.open("r", encoding="ascii", newline="") as stream:
        rows = list(csv.reader(stream))
    if len(rows) != EXPECTED_CAMERA_COUNT + 1 or len(rows[0]) != 2 or not rows[0][0].startswith("#timestamp"):
        raise ContractError("CAMERA_CSV_SCHEMA_OR_COUNT_MISMATCH")
    for index, (row, stamp, filename) in enumerate(zip(rows[1:], stamps, expected_names)):
        if row != [str(stamp), filename]:
            raise ContractError(f"CAMERA_CSV_ROW_MISMATCH:{index}")

    aggregate = hashlib.sha256()
    total_image_bytes = 0
    first_image = last_image = None
    for index, (stamp, filename) in enumerate(zip(stamps, expected_names)):
        path = image_root / filename
        header = png_header(path)
        if header != {"width": EXPECTED_WIDTH, "height": EXPECTED_HEIGHT, "bit_depth": 8, "color_type": 0}:
            raise ContractError(f"CAMERA_IMAGE_FORMAT_MISMATCH:{index}:{header}")
        observed = audit_file(path)
        relative = path.relative_to(root).as_posix()
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(str(observed["size_bytes"]).encode("ascii"))
        aggregate.update(b"\0")
        aggregate.update(str(observed["sha256"]).encode("ascii"))
        aggregate.update(b"\n")
        total_image_bytes += int(observed["size_bytes"])
        if index == 0:
            first_image = observed
        if index == len(stamps) - 1:
            last_image = observed

    with imu_csv.open("r", encoding="ascii", newline="") as stream:
        imu_rows = list(csv.reader(stream))
    if not imu_rows or len(imu_rows[0]) != 7 or not imu_rows[0][0].startswith("#timestamp"):
        raise ContractError("IMU_CSV_HEADER_MISMATCH")
    imu_stamps: list[int] = []
    for index, fields in enumerate(imu_rows[1:]):
        if len(fields) != 7:
            raise ContractError(f"IMU_FIELD_COUNT:{index}")
        try:
            stamp = int(fields[0])
            values = [float(value) for value in fields[1:]]
        except ValueError as error:
            raise ContractError(f"IMU_NONNUMERIC:{index}") from error
        if str(stamp) != fields[0] or not all(math.isfinite(value) for value in values):
            raise ContractError(f"IMU_INVALID_VALUE:{index}")
        imu_stamps.append(stamp)
    if not imu_stamps or any(right <= left for left, right in zip(imu_stamps, imu_stamps[1:])):
        raise ContractError("IMU_TIMESTAMPS_NOT_STRICT")
    if not (imu_stamps[0] <= stamps[0] and imu_stamps[-1] >= stamps[-1]):
        raise ContractError("IMU_DOES_NOT_BRACKET_CAMERA")

    with gt_csv.open("r", encoding="ascii", newline="") as stream:
        gt_rows = list(csv.reader(stream))
    if not gt_rows or len(gt_rows[0]) != 17 or not gt_rows[0][0].startswith("#timestamp"):
        raise ContractError("GROUNDTRUTH_CSV_HEADER_MISMATCH")
    gt_stamps: list[int] = []
    for index, fields in enumerate(gt_rows[1:]):
        if len(fields) != 17:
            raise ContractError(f"GROUNDTRUTH_FIELD_COUNT:{index}")
        try:
            stamp = int(fields[0])
            values = [float(value) for value in fields[1:]]
        except ValueError as error:
            raise ContractError(f"GROUNDTRUTH_NONNUMERIC:{index}") from error
        if str(stamp) != fields[0] or not all(math.isfinite(value) for value in values):
            raise ContractError(f"GROUNDTRUTH_INVALID_VALUE:{index}")
        gt_stamps.append(stamp)
    if not gt_stamps or any(right <= left for left, right in zip(gt_stamps, gt_stamps[1:])):
        raise ContractError("GROUNDTRUTH_TIMESTAMPS_NOT_STRICT")
    groundtruth_camera_coverage = sum(gt_stamps[0] <= stamp <= gt_stamps[-1] for stamp in stamps)

    semantic = {name: audit_file(path) for name, path in semantic_paths.items()}
    for name, observed in semantic.items():
        if any(observed.get(key) != value for key, value in EXPECTED_DATASET_METADATA[name].items()):
            raise ContractError(f"DATASET_METADATA_IDENTITY_DRIFT:{name}")
    for relative in inventory_by_path:
        if relative not in audited_records:
            audit_file(root / relative)
    extracted_digest = hashlib.sha256()
    extracted_total_bytes = 0
    for relative in inventory_by_path:
        record = audited_records[relative]
        extracted_digest.update(relative.encode("utf-8"))
        extracted_digest.update(b"\0")
        extracted_digest.update(str(record["size_bytes"]).encode("ascii"))
        extracted_digest.update(b"\0")
        extracted_digest.update(str(record["sha256"]).encode("ascii"))
        extracted_digest.update(b"\n")
        extracted_total_bytes += int(record["size_bytes"])
    if (
        len(audited_records) != EXPECTED_EXTRACTED_FILE_COUNT
        or extracted_total_bytes != EXPECTED_EXTRACTED_TOTAL_BYTES
        or extracted_digest.hexdigest() != EXPECTED_EXTRACTED_TREE_SHA256
    ):
        raise ContractError("DATASET_EXTRACTED_TREE_IDENTITY_DRIFT")
    if total_image_bytes != EXPECTED_IMAGE_TOTAL_BYTES or aggregate.hexdigest() != EXPECTED_IMAGE_PAYLOAD_TREE_SHA256:
        raise ContractError("CAMERA_IMAGE_PAYLOAD_IDENTITY_DRIFT")
    return {
        "root": str(absolute(root)),
        "camera_count": len(stamps),
        "camera_timestamps_ns": stamps,
        "camera_first_ns": stamps[0],
        "camera_last_ns": stamps[-1],
        "camera_duration_seconds": (stamps[-1] - stamps[0]) / 1e9,
        "image_format": {"width": EXPECTED_WIDTH, "height": EXPECTED_HEIGHT, "bit_depth": 8, "color_type": 0},
        "image_total_bytes": total_image_bytes,
        "image_payload_tree_sha256": aggregate.hexdigest(),
        "input_inventory": inventory_identity,
        "extracted_file_count": len(audited_records),
        "extracted_total_bytes": extracted_total_bytes,
        "extracted_tree_sha256": extracted_digest.hexdigest(),
        "first_image": first_image,
        "last_image": last_image,
        "imu_count": len(imu_stamps),
        "imu_first_ns": imu_stamps[0],
        "imu_last_ns": imu_stamps[-1],
        "imu_brackets_camera": True,
        "groundtruth_count": len(gt_stamps),
        "groundtruth_first_ns": gt_stamps[0],
        "groundtruth_last_ns": gt_stamps[-1],
        "groundtruth_camera_coverage_count": groundtruth_camera_coverage,
        "groundtruth_camera_coverage_fraction": groundtruth_camera_coverage / len(stamps),
        "semantic_files": semantic,
    }


def audit_freeze(spec: Spec) -> dict[str, Any]:
    frozen_identity = require_identity(spec.freeze, spec.expected["freeze"], "freeze")
    value = json.loads(spec.freeze.read_text(encoding="utf-8"))
    phase = value.get("phase_d", {})
    system = value.get("system", {})
    namespace = Path(str(phase.get("namespace", "")))
    expected_gate = {
        "return_code": 0,
        "timed_out": False,
        "input_images_consumed": EXPECTED_CAMERA_COUNT,
        "trajectory_rows_min": MIN_TRAJECTORY_ROWS,
        "trajectory_span_seconds_min": 120,
        "trajectory_reaches_last_input_fraction_min": MIN_LAST_INPUT_FRACTION,
        "keyframes_min": MIN_KEYFRAMES,
        "late_keyframe_required": True,
    }
    if (
        value.get("schema_version") != "aqua-fe-published-hfnet-two-stage-runability-freeze-v1"
        or value.get("status") != "FROZEN_BEFORE_HFNET_PROCESS_START"
        or value.get("authorization", {}).get("development_runability_execution_authorized") is not True
        or value.get("authorization", {}).get("formal_scientific_adoption_authorized") is not False
        or system.get("official_commit") != OFFICIAL_COMMIT
        or system.get("official_tree") != OFFICIAL_TREE
        or phase.get("role") != "official_euroc_mh01_development_runability"
        or phase.get("input", {}).get("dataset") != "EuRoC_MH_01_easy"
        or phase.get("pass_gate") != expected_gate
        or absolute(namespace) != absolute(spec.attempt)
    ):
        raise ContractError("PHASE_D_FREEZE_SEMANTICS_MISMATCH")
    return {
        "identity": frozen_identity,
        "status": value["status"],
        "role": phase["role"],
        "pass_gate": expected_gate,
        "claim_boundary": value.get("claim_boundary"),
        "stop_policy": phase.get("stop_policy"),
    }


def audit_archive(spec: Spec) -> dict[str, Any]:
    archive = require_identity(spec.archive, spec.expected["archive"], "archive")
    manifest_identity = require_identity(spec.download_manifest, spec.expected["download_manifest"], "download_manifest")
    manifest = json.loads(spec.download_manifest.read_text(encoding="utf-8"))
    if (
        manifest.get("schema_version") != "aqua-fe-official-euroc-mh01-download-v1"
        or manifest.get("archive") != archive
        or manifest.get("source", {}).get("member") != "machine_hall/MH_01_easy/MH_01_easy.zip"
        or manifest.get("source", {}).get("inner_crc32") != "a1c54dd7"
    ):
        raise ContractError("OFFICIAL_ARCHIVE_MANIFEST_MISMATCH")
    return {"archive": archive, "download_manifest": manifest_identity, "source": manifest["source"]}


def audit_adoption(
    spec: Spec,
    freeze: Mapping[str, Any],
    archive: Mapping[str, Any],
    input_audit: Mapping[str, Any],
) -> dict[str, Any]:
    adoption_identity = require_identity(spec.adoption, spec.expected["adoption"], "adoption")
    adoption = json.loads(spec.adoption.read_text(encoding="utf-8"))
    extraction = adoption.get("selected_lossless_extraction", {})
    disclosed_input = adoption.get("input_audit", {})
    continuation = adoption.get("continuation", {})
    boundaries = adoption.get("headless_semantic_boundary_records", {})
    materialization = adoption.get("materialization", {})
    metadata_key_map = {
        "cam0_data_csv": "camera_csv",
        "cam0_sensor_yaml": "camera_sensor",
        "imu0_data_csv": "imu_csv",
        "imu0_sensor_yaml": "imu_sensor",
        "groundtruth_data_csv": "groundtruth_csv",
        "groundtruth_sensor_yaml": "groundtruth_sensor",
    }
    observed_metadata = {
        adoption_name: {
            "sha256": input_audit["semantic_files"][audit_name]["sha256"],
            "size_bytes": input_audit["semantic_files"][audit_name]["size_bytes"],
        }
        for adoption_name, audit_name in metadata_key_map.items()
    }
    expected_inventory_record = {
        **input_audit["input_inventory"],
        "contains_ordered_path_size_sha256_records": EXPECTED_EXTRACTED_FILE_COUNT,
    }
    expected_additional_gates = {
        "process_start_count_exact": 1,
        "full_input_loop_completed_over_frozen_timestamp_count": EXPECTED_CAMERA_COUNT,
        "trajectory_and_keyframe_rows_finite_fields_exact": 8,
        "trajectory_and_keyframe_timestamps_strictly_increasing": True,
        "trajectory_and_keyframe_quaternion_norm_tolerance": QUATERNION_NORM_TOLERANCE,
        "unique_camera_grid_association_max_error_ns": MAX_CAMERA_ASSOCIATION_ERROR_NS,
        "official_stack_pre_post_identity_required": True,
        "onnx_pre_post_identity_required": True,
        "derived_config_pre_post_identity_required": True,
        "shared_cache_pre_post_identity_required": True,
        "run_local_cache_change_allowed": True,
        "shared_cache_writeback_allowed": False,
    }
    expected_disclosed_input = {
        "official_timestamp_list_matches_cam0_csv_exactly": True,
        "camera_png_names_match_timestamp_grid_exactly": True,
        "camera_count": EXPECTED_CAMERA_COUNT,
        "camera_span_seconds": input_audit["camera_duration_seconds"],
        "camera_timestamps_strictly_increasing": True,
        "imu_count": input_audit["imu_count"],
        "imu_span_seconds": (input_audit["imu_last_ns"] - input_audit["imu_first_ns"]) / 1e9,
        "imu_timestamps_strictly_increasing": True,
        "imu_brackets_all_camera_timestamps": True,
        "groundtruth_count": input_audit["groundtruth_count"],
        "groundtruth_span_seconds": (input_audit["groundtruth_last_ns"] - input_audit["groundtruth_first_ns"]) / 1e9,
        "groundtruth_timestamps_strictly_increasing": True,
        "camera_timestamps_inside_groundtruth_interval": input_audit["groundtruth_camera_coverage_count"],
        "groundtruth_camera_coverage_fraction": input_audit["groundtruth_camera_coverage_fraction"],
    }
    if (
        adoption.get("schema_version") != "aqua-fe-hfnet-v6-mh01-input-adoption-v1"
        or adoption.get("status") != "ADOPTED_BEFORE_ANY_HFNET_V6_PROCESS_START"
        or adoption.get("parent_freeze") != freeze["identity"]
        or adoption.get("late_binding_disclosure", {}).get("hfnet_v6_process_start_count_before_this_adoption") != 0
        or adoption.get("late_binding_disclosure", {}).get("scientific_result_observed") is not False
        or materialization.get("download_manifest") != archive["download_manifest"]
        or materialization.get("inner_archive", {}).get("path") != archive["archive"]["path"]
        or materialization.get("inner_archive", {}).get("sha256") != archive["archive"]["sha256"]
        or materialization.get("inner_archive", {}).get("size_bytes") != archive["archive"]["size_bytes"]
        or extraction.get("root") != str(absolute(spec.dataset))
        or extraction.get("included_prefixes") != ["mav0/cam0/", "mav0/imu0/", "mav0/state_groundtruth_estimate0/"]
        or extraction.get("excluded_sensor_data") != ["mav0/cam1/"]
        or extraction.get("tree_digest_algorithm") != "sha256_of_inventory_record_order_relpath_NUL_decimal_size_NUL_lowercase_hex_sha256_newline"
        or extraction.get("tree_sha256") != input_audit["extracted_tree_sha256"]
        or extraction.get("file_count") != input_audit["extracted_file_count"]
        or extraction.get("total_bytes") != input_audit["extracted_total_bytes"]
        or extraction.get("no_symlinks") is not True
        or extraction.get("exact_file_inventory") != expected_inventory_record
        or extraction.get("metadata_records") != observed_metadata
        or disclosed_input != expected_disclosed_input
        or continuation.get("phase_d_hfnet_preflight_and_single_attempt_may_continue") is not True
        or continuation.get("phase_f_fresh_underwater_execution_authorized") is not False
        or continuation.get("algorithm_or_threshold_change_authorized") is not False
        or continuation.get("additional_mandatory_runner_gates") != expected_additional_gates
        or boundaries.get("build_manifest") != dict(spec.expected["build_manifest"])
        or boundaries.get("headless_source") != dict(spec.expected["headless_source"])
        or boundaries.get("official_entry_source") != dict(spec.expected["official_entry"])
        or boundaries.get("claimed_delta") != "viewer_disabled_only"
    ):
        raise ContractError("INPUT_ADOPTION_SEMANTICS_OR_CROSS_AUDIT_MISMATCH")
    return {
        "identity": adoption_identity,
        "status": adoption["status"],
        "extracted_tree_sha256": input_audit["extracted_tree_sha256"],
        "input_inventory": input_audit["input_inventory"],
        "metadata_records": observed_metadata,
        "additional_mandatory_runner_gates": expected_additional_gates,
    }


def _parse_ldd(payload: str) -> tuple[dict[str, str], list[str]]:
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for raw in payload.splitlines():
        line = raw.strip()
        if "=> not found" in line:
            missing.append(line.split("=>", 1)[0].strip())
        elif "=>" in line:
            name, rest = line.split("=>", 1)
            resolved[name.strip()] = rest.strip().split(" ", 1)[0]
    return resolved, missing


def audit_official_stack(spec: Spec, probe: Probe = default_probe) -> dict[str, Any]:
    paths = {
        "binary": spec.binary,
        "build_manifest": spec.build_manifest,
        "official_library": spec.official_library,
        "official_entry": spec.official_entry,
        "headless_source": spec.headless_source,
        "official_config": spec.official_config,
        "timestamps": spec.timestamps,
        "onnx": spec.onnx,
        "cache_seed": spec.cache_seed,
    }
    identities = {name: require_identity(path, spec.expected[name], name) for name, path in paths.items()}
    if spec.binary.read_bytes()[:4] != b"\x7fELF" or not spec.binary.stat().st_mode & stat.S_IXUSR:
        raise ContractError("HEADLESS_BINARY_NOT_EXECUTABLE_ELF")
    build = json.loads(spec.build_manifest.read_text(encoding="utf-8"))
    if build.get("semantic_delta") != {"all_other_entry_logic": "included_from_frozen_official_source", "system_constructor_bUseViewer": False}:
        raise ContractError("HEADLESS_BUILD_MANIFEST_DELTA_MISMATCH")
    harness = spec.headless_source.read_text(encoding="utf-8")
    required_harness = (
        ": System(settings_file, sensor, false, init_frame)",
        f'#include "{absolute(spec.official_entry)}"',
        "#define System HeadlessSystem",
    )
    if any(token not in harness for token in required_harness) or "TrackMonocular(" in harness:
        raise ContractError("HEADLESS_SINGLE_DELTA_AUDIT_FAILED")
    config = spec.official_config.read_text(encoding="utf-8")
    tokens = (
        OFFICIAL_MODEL_PATH_LINE,
        'Extractor.type: "HFNetRT"',
        "Extractor.scaleFactor: 1.2",
        "Extractor.nLevels: 4",
        "Extractor.nFeatures: 675",
        "Extractor.threshold: 0.01",
        "loopClosing: 1",
    )
    if any(config.count(token) != 1 for token in tokens):
        raise ContractError("OFFICIAL_EUROC_CONFIG_TOKEN_MISMATCH")
    parse_timestamps(spec.timestamps)

    git_commands = {
        "commit": ["git", "-C", str(spec.official_root), "rev-parse", "HEAD^{commit}"],
        "tree": ["git", "-C", str(spec.official_root), "rev-parse", "HEAD^{tree}"],
        "origin": ["git", "-C", str(spec.official_root), "remote", "get-url", "origin"],
        "status": ["git", "-C", str(spec.official_root), "status", "--porcelain=v1", "--untracked-files=no"],
    }
    git = {name: probe(command, None, None) for name, command in git_commands.items()}
    if any(row.returncode != 0 or row.timed_out for row in git.values()):
        raise ContractError("OFFICIAL_GIT_PROBE_FAILED")
    if (
        git["commit"].stdout.strip() != OFFICIAL_COMMIT
        or git["tree"].stdout.strip() != OFFICIAL_TREE
        or git["origin"].stdout.strip() != OFFICIAL_ORIGIN
        or git["status"].stdout.strip()
    ):
        raise ContractError("OFFICIAL_SOURCE_IDENTITY_OR_CLEANLINESS_MISMATCH")
    ldd = probe(["ldd", str(absolute(spec.binary))], runtime_environment(spec), None)
    resolved, missing = _parse_ldd(ldd.stdout)
    hfnet = [absolute(Path(path)) for name, path in resolved.items() if name.startswith("libHFNet_SLAM.so")]
    if ldd.returncode != 0 or ldd.timed_out or missing or hfnet != [absolute(spec.official_library)]:
        raise ContractError("HEADLESS_RUNTIME_LINKAGE_MISMATCH")
    return {
        "baseline": {"commit": OFFICIAL_COMMIT, "tree": OFFICIAL_TREE, "origin": OFFICIAL_ORIGIN},
        "identities": identities,
        "headless_boundary": {"viewer_enabled": False, "official_entry_included": True, "algorithm_or_threshold_modified": False},
        "runtime": {"environment": runtime_environment(spec), "ldd_missing": missing, "official_library_resolved": str(hfnet[0])},
    }


def collect_profile(spec: Spec, probe: Probe = default_probe) -> dict[str, Any]:
    freeze = audit_freeze(spec)
    archive = audit_archive(spec)
    input_audit = audit_dataset(spec)
    adoption = audit_adoption(spec, freeze, archive, input_audit)
    return {
        "schema_version": PREFLIGHT_SCHEMA,
        "scientific_role": ROLE,
        "freeze": freeze,
        "input_adoption": adoption,
        "official_stack": audit_official_stack(spec, probe),
        "official_archive_provenance": archive,
        "input": input_audit,
        "execution_policy": {
            "phase": "D",
            "dataset": "EuRoC_MH_01_easy",
            "maximum_process_starts": 1,
            "retry": False,
            "result_conditioned_selection": False,
            "formal_scientific_adoption": False,
        },
    }


def preflight(spec: Spec = DEFAULT_SPEC, *, probe: Probe = default_probe) -> dict[str, Any]:
    errors: list[str] = []
    profile = None
    try:
        profile = collect_profile(spec, probe)
    except (ContractError, OSError, UnicodeError, ValueError, json.JSONDecodeError, csv.Error) as error:
        errors.append(str(error))
    reservations = {"attempt_namespace_absent": not spec.attempt.exists() and not spec.attempt.is_symlink()}
    if not all(reservations.values()):
        errors.append("ATTEMPT_NAMESPACE_NOT_FRESH")
    return {
        "schema_version": PREFLIGHT_SCHEMA,
        "status": "PREFLIGHT_READY_FOR_PREPARE" if not errors else "PREFLIGHT_BLOCKED",
        "ready": not errors,
        "return_code": RC_OK if not errors else RC_BLOCKED,
        "errors": errors,
        "profile": profile,
        "reservations": reservations,
        "claims": {"filesystem_writes": False, "hfnet_process_started": False},
    }


def derive_runtime_config(source: str, final_model_dir: Path) -> str:
    replacement = f'Extractor.modelPath: "{absolute(final_model_dir)}/"'
    if source.count(OFFICIAL_MODEL_PATH_LINE) != 1:
        raise ContractError("OFFICIAL_CONFIG_MODEL_PATH_LINE_MISMATCH")
    derived = source.replace(OFFICIAL_MODEL_PATH_LINE, replacement)
    source_lines = source.splitlines(keepends=True)
    derived_lines = derived.splitlines(keepends=True)
    changed = [index for index, (left, right) in enumerate(zip(source_lines, derived_lines)) if left != right]
    if len(source_lines) != len(derived_lines) or len(changed) != 1:
        raise ContractError("DERIVED_CONFIG_NOT_SINGLE_LINE_CHANGE")
    for token in (
        'Extractor.type: "HFNetRT"',
        "Extractor.scaleFactor: 1.2",
        "Extractor.nLevels: 4",
        "Extractor.nFeatures: 675",
        "Extractor.threshold: 0.01",
        "loopClosing: 1",
    ):
        if source.count(token) != 1 or derived.count(token) != 1:
            raise ContractError("DERIVED_CONFIG_ALGORITHM_TOKEN_DRIFT")
    return derived


def profile_digest(profile: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(profile).encode("utf-8")).hexdigest()


def build_prepared_manifest(profile: Mapping[str, Any], spec: Spec, staged: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": PREPARED_SCHEMA,
        "scientific_role": ROLE,
        "prepared_at_utc": staged["prepared_at_utc"],
        "frozen_profile": dict(profile),
        "frozen_profile_sha256": profile_digest(profile),
        "namespace": str(absolute(spec.attempt)),
        "paths": {
            "dataset": str(absolute(spec.dataset)),
            "derived_config": str(absolute(spec.derived_config)),
            "run_local_model": str(absolute(spec.model_dir)),
            "result_directory": str(absolute(spec.result_dir)),
            "stdout": str(absolute(spec.stdout_log)),
            "stderr": str(absolute(spec.stderr_log)),
            "process_start_claim": str(absolute(spec.start_claim)),
            "run_result": str(absolute(spec.run_result)),
        },
        "staged": {
            "onnx": staged["onnx"],
            "cache_seed": staged["cache_seed"],
            "derived_config": staged["derived_config"],
            "official_shared_cache_pre": staged["official_shared_cache_pre"],
        },
        "launch": {
            "argv": command_argv(spec),
            "environment": runtime_environment(spec),
            "cwd": str(absolute(spec.attempt)),
            "timeout_seconds": spec.timeout_seconds,
            "authorization_token_required": RUN_AUTHORIZATION_TOKEN,
            "maximum_process_starts": 1,
            "retry": False,
        },
        "claims": {
            "hfnet_process_started": False,
            "official_source_modified": False,
            "algorithm_or_threshold_modified": False,
            "underwater_accuracy_result": False,
        },
    }


def prepare(spec: Spec = DEFAULT_SPEC, *, probe: Probe = default_probe) -> dict[str, Any]:
    decision = preflight(spec, probe=probe)
    if not decision["ready"]:
        return {**decision, "status": "PREPARE_BLOCKED", "return_code": RC_BLOCKED}
    profile = decision["profile"]
    parent = spec.attempt.parent
    temporary: Optional[Path] = None
    try:
        parent.mkdir(parents=True, exist_ok=True)
        if spec.attempt.exists() or spec.attempt.is_symlink():
            raise ContractError("ATTEMPT_NAMESPACE_RACE_OR_CLOBBER")
        temporary = Path(tempfile.mkdtemp(prefix=f".{spec.attempt.name}.prepare.", dir=str(parent)))
        temp_model = temporary / "run_local_model/HFNet-RT"
        temp_model.mkdir(parents=True)
        temp_onnx = temp_model / "HF-Net.onnx"
        temp_cache = temp_model / "HF-Net.cache"
        shutil.copyfile(spec.onnx, temp_onnx)
        shutil.copyfile(spec.cache_seed, temp_cache)
        os.chmod(temp_onnx, 0o444)
        os.chmod(temp_cache, 0o644)
        staged_onnx = identity(temp_onnx, recorded_path=spec.model_dir / "HF-Net.onnx")
        staged_cache = identity(temp_cache, recorded_path=spec.model_dir / "HF-Net.cache")
        source_onnx = identity(spec.onnx)
        source_cache = identity(spec.cache_seed)
        if staged_onnx["sha256"] != source_onnx["sha256"] or staged_onnx["size_bytes"] != source_onnx["size_bytes"]:
            raise ContractError("RUN_LOCAL_ONNX_COPY_MISMATCH")
        if staged_cache["sha256"] != source_cache["sha256"] or staged_cache["size_bytes"] != source_cache["size_bytes"]:
            raise ContractError("RUN_LOCAL_CACHE_COPY_MISMATCH")
        config_payload = derive_runtime_config(spec.official_config.read_text(encoding="utf-8"), spec.model_dir).encode("utf-8")
        temp_config = temporary / spec.derived_config.name
        write_exclusive(temp_config, config_payload)
        staged_config = identity(temp_config, recorded_path=spec.derived_config)
        staged = {
            "prepared_at_utc": now_utc(),
            "onnx": staged_onnx,
            "cache_seed": staged_cache,
            "derived_config": staged_config,
            "official_shared_cache_pre": source_cache,
        }
        manifest = build_prepared_manifest(profile, spec, staged)
        write_exclusive(temporary / spec.prepared_manifest.name, canonical_json(manifest).encode("utf-8"))
        for path in (temp_onnx, temp_cache, temp_config, temporary / spec.prepared_manifest.name):
            descriptor = os.open(str(path), os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        fsync_directory(temp_model)
        fsync_directory(temp_model.parent)
        fsync_directory(temporary)
        if identity(spec.cache_seed) != source_cache:
            raise ContractError("OFFICIAL_SHARED_CACHE_CHANGED_DURING_PREPARE")
        os.rename(temporary, spec.attempt)
        temporary = None
        fsync_directory(parent)
        prepared_identity = identity(spec.prepared_manifest)
        return {
            "schema_version": PREPARED_SCHEMA,
            "status": "PREPARED_NO_HFNET_PROCESS_STARTED",
            "return_code": RC_OK,
            "ready_for_check": True,
            "prepared_manifest": prepared_identity,
            "namespace": str(absolute(spec.attempt)),
            "claims": {"filesystem_writes": True, "hfnet_process_started": False},
        }
    except (ContractError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        if temporary is not None and temporary.exists():
            shutil.rmtree(temporary)
        return {
            "schema_version": PREPARED_SCHEMA,
            "status": "PREPARE_BLOCKED",
            "return_code": RC_BLOCKED,
            "ready_for_check": False,
            "errors": [str(error)],
            "claims": {"hfnet_process_started": False},
        }


def _prepared_allowed_files(spec: Spec) -> set[str]:
    return {
        "prepared_manifest.json",
        "runtime_config_model_path_only.yaml",
        "run_local_model/HFNet-RT/HF-Net.onnx",
        "run_local_model/HFNet-RT/HF-Net.cache",
    }


def _content_identity(path: Path) -> dict[str, object]:
    observed = identity(path)
    return {"sha256": observed["sha256"], "size_bytes": observed["size_bytes"]}


def audit_prestart_incident(spec: Spec, prepared: Mapping[str, Any]) -> dict[str, Any]:
    incident_identity = require_identity(
        spec.prestart_incident,
        spec.expected["prestart_incident"],
        "prestart_incident",
    )
    incident = json.loads(spec.prestart_incident.read_text(encoding="utf-8"))
    current = incident.get("attempt_001", {})
    prior = incident.get("prior_preparation_observation", {})
    continuation = incident.get("continuation", {})
    boundary = incident.get("claim_boundary", {})
    absences = {
        "process_start_claim_absent": not spec.start_claim.exists() and not spec.start_claim.is_symlink(),
        "run_result_absent": not spec.run_result.exists() and not spec.run_result.is_symlink(),
        "stdout_log_absent": not spec.stdout_log.exists() and not spec.stdout_log.is_symlink(),
        "stderr_log_absent": not spec.stderr_log.exists() and not spec.stderr_log.is_symlink(),
        "result_directory_absent": not spec.result_dir.exists() and not spec.result_dir.is_symlink(),
    }
    if (
        incident.get("schema_version") != "aqua-fe-hfnet-v6-phase-d-prestart-incident-v1"
        or incident.get("status") != "RECORDED_PRESTART_REPREPARATION_ATTEMPT_001_CURRENT_FINAL"
        or incident.get("scope", {}).get("phase") != "D_OFFICIAL_EUROC_MH01_DEVELOPMENT_RUNABILITY"
        or incident.get("scope", {}).get("parent_freeze") != identity(spec.freeze)
        or incident.get("scope", {}).get("final_input_adoption") != identity(spec.adoption)
        or current.get("path") != str(absolute(spec.attempt))
        or current.get("prepared_manifest") != _content_identity(spec.prepared_manifest)
        or current.get("derived_config") != _content_identity(spec.derived_config)
        or current.get("run_local_onnx") != _content_identity(spec.model_dir / "HF-Net.onnx")
        or current.get("run_local_cache_seed") != _content_identity(spec.model_dir / "HF-Net.cache")
        or current.get("prepared_at_utc") != prepared.get("prepared_at_utc")
        or current.get("frozen_profile_sha256") != prepared.get("frozen_profile_sha256")
        or current.get("prepared_against_final_input_adoption_and_runner_crossbind") is not True
        or any(current.get(name) is not value for name, value in absences.items())
        or current.get("hfnet_process_start_count") != 0
        or current.get("scientific_output_observed") is not False
        or current.get("disposition") != "CURRENT_PREPARED_NAMESPACE_MAY_START_EXACTLY_ONCE_AFTER_FINAL_CHECK"
        or prior.get("prepared_manifest_sha256") != "cb1832b2b2fa66932d9ffee08d2ad05db96bd4767db9b9186dcbf496ffea04ad"
        or prior.get("prepared_manifest_size_bytes") != 121_192
        or prior.get("observation_was_not_retained_on_disk") is not True
        or prior.get("hfnet_process_start_count_before_reprepare") != 0
        or prior.get("scientific_output_observed") is not False
        or prior.get("reconstruction_or_republication_authorized") is not False
        or continuation.get("attempt_001_current_preparation_may_start_after_exact_check") is not True
        or continuation.get("attempt_001_maximum_hfnet_process_starts") != 1
        or continuation.get("attempt_001_exact_start_token") != RUN_AUTHORIZATION_TOKEN
        or continuation.get("attempt_002_reserved_or_authorized") is not False
        or continuation.get("algorithm_or_threshold_change_authorized") is not False
        or continuation.get("phase_f_underwater_execution_authorized") is not False
        or continuation.get("further_attempt_001_deletion_or_mutation_before_start_authorized") is not False
        or boundary != {
            "this_incident_is_not_a_scientific_result": True,
            "this_incident_does_not_authorize_formal_adoption": True,
            "this_incident_only_adopts_the_current_prestart_development_preparation": True,
        }
        or prepared.get("frozen_profile", {}).get("input_adoption", {}).get("identity") != identity(spec.adoption)
        or not all(absences.values())
    ):
        raise ContractError("PRESTART_INCIDENT_SEMANTICS_OR_CURRENT_STATE_MISMATCH")
    return {"identity": incident_identity, "status": incident["status"], "current_absences": absences}


def audit_execution_lock(spec: Spec) -> dict[str, Any]:
    if not spec.execution_lock.exists() or spec.execution_lock.is_symlink():
        raise ContractError("FINAL_EXECUTION_LOCK_MISSING")
    lock_identity = identity(spec.execution_lock)
    lock = json.loads(spec.execution_lock.read_text(encoding="utf-8"))
    expected_attempt = {
        "path": str(absolute(spec.attempt)),
        "exact_start_token": RUN_AUTHORIZATION_TOKEN,
        "maximum_process_starts": 1,
        "process_start_claim_absent": True,
        "run_result_absent": True,
    }
    if (
        lock.get("schema_version") != "aqua-fe-hfnet-v6-attempt-001-execution-lock-v1"
        or lock.get("status") != "LOCKED_BEFORE_EXACTLY_ONE_HFNET_PROCESS_START"
        or lock.get("runner") != identity(Path(__file__).resolve())
        or lock.get("prepared_manifest") != identity(spec.prepared_manifest)
        or lock.get("parent_freeze") != identity(spec.freeze)
        or lock.get("final_input_adoption") != identity(spec.adoption)
        or lock.get("prestart_incident") != identity(spec.prestart_incident)
        or lock.get("attempt") != expected_attempt
        or spec.start_claim.exists()
        or spec.start_claim.is_symlink()
        or spec.run_result.exists()
        or spec.run_result.is_symlink()
    ):
        raise ContractError("FINAL_EXECUTION_LOCK_SEMANTICS_OR_CURRENT_STATE_MISMATCH")
    return {"identity": lock_identity, "status": lock["status"], "runner": lock["runner"], "attempt": expected_attempt}


def audit_prepared(spec: Spec, *, probe: Probe = default_probe, require_unstarted: bool = True) -> dict[str, Any]:
    if not spec.attempt.is_dir() or spec.attempt.is_symlink():
        raise ContractError("PREPARED_NAMESPACE_MISSING_OR_SYMLINK")
    manifest_value = read_canonical_json(spec.prepared_manifest)
    if not isinstance(manifest_value, dict) or manifest_value.get("schema_version") != PREPARED_SCHEMA:
        raise ContractError("PREPARED_MANIFEST_SCHEMA_MISMATCH")
    profile = collect_profile(spec, probe)
    if manifest_value.get("frozen_profile") != profile or manifest_value.get("frozen_profile_sha256") != profile_digest(profile):
        raise ContractError("PREPARED_FROZEN_PROFILE_DRIFT")
    local_onnx = identity(spec.model_dir / "HF-Net.onnx")
    local_cache = identity(spec.model_dir / "HF-Net.cache")
    source_onnx = identity(spec.onnx)
    source_cache = identity(spec.cache_seed)
    derived = identity(spec.derived_config)
    expected_config = derive_runtime_config(spec.official_config.read_text(encoding="utf-8"), spec.model_dir).encode("utf-8")
    if spec.derived_config.read_bytes() != expected_config:
        raise ContractError("DERIVED_CONFIG_CONTENT_DRIFT")
    staged = manifest_value.get("staged", {})
    if (
        local_onnx != staged.get("onnx")
        or local_cache != staged.get("cache_seed")
        or derived != staged.get("derived_config")
        or source_cache != staged.get("official_shared_cache_pre")
        or local_onnx["sha256"] != source_onnx["sha256"]
        or local_cache["sha256"] != source_cache["sha256"]
    ):
        raise ContractError("PREPARED_STAGED_IDENTITY_DRIFT")
    expected_launch = {
        "argv": command_argv(spec),
        "environment": runtime_environment(spec),
        "cwd": str(absolute(spec.attempt)),
        "timeout_seconds": spec.timeout_seconds,
        "authorization_token_required": RUN_AUTHORIZATION_TOKEN,
        "maximum_process_starts": 1,
        "retry": False,
    }
    if manifest_value.get("launch") != expected_launch:
        raise ContractError("PREPARED_LAUNCH_CONTRACT_DRIFT")
    observed_files: set[str] = set()
    for path in spec.attempt.rglob("*"):
        if path.is_symlink():
            raise ContractError(f"PREPARED_SYMLINK_FORBIDDEN:{path}")
        if path.is_file():
            observed_files.add(path.relative_to(spec.attempt).as_posix())
    if require_unstarted and observed_files != _prepared_allowed_files(spec):
        raise ContractError(f"PREPARED_NAMESPACE_FILE_SET_DRIFT:{sorted(observed_files)}")
    if require_unstarted and any(path.exists() or path.is_symlink() for path in (spec.result_dir, spec.start_claim, spec.stdout_log, spec.stderr_log, spec.run_result)):
        raise ContractError("PREPARED_NAMESPACE_ALREADY_STARTED_OR_CONTAMINATED")
    incident = audit_prestart_incident(spec, manifest_value) if spec.governance_records_required else None
    execution_lock = audit_execution_lock(spec) if spec.governance_records_required else None
    return {
        "prepared_manifest": identity(spec.prepared_manifest),
        "frozen_profile_sha256": manifest_value["frozen_profile_sha256"],
        "launch": expected_launch,
        "staged": {"onnx": local_onnx, "cache_seed": local_cache, "derived_config": derived},
        "profile": profile,
        "prestart_incident": incident,
        "execution_lock": execution_lock,
        "observed_files": sorted(observed_files),
    }


def check(spec: Spec = DEFAULT_SPEC, *, probe: Probe = default_probe) -> dict[str, Any]:
    errors: list[str] = []
    audit = None
    try:
        audit = audit_prepared(spec, probe=probe, require_unstarted=True)
    except (ContractError, OSError, UnicodeError, ValueError, json.JSONDecodeError, csv.Error) as error:
        errors.append(str(error))
    return {
        "schema_version": CHECK_SCHEMA,
        "status": "CHECK_READY_FOR_EXPLICIT_ONE_SHOT_RUN" if not errors else "CHECK_BLOCKED",
        "ready": not errors,
        "return_code": RC_OK if not errors else RC_BLOCKED,
        "errors": errors,
        "audit": audit,
        "authorization_token_required": RUN_AUTHORIZATION_TOKEN,
        "claims": {"filesystem_writes": False, "hfnet_process_started": False},
    }


def parse_trajectory(path: Path, camera_timestamps_ns: Sequence[int], *, keyframes: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "exists": False,
        "identity": None,
        "pose_count": 0,
        "strictly_increasing_timestamps": False,
        "finite_valid_pose_rows": False,
        "all_rows_uniquely_associated_to_camera": False,
        "association_max_abs_error_ns": None,
        "associated_first_camera_index": None,
        "associated_last_camera_index": None,
        "reaches_last_input_fraction": None,
        "span_seconds": None,
        "late_keyframe": False,
        "gate_pass": False,
        "errors": [],
    }
    if len(camera_timestamps_ns) != EXPECTED_CAMERA_COUNT or any(right <= left for left, right in zip(camera_timestamps_ns, camera_timestamps_ns[1:])):
        result["errors"] = ["invalid_frozen_camera_timestamp_grid"]
        return result
    try:
        payload = path.read_bytes()
        if path.is_symlink() or not path.is_file():
            raise ContractError("TRAJECTORY_NOT_REGULAR_NONSYMLINK_FILE")
        lines = payload.decode("ascii").splitlines()
        result["exists"] = True
        result["identity"] = {"path": str(absolute(path)), "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload)}
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
        quaternion_norm = math.sqrt(sum(value * value for value in values[3:7]))
        if abs(quaternion_norm - 1.0) > QUATERNION_NORM_TOLERANCE:
            errors.append(f"row_{index}_invalid_quaternion")
            continue
        stamps.append(int(raw_stamp))
    valid = not errors and len(stamps) == len(lines)
    strict = valid and all(right > left for left, right in zip(stamps, stamps[1:]))
    associations: list[int] = []
    association_errors: list[int] = []
    if valid:
        for row_index, stamp in enumerate(stamps):
            insertion = bisect.bisect_left(camera_timestamps_ns, stamp)
            candidates = [candidate for candidate in (insertion - 1, insertion) if 0 <= candidate < len(camera_timestamps_ns)]
            if not candidates:
                errors.append(f"row_{row_index}_no_camera_candidate")
                associations.append(-1)
                continue
            nearest = min(candidates, key=lambda candidate: (abs(camera_timestamps_ns[candidate] - stamp), candidate))
            error = abs(camera_timestamps_ns[nearest] - stamp)
            if error > MAX_CAMERA_ASSOCIATION_ERROR_NS:
                errors.append(f"row_{row_index}_camera_association_error_gt_{MAX_CAMERA_ASSOCIATION_ERROR_NS}ns")
                associations.append(-1)
                continue
            associations.append(nearest)
            association_errors.append(error)
    association_strict = (
        len(associations) == len(stamps)
        and all(index >= 0 for index in associations)
        and len(set(associations)) == len(associations)
        and all(right > left for left, right in zip(associations, associations[1:]))
    )
    if associations and not association_strict:
        errors.append("associated_camera_indices_not_unique_and_strict")
    last_fraction = associations[-1] / (EXPECTED_CAMERA_COUNT - 1) if association_strict else None
    span = (stamps[-1] - stamps[0]) / 1e9 if strict else None
    late = bool(last_fraction is not None and last_fraction >= MIN_LAST_INPUT_FRACTION)
    result.update(
        {
            "pose_count": len(stamps),
            "strictly_increasing_timestamps": strict,
            "finite_valid_pose_rows": valid,
            "all_rows_uniquely_associated_to_camera": association_strict,
            "association_max_abs_error_ns": max(association_errors) if association_errors else None,
            "associated_first_camera_index": associations[0] if association_strict else None,
            "associated_last_camera_index": associations[-1] if association_strict else None,
            "reaches_last_input_fraction": last_fraction,
            "span_seconds": span,
            "late_keyframe": late if keyframes else False,
            "errors": errors,
        }
    )
    if keyframes:
        result["gate_pass"] = bool(valid and strict and association_strict and len(stamps) >= MIN_KEYFRAMES and late)
    else:
        result["gate_pass"] = bool(
            valid
            and strict
            and association_strict
            and len(stamps) >= MIN_TRAJECTORY_ROWS
            and span is not None
            and span >= MIN_TRAJECTORY_SPAN_SECONDS
            and late
        )
    return result


def build_start_claim(prepared: Mapping[str, Any], spec: Spec) -> dict[str, Any]:
    return {
        "schema_version": START_CLAIM_SCHEMA,
        "scientific_role": ROLE,
        "claimed_at_utc": now_utc(),
        "prepared_manifest": prepared["prepared_manifest"],
        "frozen_profile_sha256": prepared["frozen_profile_sha256"],
        "argv": prepared["launch"]["argv"],
        "environment": prepared["launch"]["environment"],
        "cwd": prepared["launch"]["cwd"],
        "timeout_seconds": prepared["launch"]["timeout_seconds"],
        "process_start_count_claimed": 1,
        "retry_permitted": False,
    }


def run(
    spec: Spec = DEFAULT_SPEC,
    *,
    authorization_token: str = "",
    probe: Probe = default_probe,
    execute: Execute = default_execute,
) -> dict[str, Any]:
    if authorization_token != RUN_AUTHORIZATION_TOKEN:
        return {
            "schema_version": RESULT_SCHEMA,
            "status": "RUN_NOT_AUTHORIZED",
            "return_code": RC_BLOCKED,
            "evaluable": False,
            "errors": ["EXACT_ONE_SHOT_AUTHORIZATION_TOKEN_REQUIRED"],
            "execution": {"command_started": False, "process_start_count": 0},
        }
    try:
        prepared_audit = audit_prepared(spec, probe=probe, require_unstarted=True)
        prepared = read_canonical_json(spec.prepared_manifest)
        if not isinstance(prepared, dict):
            raise ContractError("PREPARED_MANIFEST_NOT_OBJECT")
        shared_cache_pre = identity(spec.cache_seed)
        local_cache_pre = identity(spec.model_dir / "HF-Net.cache")
        local_onnx_pre = identity(spec.model_dir / "HF-Net.onnx")
        derived_config_pre = identity(spec.derived_config)
        profile_pre = prepared_audit["profile"]
        claim = build_start_claim(prepared_audit, spec)
        write_exclusive(spec.start_claim, canonical_json(claim).encode("utf-8"))
    except (ContractError, OSError, UnicodeError, ValueError, json.JSONDecodeError, csv.Error) as error:
        return {
            "schema_version": RESULT_SCHEMA,
            "status": "RUN_CONTRACT_BLOCKED",
            "return_code": RC_BLOCKED,
            "evaluable": False,
            "errors": [str(error)],
            "execution": {"command_started": False, "process_start_count": 0},
        }

    started_at = now_utc()
    execution = execute(command_argv(spec), runtime_environment(spec), spec.attempt, spec.timeout_seconds)
    ended_at = now_utc()
    write_exclusive(spec.stdout_log, execution.stdout.encode("utf-8", errors="replace"))
    write_exclusive(spec.stderr_log, execution.stderr.encode("utf-8", errors="replace"))
    post_audit_errors: list[str] = []

    def post_identity(path: Path, label: str) -> Optional[dict[str, object]]:
        try:
            return identity(path)
        except (ContractError, OSError) as error:
            post_audit_errors.append(f"POST_IDENTITY_FAILED:{label}:{error}")
            return None

    try:
        profile_post: Optional[dict[str, Any]] = collect_profile(spec, probe)
    except (ContractError, OSError, UnicodeError, ValueError, json.JSONDecodeError, csv.Error) as error:
        profile_post = None
        post_audit_errors.append(f"POST_PROFILE_AUDIT_FAILED:{error}")
    shared_cache_post = post_identity(spec.cache_seed, "official_shared_cache")
    local_cache_post = post_identity(spec.model_dir / "HF-Net.cache", "run_local_cache")
    local_onnx_post = post_identity(spec.model_dir / "HF-Net.onnx", "run_local_onnx")
    derived_config_post = post_identity(spec.derived_config, "derived_config")
    camera_timestamps = prepared_audit["profile"]["input"]["camera_timestamps_ns"]
    trajectory = parse_trajectory(spec.result_dir / "trajectory.txt", camera_timestamps, keyframes=False)
    keyframes = parse_trajectory(spec.result_dir / "trajectory_keyframe.txt", camera_timestamps, keyframes=True)
    profile_unchanged = profile_post == profile_pre
    official_stack_unchanged = bool(profile_post is not None and profile_post.get("official_stack") == profile_pre.get("official_stack"))
    adoption_unchanged = bool(profile_post is not None and profile_post.get("input_adoption") == profile_pre.get("input_adoption"))
    local_onnx_unchanged = local_onnx_post == local_onnx_pre
    derived_config_unchanged = derived_config_post == derived_config_pre
    shared_unchanged = shared_cache_post == shared_cache_pre
    inferred_images_consumed = EXPECTED_CAMERA_COUNT if execution.returncode == 0 and not execution.timed_out else None
    passed = bool(
        execution.returncode == 0
        and not execution.timed_out
        and inferred_images_consumed == EXPECTED_CAMERA_COUNT
        and trajectory["gate_pass"]
        and keyframes["gate_pass"]
        and not post_audit_errors
        and profile_unchanged
        and official_stack_unchanged
        and adoption_unchanged
        and local_onnx_unchanged
        and derived_config_unchanged
        and shared_unchanged
    )
    errors: list[str] = list(post_audit_errors)
    if not profile_unchanged:
        errors.append("FROZEN_PROFILE_PRE_POST_MISMATCH")
    if not official_stack_unchanged:
        errors.append("OFFICIAL_STACK_PRE_POST_MISMATCH")
    if not adoption_unchanged:
        errors.append("INPUT_ADOPTION_PRE_POST_MISMATCH")
    if not local_onnx_unchanged:
        errors.append("RUN_LOCAL_ONNX_PRE_POST_MISMATCH")
    if not derived_config_unchanged:
        errors.append("DERIVED_CONFIG_PRE_POST_MISMATCH")
    if not shared_unchanged:
        errors.append("OFFICIAL_SHARED_CACHE_WAS_MODIFIED")
    result = {
        "schema_version": RESULT_SCHEMA,
        "scientific_role": ROLE,
        "status": "PASS_PHASE_D_OFFICIAL_MH01_RUNABILITY" if passed else "FAIL_PHASE_D_OFFICIAL_MH01_RUNABILITY",
        "return_code": RC_OK if passed else RC_FAILED,
        "evaluable": passed,
        "errors": errors,
        "argv": command_argv(spec),
        "environment": runtime_environment(spec),
        "cwd": str(absolute(spec.attempt)),
        "execution": {
            "command_started": True,
            "process_start_count": 1,
            "retry_performed": False,
            "raw_returncode": execution.returncode,
            "timed_out": execution.timed_out,
            "timeout_seconds": spec.timeout_seconds,
            "started_at_utc": started_at,
            "ended_at_utc": ended_at,
            "duration_seconds": execution.duration_seconds,
        },
        "identities": {
            "prepared_manifest": identity(spec.prepared_manifest),
            "process_start_claim": identity(spec.start_claim),
            "stdout": identity(spec.stdout_log),
            "stderr": identity(spec.stderr_log),
            "derived_config_pre": derived_config_pre,
            "derived_config_post": derived_config_post,
            "run_local_onnx_pre": local_onnx_pre,
            "run_local_onnx_post": local_onnx_post,
            "run_local_cache_pre": local_cache_pre,
            "run_local_cache_post": local_cache_post,
            "official_shared_cache_pre": shared_cache_pre,
            "official_shared_cache_post": shared_cache_post,
        },
        "gate": {
            "return_code_zero": execution.returncode == 0,
            "timed_out_false": not execution.timed_out,
            "input_images_consumed": inferred_images_consumed,
            "input_images_consumed_basis": "official_entry_normal_return_after_sequential_3682_image_loop",
            "trajectory": trajectory,
            "keyframes": keyframes,
            "frozen_profile_pre_post_exact": profile_unchanged,
            "official_stack_pre_post_exact": official_stack_unchanged,
            "input_adoption_pre_post_exact": adoption_unchanged,
            "run_local_onnx_pre_post_exact": local_onnx_unchanged,
            "derived_config_pre_post_exact": derived_config_unchanged,
            "official_shared_cache_unchanged": shared_unchanged,
        },
        "pre_post_audit": {
            "profile_pre_sha256": profile_digest(profile_pre),
            "profile_post_sha256": profile_digest(profile_post) if profile_post is not None else None,
            "official_stack_pre": profile_pre.get("official_stack", {}).get("identities"),
            "official_stack_post": profile_post.get("official_stack", {}).get("identities") if profile_post is not None else None,
            "input_adoption_pre": profile_pre.get("input_adoption", {}).get("identity"),
            "input_adoption_post": profile_post.get("input_adoption", {}).get("identity") if profile_post is not None else None,
            "post_audit_errors": post_audit_errors,
        },
        "claim_boundary": {
            "official_dataset_runability_only": True,
            "underwater_scientific_result": False,
            "cross_dataset_superiority_claimed": False,
            "formal_scientific_adoption": False,
        },
    }
    write_exclusive(spec.run_result, canonical_json(result).encode("utf-8"))
    return result


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--action", choices=("preflight", "prepare", "check", "run"), default="preflight")
    value.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    value.add_argument("--attempt", type=Path, default=DEFAULT_ATTEMPT)
    value.add_argument("--authorization-token", default="")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    spec = replace(DEFAULT_SPEC, dataset=args.dataset, attempt=args.attempt)
    if args.action == "preflight":
        decision = preflight(spec)
    elif args.action == "prepare":
        decision = prepare(spec)
    elif args.action == "check":
        decision = check(spec)
    else:
        decision = run(spec, authorization_token=args.authorization_token)
    sys.stdout.write(canonical_json(decision))
    return int(decision["return_code"])


if __name__ == "__main__":
    raise SystemExit(main())
