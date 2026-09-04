#!/usr/bin/env python3
"""Bridge frozen official R2D2 archives to paper-era AnyFeature bins.

The adapter is deliberately high level: it validates an exported AQUALOC A02
sequence and official NAVER R2D2 ``.png.r2d2`` archives, then writes only the
three raw feature trees expected by AnyFeature-VSLAM commit 6aa014b.  It never
loads a model, runs inference, edits AnyFeature, or launches SLAM.

Production profiles are outcome-independent: ``a02-prefix200`` consumes camera
indices 0..199; ``a02-full`` must promote the sealed prefix byte-for-byte and
consumes new producer archives only for indices 200..900.  A separate
``smoke-view`` action creates a one-image, non-evaluation sequence view from
the already materialized prefix without re-encoding or re-inference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping, Sequence

import numpy as np
import cv2


ADAPTER_VERSION = "anyfeature-r2d2-bins-v1"
ADAPTER_SCRIPT_RELATIVE = "scripts/materialize_anyfeature_r2d2_bins_v1.py"
EXPORT_ADAPTER_VERSION = "aqualoc-anyfeature-camera-v1"
EXPORT_ADAPTER_SCRIPT_RELATIVE = "scripts/export_aqualoc_to_anyfeature_v1.py"
EXPORT_SEQUENCE_IDENTITY_SCHEMA = "aqualoc-anyfeature-sequence-identity-v1"

ANYFEATURE_ORIGIN = "https://github.com/alejandrofontan/AnyFeature-VSLAM.git"
ANYFEATURE_PAPER_COMMIT = "6aa014b724f7a61bcbff2f8f28f20836986a43dc"
ANYFEATURE_CONTRACT_FILE_SHA256 = {
    "src/mono.cpp": "6b7926aefa29d93285b80b2f35644cf1574aa6f8f76b707f3e0847cad60e0a82",
    "src/Image.cpp": "95d7f6f8493c7383c023967b8c7f8db4531002c0012a26ef58e1c87e5564dccd",
    "src/Feature_r2d2_128.cpp": (
        "21e56aab8997ea8a9ed05a3534ea33ffc57f6ff5ce1f039d57bd76f84708b512"
    ),
    "src/Utils.cpp": "8af8f97cfe31f5862263fba04f5074fc92eea019cee31dc8185cd6f7e59c2e28",
}
R2D2_ORIGIN = "https://github.com/naver/r2d2.git"
R2D2_PRODUCER_COMMIT = "0ff8f6afcbea91f19613d0cb7d93143a977830f5"
R2D2_PRODUCER_GIT_TREE = "47719bdaca38c6d90c124128492249818a442b95"
R2D2_EXTRACT_PY_SHA256 = (
    "1720d85eadbcca605eafd35d430b41be12cdc22cd39b478b4fc5ad2ce977ad80"
)
R2D2_CHECKPOINT_SHA256 = "9ae90e02a9a133d100ca7aeaa32f4d4d7736a6dd222a530a25c8f7da5e508528"
R2D2_CHECKPOINT_SIZE_BYTES = 1_950_677
R2D2_FORMAL_FLAGS = {
    "tag": "r2d2",
    "gpu": -1,
    "top_k": 5000,
    "scale_f": 1.189207115002721,
    "min_size": 256,
    "max_size": 1024,
    "min_scale": 0,
    "max_scale": 1,
    "reliability_thr": 0.7,
    "repeatability_thr": 0.7,
}
PRODUCER_RUN_MANIFEST_NAME = "producer_run_manifest.json"
PRODUCER_RUN_SCHEMA = "anyfeature-r2d2-producer-run-v1"
FORMAL_SMOKE_VIEW_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/anyfeature_adapter/"
    "aqualoc_a02_0005_frame000_smoke_view_r1"
)
FORMAL_SMOKE_EXPERIMENT_FOLDER = Path(
    "/mnt/data/AQUA-FE_WS/published_anyfeature_vslam_v1/"
    "model_smokes/a02_frame000_r1"
)
DEFAULT_PREREGISTRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "papers/anyfeature_vslam_r2d2_a02_preregistration.md"
)

STATUS_VALID = "VALID_FOR_MATERIALIZATION"
STATUS_MATERIALIZED = "MATERIALIZED"
STATUS_OUTPUT_VALID = "MATERIALIZED_OUTPUT_VALID"
STATUS_SMOKE_VIEW = "SMOKE_VIEW_MATERIALIZED"
STATUS_SMOKE_VIEW_VALID = "SMOKE_VIEW_VALID"
STATUS_INTEGRITY_ERROR = "INTEGRITY_ERROR"
RC_READY = 0
RC_INTEGRITY_ERROR = 2

REQUIRED_COLUMNS = {"keypoints": 3, "scores": 1, "descriptors": 128}
REQUIRED_ARCHIVE_FIELDS = ("imsize", "keypoints", "scores", "descriptors")
EXPECTED_IMAGE_SIZE_WH = (968, 608)
EXPECTED_A02_SOURCE_BAG_SHA256 = "8cceb4c76065f3862e60428b14ba10f9a26fc7249e11e9e9d090fed2437238a8"
EXPECTED_A02_SOURCE_CALIBRATION_SHA256 = (
    "e8ce9ad65d82ae563c676689444abd210f81c362586473c5752ee5f9bf2c32e2"
)
MAX_FEATURES_PER_FRAME = 5000
PRODUCER_DTYPE = np.dtype("<f4")
CONSUMER_DTYPE = np.dtype("<f8")
RGB_ROW_RE = re.compile(r"^([0-9]+)\.([0-9]{9}) (rgb/([0-9]+)\.png)$")


class ContractError(RuntimeError):
    """A source, producer archive, view, or output violates the contract."""


@dataclass(frozen=True)
class SequenceProfile:
    name: str
    expected_count: int
    expected_first_ns: int | None
    expected_last_ns: int | None
    prefix_reuse_count: int = 0


PROFILES = {
    "a02-prefix200": SequenceProfile(
        "a02-prefix200",
        200,
        1_542_829_016_700_435_392,
        1_542_829_026_649_564_544,
    ),
    "a02-full": SequenceProfile(
        "a02-full", 901, 1_542_829_016_700_435_392, None, 200
    ),
}
SMOKE_PROFILE = "a02-prefix200-index0-smoke-view"


@dataclass(frozen=True)
class FrameSpec:
    row_index: int
    timestamp_ns: int
    timestamp_text: str
    image_relative: str
    image_path: Path
    image_sha256: str
    image_size_bytes: int
    producer_path: Path
    output_filename: str
    reused_from_prefix: bool = False


@dataclass(frozen=True)
class SequenceAudit:
    root: Path
    profile: SequenceProfile
    frames: tuple[FrameSpec, ...]
    conversion_manifest_path: Path
    conversion_manifest_sha256: str
    conversion_manifest: Mapping[str, Any]
    sequence_identity_sha256: str
    rgb_txt_sha256: str
    calibration_sha256: str
    producer_run_manifest_path: Path
    producer_run_manifest_sha256: str
    producer_run_manifest: Mapping[str, Any]


@dataclass(frozen=True)
class FrameFeatures:
    keypoints: np.ndarray
    scores: np.ndarray
    descriptors: np.ndarray
    source_shapes: Mapping[str, tuple[int, ...]]
    source_dtypes: Mapping[str, str]

    @property
    def count(self) -> int:
        return int(self.keypoints.shape[0])


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"


def runtime_byteorder() -> str:
    return sys.byteorder


def require_little_endian(byteorder: str | None = None) -> None:
    observed = runtime_byteorder() if byteorder is None else byteorder
    if observed != "little":
        raise ContractError(f"HOST_BYTEORDER_NOT_LITTLE:{observed}")


def _script_identity(path: Path, relative: str) -> dict[str, str]:
    if not path.is_file() or path.is_symlink():
        raise ContractError(f"ADAPTER_SCRIPT_MISSING_OR_SYMLINK:{relative}")
    return {
        "script": relative,
        "resolved_script": str(path.resolve()),
        "sha256": sha256_file(path),
    }


def adapter_identity() -> dict[str, str]:
    return _script_identity(Path(__file__).resolve(), ADAPTER_SCRIPT_RELATIVE)


def exporter_identity() -> dict[str, str]:
    path = Path(__file__).resolve().with_name("export_aqualoc_to_anyfeature_v1.py")
    return _script_identity(path, EXPORT_ADAPTER_SCRIPT_RELATIVE)


def _regular_file(path: Path, label: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise ContractError(f"{label}_MISSING_OR_SYMLINK:{path}")


def _regular_directory(path: Path, label: str) -> None:
    if not path.is_dir() or path.is_symlink():
        raise ContractError(f"{label}_MISSING_OR_SYMLINK:{path}")


def _json_object(path: Path, label: str) -> dict[str, Any]:
    _regular_file(path, label)
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label}_INVALID_JSON") from exc
    if not isinstance(result, dict):
        raise ContractError(f"{label}_ROOT_NOT_OBJECT")
    return result


def _aggregate_rows(rows: Sequence[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for relative, file_hash in rows:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _sequence_identity_record(
    manifest: Mapping[str, Any], image_rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    source = manifest.get("source")
    camera = manifest.get("camera")
    calibration = manifest.get("calibration")
    identity = manifest.get("adapter_identity")
    if not all(isinstance(value, Mapping) for value in (source, camera, calibration, identity)):
        raise ContractError("CONVERSION_MANIFEST_IDENTITY_INPUT_MISSING")
    source_calibration = source.get("calibration")  # type: ignore[union-attr]
    rgb_txt = camera.get("rgb_txt")  # type: ignore[union-attr]
    if not isinstance(source_calibration, Mapping) or not isinstance(rgb_txt, Mapping):
        raise ContractError("CONVERSION_MANIFEST_IDENTITY_INPUT_MISSING")
    return {
        "schema": EXPORT_SEQUENCE_IDENTITY_SCHEMA,
        "adapter_version": EXPORT_ADAPTER_VERSION,
        "adapter_sha256": str(identity.get("sha256")),  # type: ignore[union-attr]
        "profile": str(manifest.get("profile")),
        "source_bag_sha256": str(source.get("sha256")),  # type: ignore[union-attr]
        "source_calibration_sha256": str(source_calibration.get("sha256")),
        "rgb_txt_sha256": str(rgb_txt.get("sha256")),
        "output_calibration_sha256": str(calibration.get("output_sha256")),  # type: ignore[union-attr]
        "images": [
            {
                "source_index": int(row["source_index"]),
                "raw_header_ns": int(row["raw_header_ns"]),
                "relative_path": str(row["relative_path"]),
                "source_pixel_sha256": str(row["source_pixel_sha256"]),
                "png_sha256": str(row["png_sha256"]),
                "png_size_bytes": int(row["png_size_bytes"]),
            }
            for row in image_rows
        ],
    }


def _sequence_identity_sha256(
    manifest: Mapping[str, Any], image_rows: Sequence[Mapping[str, Any]]
) -> str:
    return sha256_bytes(canonical_json(_sequence_identity_record(manifest, image_rows)).encode("utf-8"))


def _safe_rgb_path(text: str, row_index: int) -> PurePosixPath:
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts:
        raise ContractError(f"RGB_TXT_UNSAFE_PATH:{row_index}")
    if len(path.parts) != 2 or path.parts[0] != "rgb" or path.suffix != ".png":
        raise ContractError(f"RGB_TXT_PATH_NOT_CANONICAL_PNG:{row_index}")
    return path


def _sha256_text_lines(lines: Sequence[str]) -> str:
    return sha256_bytes(("\n".join(lines) + "\n").encode("utf-8"))


def _manifest_file_binding(
    row: Mapping[str, Any],
    label: str,
    expected_sha256: str | None = None,
    require_exists: bool = True,
) -> Path:
    path_text = row.get("path")
    digest = row.get("sha256")
    size = row.get("size_bytes")
    if (
        not isinstance(path_text, str)
        or not Path(path_text).is_absolute()
        or not isinstance(digest, str)
        or len(digest) != 64
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size < 0
    ):
        raise ContractError(f"PRODUCER_RUN_{label}_BINDING_INVALID")
    path = Path(path_text)
    if str(path.resolve()) != path_text:
        raise ContractError(f"PRODUCER_RUN_{label}_PATH_NOT_CANONICAL")
    if expected_sha256 is not None and digest != expected_sha256:
        raise ContractError(f"PRODUCER_RUN_{label}_SHA256_MISMATCH")
    if require_exists or path.exists() or path.is_symlink():
        _regular_file(path, f"PRODUCER_RUN_{label}")
        if path.stat().st_size != size or sha256_file(path) != digest:
            raise ContractError(f"PRODUCER_RUN_{label}_SHA256_MISMATCH")
    return path


def audit_producer_run(
    producer_root: Path,
    frames: Sequence[FrameSpec],
    indices: Sequence[int],
    formal_profile: bool,
) -> tuple[Path, str, Mapping[str, Any]]:
    """Validate the frozen, externally produced R2D2 run evidence bundle.

    This tool does not implement inference.  A separate runner must seal this
    manifest before validation/materialization, including environment, command,
    logs, timing, image list, and every archive hash.
    """
    manifest_path = producer_root / PRODUCER_RUN_MANIFEST_NAME
    manifest = _json_object(manifest_path, "PRODUCER_RUN_MANIFEST")
    if manifest.get("schema") != PRODUCER_RUN_SCHEMA or manifest.get("status") != "COMPLETED":
        raise ContractError("PRODUCER_RUN_MANIFEST_IDENTITY_MISMATCH")
    producer = manifest.get("producer")
    if not isinstance(producer, Mapping):
        raise ContractError("PRODUCER_RUN_PRODUCER_BLOCK_MISSING")
    expected_producer = {
        "origin": R2D2_ORIGIN,
        "commit": R2D2_PRODUCER_COMMIT,
        "git_tree": R2D2_PRODUCER_GIT_TREE,
        "worktree_clean": True,
        "extract_py_sha256": R2D2_EXTRACT_PY_SHA256,
    }
    for key, value in expected_producer.items():
        if producer.get(key) != value:
            raise ContractError(f"PRODUCER_RUN_{key.upper()}_MISMATCH")
    extract_binding = producer.get("extract_py")
    if not isinstance(extract_binding, Mapping):
        raise ContractError("PRODUCER_RUN_EXTRACT_PY_BINDING_MISSING")
    extract_path = _manifest_file_binding(
        extract_binding,
        "EXTRACT_PY",
        R2D2_EXTRACT_PY_SHA256,
        require_exists=formal_profile,
    )

    checkpoint = manifest.get("checkpoint")
    runtime = manifest.get("runtime")
    invocation = manifest.get("invocation")
    process = manifest.get("process")
    if not all(isinstance(value, Mapping) for value in (checkpoint, runtime, invocation, process)):
        raise ContractError("PRODUCER_RUN_REQUIRED_BLOCK_MISSING")
    checkpoint_path = _manifest_file_binding(checkpoint, "CHECKPOINT")  # type: ignore[arg-type]
    if formal_profile:
        if checkpoint.get("sha256") != R2D2_CHECKPOINT_SHA256:  # type: ignore[union-attr]
            raise ContractError("PRODUCER_RUN_CHECKPOINT_NOT_FROZEN_MODEL")
        if checkpoint_path.stat().st_size != R2D2_CHECKPOINT_SIZE_BYTES:
            raise ContractError("PRODUCER_RUN_CHECKPOINT_SIZE_MISMATCH")
    if not isinstance(runtime.get("cpu"), str) or not runtime.get("cpu"):  # type: ignore[union-attr]
        raise ContractError("PRODUCER_RUN_CPU_IDENTITY_MISSING")
    if not isinstance(runtime.get("python_version"), str) or not runtime.get("python_version"):  # type: ignore[union-attr]
        raise ContractError("PRODUCER_RUN_PYTHON_IDENTITY_MISSING")
    python_executable = runtime.get("python_executable")  # type: ignore[union-attr]
    if not isinstance(python_executable, Mapping):
        raise ContractError("PRODUCER_RUN_PYTHON_EXECUTABLE_MISSING")
    python_executable_path = _manifest_file_binding(
        python_executable, "PYTHON_EXECUTABLE"
    )
    environment = runtime.get("environment_lock")  # type: ignore[union-attr]
    if not isinstance(environment, Mapping):
        raise ContractError("PRODUCER_RUN_ENVIRONMENT_LOCK_MISSING")
    _manifest_file_binding(environment, "ENVIRONMENT_LOCK")

    argv = invocation.get("argv")  # type: ignore[union-attr]
    flags = invocation.get("flags")  # type: ignore[union-attr]
    working_directory = invocation.get("working_directory")  # type: ignore[union-attr]
    expected_working_directory = str(frames[0].image_path.parent.parent.resolve())
    if (
        not isinstance(working_directory, str)
        or working_directory != expected_working_directory
        or str(Path(working_directory).resolve()) != working_directory
        or any(
            frame.image_path.parent.parent.resolve()
            != Path(working_directory).resolve()
            for frame in frames
        )
    ):
        raise ContractError("PRODUCER_RUN_WORKING_DIRECTORY_MISMATCH")
    if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) for arg in argv):
        raise ContractError("PRODUCER_RUN_ARGV_INVALID")
    if invocation.get("argv_sha256") != _sha256_text_lines(argv):  # type: ignore[union-attr]
        raise ContractError("PRODUCER_RUN_ARGV_SHA256_MISMATCH")
    if not isinstance(flags, Mapping) or not flags:
        raise ContractError("PRODUCER_RUN_FLAGS_MISSING")
    expected_flags_hash = sha256_bytes(
        canonical_json(dict(flags)).encode("utf-8")
    )
    if invocation.get("flags_sha256") != expected_flags_hash:  # type: ignore[union-attr]
        raise ContractError("PRODUCER_RUN_FLAGS_SHA256_MISMATCH")
    if invocation.get("tag") != "r2d2" or flags.get("tag") != "r2d2":  # type: ignore[union-attr]
        raise ContractError("PRODUCER_RUN_TAG_NOT_R2D2")
    if formal_profile:
        if set(flags) != set(R2D2_FORMAL_FLAGS) | {"model", "images"}:
            raise ContractError("PRODUCER_RUN_FORMAL_FLAG_SET_MISMATCH")
        for key, value in R2D2_FORMAL_FLAGS.items():
            if flags.get(key) != value:
                raise ContractError(f"PRODUCER_RUN_FORMAL_FLAG_{key.upper()}_MISMATCH")
        if flags.get("model") != str(checkpoint_path):
            raise ContractError("PRODUCER_RUN_MODEL_FLAG_PATH_MISMATCH")
    image_list = invocation.get("image_list")  # type: ignore[union-attr]
    if not isinstance(image_list, Mapping):
        raise ContractError("PRODUCER_RUN_IMAGE_LIST_MISSING")
    image_list_path = _manifest_file_binding(image_list, "IMAGE_LIST")
    if formal_profile and flags.get("images") != str(image_list_path):
        raise ContractError("PRODUCER_RUN_IMAGES_FLAG_PATH_MISMATCH")
    expected_entries = [frames[index].image_relative for index in indices]
    if image_list.get("entries") != expected_entries or image_list.get("count") != len(expected_entries):
        raise ContractError("PRODUCER_RUN_IMAGE_LIST_ENTRIES_MISMATCH")
    expected_list_hash = _sha256_text_lines(expected_entries)
    if image_list.get("sha256") != expected_list_hash or sha256_file(image_list_path) != expected_list_hash:
        raise ContractError("PRODUCER_RUN_IMAGE_LIST_SHA256_MISMATCH")
    if formal_profile:
        expected_argv = canonical_formal_r2d2_argv(
            python_executable_path,
            extract_path,
            checkpoint_path,
            image_list_path,
        )
        if argv != expected_argv:
            raise ContractError("PRODUCER_RUN_FORMAL_ARGV_SEMANTICS_MISMATCH")

    if process.get("return_code") != 0:  # type: ignore[union-attr]
        raise ContractError("PRODUCER_RUN_RETURN_CODE_NOT_ZERO")
    stdout = process.get("stdout")  # type: ignore[union-attr]
    stderr = process.get("stderr")  # type: ignore[union-attr]
    timing = process.get("timing")  # type: ignore[union-attr]
    if not isinstance(stdout, Mapping) or not isinstance(stderr, Mapping) or not isinstance(timing, Mapping):
        raise ContractError("PRODUCER_RUN_PROCESS_EVIDENCE_MISSING")
    _manifest_file_binding(stdout, "STDOUT")
    _manifest_file_binding(stderr, "STDERR")
    if not isinstance(timing.get("start_utc"), str) or not isinstance(timing.get("end_utc"), str):
        raise ContractError("PRODUCER_RUN_TIMING_ENDPOINT_MISSING")
    elapsed = timing.get("elapsed_seconds")
    if not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool) or elapsed < 0 or not np.isfinite(elapsed):
        raise ContractError("PRODUCER_RUN_TIMING_INVALID")

    archive_rows = manifest.get("archives")
    if not isinstance(archive_rows, list) or len(archive_rows) != len(expected_entries):
        raise ContractError("PRODUCER_RUN_ARCHIVE_ROWS_MISMATCH")
    for output_index, (source_index, row) in enumerate(zip(indices, archive_rows)):
        if not isinstance(row, Mapping):
            raise ContractError(f"PRODUCER_RUN_ARCHIVE_ROW_NOT_OBJECT:{output_index}")
        frame = frames[source_index]
        expected_relative = f"rgb/{frame.timestamp_ns}.png.r2d2"
        archive_path = producer_root / expected_relative
        _regular_file(archive_path, f"PRODUCER_RUN_ARCHIVE:{source_index}")
        expected = {
            "source_index": source_index,
            "image_relative": frame.image_relative,
            "archive_relative": expected_relative,
            "sha256": sha256_file(archive_path),
            "size_bytes": archive_path.stat().st_size,
        }
        for key, value in expected.items():
            if row.get(key) != value:
                raise ContractError(f"PRODUCER_RUN_ARCHIVE_{key.upper()}_MISMATCH:{source_index}")
    return manifest_path, sha256_file(manifest_path), manifest


def canonical_formal_r2d2_argv(
    python_executable: Path,
    extract_py: Path,
    checkpoint: Path,
    image_list: Path,
) -> list[str]:
    """Exact preregistered official extractor command, including defaults."""
    return [
        str(python_executable),
        str(extract_py),
        "--model",
        str(checkpoint),
        "--images",
        str(image_list),
        "--tag",
        "r2d2",
        "--top-k",
        "5000",
        "--scale-f",
        "1.189207115002721",
        "--min-size",
        "256",
        "--max-size",
        "1024",
        "--min-scale",
        "0",
        "--max-scale",
        "1",
        "--reliability-thr",
        "0.7",
        "--repeatability-thr",
        "0.7",
        "--gpu",
        "-1",
    ]


def _parse_rgb_txt(sequence_root: Path) -> tuple[tuple[int, str, str], ...]:
    rgb_txt = sequence_root / "rgb.txt"
    _regular_file(rgb_txt, "RGB_TXT")
    payload = rgb_txt.read_bytes()
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ContractError("RGB_TXT_NOT_ASCII") from exc
    if not text.endswith("\n"):
        raise ContractError("RGB_TXT_FINAL_NEWLINE_MISSING")
    lines = text[:-1].split("\n")
    if not lines or any(not line for line in lines):
        raise ContractError("RGB_TXT_HEADER_COMMENT_OR_BLANK")
    rows: list[tuple[int, str, str]] = []
    previous: int | None = None
    for index, line in enumerate(lines):
        match = RGB_ROW_RE.fullmatch(line)
        if match is None:
            raise ContractError(f"RGB_TXT_ROW_NOT_CANONICAL:{index}")
        seconds, nanos, relative_text, basename_ns = match.groups()
        stamp_ns = int(seconds) * 1_000_000_000 + int(nanos)
        canonical = f"{stamp_ns // 1_000_000_000}.{stamp_ns % 1_000_000_000:09d} rgb/{stamp_ns}.png"
        if line != canonical:
            raise ContractError(f"RGB_TXT_ROW_NOT_CANONICAL:{index}")
        _safe_rgb_path(relative_text, index)
        if int(basename_ns) != stamp_ns:
            raise ContractError(f"RGB_FILENAME_TIMESTAMP_MISMATCH:{index}")
        if previous is not None and stamp_ns <= previous:
            raise ContractError(f"RGB_TXT_TIMESTAMPS_NOT_STRICT:{index}")
        previous = stamp_ns
        rows.append((stamp_ns, line.split(" ", 1)[0], relative_text))
    return tuple(rows)


def audit_sequence(
    sequence_root: Path,
    profile: SequenceProfile,
    producer_root: Path | None = None,
    producer_indices: range | None = None,
) -> SequenceAudit:
    require_little_endian()
    _regular_directory(sequence_root, "SEQUENCE_ROOT")
    rgb_directory = sequence_root / "rgb"
    _regular_directory(rgb_directory, "RGB_DIRECTORY")
    rows = _parse_rgb_txt(sequence_root)
    if len(rows) != profile.expected_count:
        raise ContractError("PROFILE_RGB_ROW_COUNT_MISMATCH")
    if profile.expected_first_ns is not None and rows[0][0] != profile.expected_first_ns:
        raise ContractError("PROFILE_FIRST_TIMESTAMP_MISMATCH")
    if profile.expected_last_ns is not None and rows[-1][0] != profile.expected_last_ns:
        raise ContractError("PROFILE_LAST_TIMESTAMP_MISMATCH")

    conversion_path = sequence_root / "conversion_manifest.json"
    manifest = _json_object(conversion_path, "CONVERSION_MANIFEST")
    expected_exporter = exporter_identity()
    if manifest.get("adapter_version") != EXPORT_ADAPTER_VERSION or manifest.get("status") != "EXPORTED":
        raise ContractError("CONVERSION_MANIFEST_IDENTITY_MISMATCH")
    if manifest.get("adapter_identity") != expected_exporter:
        raise ContractError("CONVERSION_MANIFEST_ADAPTER_SHA256_MISMATCH")
    if manifest.get("profile") != profile.name:
        raise ContractError("CONVERSION_MANIFEST_PROFILE_MISMATCH")

    camera = manifest.get("camera")
    calibration = manifest.get("calibration")
    source = manifest.get("source")
    if not isinstance(camera, Mapping) or not isinstance(calibration, Mapping):
        raise ContractError("CONVERSION_MANIFEST_CAMERA_OR_CALIBRATION_MISSING")
    if not isinstance(source, Mapping) or not isinstance(source.get("calibration"), Mapping):
        raise ContractError("CONVERSION_MANIFEST_SOURCE_BINDING_MISSING")
    if profile.name in PROFILES:
        if source.get("sha256") != EXPECTED_A02_SOURCE_BAG_SHA256:
            raise ContractError("CONVERSION_MANIFEST_SOURCE_BAG_SHA256_MISMATCH")
        if source["calibration"].get("sha256") != EXPECTED_A02_SOURCE_CALIBRATION_SHA256:
            raise ContractError("CONVERSION_MANIFEST_SOURCE_CALIBRATION_SHA256_MISMATCH")
    if camera.get("count") != profile.expected_count:
        raise ContractError("CONVERSION_MANIFEST_CAMERA_COUNT_MISMATCH")
    if camera.get("source_indices_inclusive") != [0, profile.expected_count - 1]:
        raise ContractError("CONVERSION_MANIFEST_CAMERA_INDICES_MISMATCH")
    if camera.get("selected_header_ns_inclusive") != [rows[0][0], rows[-1][0]]:
        raise ContractError("CONVERSION_MANIFEST_FIRST_LAST_TIMESTAMP_MISMATCH")
    expected_camera_schema = {
        "topic": "/camera/image_raw",
        "message_type": "sensor_msgs/Image",
        "width": EXPECTED_IMAGE_SIZE_WH[0],
        "height": EXPECTED_IMAGE_SIZE_WH[1],
        "encoding": "mono8",
        "nominal_fps": 20.0,
    }
    if camera.get("schema") != expected_camera_schema:
        raise ContractError("CONVERSION_MANIFEST_CAMERA_SCHEMA_MISMATCH")

    rgb_txt_hash = sha256_file(sequence_root / "rgb.txt")
    rgb_meta = camera.get("rgb_txt")
    if not isinstance(rgb_meta, Mapping) or rgb_meta.get("sha256") != rgb_txt_hash:
        raise ContractError("CONVERSION_MANIFEST_RGB_TXT_SHA256_MISMATCH")
    if rgb_meta.get("row_count") != profile.expected_count:
        raise ContractError("CONVERSION_MANIFEST_RGB_TXT_COUNT_MISMATCH")

    calibration_path = sequence_root / "calibration.yaml"
    _regular_file(calibration_path, "CALIBRATION")
    calibration_hash = sha256_file(calibration_path)
    if calibration.get("output_sha256") != calibration_hash:
        raise ContractError("CONVERSION_MANIFEST_CALIBRATION_SHA256_MISMATCH")

    image_rows = camera.get("images")
    if not isinstance(image_rows, list) or len(image_rows) != profile.expected_count:
        raise ContractError("CONVERSION_MANIFEST_IMAGE_ROWS_MISMATCH")
    expected_png_names: set[str] = set()
    frame_specs: list[FrameSpec] = []
    tree_rows: list[tuple[str, str]] = [("rgb.txt", rgb_txt_hash), ("calibration.yaml", calibration_hash)]
    for index, ((stamp_ns, timestamp_text, relative), image_row) in enumerate(zip(rows, image_rows)):
        if not isinstance(image_row, Mapping):
            raise ContractError(f"CONVERSION_MANIFEST_IMAGE_ROW_NOT_OBJECT:{index}")
        image_path = sequence_root / relative
        _regular_file(image_path, f"RGB_IMAGE:{index}")
        image_hash = sha256_file(image_path)
        image_size = image_path.stat().st_size
        expected_png_names.add(Path(relative).name)
        expected_values = {
            "source_index": index,
            "raw_header_ns": stamp_ns,
            "record_ns": stamp_ns,
            "relative_path": relative,
            "png_sha256": image_hash,
            "png_size_bytes": image_size,
            "pixel_identity_verified": True,
            "reused_from_prefix": index < profile.prefix_reuse_count,
        }
        if set(image_row) != {
            "source_index",
            "raw_header_ns",
            "record_ns",
            "relative_path",
            "source_pixel_sha256",
            "png_sha256",
            "png_size_bytes",
            "pixel_identity_verified",
            "reused_from_prefix",
        }:
            raise ContractError(f"CONVERSION_MANIFEST_IMAGE_FIELD_SET_MISMATCH:{index}")
        for key, value in expected_values.items():
            if image_row.get(key) != value:
                raise ContractError(f"CONVERSION_MANIFEST_IMAGE_{key.upper()}_MISMATCH:{index}")
        decoded = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
        if (
            decoded is None
            or decoded.dtype != np.uint8
            or decoded.shape != (EXPECTED_IMAGE_SIZE_WH[1], EXPECTED_IMAGE_SIZE_WH[0])
        ):
            raise ContractError(f"RGB_PNG_DECODED_SCHEMA_MISMATCH:{index}")
        pixel_hash = sha256_bytes(decoded.tobytes(order="C"))
        if image_row.get("source_pixel_sha256") != pixel_hash:
            raise ContractError(f"CONVERSION_MANIFEST_SOURCE_PIXEL_SHA256_MISMATCH:{index}")
        tree_rows.append((relative, image_hash))
        frame_specs.append(
            FrameSpec(
                index,
                stamp_ns,
                timestamp_text,
                relative,
                image_path,
                image_hash,
                image_size,
                Path(),
                f"{stamp_ns}.bin",
            )
        )

    entries = list(rgb_directory.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise ContractError("RGB_DIRECTORY_HAS_SYMLINK_OR_NONFILE_ENTRY")
    actual_png_names = {path.name for path in entries if path.name.endswith(".png")}
    if actual_png_names != expected_png_names:
        raise ContractError("RGB_PNG_FILE_SET_MISMATCH")
    if any(not (path.name.endswith(".png") or path.name.endswith(".png.r2d2")) for path in entries):
        raise ContractError("RGB_DIRECTORY_HAS_EXTRA_FILE")

    if manifest.get("payload_tree_sha256_excluding_manifest") != _aggregate_rows(sorted(tree_rows)):
        raise ContractError("CONVERSION_MANIFEST_PAYLOAD_TREE_SHA256_MISMATCH")
    sequence_identity = manifest.get("sequence_identity")
    expected_identity_record = _sequence_identity_record(manifest, image_rows)
    expected_identity = sha256_bytes(
        canonical_json(expected_identity_record).encode("utf-8")
    )
    if not isinstance(sequence_identity, Mapping) or sequence_identity.get("schema") != EXPORT_SEQUENCE_IDENTITY_SCHEMA:
        raise ContractError("CONVERSION_MANIFEST_SEQUENCE_IDENTITY_SCHEMA_MISMATCH")
    if sequence_identity.get("record") != expected_identity_record:
        raise ContractError("CONVERSION_MANIFEST_SEQUENCE_IDENTITY_RECORD_MISMATCH")
    if sequence_identity.get("sha256") != expected_identity:
        raise ContractError("CONVERSION_MANIFEST_SEQUENCE_IDENTITY_SHA256_MISMATCH")

    root_for_archives = producer_root if producer_root is not None else sequence_root
    indices = producer_indices if producer_indices is not None else range(profile.expected_count)
    expected_archive_names = {f"{rows[index][0]}.png.r2d2" for index in indices}
    producer_rgb = root_for_archives / "rgb"
    _regular_directory(producer_rgb, "PRODUCER_RGB_DIRECTORY")
    producer_entries = list(producer_rgb.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in producer_entries):
        raise ContractError("PRODUCER_RGB_HAS_SYMLINK_OR_NONFILE_ENTRY")
    actual_archive_names = {path.name for path in producer_entries if path.name.endswith(".r2d2")}
    if actual_archive_names != expected_archive_names:
        raise ContractError("R2D2_PRODUCER_ARCHIVE_FILE_SET_MISMATCH")
    if root_for_archives != sequence_root and any(not path.name.endswith(".r2d2") for path in producer_entries):
        raise ContractError("PRODUCER_RGB_HAS_EXTRA_FILE")

    frames: list[FrameSpec] = []
    for base in frame_specs:
        archive = producer_rgb / f"{base.timestamp_ns}.png.r2d2"
        if base.row_index in indices:
            _regular_file(archive, f"R2D2_PRODUCER_ARCHIVE:{base.row_index}")
        frames.append(
            FrameSpec(
                **{
                    **base.__dict__,
                    "producer_path": archive,
                    "reused_from_prefix": False,
                }
            )
        )
    producer_manifest_path, producer_manifest_hash, producer_manifest = audit_producer_run(
        root_for_archives, frames, tuple(indices), profile.name in PROFILES
    )
    return SequenceAudit(
        sequence_root,
        profile,
        tuple(frames),
        conversion_path,
        sha256_file(conversion_path),
        manifest,
        expected_identity,
        rgb_txt_hash,
        calibration_hash,
        producer_manifest_path,
        producer_manifest_hash,
        producer_manifest,
    )


def _validate_full_prefix_binding(full: SequenceAudit, prefix: SequenceAudit) -> None:
    count = full.profile.prefix_reuse_count
    if count <= 0 or prefix.profile.expected_count != count:
        raise ContractError("FULL_PREFIX_PROFILE_COUNT_MISMATCH")
    prefix_reuse = full.conversion_manifest.get("prefix_reuse")
    if not isinstance(prefix_reuse, Mapping) or prefix_reuse.get("required") is not True:
        raise ContractError("FULL_CONVERSION_PREFIX_REUSE_MISSING")
    expected = {
        "count": count,
        "source_indices_inclusive": [0, count - 1],
        "prefix_conversion_manifest_sha256": prefix.conversion_manifest_sha256,
        "prefix_sequence_identity_sha256": prefix.sequence_identity_sha256,
        "png_byte_identity": True,
        "calibration_byte_identity": True,
    }
    for key, value in expected.items():
        if prefix_reuse.get(key) != value:
            raise ContractError(f"FULL_CONVERSION_PREFIX_{key.upper()}_MISMATCH")
    if full.calibration_sha256 != prefix.calibration_sha256:
        raise ContractError("FULL_PREFIX_CALIBRATION_BYTE_MISMATCH")
    for index in range(count):
        left = full.frames[index]
        right = prefix.frames[index]
        if (left.timestamp_ns, left.image_sha256, left.image_size_bytes) != (
            right.timestamp_ns,
            right.image_sha256,
            right.image_size_bytes,
        ):
            raise ContractError(f"FULL_PREFIX_PNG_BYTE_IDENTITY_MISMATCH:{index}")


def _audits_for_profile(
    sequence_root: Path,
    producer_root: Path,
    profile: SequenceProfile,
    prefix_sequence_root: Path | None,
) -> tuple[SequenceAudit, SequenceAudit | None]:
    if profile.prefix_reuse_count:
        if prefix_sequence_root is None:
            raise ContractError("PREFIX_SEQUENCE_ROOT_REQUIRED_FOR_FULL")
        prefix_profile = PROFILES["a02-prefix200"] if profile.name == "a02-full" else SequenceProfile(
            f"{profile.name}-prefix", profile.prefix_reuse_count, profile.expected_first_ns, None
        )
        prefix = audit_sequence(prefix_sequence_root, prefix_profile, prefix_sequence_root)
        full = audit_sequence(
            sequence_root,
            profile,
            producer_root,
            range(profile.prefix_reuse_count, profile.expected_count),
        )
        _validate_full_prefix_binding(full, prefix)
        return full, prefix
    if prefix_sequence_root is not None:
        raise ContractError("PREFIX_SEQUENCE_ROOT_NOT_ALLOWED_FOR_PREFIX_PROFILE")
    return audit_sequence(sequence_root, profile, producer_root), None


def read_frame_specs(
    sequence_root: Path,
    producer_root: Path,
    profile: SequenceProfile | None = None,
) -> tuple[FrameSpec, ...]:
    """Compatibility entry point; production callers must pass a profile."""
    if profile is None:
        raise ContractError("EXPLICIT_PROFILE_REQUIRED")
    return audit_sequence(sequence_root, profile, producer_root).frames


def load_frame_features(
    archive_path: Path, image_relative: str = "unknown"
) -> FrameFeatures:
    require_little_endian()
    _regular_file(archive_path, "R2D2_PRODUCER_ARCHIVE")
    try:
        with np.load(archive_path, allow_pickle=False) as archive:
            if set(archive.files) != set(REQUIRED_ARCHIVE_FIELDS):
                raise ContractError(f"ARCHIVE_FIELD_SET_MISMATCH:{image_relative}")
            imsize = archive["imsize"]
            keypoints = archive["keypoints"]
            scores = archive["scores"]
            descriptors = archive["descriptors"]
    except ContractError:
        raise
    except Exception as exc:
        raise ContractError(f"ARCHIVE_LOAD_FAILED:{image_relative}") from exc
    if imsize.shape != (2,) or imsize.dtype.kind not in "iu":
        raise ContractError(f"IMSIZE_DTYPE_OR_SHAPE_NOT_INTEGER_PAIR:{image_relative}")
    if tuple(int(value) for value in imsize) != EXPECTED_IMAGE_SIZE_WH:
        raise ContractError(f"IMSIZE_NOT_A02_968X608:{image_relative}")
    arrays = {"keypoints": keypoints, "scores": scores, "descriptors": descriptors}
    for name, array in arrays.items():
        if array.dtype.str != PRODUCER_DTYPE.str:
            raise ContractError(f"{name.upper()}_DTYPE_NOT_LE_FLOAT32:{image_relative}")
        if not np.isfinite(array).all():
            raise ContractError(f"{name.upper()}_NONFINITE:{image_relative}")
    if keypoints.ndim != 2 or keypoints.shape[1] != 3:
        raise ContractError(f"KEYPOINTS_SHAPE_NOT_NX3:{image_relative}")
    if scores.ndim != 1:
        raise ContractError(f"SCORES_SHAPE_NOT_N:{image_relative}")
    if descriptors.ndim != 2 or descriptors.shape[1] != 128:
        raise ContractError(f"DESCRIPTORS_SHAPE_NOT_NX128:{image_relative}")
    count = int(keypoints.shape[0])
    if int(scores.shape[0]) != count or int(descriptors.shape[0]) != count:
        raise ContractError(f"ARRAY_COUNT_MISMATCH:{image_relative}")
    if count > MAX_FEATURES_PER_FRAME:
        raise ContractError(f"FEATURE_COUNT_EXCEEDS_5000:{image_relative}")
    if count:
        if np.any(keypoints[:, 0] < 0) or np.any(keypoints[:, 0] >= EXPECTED_IMAGE_SIZE_WH[0]):
            raise ContractError(f"KEYPOINT_X_OUT_OF_BOUNDS:{image_relative}")
        if np.any(keypoints[:, 1] < 0) or np.any(keypoints[:, 1] >= EXPECTED_IMAGE_SIZE_WH[1]):
            raise ContractError(f"KEYPOINT_Y_OUT_OF_BOUNDS:{image_relative}")
        if np.any(keypoints[:, 2] <= 0):
            raise ContractError(f"KEYPOINT_SCALE_NOT_POSITIVE:{image_relative}")
    return FrameFeatures(
        np.ascontiguousarray(keypoints, dtype=PRODUCER_DTYPE),
        np.ascontiguousarray(scores.reshape(count, 1), dtype=PRODUCER_DTYPE),
        np.ascontiguousarray(descriptors, dtype=PRODUCER_DTYPE),
        {name: tuple(array.shape) for name, array in arrays.items()},
        {name: array.dtype.str for name, array in arrays.items()},
    )


def _array_sha256(array: np.ndarray) -> str:
    return sha256_bytes(np.ascontiguousarray(array).tobytes(order="C"))


def frame_validation_row(frame: FrameSpec, features: FrameFeatures) -> dict[str, Any]:
    return {
        "row_index": frame.row_index,
        "timestamp_ns": frame.timestamp_ns,
        "timestamp_text": frame.timestamp_text,
        "image_relative": frame.image_relative,
        "image_sha256": frame.image_sha256,
        "image_size_bytes": frame.image_size_bytes,
        "producer_archive": str(frame.producer_path.resolve()),
        "producer_archive_sha256": sha256_file(frame.producer_path),
        "producer_archive_size_bytes": frame.producer_path.stat().st_size,
        "reused_from_prefix": frame.reused_from_prefix,
        "N": features.count,
        "source_shapes": {name: list(shape) for name, shape in features.source_shapes.items()},
        "source_dtypes": dict(features.source_dtypes),
        "canonical_shapes": {
            "keypoints": [features.count, 3],
            "scores": [features.count, 1],
            "descriptors": [features.count, 128],
        },
        "canonical_array_sha256": {
            "keypoints": _array_sha256(features.keypoints),
            "scores": _array_sha256(features.scores),
            "descriptors": _array_sha256(features.descriptors),
        },
        "keypoint_domain": "0<=x<968; 0<=y<608; scale>0",
        "same_N": True,
        "finite": True,
        "empty": features.count == 0,
    }


@contextmanager
def atomic_directory(target: Path) -> Iterator[Path]:
    if target.exists() or target.is_symlink():
        raise ContractError(f"OUTPUT_ALREADY_EXISTS:{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.tmp-", dir=str(target.parent)))
    committed = False
    try:
        yield staging
        if target.exists() or target.is_symlink():
            raise ContractError(f"OUTPUT_APPEARED_DURING_COMMIT:{target}")
        os.rename(staging, target)
        committed = True
    finally:
        if not committed:
            shutil.rmtree(staging, ignore_errors=True)


def validate_roundtrip_file(
    path: Path, source: np.ndarray, expected_columns: int, label: str
) -> dict[str, Any]:
    require_little_endian()
    _regular_file(path, f"OUTPUT_BIN:{label}")
    expected_bytes = int(source.shape[0]) * expected_columns * CONSUMER_DTYPE.itemsize
    payload = path.read_bytes()
    if len(payload) != expected_bytes:
        raise ContractError(f"OUTPUT_BYTE_COUNT_MISMATCH:{label}")
    reread = np.frombuffer(payload, dtype=CONSUMER_DTYPE).reshape(source.shape[0], expected_columns)
    if not np.array_equal(reread, source.astype(CONSUMER_DTYPE, copy=False)):
        raise ContractError(f"OUTPUT_FLOAT32_TO_FLOAT64_ROUNDTRIP_MISMATCH:{label}")
    if not np.isfinite(reread).all():
        raise ContractError(f"OUTPUT_NONFINITE_AFTER_ROUNDTRIP:{label}")
    return {
        "path": str(path),
        "dtype": "<f8",
        "shape": [int(source.shape[0]), expected_columns],
        "byte_count": expected_bytes,
        "sha256": sha256_bytes(payload),
        "roundtrip_exact": True,
        "finite": True,
    }


def write_and_roundtrip(
    path: Path, source: np.ndarray, expected_columns: int, label: str
) -> dict[str, Any]:
    require_little_endian()
    target = np.ascontiguousarray(source, dtype=CONSUMER_DTYPE)
    path.write_bytes(target.tobytes(order="C"))
    return validate_roundtrip_file(path, source, expected_columns, label)


def _bind_frames_to_prefix(
    full: SequenceAudit, prefix: SequenceAudit | None
) -> tuple[FrameSpec, ...]:
    if prefix is None:
        return full.frames
    frames: list[FrameSpec] = []
    for frame in full.frames:
        if frame.row_index < full.profile.prefix_reuse_count:
            source = prefix.frames[frame.row_index]
            frames.append(FrameSpec(**{**frame.__dict__, "producer_path": source.producer_path, "reused_from_prefix": True}))
        else:
            frames.append(frame)
    return tuple(frames)


def _prefix_materialization_binding(prefix: SequenceAudit | None) -> dict[str, Any]:
    if prefix is None:
        return {"required": False, "count": 0}
    manifest_path = prefix.root / "r2d2" / "materialization_manifest.json"
    return {
        "required": True,
        "count": prefix.profile.expected_count,
        "source_indices_inclusive": [0, prefix.profile.expected_count - 1],
        "prefix_sequence_root": str(prefix.root.resolve()),
        "prefix_conversion_manifest_sha256": prefix.conversion_manifest_sha256,
        "prefix_sequence_identity_sha256": prefix.sequence_identity_sha256,
        "prefix_materialization_manifest_sha256": sha256_file(manifest_path),
        "archive_byte_identity": True,
        "bin_byte_identity": True,
    }


def _sequence_binding(audit: SequenceAudit) -> dict[str, Any]:
    return {
        "profile": audit.profile.name,
        "sequence_root": str(audit.root.resolve()),
        "conversion_manifest": str(audit.conversion_manifest_path.resolve()),
        "conversion_manifest_sha256": audit.conversion_manifest_sha256,
        "sequence_identity_schema": EXPORT_SEQUENCE_IDENTITY_SCHEMA,
        "sequence_identity_sha256": audit.sequence_identity_sha256,
        "rgb_txt_sha256": audit.rgb_txt_sha256,
        "calibration_sha256": audit.calibration_sha256,
        "images": [
            {
                "row_index": frame.row_index,
                "timestamp_ns": frame.timestamp_ns,
                "relative_path": frame.image_relative,
                "sha256": frame.image_sha256,
                "size_bytes": frame.image_size_bytes,
            }
            for frame in audit.frames
        ],
    }


def _producer_run_binding(
    audit: SequenceAudit, prefix: SequenceAudit | None
) -> dict[str, Any]:
    current = {
        "manifest": str(audit.producer_run_manifest_path.resolve()),
        "manifest_sha256": audit.producer_run_manifest_sha256,
        "schema": PRODUCER_RUN_SCHEMA,
        "repo_commit": R2D2_PRODUCER_COMMIT,
        "repo_git_tree": audit.producer_run_manifest["producer"]["git_tree"],
        "worktree_clean": True,
        "extract_py_sha256": R2D2_EXTRACT_PY_SHA256,
        "checkpoint_sha256": audit.producer_run_manifest["checkpoint"]["sha256"],
        "environment_lock_sha256": audit.producer_run_manifest["runtime"]["environment_lock"]["sha256"],
        "python_executable_sha256": audit.producer_run_manifest["runtime"]["python_executable"]["sha256"],
        "argv_sha256": audit.producer_run_manifest["invocation"]["argv_sha256"],
        "flags_sha256": audit.producer_run_manifest["invocation"]["flags_sha256"],
        "image_list_sha256": audit.producer_run_manifest["invocation"]["image_list"]["sha256"],
        "working_directory": audit.producer_run_manifest["invocation"]["working_directory"],
        "return_code": 0,
    }
    result: dict[str, Any] = {"current": current}
    if prefix is not None:
        result["prefix"] = {
            "manifest": str(prefix.producer_run_manifest_path.resolve()),
            "manifest_sha256": prefix.producer_run_manifest_sha256,
            "schema": PRODUCER_RUN_SCHEMA,
            "archive_count": prefix.profile.expected_count,
        }
    return result


def _manifest(
    audit: SequenceAudit,
    producer_root: Path,
    prefix: SequenceAudit | None,
    frame_rows: Sequence[Mapping[str, Any]],
    tree_rows: Sequence[tuple[str, str]],
) -> dict[str, Any]:
    counts = [int(row["N"]) for row in frame_rows]
    return {
        "adapter_version": ADAPTER_VERSION,
        "adapter_identity": adapter_identity(),
        "status": STATUS_MATERIALIZED,
        "host_byteorder": runtime_byteorder(),
        "profile": audit.profile.name,
        "sequence_root": str(audit.root.resolve()),
        "producer_root": str(producer_root.resolve()),
        "sequence_binding": _sequence_binding(audit),
        "producer_run_binding": _producer_run_binding(audit, prefix),
        "prefix_promotion": _prefix_materialization_binding(prefix),
        "producer_contract": {
            "origin": R2D2_ORIGIN,
            "commit": R2D2_PRODUCER_COMMIT,
            "extract_py_sha256": R2D2_EXTRACT_PY_SHA256,
            "tag": "r2d2",
            "archive_name": "rgb/<timestamp_ns>.png.r2d2",
            "required_arrays": {
                "imsize": "integer [968, 608] in (width, height) order",
                "keypoints": "float32 N x 3 with in-image x/y and scale>0",
                "scores": "float32 N (N x 1 is rejected)",
                "descriptors": "float32 N x 128",
            },
        },
        "consumer_contract": {
            "origin": ANYFEATURE_ORIGIN,
            "paper_commit": ANYFEATURE_PAPER_COMMIT,
            "file_sha256": ANYFEATURE_CONTRACT_FILE_SHA256,
            "native_reader_precondition": "host byteorder must be little",
            "dtype": "little-endian IEEE-754 float64 (<f8)",
            "layout": "raw headerless C-order rows",
            "shapes": {"keypoints": "N x 3", "scores": "N x 1", "descriptors": "N x 128"},
            "feature_count_range": "0 <= N <= 5000",
            "zero_feature_policy": "PRESERVE_AS_THREE_0_BYTE_BINS",
        },
        "frames": list(frame_rows),
        "summary": {
            "frame_count": len(frame_rows),
            "min_features": min(counts),
            "max_features": max(counts),
            "all_same_N_per_frame": True,
            "all_finite": True,
            "zero_feature_frame_count": sum(count == 0 for count in counts),
            "all_roundtrip_exact": True,
        },
        "payload_tree_sha256_excluding_manifest": _aggregate_rows(sorted(tree_rows)),
        "claims": {
            "model_loaded_by_adapter": False,
            "model_run_by_adapter": False,
            "external_producer_run_manifest_validated": True,
            "producer_archives_modified": False,
            "sequence_images_modified": False,
            "anyfeature_source_modified": False,
            "anyfeature_built": False,
            "anyfeature_started": False,
            "trajectory_produced": False,
        },
    }


def _audit_output_tree(
    target: Path,
    frames: Sequence[FrameSpec],
    write: bool,
    prefix: SequenceAudit | None,
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    expected_names = {frame.output_filename for frame in frames}
    if write:
        for name in REQUIRED_COLUMNS:
            (target / name).mkdir()
    else:
        expected_root = set(REQUIRED_COLUMNS) | {"materialization_manifest.json"}
        if {path.name for path in target.iterdir()} != expected_root:
            raise ContractError("OUTPUT_R2D2_ROOT_ENTRY_SET_MISMATCH")
    for name in REQUIRED_COLUMNS:
        directory = target / name
        _regular_directory(directory, f"OUTPUT_COMPONENT_DIRECTORY:{name}")
        if not write:
            entries = list(directory.iterdir())
            if any(path.is_symlink() or not path.is_file() for path in entries):
                raise ContractError(f"OUTPUT_COMPONENT_HAS_SYMLINK_OR_NONFILE:{name}")
            if {path.name for path in entries} != expected_names:
                raise ContractError(f"OUTPUT_BIN_SET_MISMATCH:{name}")
    rows: list[dict[str, Any]] = []
    tree_rows: list[tuple[str, str]] = []
    for frame in frames:
        features = load_frame_features(frame.producer_path, frame.image_relative)
        row = frame_validation_row(frame, features)
        arrays = {"keypoints": features.keypoints, "scores": features.scores, "descriptors": features.descriptors}
        outputs: dict[str, Any] = {}
        for name, source in arrays.items():
            relative = f"{name}/{frame.output_filename}"
            path = target / relative
            if write:
                if frame.reused_from_prefix:
                    if prefix is None:
                        raise ContractError("INTERNAL_PREFIX_CONTEXT_MISSING")
                    source_bin = prefix.root / "r2d2" / relative
                    _regular_file(source_bin, f"PREFIX_BIN:{relative}")
                    shutil.copyfile(source_bin, path)
                    if sha256_file(source_bin) != sha256_file(path):
                        raise ContractError(f"PREFIX_BIN_COPY_SHA256_MISMATCH:{relative}")
                else:
                    write_and_roundtrip(path, source, REQUIRED_COLUMNS[name], frame.image_relative)
            result = validate_roundtrip_file(path, source, REQUIRED_COLUMNS[name], f"{frame.image_relative}:{name}")
            result["path"] = f"r2d2/{relative}"
            outputs[name] = result
            tree_rows.append((relative, str(result["sha256"])))
        row["outputs"] = outputs
        rows.append(row)
    return rows, tree_rows


def validate_sequence(
    sequence_root: Path,
    producer_root: Path,
    profile: SequenceProfile,
    prefix_sequence_root: Path | None = None,
) -> tuple[tuple[FrameSpec, ...], list[dict[str, Any]]]:
    require_little_endian()
    target = sequence_root / "r2d2"
    if target.exists() or target.is_symlink():
        raise ContractError(f"OUTPUT_ALREADY_EXISTS:{target}")
    audit, prefix = _audits_for_profile(sequence_root, producer_root, profile, prefix_sequence_root)
    if prefix is not None:
        validate_materialized_output(prefix.root, prefix.root, prefix.profile)
    frames = _bind_frames_to_prefix(audit, prefix)
    return frames, [frame_validation_row(frame, load_frame_features(frame.producer_path, frame.image_relative)) for frame in frames]


def validation_result(
    sequence_root: Path,
    producer_root: Path,
    frames: Sequence[FrameSpec],
    rows: Sequence[Mapping[str, Any]],
    profile: SequenceProfile | None = None,
) -> dict[str, Any]:
    return {
        "adapter_version": ADAPTER_VERSION,
        "adapter_identity": adapter_identity(),
        "status": STATUS_VALID,
        "host_byteorder": runtime_byteorder(),
        "profile": profile.name if profile else "UNSPECIFIED_TEST_PROFILE",
        "sequence_root": str(sequence_root.resolve()),
        "producer_root": str(producer_root.resolve()),
        "frame_count": len(frames),
        "frames": list(rows),
        "summary": {
            "min_features": min(int(row["N"]) for row in rows),
            "max_features": max(int(row["N"]) for row in rows),
            "zero_feature_frame_count": sum(int(row["N"]) == 0 for row in rows),
        },
        "claims": {
            "output_created": False,
            "model_loaded_by_adapter": False,
            "model_run_by_adapter": False,
            "external_producer_run_manifest_validated": True,
            "anyfeature_started": False,
        },
    }


def materialize_sequence(
    sequence_root: Path,
    producer_root: Path,
    profile: SequenceProfile,
    prefix_sequence_root: Path | None = None,
) -> dict[str, Any]:
    require_little_endian()
    target = sequence_root / "r2d2"
    if target.exists() or target.is_symlink():
        raise ContractError(f"OUTPUT_ALREADY_EXISTS:{target}")
    audit, prefix = _audits_for_profile(sequence_root, producer_root, profile, prefix_sequence_root)
    if prefix is not None:
        validate_materialized_output(prefix.root, prefix.root, prefix.profile)
    frames = _bind_frames_to_prefix(audit, prefix)
    with atomic_directory(target) as staging:
        rows, tree_rows = _audit_output_tree(staging, frames, True, prefix)
        manifest = _manifest(audit, producer_root, prefix, rows, tree_rows)
        (staging / "materialization_manifest.json").write_text(canonical_json(manifest), encoding="utf-8")
    return manifest


def validate_materialized_output(
    sequence_root: Path,
    producer_root: Path,
    profile: SequenceProfile,
    prefix_sequence_root: Path | None = None,
) -> dict[str, Any]:
    require_little_endian()
    audit, prefix = _audits_for_profile(sequence_root, producer_root, profile, prefix_sequence_root)
    if prefix is not None:
        validate_materialized_output(prefix.root, prefix.root, prefix.profile)
    frames = _bind_frames_to_prefix(audit, prefix)
    target = sequence_root / "r2d2"
    _regular_directory(target, "MATERIALIZED_R2D2_DIRECTORY")
    manifest_path = target / "materialization_manifest.json"
    existing = _json_object(manifest_path, "OUTPUT_MANIFEST")
    rows, tree_rows = _audit_output_tree(target, frames, False, prefix)
    expected = _manifest(audit, producer_root, prefix, rows, tree_rows)
    if existing.get("host_byteorder") != "little":
        raise ContractError("OUTPUT_MANIFEST_HOST_BYTEORDER_MISMATCH")
    if existing != expected:
        raise ContractError("OUTPUT_MANIFEST_CONTENT_MISMATCH")
    return {
        "adapter_version": ADAPTER_VERSION,
        "status": STATUS_OUTPUT_VALID,
        "host_byteorder": runtime_byteorder(),
        "profile": profile.name,
        "sequence_root": str(sequence_root.resolve()),
        "producer_root": str(producer_root.resolve()),
        "frame_count": len(frames),
        "conversion_manifest_sha256": audit.conversion_manifest_sha256,
        "materialization_manifest_sha256": sha256_file(manifest_path),
        "payload_tree_sha256_excluding_manifest": expected["payload_tree_sha256_excluding_manifest"],
        "zero_feature_frame_count": expected["summary"]["zero_feature_frame_count"],
        "all_same_N_per_frame": True,
        "all_finite": True,
        "all_roundtrip_exact": True,
        "frames": rows,
        "claims": {
            "output_created": False,
            "output_modified": False,
            "model_loaded_by_adapter": False,
            "model_run_by_adapter": False,
            "external_producer_run_manifest_validated": True,
            "anyfeature_started": False,
        },
    }


def _paths_overlap(left: Path, right: Path) -> bool:
    a, b = left.resolve(), right.resolve()
    return a == b or a in b.parents or b in a.parents


def _smoke_manifest(
    prefix: SequenceAudit,
    view_root: Path,
    experiment_folder: Path,
    preregistration_path: Path | None = None,
) -> dict[str, Any]:
    frame = prefix.frames[0]
    features = load_frame_features(frame.producer_path, frame.image_relative)
    if features.count <= 0:
        raise ContractError("SMOKE_VIEW_INDEX0_HAS_ZERO_FEATURES")
    source_bins = {
        name: prefix.root / "r2d2" / name / frame.output_filename for name in REQUIRED_COLUMNS
    }
    target_bins = {
        name: view_root / "r2d2" / name / frame.output_filename for name in REQUIRED_COLUMNS
    }
    preregistration = (
        audit_smoke_preregistration(preregistration_path)
        if preregistration_path is not None
        else {
            "required_for_real_run": True,
            "verified": False,
        }
    )
    return {
        "adapter_version": ADAPTER_VERSION,
        "adapter_identity": adapter_identity(),
        "status": STATUS_SMOKE_VIEW,
        "host_byteorder": runtime_byteorder(),
        "profile": SMOKE_PROFILE,
        "evaluation_eligible": False,
        "sequence_root": str(view_root.resolve()),
        "experiment_folder_reserved": str(experiment_folder.resolve()),
        "formal_reserved_paths": {
            "one_image_sequence_view": str(FORMAL_SMOKE_VIEW_ROOT),
            "experiment_folder": str(FORMAL_SMOKE_EXPERIMENT_FOLDER),
            "preregistration": preregistration,
        },
        "path_separation_verified": not _paths_overlap(view_root, experiment_folder),
        "source_prefix": {
            "sequence_root": str(prefix.root.resolve()),
            "conversion_manifest": str(prefix.conversion_manifest_path.resolve()),
            "conversion_manifest_sha256": prefix.conversion_manifest_sha256,
            "sequence_identity_sha256": prefix.sequence_identity_sha256,
            "materialization_manifest_sha256": sha256_file(prefix.root / "r2d2" / "materialization_manifest.json"),
            "producer_run_manifest_sha256": prefix.producer_run_manifest_sha256,
        },
        "frame": {
            "source_index": 0,
            "timestamp_ns": frame.timestamp_ns,
            "rgb_txt_row": f"{frame.timestamp_text} {frame.image_relative}",
            "source_png": str(frame.image_path.resolve()),
            "source_png_sha256": frame.image_sha256,
            "source_png_size_bytes": frame.image_size_bytes,
            "target_png": frame.image_relative,
            "target_png_sha256": sha256_file(view_root / frame.image_relative),
            "target_png_size_bytes": (view_root / frame.image_relative).stat().st_size,
            "producer_archive_sha256": sha256_file(frame.producer_path),
            "N": features.count,
            "bins": {
                name: {
                    "source": str(source_bins[name].resolve()),
                    "source_sha256": sha256_file(source_bins[name]),
                    "source_size_bytes": source_bins[name].stat().st_size,
                    "target": f"r2d2/{name}/{frame.output_filename}",
                    "target_sha256": sha256_file(target_bins[name]),
                    "target_size_bytes": target_bins[name].stat().st_size,
                }
                for name in REQUIRED_COLUMNS
            },
        },
        "calibration": {
            "source": str((prefix.root / "calibration.yaml").resolve()),
            "source_sha256": prefix.calibration_sha256,
            "target": "calibration.yaml",
            "target_sha256": sha256_file(view_root / "calibration.yaml"),
        },
        "rgb_txt": {
            "path": "rgb.txt",
            "row_count": 1,
            "sha256": sha256_file(view_root / "rgb.txt"),
        },
        "claims": {
            "image_reencoded": False,
            "inference_rerun_for_smoke": False,
            "source_inference_manifest_validated": True,
            "bins_rematerialized": False,
            "anyfeature_started": False,
            "trajectory_produced": False,
        },
    }


def materialize_smoke_view(
    prefix_sequence_root: Path,
    view_root: Path,
    experiment_folder: Path,
    prefix_profile: SequenceProfile = PROFILES["a02-prefix200"],
    preregistration_path: Path | None = None,
) -> dict[str, Any]:
    require_little_endian()
    if _paths_overlap(prefix_sequence_root, view_root):
        raise ContractError("SMOKE_VIEW_OVERLAPS_PREFIX_SEQUENCE")
    if _paths_overlap(view_root, experiment_folder) or _paths_overlap(prefix_sequence_root, experiment_folder):
        raise ContractError("SMOKE_EXPERIMENT_FOLDER_NOT_SEPARATE")
    if experiment_folder.exists() or experiment_folder.is_symlink():
        raise ContractError("SMOKE_EXPERIMENT_FOLDER_ALREADY_EXISTS")
    validate_materialized_output(prefix_sequence_root, prefix_sequence_root, prefix_profile)
    prefix = audit_sequence(prefix_sequence_root, prefix_profile, prefix_sequence_root)
    frame = prefix.frames[0]
    if load_frame_features(frame.producer_path, frame.image_relative).count <= 0:
        raise ContractError("SMOKE_VIEW_INDEX0_HAS_ZERO_FEATURES")
    with atomic_directory(view_root) as staging:
        (staging / "rgb").mkdir()
        for name in REQUIRED_COLUMNS:
            (staging / "r2d2" / name).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(frame.image_path, staging / frame.image_relative)
        shutil.copyfile(prefix.root / "calibration.yaml", staging / "calibration.yaml")
        (staging / "rgb.txt").write_text(f"{frame.timestamp_text} {frame.image_relative}\n", encoding="ascii")
        for name in REQUIRED_COLUMNS:
            source = prefix.root / "r2d2" / name / frame.output_filename
            shutil.copyfile(source, staging / "r2d2" / name / frame.output_filename)
        manifest = _smoke_manifest(
            prefix, staging, experiment_folder, preregistration_path
        )
        # Bind the final path, not the ephemeral staging path.
        manifest["sequence_root"] = str(view_root.resolve())
        (staging / "smoke_view_manifest.json").write_text(canonical_json(manifest), encoding="utf-8")
    return manifest


def validate_smoke_view(
    prefix_sequence_root: Path,
    view_root: Path,
    experiment_folder: Path,
    prefix_profile: SequenceProfile = PROFILES["a02-prefix200"],
    preregistration_path: Path | None = None,
) -> dict[str, Any]:
    require_little_endian()
    if _paths_overlap(prefix_sequence_root, view_root) or _paths_overlap(view_root, experiment_folder) or _paths_overlap(prefix_sequence_root, experiment_folder):
        raise ContractError("SMOKE_VIEW_PATH_SEPARATION_MISMATCH")
    validate_materialized_output(prefix_sequence_root, prefix_sequence_root, prefix_profile)
    prefix = audit_sequence(prefix_sequence_root, prefix_profile, prefix_sequence_root)
    _regular_directory(view_root, "SMOKE_VIEW_ROOT")
    expected_root = {"rgb", "rgb.txt", "calibration.yaml", "r2d2", "smoke_view_manifest.json"}
    if {path.name for path in view_root.iterdir()} != expected_root or any(path.is_symlink() for path in view_root.iterdir()):
        raise ContractError("SMOKE_VIEW_ROOT_ENTRY_SET_MISMATCH")
    frame = prefix.frames[0]
    _regular_directory(view_root / "rgb", "SMOKE_VIEW_RGB_DIRECTORY")
    _regular_file(view_root / "rgb.txt", "SMOKE_VIEW_RGB_TXT")
    _regular_file(view_root / "calibration.yaml", "SMOKE_VIEW_CALIBRATION")
    _regular_directory(view_root / "r2d2", "SMOKE_VIEW_R2D2_DIRECTORY")
    r2d2_entries = list((view_root / "r2d2").iterdir())
    if (
        {path.name for path in r2d2_entries} != set(REQUIRED_COLUMNS)
        or any(path.is_symlink() or not path.is_dir() for path in r2d2_entries)
    ):
        raise ContractError("SMOKE_VIEW_R2D2_ENTRY_SET_MISMATCH")
    rgb_entries = list((view_root / "rgb").iterdir())
    if len(rgb_entries) != 1 or rgb_entries[0].name != Path(frame.image_relative).name or rgb_entries[0].is_symlink():
        raise ContractError("SMOKE_VIEW_RGB_FILE_SET_MISMATCH")
    expected_rgb = f"{frame.timestamp_text} {frame.image_relative}\n".encode("ascii")
    if (view_root / "rgb.txt").read_bytes() != expected_rgb:
        raise ContractError("SMOKE_VIEW_RGB_TXT_BYTE_MISMATCH")
    if sha256_file(view_root / frame.image_relative) != frame.image_sha256:
        raise ContractError("SMOKE_VIEW_PNG_BYTE_MISMATCH")
    if sha256_file(view_root / "calibration.yaml") != prefix.calibration_sha256:
        raise ContractError("SMOKE_VIEW_CALIBRATION_BYTE_MISMATCH")
    for name in REQUIRED_COLUMNS:
        directory = view_root / "r2d2" / name
        _regular_directory(directory, f"SMOKE_VIEW_BIN_DIRECTORY:{name}")
        entries = list(directory.iterdir())
        if len(entries) != 1 or entries[0].name != frame.output_filename or entries[0].is_symlink():
            raise ContractError(f"SMOKE_VIEW_BIN_FILE_SET_MISMATCH:{name}")
        if sha256_file(entries[0]) != sha256_file(prefix.root / "r2d2" / name / frame.output_filename):
            raise ContractError(f"SMOKE_VIEW_BIN_BYTE_MISMATCH:{name}")
    manifest_path = view_root / "smoke_view_manifest.json"
    existing = _json_object(manifest_path, "SMOKE_VIEW_MANIFEST")
    expected = _smoke_manifest(
        prefix, view_root, experiment_folder, preregistration_path
    )
    if existing != expected:
        raise ContractError("SMOKE_VIEW_MANIFEST_CONTENT_MISMATCH")
    return {
        "adapter_version": ADAPTER_VERSION,
        "status": STATUS_SMOKE_VIEW_VALID,
        "host_byteorder": runtime_byteorder(),
        "sequence_root": str(view_root.resolve()),
        "experiment_folder_reserved": str(experiment_folder.resolve()),
        "smoke_view_manifest_sha256": sha256_file(manifest_path),
        "frame_count": 1,
        "evaluation_eligible": False,
    }


def _is_within(path: Path, root: Path) -> bool:
    resolved, parent = path.resolve(), root.resolve()
    return resolved == parent or parent in resolved.parents


def audit_smoke_preregistration(path: Path) -> dict[str, Any]:
    _regular_file(path, "SMOKE_PREREGISTRATION")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ContractError("SMOKE_PREREGISTRATION_NOT_UTF8") from exc
    required = {
        str(FORMAL_SMOKE_VIEW_ROOT),
        str(FORMAL_SMOKE_EXPERIMENT_FOLDER),
    }
    if not required.issubset(set(lines)):
        raise ContractError("SMOKE_RESERVED_PATH_NOT_IN_PREREGISTRATION")
    return {
        "required_for_real_run": True,
        "verified": True,
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "reserved_paths_present": sorted(required),
    }


def _inside_staging_namespace(path: Path, target: Path) -> bool:
    try:
        relative = path.resolve().relative_to(target.parent.resolve())
    except ValueError:
        return False
    return bool(relative.parts) and relative.parts[0].startswith(f".{target.name}.tmp-")


def validate_report_target(
    path: Path,
    forbidden_roots: Sequence[Path],
    staging_targets: Sequence[Path] = (),
) -> None:
    if path.exists() or path.is_symlink():
        raise ContractError(f"REPORT_JSON_ALREADY_EXISTS:{path}")
    for root in forbidden_roots:
        if _is_within(path, root):
            raise ContractError(f"REPORT_JSON_INSIDE_FORBIDDEN_ROOT:{root}")
    for target in staging_targets:
        if _inside_staging_namespace(path, target):
            raise ContractError(f"REPORT_JSON_INSIDE_STAGING_NAMESPACE:{target}")


def _write_report_exclusive(path: Path, text: str) -> None:
    if path.exists() or path.is_symlink():
        raise ContractError(f"REPORT_JSON_ALREADY_EXISTS:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.tmp-", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise ContractError(f"REPORT_JSON_ALREADY_EXISTS:{path}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action",
        choices=("validate", "materialize", "validate-output", "smoke-view", "validate-smoke-view"),
        default="validate",
    )
    parser.add_argument("--profile", choices=tuple(PROFILES))
    parser.add_argument("--sequence-root", type=Path)
    parser.add_argument("--producer-root", type=Path)
    parser.add_argument("--prefix-sequence-root", type=Path)
    parser.add_argument("--smoke-view-root", type=Path, default=FORMAL_SMOKE_VIEW_ROOT)
    parser.add_argument(
        "--experiment-folder", type=Path, default=FORMAL_SMOKE_EXPERIMENT_FOLDER
    )
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=DEFAULT_PREREGISTRATION_PATH,
        help="Frozen protocol; formal smoke requires both reserved paths in it",
    )
    parser.add_argument("--report-json", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report_valid = False
    try:
        require_little_endian()
        smoke_action = args.action in ("smoke-view", "validate-smoke-view")
        if smoke_action:
            if args.prefix_sequence_root is None:
                raise ContractError("SMOKE_PREFIX_SEQUENCE_ROOT_REQUIRED")
            if (
                args.smoke_view_root.resolve() != FORMAL_SMOKE_VIEW_ROOT.resolve()
                or args.experiment_folder.resolve()
                != FORMAL_SMOKE_EXPERIMENT_FOLDER.resolve()
            ):
                raise ContractError("SMOKE_FORMAL_RESERVED_PATH_MISMATCH")
            if args.preregistration.resolve() != DEFAULT_PREREGISTRATION_PATH.resolve():
                raise ContractError("SMOKE_PREREGISTRATION_AUTHORITY_PATH_MISMATCH")
            audit_smoke_preregistration(args.preregistration)
            forbidden = [args.prefix_sequence_root, args.smoke_view_root, args.experiment_folder]
        else:
            if args.sequence_root is None or args.profile is None:
                raise ContractError("SEQUENCE_ROOT_AND_EXPLICIT_PROFILE_REQUIRED")
            producer_root = args.producer_root or args.sequence_root
            forbidden = [args.sequence_root, producer_root]
            if args.prefix_sequence_root is not None:
                forbidden.append(args.prefix_sequence_root)
        if args.report_json is not None:
            staging_targets = [args.smoke_view_root] if smoke_action else [args.sequence_root / "r2d2"]
            validate_report_target(args.report_json, forbidden, staging_targets)
            report_valid = True
        if smoke_action:
            if args.action == "smoke-view":
                result = materialize_smoke_view(
                    args.prefix_sequence_root,
                    args.smoke_view_root,
                    args.experiment_folder,
                    preregistration_path=args.preregistration,
                )
            else:
                result = validate_smoke_view(
                    args.prefix_sequence_root,
                    args.smoke_view_root,
                    args.experiment_folder,
                    preregistration_path=args.preregistration,
                )
        else:
            profile = PROFILES[args.profile]
            producer_root = args.producer_root or args.sequence_root
            if args.action == "validate":
                frames, rows = validate_sequence(args.sequence_root, producer_root, profile, args.prefix_sequence_root)
                result = validation_result(args.sequence_root, producer_root, frames, rows, profile)
            elif args.action == "materialize":
                result = materialize_sequence(args.sequence_root, producer_root, profile, args.prefix_sequence_root)
            else:
                result = validate_materialized_output(args.sequence_root, producer_root, profile, args.prefix_sequence_root)
        rc = RC_READY
    except ContractError as exc:
        result = {
            "adapter_version": ADAPTER_VERSION,
            "status": STATUS_INTEGRITY_ERROR,
            "errors": [str(exc)],
            "claims": {"output_created": False, "model_loaded": False, "model_run": False, "anyfeature_started": False},
        }
        rc = RC_INTEGRITY_ERROR
    except Exception as exc:
        result = {
            "adapter_version": ADAPTER_VERSION,
            "status": STATUS_INTEGRITY_ERROR,
            "errors": [f"UNEXPECTED_{type(exc).__name__}:{exc}"],
            "claims": {"output_created": False, "model_loaded": False, "model_run": False, "anyfeature_started": False},
        }
        rc = RC_INTEGRITY_ERROR
    rendered = canonical_json(result)
    if args.report_json is not None and report_valid:
        try:
            _write_report_exclusive(args.report_json, rendered)
        except ContractError as exc:
            rendered = canonical_json({
                "adapter_version": ADAPTER_VERSION,
                "status": STATUS_INTEGRITY_ERROR,
                "errors": [str(exc)],
                "claims": {"output_created": False, "model_loaded": False, "model_run": False, "anyfeature_started": False},
            })
            rc = RC_INTEGRITY_ERROR
    sys.stdout.write(rendered)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
