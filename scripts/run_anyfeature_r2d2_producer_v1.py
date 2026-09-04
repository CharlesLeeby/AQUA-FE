#!/usr/bin/env python3
"""Run the frozen official R2D2 extractor for the AnyFeature comparison.

This is a project-side provenance runner.  It does not implement a feature
extractor and does not edit either upstream checkout.  Its two formal modes
are the A02 prefix (indices 0..199) and the full continuation (200..900 only).
The official ``extract.py`` remains the only model-inference entry point.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

try:
    from scripts import materialize_anyfeature_r2d2_bins_v1 as materializer
except ModuleNotFoundError:
    # Support the documented direct invocation from the workspace root while
    # keeping the package import used by unittest.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import materialize_anyfeature_r2d2_bins_v1 as materializer


RUNNER_VERSION = "anyfeature-r2d2-producer-v1"
RUNNER_SCHEMA = materializer.PRODUCER_RUN_SCHEMA
RUNNER_SCRIPT_RELATIVE = "scripts/run_anyfeature_r2d2_producer_v1.py"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"
STATUS_INTEGRITY_ERROR = "INTEGRITY_ERROR"
RC_COMPLETED = 0
RC_PROCESS_FAILED = 1
RC_INTEGRITY_ERROR = 2

R2D2_REPO = Path("/mnt/data/SLAM/r2d2-official-r1")
R2D2_CHECKPOINT = R2D2_REPO / "models/r2d2_WASF_N16.pt"
ANYFEATURE_REPO = Path("/mnt/data/SLAM/AnyFeature-VSLAM-paper-2024-r3")
PREFIX_SEQUENCE_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/anyfeature_adapter/aqualoc_a02_0005_prefix200_r1"
)
FULL_SEQUENCE_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/anyfeature_adapter/aqualoc_a02_0005_full_r1"
)
R2D2_PYTHON_SYMLINK = Path(
    "/mnt/data/opt/anyfeature-paper-2024-r1/r2d2-pyenv/bin/python"
)
R2D2_PYTHON = R2D2_PYTHON_SYMLINK.with_name(
    "python-anyfeature-r2d2-cpu-v1"
)
FORMAL_CACHE_ROOT = Path("/mnt/data/opt/anyfeature-paper-2024-r1")
RUNTIME_HOOK_DIRECTORY = Path(__file__).resolve().parent / "anyfeature_r2d2_cpu_runtime"
RUNTIME_HOOK = RUNTIME_HOOK_DIRECTORY / "sitecustomize.py"
CPU_INTRAOP_THREADS = 6
CPU_INTEROP_THREADS = 1

ANYFEATURE_ORIGIN = materializer.ANYFEATURE_ORIGIN
ANYFEATURE_PAPER_COMMIT = materializer.ANYFEATURE_PAPER_COMMIT
ANYFEATURE_PAPER_TREE = "36b264e1da05c6fe9cd987965e9a75ba96930b63"
ANYFEATURE_README_SHA256 = (
    "54bb83ae94b871af64ca15a27bfe871bbce4dbdeeea6d1a87abd34cf72d9c612"
)
VSLAM_LAB_ORIGIN = "https://github.com/alejandrofontan/VSLAM-LAB"
VSLAM_LAB_REFERENCE_TEXT = (
    "AnyFeature-VSLAM runs seamlessly as a baseline for experiments within the"
)

R2D2_LICENSE_SHA256 = (
    "2891af7a316a5783cdbde291bb6122637f0934473997fd7a335f8b668e2dcd7f"
)
R2D2_EXTRACT_SHA256 = materializer.R2D2_EXTRACT_PY_SHA256
R2D2_COMMIT = materializer.R2D2_PRODUCER_COMMIT
R2D2_TREE = materializer.R2D2_PRODUCER_GIT_TREE
R2D2_ORIGIN = materializer.R2D2_ORIGIN
CHECKPOINT_SHA256 = materializer.R2D2_CHECKPOINT_SHA256
CHECKPOINT_SIZE_BYTES = materializer.R2D2_CHECKPOINT_SIZE_BYTES

REQUIRED_CACHE_VARIABLES = (
    "MAMBA_ROOT_PREFIX",
    "CONDA_PKGS_DIRS",
    "PIP_CACHE_DIR",
    "HF_HOME",
    "XDG_CACHE_HOME",
    "TMPDIR",
)
EXECUTION_ENVIRONMENT = {
    "CUDA_VISIBLE_DEVICES": "-1",
    "OMP_NUM_THREADS": str(CPU_INTRAOP_THREADS),
    "MKL_NUM_THREADS": str(CPU_INTRAOP_THREADS),
    "AQUA_R2D2_TORCH_NUM_THREADS": str(CPU_INTRAOP_THREADS),
    "AQUA_R2D2_TORCH_INTEROP_THREADS": str(CPU_INTEROP_THREADS),
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONPATH": str(RUNTIME_HOOK_DIRECTORY),
}
RUNTIME_ENVIRONMENT_KEYS = REQUIRED_CACHE_VARIABLES + tuple(EXECUTION_ENVIRONMENT)
RUNTIME_MODULES = {
    "torch": ("torch", "torch"),
    "torchvision": ("torchvision", "torchvision"),
    "numpy": ("numpy", "numpy"),
    "Pillow": ("PIL", "Pillow"),
    "scipy": ("scipy", "scipy"),
    "tqdm": ("tqdm", "tqdm"),
    "matplotlib": ("matplotlib", "matplotlib"),
}


class ContractError(RuntimeError):
    """A no-clobber, identity, environment, or input contract failed."""


class ProcessFailure(RuntimeError):
    """The official process started but did not produce a sealable run."""


@dataclass(frozen=True)
class RunProfile:
    name: str
    sequence_profile: str
    sequence_count: int
    inference_start: int
    inference_stop: int
    expected_first_ns: Optional[int] = None
    expected_last_ns: Optional[int] = None
    prefix_reuse_count: int = 0

    @property
    def inference_indices(self) -> Tuple[int, ...]:
        return tuple(range(self.inference_start, self.inference_stop + 1))

    @property
    def inference_count(self) -> int:
        return self.inference_stop - self.inference_start + 1


FORMAL_PROFILES = {
    "a02-prefix200": RunProfile(
        "a02-prefix200",
        "a02-prefix200",
        200,
        0,
        199,
        1_542_829_016_700_435_392,
        1_542_829_026_649_564_544,
        0,
    ),
    "a02-full-continuation": RunProfile(
        "a02-full-continuation",
        "a02-full",
        901,
        200,
        900,
        1_542_829_016_700_435_392,
        None,
        200,
    ),
}


@dataclass(frozen=True)
class Frame:
    source_index: int
    timestamp_ns: int
    image_relative: str
    image_path: Path
    image_sha256: str
    image_size_bytes: int

    @property
    def archive_relative(self) -> str:
        return self.image_relative + ".r2d2"

    @property
    def archive_path(self) -> Path:
        return self.image_path.with_name(self.image_path.name + ".r2d2")


@dataclass(frozen=True)
class RuntimeSeal:
    probe: Mapping[str, Any]
    pip_freeze: bytes
    probe_stderr: bytes = b""


@dataclass(frozen=True)
class ProcessObservation:
    return_code: int
    start_utc: str
    end_utc: str
    elapsed_seconds: float
    archive_observations: Tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class RunConfig:
    profile: RunProfile
    sequence_root: Path
    python_executable: Path
    r2d2_repo: Path = R2D2_REPO
    checkpoint: Path = R2D2_CHECKPOINT
    anyfeature_repo: Path = ANYFEATURE_REPO
    prefix_sequence_root: Optional[Path] = None
    formal_paths: bool = True
    enforce_cache_contract: bool = True


@dataclass(frozen=True)
class RunResult:
    rc: int
    manifest: Mapping[str, Any]


RuntimeProvider = Callable[[Path, Path, Mapping[str, str]], RuntimeSeal]
ProcessExecutor = Callable[
    [Sequence[str], Path, Mapping[str, str], Path, Path, Sequence[Frame]],
    ProcessObservation,
]


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _regular_file(path: Path, label: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise ContractError("%s_MISSING_OR_SYMLINK:%s" % (label, path))


def _regular_directory(path: Path, label: str) -> None:
    if not path.is_dir() or path.is_symlink():
        raise ContractError("%s_MISSING_OR_SYMLINK:%s" % (label, path))


def _canonical_absolute(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise ContractError("%s_NOT_ABSOLUTE:%s" % (label, path))
    resolved = path.resolve()
    if str(path) != str(resolved):
        raise ContractError("%s_NOT_CANONICAL:%s" % (label, path))
    return resolved


def file_binding(path: Path, label: str, expected_hash: Optional[str] = None) -> Dict[str, Any]:
    path = _canonical_absolute(path.resolve(), label)
    _regular_file(path, label)
    digest = sha256_file(path)
    if expected_hash is not None and digest != expected_hash:
        raise ContractError("%s_SHA256_MISMATCH" % label)
    return {
        "path": str(path),
        "sha256": digest,
        "size_bytes": path.stat().st_size,
    }


def _exclusive_write(path: Path, payload: bytes, mode: int = 0o600) -> None:
    if path.exists() or path.is_symlink():
        raise ContractError("OUTPUT_ALREADY_EXISTS:%s" % path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(str(path), flags, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _exclusive_manifest(path: Path, value: Mapping[str, Any]) -> None:
    _exclusive_write(path, canonical_json(value).encode("utf-8"))


def runner_identity() -> Dict[str, Any]:
    script = Path(__file__).resolve()
    result = file_binding(script, "RUNNER_SCRIPT")
    result.update({"relative": RUNNER_SCRIPT_RELATIVE, "version": RUNNER_VERSION})
    return result


def prepare_python_executable(config: RunConfig) -> Tuple[Path, Dict[str, Any]]:
    """Materialize/verify the one regular byte-copy accepted by the consumer audit.

    A normal venv ``bin/python`` is a symlink.  Resolving and invoking its target
    would lose the venv's adjacent ``pyvenv.cfg``; recording the symlink itself
    would fail the materializer's regular-file gate.  The venv and ``/usr/bin``
    may be on different filesystems, so a no-clobber byte-for-byte regular copy
    in ``venv/bin`` preserves both the venv semantics and an immutable executable
    binding.  No package or upstream source is changed.
    """
    requested = config.python_executable
    created = False
    if config.formal_paths:
        if requested != R2D2_PYTHON:
            raise ContractError("FORMAL_PYTHON_EXECUTABLE_PATH_MISMATCH")
        source_link = R2D2_PYTHON_SYMLINK
        if not source_link.is_symlink():
            raise ContractError("FORMAL_VENV_PYTHON_SYMLINK_MISSING")
        source = source_link.resolve()
        _regular_file(source, "FORMAL_VENV_PYTHON_TARGET")
        if requested.exists() or requested.is_symlink():
            _regular_file(requested, "FORMAL_PYTHON_EXECUTABLE")
        else:
            descriptor = None
            try:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                descriptor = os.open(str(requested), flags, source.stat().st_mode & 0o777)
                with source.open("rb") as source_handle, os.fdopen(
                    descriptor, "wb"
                ) as target_handle:
                    descriptor = None
                    shutil.copyfileobj(source_handle, target_handle, 1024 * 1024)
                    target_handle.flush()
                    os.fsync(target_handle.fileno())
                os.chmod(requested, source.stat().st_mode & 0o777)
            except FileExistsError as exc:
                raise ContractError(
                    "FORMAL_PYTHON_EXECUTABLE_CREATION_RACE"
                ) from exc
            except OSError as exc:
                if descriptor is not None:
                    os.close(descriptor)
                requested.unlink(missing_ok=True)
                raise ContractError(
                    "FORMAL_PYTHON_EXECUTABLE_COPY_FAILED:%s" % exc
                ) from exc
            created = True
        source_stat = source.stat()
        requested_stat = requested.stat()
        if (
            source_stat.st_size != requested_stat.st_size
            or sha256_file(source) != sha256_file(requested)
        ):
            raise ContractError("FORMAL_PYTHON_EXECUTABLE_BYTE_COPY_MISMATCH")
        if not os.access(str(requested), os.X_OK):
            raise ContractError("FORMAL_PYTHON_EXECUTABLE_NOT_EXECUTABLE")
        executable = requested
        source_binding = file_binding(source, "FORMAL_VENV_PYTHON_TARGET")
    else:
        executable = requested.resolve()
        _regular_file(executable, "PYTHON_EXECUTABLE")
        source_link = requested
        source_binding = file_binding(executable, "PYTHON_EXECUTABLE_SOURCE")
    executable_binding = file_binding(executable, "PYTHON_EXECUTABLE")
    return executable, {
        "requested": str(requested),
        "venv_python_symlink": str(source_link),
        "source_target": source_binding,
        "executable": executable_binding,
        "regular_file": not executable.is_symlink(),
        "source_device": source.stat().st_dev if config.formal_paths else executable.stat().st_dev,
        "source_inode": source.stat().st_ino if config.formal_paths else executable.stat().st_ino,
        "copy_device": executable.stat().st_dev,
        "copy_inode": executable.stat().st_ino,
        "source_mode": oct(source.stat().st_mode & 0o777) if config.formal_paths else oct(executable.stat().st_mode & 0o777),
        "copy_mode": oct(executable.stat().st_mode & 0o777),
        "byte_identity_sha256_and_size": (
            source_binding["sha256"] == executable_binding["sha256"]
            and source_binding["size_bytes"] == executable_binding["size_bytes"]
        ),
        "same_device_inode_required": False,
        "created_by_this_run": created,
        "materialization": "no-clobber regular byte-for-byte copy",
        "package_install_or_replacement_performed": False,
    }


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise ContractError(
            "GIT_COMMAND_FAILED:%s:%s"
            % (" ".join(args), completed.stderr.decode("utf-8", "replace").strip())
        )
    return completed.stdout.decode("utf-8", "strict").strip()


def _git_identity(
    repo: Path,
    label: str,
    origin: str,
    commit: str,
    tree: str,
) -> Dict[str, Any]:
    repo = _canonical_absolute(repo, label + "_REPO")
    _regular_directory(repo, label + "_REPO")
    observed = {
        "origin": _git(repo, "remote", "get-url", "origin"),
        "commit": _git(repo, "rev-parse", "HEAD"),
        "git_tree": _git(repo, "rev-parse", "HEAD^{tree}"),
        "worktree_clean": _git(
            repo, "status", "--porcelain=v1", "--untracked-files=all"
        )
        == "",
    }
    expected = {
        "origin": origin,
        "commit": commit,
        "git_tree": tree,
        "worktree_clean": True,
    }
    if observed != expected:
        raise ContractError("%s_GIT_IDENTITY_MISMATCH" % label)
    observed["path"] = str(repo)
    return observed


def capture_static_identity(config: RunConfig) -> Dict[str, Any]:
    r2d2 = _git_identity(
        config.r2d2_repo, "R2D2", R2D2_ORIGIN, R2D2_COMMIT, R2D2_TREE
    )
    extract = file_binding(
        config.r2d2_repo / "extract.py", "R2D2_EXTRACT_PY", R2D2_EXTRACT_SHA256
    )
    license_binding = file_binding(
        config.r2d2_repo / "LICENSE", "R2D2_LICENSE", R2D2_LICENSE_SHA256
    )
    checkpoint = file_binding(config.checkpoint, "R2D2_CHECKPOINT", CHECKPOINT_SHA256)
    if checkpoint["size_bytes"] != CHECKPOINT_SIZE_BYTES:
        raise ContractError("R2D2_CHECKPOINT_SIZE_MISMATCH")
    if Path(checkpoint["path"]) != (config.r2d2_repo / "models/r2d2_WASF_N16.pt"):
        raise ContractError("R2D2_CHECKPOINT_PATH_MISMATCH")

    anyfeature = _git_identity(
        config.anyfeature_repo,
        "ANYFEATURE",
        ANYFEATURE_ORIGIN,
        ANYFEATURE_PAPER_COMMIT,
        ANYFEATURE_PAPER_TREE,
    )
    readme = file_binding(
        config.anyfeature_repo / "README.md",
        "ANYFEATURE_README",
        ANYFEATURE_README_SHA256,
    )
    readme_text = Path(readme["path"]).read_text(encoding="utf-8")
    if VSLAM_LAB_REFERENCE_TEXT not in readme_text or VSLAM_LAB_ORIGIN not in readme_text:
        raise ContractError("ANYFEATURE_VSLAM_LAB_REFERENCE_MISMATCH")

    r2d2.update(
        {
            "extract_py_sha256": R2D2_EXTRACT_SHA256,
            "extract_py": extract,
            "license": license_binding,
        }
    )
    return {
        "producer": r2d2,
        "checkpoint": checkpoint,
        "author_integration_context": {
            "anyfeature": {**anyfeature, "readme": readme},
            "vslam_lab": {
                "origin": VSLAM_LAB_ORIGIN,
                "identity_source": "frozen AnyFeature paper-snapshot README",
                "code_executed": False,
            },
            "official_r2d2_extract_py_is_sole_inference_entry_point": True,
        },
    }


def _assert_static_identity_unchanged(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> None:
    if before != after:
        raise ProcessFailure("STATIC_IDENTITY_HASH_DRIFT_AFTER_PROCESS")


def _aggregate_rows(rows: Iterable[Tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for name, file_hash in rows:
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def load_sequence_contract(config: RunConfig) -> Tuple[Frame, ...]:
    if sys.byteorder != "little":
        raise ContractError("HOST_BYTEORDER_NOT_LITTLE:%s" % sys.byteorder)
    root = _canonical_absolute(config.sequence_root, "SEQUENCE_ROOT")
    _regular_directory(root, "SEQUENCE_ROOT")
    _regular_directory(root / "rgb", "RGB_DIRECTORY")
    rows = materializer._parse_rgb_txt(root)
    profile = config.profile
    if len(rows) != profile.sequence_count:
        raise ContractError("SEQUENCE_COUNT_MISMATCH")
    if profile.expected_first_ns is not None and rows[0][0] != profile.expected_first_ns:
        raise ContractError("SEQUENCE_FIRST_TIMESTAMP_MISMATCH")
    if profile.expected_last_ns is not None and rows[-1][0] != profile.expected_last_ns:
        raise ContractError("SEQUENCE_LAST_TIMESTAMP_MISMATCH")

    manifest_path = root / "conversion_manifest.json"
    _regular_file(manifest_path, "CONVERSION_MANIFEST")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("CONVERSION_MANIFEST_INVALID_JSON") from exc
    if not isinstance(manifest, dict):
        raise ContractError("CONVERSION_MANIFEST_NOT_OBJECT")
    if (
        manifest.get("adapter_version") != materializer.EXPORT_ADAPTER_VERSION
        or manifest.get("adapter_identity") != materializer.exporter_identity()
        or manifest.get("status") != "EXPORTED"
        or manifest.get("profile") != profile.sequence_profile
    ):
        raise ContractError("CONVERSION_MANIFEST_IDENTITY_MISMATCH")
    source = manifest.get("source")
    if profile.sequence_profile in materializer.PROFILES:
        if not isinstance(source, dict) or source.get("sha256") != materializer.EXPECTED_A02_SOURCE_BAG_SHA256:
            raise ContractError("CONVERSION_MANIFEST_SOURCE_BAG_SHA256_MISMATCH")
        calibration_source = source.get("calibration")
        if (
            not isinstance(calibration_source, dict)
            or calibration_source.get("sha256")
            != materializer.EXPECTED_A02_SOURCE_CALIBRATION_SHA256
        ):
            raise ContractError("CONVERSION_MANIFEST_SOURCE_CALIBRATION_SHA256_MISMATCH")
    camera = manifest.get("camera")
    calibration = manifest.get("calibration")
    if not isinstance(camera, dict) or not isinstance(calibration, dict):
        raise ContractError("CONVERSION_MANIFEST_CAMERA_OR_CALIBRATION_MISSING")
    image_rows = camera.get("images")
    if (
        camera.get("count") != profile.sequence_count
        or camera.get("source_indices_inclusive") != [0, profile.sequence_count - 1]
        or not isinstance(image_rows, list)
        or len(image_rows) != profile.sequence_count
    ):
        raise ContractError("CONVERSION_MANIFEST_CAMERA_ROWS_MISMATCH")

    rgb_hash = sha256_file(root / "rgb.txt")
    if camera.get("rgb_txt", {}).get("sha256") != rgb_hash:
        raise ContractError("CONVERSION_MANIFEST_RGB_TXT_SHA256_MISMATCH")
    calibration_path = root / "calibration.yaml"
    calibration_hash = sha256_file(calibration_path)
    if calibration.get("output_sha256") != calibration_hash:
        raise ContractError("CONVERSION_MANIFEST_CALIBRATION_SHA256_MISMATCH")

    frames: List[Frame] = []
    tree_rows: List[Tuple[str, str]] = [
        ("rgb.txt", rgb_hash),
        ("calibration.yaml", calibration_hash),
    ]
    expected_pngs = set()
    for index, ((stamp, _stamp_text, relative), row) in enumerate(zip(rows, image_rows)):
        if not isinstance(row, dict):
            raise ContractError("CONVERSION_MANIFEST_IMAGE_ROW_NOT_OBJECT:%d" % index)
        path = root / relative
        _regular_file(path, "RGB_IMAGE:%d" % index)
        digest = sha256_file(path)
        size = path.stat().st_size
        expected_reused = index < profile.prefix_reuse_count
        expected = {
            "source_index": index,
            "raw_header_ns": stamp,
            "record_ns": stamp,
            "relative_path": relative,
            "png_sha256": digest,
            "png_size_bytes": size,
            "pixel_identity_verified": True,
            "reused_from_prefix": expected_reused,
        }
        for key, value in expected.items():
            if row.get(key) != value:
                raise ContractError(
                    "CONVERSION_MANIFEST_IMAGE_%s_MISMATCH:%d" % (key.upper(), index)
                )
        frames.append(Frame(index, stamp, relative, path, digest, size))
        tree_rows.append((relative, digest))
        expected_pngs.add(path.name)

    entries = list((root / "rgb").iterdir())
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise ContractError("RGB_DIRECTORY_HAS_SYMLINK_OR_NONFILE_ENTRY")
    actual_pngs = {path.name for path in entries if path.name.endswith(".png")}
    if actual_pngs != expected_pngs:
        raise ContractError("RGB_PNG_FILE_SET_MISMATCH")
    archives = [path for path in entries if path.name.endswith(".png.r2d2")]
    if archives:
        raise ContractError("R2D2_ARCHIVE_ALREADY_EXISTS:%s" % archives[0])
    if any(not path.name.endswith(".png") for path in entries):
        raise ContractError("RGB_DIRECTORY_HAS_EXTRA_FILE")
    if manifest.get("payload_tree_sha256_excluding_manifest") != _aggregate_rows(
        sorted(tree_rows)
    ):
        raise ContractError("CONVERSION_MANIFEST_PAYLOAD_TREE_SHA256_MISMATCH")
    expected_identity_record = materializer._sequence_identity_record(manifest, image_rows)
    identity = manifest.get("sequence_identity")
    if (
        not isinstance(identity, dict)
        or identity.get("schema") != materializer.EXPORT_SEQUENCE_IDENTITY_SCHEMA
        or identity.get("record") != expected_identity_record
        or identity.get("sha256")
        != sha256_bytes(canonical_json(expected_identity_record).encode("utf-8"))
    ):
        raise ContractError("CONVERSION_MANIFEST_SEQUENCE_IDENTITY_MISMATCH")
    return tuple(frames)


def _probe_program() -> str:
    modules = repr(RUNTIME_MODULES)
    return r'''
import hashlib, importlib, importlib.metadata, json, os, pathlib, platform, sys

MODULES = %s

def binding(path):
    p = pathlib.Path(path).resolve()
    h = hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return {'path': str(p), 'sha256': h.hexdigest(), 'size_bytes': p.stat().st_size}

loaded = {}
objects = {}
for label, (module_name, distribution_name) in MODULES.items():
    module = importlib.import_module(module_name)
    objects[label] = module
    module_file = getattr(module, '__file__', None)
    if not module_file:
        raise RuntimeError('module has no file: ' + label)
    try:
        version = importlib.metadata.version(distribution_name)
    except importlib.metadata.PackageNotFoundError:
        version = getattr(module, '__version__', None)
    if not isinstance(version, str) or not version:
        raise RuntimeError('module has no version: ' + label)
    loaded[label] = {'version': version, 'module_file': binding(module_file)}

torch = objects['torch']
result = {
    'schema': 'anyfeature-r2d2-runtime-probe-v1',
    'python_version': platform.python_version(),
    'python_implementation': platform.python_implementation(),
    'python_executable': binding(sys.executable),
    'sys_prefix': str(pathlib.Path(sys.prefix).resolve()),
    'sys_base_prefix': str(pathlib.Path(sys.base_prefix).resolve()),
    'sys_path': list(sys.path),
    'cpu': platform.processor() or platform.machine() or 'unknown-cpu',
    'platform': platform.platform(),
    'byteorder': sys.byteorder,
    'modules': loaded,
    'torch_status': {
        'cuda_available': bool(torch.cuda.is_available()),
        'compiled_cuda': getattr(torch.version, 'cuda', None),
        'device_count': int(torch.cuda.device_count()),
        'num_threads': int(torch.get_num_threads()),
        'num_interop_threads': int(torch.get_num_interop_threads()),
    },
    'selected_environment': {
        key: os.environ.get(key)
        for key in (%s)
    },
}
print(json.dumps(result, sort_keys=True, allow_nan=False))
''' % (modules, repr(RUNTIME_ENVIRONMENT_KEYS))


def default_runtime_provider(
    python_executable: Path, cwd: Path, environment: Mapping[str, str]
) -> RuntimeSeal:
    probe = subprocess.run(
        [str(python_executable), "-c", _probe_program()],
        cwd=str(cwd),
        env=dict(environment),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if probe.returncode != 0:
        raise ContractError(
            "RUNTIME_PROBE_FAILED:%s"
            % probe.stderr.decode("utf-8", "replace").strip()
        )
    try:
        value = json.loads(probe.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("RUNTIME_PROBE_INVALID_JSON") from exc
    freeze = subprocess.run(
        [str(python_executable), "-m", "pip", "freeze", "--all"],
        cwd=str(cwd),
        env=dict(environment),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if freeze.returncode != 0:
        raise ContractError(
            "PIP_FREEZE_FAILED:%s"
            % freeze.stderr.decode("utf-8", "replace").strip()
        )
    return RuntimeSeal(value, freeze.stdout, probe.stderr + freeze.stderr)


def validate_runtime_seal(
    seal: RuntimeSeal,
    python_executable: Path,
    environment: Mapping[str, str],
) -> Dict[str, Any]:
    probe = dict(seal.probe)
    if probe.get("schema") != "anyfeature-r2d2-runtime-probe-v1":
        raise ContractError("RUNTIME_PROBE_SCHEMA_MISMATCH")
    if probe.get("byteorder") != "little":
        raise ContractError("RUNTIME_PROBE_BYTEORDER_NOT_LITTLE")
    expected_python = file_binding(python_executable.resolve(), "PYTHON_EXECUTABLE")
    if probe.get("python_executable") != expected_python:
        raise ContractError("RUNTIME_PYTHON_EXECUTABLE_MISMATCH")
    if not isinstance(probe.get("python_version"), str) or not probe.get("python_version"):
        raise ContractError("RUNTIME_PYTHON_VERSION_MISSING")
    if not isinstance(probe.get("sys_prefix"), str) or not probe.get("sys_prefix"):
        raise ContractError("RUNTIME_SYS_PREFIX_MISSING")
    if not isinstance(probe.get("sys_path"), list) or not all(
        isinstance(item, str) for item in probe.get("sys_path", [])
    ):
        raise ContractError("RUNTIME_SYS_PATH_INVALID")
    if not isinstance(probe.get("cpu"), str) or not probe.get("cpu"):
        raise ContractError("RUNTIME_CPU_IDENTITY_MISSING")
    status = probe.get("torch_status")
    if (
        not isinstance(status, dict)
        or status.get("cuda_available") is not False
        or status.get("compiled_cuda") is not None
        or status.get("device_count") != 0
        or status.get("num_threads") != CPU_INTRAOP_THREADS
        or status.get("num_interop_threads") != CPU_INTEROP_THREADS
    ):
        raise ContractError("RUNTIME_TORCH_NOT_CPU_ONLY")
    modules = probe.get("modules")
    if not isinstance(modules, dict) or set(modules) != set(RUNTIME_MODULES):
        raise ContractError("RUNTIME_MODULE_SET_MISMATCH")
    for label, row in modules.items():
        if not isinstance(row, dict) or not isinstance(row.get("version"), str):
            raise ContractError("RUNTIME_MODULE_IDENTITY_INVALID:%s" % label)
        binding = row.get("module_file")
        if not isinstance(binding, dict):
            raise ContractError("RUNTIME_MODULE_BINDING_MISSING:%s" % label)
        observed = file_binding(Path(str(binding.get("path"))), "RUNTIME_MODULE:%s" % label)
        if binding != observed:
            raise ContractError("RUNTIME_MODULE_HASH_DRIFT:%s" % label)
    selected = probe.get("selected_environment")
    if not isinstance(selected, dict):
        raise ContractError("RUNTIME_SELECTED_ENVIRONMENT_MISSING")
    for key in RUNTIME_ENVIRONMENT_KEYS:
        if selected.get(key) != environment.get(key):
            raise ContractError("RUNTIME_ENVIRONMENT_MISMATCH:%s" % key)
    fingerprint_record = {
        "python_version": probe["python_version"],
        "python_implementation": probe.get("python_implementation"),
        "python_executable": expected_python,
        "sys_prefix": probe["sys_prefix"],
        "sys_base_prefix": probe.get("sys_base_prefix"),
        "sys_path": probe["sys_path"],
        "modules": modules,
        "torch_status": status,
        "pip_freeze_sha256": sha256_bytes(seal.pip_freeze),
        "selected_environment": selected,
    }
    return {
        **probe,
        "python_executable": expected_python,
        "pip_freeze_sha256": sha256_bytes(seal.pip_freeze),
        "fingerprint_record": fingerprint_record,
        "fingerprint_sha256": sha256_bytes(
            canonical_json(fingerprint_record).encode("utf-8")
        ),
    }


def _assert_runtime_unchanged(before: Mapping[str, Any], after: Mapping[str, Any]) -> None:
    if before.get("fingerprint_sha256") != after.get("fingerprint_sha256"):
        raise ProcessFailure("RUNTIME_ENVIRONMENT_HASH_DRIFT_AFTER_PROCESS")


def build_environment(config: RunConfig) -> Dict[str, str]:
    result = dict(os.environ)
    if config.enforce_cache_contract:
        for key in REQUIRED_CACHE_VARIABLES:
            value = result.get(key)
            if not value:
                raise ContractError("CACHE_VARIABLE_MISSING:%s" % key)
            path = Path(value)
            if not path.is_absolute():
                raise ContractError("CACHE_VARIABLE_NOT_ABSOLUTE:%s" % key)
            resolved = path.resolve()
            try:
                resolved.relative_to(FORMAL_CACHE_ROOT.resolve())
            except ValueError as exc:
                raise ContractError("CACHE_VARIABLE_OUTSIDE_FORMAL_ROOT:%s" % key) from exc
    _regular_directory(RUNTIME_HOOK_DIRECTORY, "RUNTIME_CPU_HOOK_DIRECTORY")
    hook_entries = list(RUNTIME_HOOK_DIRECTORY.iterdir())
    if (
        len(hook_entries) != 1
        or hook_entries[0] != RUNTIME_HOOK
        or hook_entries[0].is_symlink()
    ):
        raise ContractError("RUNTIME_CPU_HOOK_DIRECTORY_NOT_SEALED")
    file_binding(RUNTIME_HOOK.resolve(), "RUNTIME_CPU_HOOK")
    for key, value in EXECUTION_ENVIRONMENT.items():
        result[key] = value
    return result


def canonical_flags(checkpoint: Path, image_list: Path) -> Dict[str, Any]:
    return {
        **materializer.R2D2_FORMAL_FLAGS,
        "model": str(checkpoint),
        "images": str(image_list),
    }


def canonical_argv(
    python_executable: Path, extract_py: Path, checkpoint: Path, image_list: Path
) -> List[str]:
    argv = materializer.canonical_formal_r2d2_argv(
        python_executable, extract_py, checkpoint, image_list
    )
    expected_pairs = {
        "--model": str(checkpoint),
        "--images": str(image_list),
        "--tag": "r2d2",
        "--top-k": "5000",
        "--scale-f": "1.189207115002721",
        "--min-size": "256",
        "--max-size": "1024",
        "--min-scale": "0",
        "--max-scale": "1",
        "--reliability-thr": "0.7",
        "--repeatability-thr": "0.7",
        "--gpu": "-1",
    }
    if argv[:2] != [str(python_executable), str(extract_py)]:
        raise ContractError("CANONICAL_ARGV_PREFIX_MISMATCH")
    if len(argv) != 2 + 2 * len(expected_pairs):
        raise ContractError("CANONICAL_ARGV_LENGTH_MISMATCH")
    observed = dict(zip(argv[2::2], argv[3::2]))
    if observed != expected_pairs or len(observed) != len(expected_pairs):
        raise ContractError("CANONICAL_ARGV_SEMANTICS_MISMATCH")
    return argv


def _hash_text_lines(lines: Sequence[str]) -> str:
    return sha256_bytes(("\n".join(lines) + "\n").encode("utf-8"))


def default_process_executor(
    argv: Sequence[str],
    cwd: Path,
    environment: Mapping[str, str],
    stdout_path: Path,
    stderr_path: Path,
    frames: Sequence[Frame],
) -> ProcessObservation:
    start_utc = _utc_now()
    start = time.monotonic()
    observed: Dict[int, float] = {}
    stop_event = threading.Event()

    def watch() -> None:
        while not stop_event.is_set():
            now = time.monotonic() - start
            for frame in frames:
                if frame.source_index not in observed and frame.archive_path.is_file():
                    observed[frame.source_index] = now
            stop_event.wait(0.02)

    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        watcher = threading.Thread(target=watch, name="r2d2-archive-watch", daemon=True)
        watcher.start()
        try:
            process = subprocess.Popen(
                list(argv),
                cwd=str(cwd),
                env=dict(environment),
                stdout=stdout,
                stderr=stderr,
            )
            return_code = process.wait()
        finally:
            stop_event.set()
            watcher.join(timeout=2.0)
    elapsed = time.monotonic() - start
    for frame in frames:
        if frame.archive_path.is_file() and frame.source_index not in observed:
            observed[frame.source_index] = elapsed
    rows: List[Mapping[str, Any]] = []
    previous = 0.0
    for frame in frames:
        completion = observed.get(frame.source_index)
        rows.append(
            {
                "source_index": frame.source_index,
                "image_relative": frame.image_relative,
                "archive_first_observed_elapsed_seconds": completion,
                "inter_completion_seconds": (
                    None if completion is None else max(0.0, completion - previous)
                ),
            }
        )
        if completion is not None:
            previous = completion
    return ProcessObservation(
        return_code,
        start_utc,
        _utc_now(),
        elapsed,
        tuple(rows),
    )


def archive_schema(frame: Frame) -> Dict[str, Any]:
    features = materializer.load_frame_features(frame.archive_path)
    with np.load(str(frame.archive_path), allow_pickle=False) as archive:
        if set(archive.files) != set(materializer.REQUIRED_ARCHIVE_FIELDS):
            raise ProcessFailure("ARCHIVE_FIELD_SET_MISMATCH:%d" % frame.source_index)
        imsize = np.asarray(archive["imsize"])
    arrays = {
        "keypoints": features.keypoints,
        "descriptors": features.descriptors,
        "scores": features.scores,
    }
    schema: Dict[str, Any] = {
        "fields": list(materializer.REQUIRED_ARCHIVE_FIELDS),
        "imsize": {
            "value": [int(value) for value in imsize.tolist()],
            "shape": list(imsize.shape),
            "dtype": imsize.dtype.str,
        },
        "N": features.count,
    }
    for name, array in arrays.items():
        schema[name] = {
            "shape": list(array.shape),
            "dtype": array.dtype.str,
            "c_contiguous": bool(array.flags.c_contiguous),
            "logical_c_order_sha256": sha256_bytes(array.tobytes(order="C")),
            "finite": bool(np.isfinite(array).all()),
        }
    return schema


def audit_archives(frames: Sequence[Frame]) -> List[Dict[str, Any]]:
    expected = {frame.archive_path.name for frame in frames}
    if not frames:
        raise ProcessFailure("NO_INFERENCE_FRAMES")
    rgb_dir = frames[0].archive_path.parent
    actual = {path.name for path in rgb_dir.iterdir() if path.name.endswith(".png.r2d2")}
    if actual != expected:
        raise ProcessFailure("ARCHIVE_FILE_SET_MISMATCH")
    result: List[Dict[str, Any]] = []
    for frame in frames:
        _regular_file(frame.archive_path, "R2D2_ARCHIVE:%d" % frame.source_index)
        result.append(
            {
                "source_index": frame.source_index,
                "image_relative": frame.image_relative,
                "image_sha256": frame.image_sha256,
                "archive_relative": frame.archive_relative,
                "sha256": sha256_file(frame.archive_path),
                "size_bytes": frame.archive_path.stat().st_size,
                "schema": archive_schema(frame),
            }
        )
    return result


def _cleanup_archives(frames: Sequence[Frame]) -> Dict[str, Any]:
    removed: List[str] = []
    errors: List[str] = []
    for frame in frames:
        path = frame.archive_path
        if path.is_symlink():
            errors.append("SYMLINK_NOT_REMOVED:%s" % path)
            continue
        if path.exists():
            if path.is_file():
                try:
                    path.unlink()
                    removed.append(frame.archive_relative)
                except OSError as exc:
                    errors.append("REMOVE_FAILED:%s:%s" % (path, exc))
            else:
                errors.append("NONFILE_NOT_REMOVED:%s" % path)
    return {"removed": removed, "errors": errors, "complete": not errors}


def _images_binding(frames: Sequence[Frame]) -> List[Dict[str, Any]]:
    return [
        {
            "source_index": frame.source_index,
            "timestamp_ns": frame.timestamp_ns,
            "relative_path": frame.image_relative,
            "sha256": frame.image_sha256,
            "size_bytes": frame.image_size_bytes,
        }
        for frame in frames
    ]


def _revalidate_images(frames: Sequence[Frame]) -> None:
    for frame in frames:
        _regular_file(frame.image_path, "RGB_IMAGE_POST:%d" % frame.source_index)
        if (
            frame.image_path.stat().st_size != frame.image_size_bytes
            or sha256_file(frame.image_path) != frame.image_sha256
        ):
            raise ProcessFailure("RGB_IMAGE_HASH_DRIFT_AFTER_PROCESS:%d" % frame.source_index)


def _load_prefix_binding(config: RunConfig, frames: Sequence[Frame]) -> Optional[Dict[str, Any]]:
    profile = config.profile
    if profile.prefix_reuse_count == 0:
        if config.prefix_sequence_root is not None:
            raise ContractError("PREFIX_ROOT_FORBIDDEN_FOR_PREFIX_RUN")
        return None
    if config.prefix_sequence_root is None:
        raise ContractError("PREFIX_SEQUENCE_ROOT_REQUIRED")
    prefix_root = _canonical_absolute(config.prefix_sequence_root, "PREFIX_SEQUENCE_ROOT")
    manifest_path = prefix_root / materializer.PRODUCER_RUN_MANIFEST_NAME
    _regular_file(manifest_path, "PREFIX_PRODUCER_RUN_MANIFEST")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("PREFIX_PRODUCER_RUN_MANIFEST_INVALID_JSON") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != RUNNER_SCHEMA
        or manifest.get("status") != STATUS_COMPLETED
        or manifest.get("run_profile", {}).get("name") != "a02-prefix200"
    ):
        raise ContractError("PREFIX_PRODUCER_RUN_MANIFEST_IDENTITY_MISMATCH")
    archives = manifest.get("archives")
    images = manifest.get("images")
    expected_indices = list(range(profile.prefix_reuse_count))
    if (
        not isinstance(archives, list)
        or [row.get("source_index") for row in archives] != expected_indices
        or not isinstance(images, list)
        or [row.get("source_index") for row in images] != expected_indices
    ):
        raise ContractError("PREFIX_PRODUCER_RUN_INDEX_SET_MISMATCH")
    for index, row in enumerate(images):
        frame = frames[index]
        if (
            row.get("relative_path") != frame.image_relative
            or row.get("sha256") != frame.image_sha256
            or row.get("size_bytes") != frame.image_size_bytes
        ):
            raise ContractError("PREFIX_FULL_PNG_BYTE_IDENTITY_MISMATCH:%d" % index)
    return {
        "path": str(prefix_root),
        "manifest": str(manifest_path.resolve()),
        "manifest_sha256": sha256_file(manifest_path),
        "manifest_value": manifest,
        "reused_indices_inclusive": [0, profile.prefix_reuse_count - 1],
        "inference_repeated": False,
    }


def _validate_prefix_runtime_and_identity(
    prefix: Optional[Mapping[str, Any]],
    runtime: Mapping[str, Any],
    static: Mapping[str, Any],
) -> None:
    if prefix is None:
        return
    manifest = prefix["manifest_value"]
    if manifest.get("runtime", {}).get("fingerprint_sha256") != runtime.get(
        "fingerprint_sha256"
    ):
        raise ContractError("FULL_RUNTIME_DIFFERS_FROM_PREFIX")
    if manifest.get("producer") != static.get("producer"):
        raise ContractError("FULL_PRODUCER_IDENTITY_DIFFERS_FROM_PREFIX")
    if manifest.get("checkpoint") != static.get("checkpoint"):
        raise ContractError("FULL_CHECKPOINT_DIFFERS_FROM_PREFIX")
    prefix_flags = manifest.get("invocation", {}).get("flags")
    if not isinstance(prefix_flags, dict):
        raise ContractError("PREFIX_FLAGS_MISSING")
    for key, value in materializer.R2D2_FORMAL_FLAGS.items():
        if prefix_flags.get(key) != value:
            raise ContractError("FULL_FLAGS_DIFFER_FROM_PREFIX:%s" % key)


def _ensure_formal_paths(config: RunConfig) -> None:
    if not config.formal_paths:
        return
    expected_root = (
        PREFIX_SEQUENCE_ROOT
        if config.profile.name == "a02-prefix200"
        else FULL_SEQUENCE_ROOT
    )
    if config.sequence_root != expected_root:
        raise ContractError("FORMAL_SEQUENCE_ROOT_MISMATCH")
    if config.r2d2_repo != R2D2_REPO or config.checkpoint != R2D2_CHECKPOINT:
        raise ContractError("FORMAL_R2D2_PATH_MISMATCH")
    if config.anyfeature_repo != ANYFEATURE_REPO:
        raise ContractError("FORMAL_ANYFEATURE_PATH_MISMATCH")
    if config.profile.prefix_reuse_count:
        if config.prefix_sequence_root != PREFIX_SEQUENCE_ROOT:
            raise ContractError("FORMAL_PREFIX_SEQUENCE_ROOT_MISMATCH")


def _no_clobber(config: RunConfig, frames: Sequence[Frame]) -> Tuple[Path, Path]:
    manifest_path = config.sequence_root / materializer.PRODUCER_RUN_MANIFEST_NAME
    evidence = config.sequence_root / "producer_evidence"
    for path in (manifest_path, evidence):
        if path.exists() or path.is_symlink():
            raise ContractError("OUTPUT_ALREADY_EXISTS:%s" % path)
    for frame in frames:
        if frame.archive_path.exists() or frame.archive_path.is_symlink():
            raise ContractError("OUTPUT_ALREADY_EXISTS:%s" % frame.archive_path)
    return manifest_path, evidence


def _process_block(
    observation: ProcessObservation, stdout: Path, stderr: Path
) -> Dict[str, Any]:
    return {
        "return_code": observation.return_code,
        "stdout": file_binding(stdout.resolve(), "STDOUT"),
        "stderr": file_binding(stderr.resolve(), "STDERR"),
        "timing": {
            "start_utc": observation.start_utc,
            "end_utc": observation.end_utc,
            "elapsed_seconds": observation.elapsed_seconds,
            "per_image": list(observation.archive_observations),
            "per_image_semantics": (
                "wall-clock archive first-observation offsets; inter-completion is "
                "reported separately from AnyFeature tracking time"
            ),
        },
    }


def run_producer(
    config: RunConfig,
    runtime_provider: RuntimeProvider = default_runtime_provider,
    process_executor: ProcessExecutor = default_process_executor,
    static_identity_provider: Callable[[RunConfig], Mapping[str, Any]] = capture_static_identity,
) -> RunResult:
    _ensure_formal_paths(config)
    frames_all = load_sequence_contract(config)
    frames = tuple(frames_all[index] for index in config.profile.inference_indices)
    manifest_path, evidence = _no_clobber(config, frames)
    static_before = dict(static_identity_provider(config))
    python_executable, interpreter_materialization = prepare_python_executable(config)
    environment = build_environment(config)
    prefix = _load_prefix_binding(config, frames_all)

    try:
        evidence.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise ContractError("OUTPUT_ALREADY_EXISTS:%s" % evidence) from exc
    image_list_path = evidence / "images.txt"
    stdout_path = evidence / "stdout.log"
    stderr_path = evidence / "stderr.log"
    before_probe_path = evidence / "runtime_probe.before.json"
    after_probe_path = evidence / "runtime_probe.after.json"
    before_freeze_path = evidence / "pip-freeze.before.txt"
    after_freeze_path = evidence / "pip-freeze.after.txt"
    probe_stderr_path = evidence / "runtime_probe.stderr.log"
    started = False
    observation: Optional[ProcessObservation] = None
    try:
        entries = [frame.image_relative for frame in frames]
        _exclusive_write(image_list_path, ("\n".join(entries) + "\n").encode("utf-8"))
        before_seal = runtime_provider(python_executable, config.sequence_root, environment)
        runtime_before = validate_runtime_seal(
            before_seal, python_executable, environment
        )
        if config.formal_paths and runtime_before.get("sys_prefix") != str(
            R2D2_PYTHON_SYMLINK.parent.parent.resolve()
        ):
            raise ContractError("FORMAL_PYTHON_SYS_PREFIX_MISMATCH")
        _validate_prefix_runtime_and_identity(prefix, runtime_before, static_before)
        _exclusive_write(
            before_probe_path, canonical_json(runtime_before).encode("utf-8")
        )
        _exclusive_write(before_freeze_path, before_seal.pip_freeze)
        _exclusive_write(probe_stderr_path, before_seal.probe_stderr)

        extract_py = Path(static_before["producer"]["extract_py"]["path"])
        checkpoint = Path(static_before["checkpoint"]["path"])
        argv = canonical_argv(
            python_executable, extract_py, checkpoint, image_list_path.resolve()
        )
        flags = canonical_flags(checkpoint, image_list_path.resolve())
        started = True
        try:
            observation = process_executor(
                argv,
                config.sequence_root,
                environment,
                stdout_path,
                stderr_path,
                frames,
            )
        except Exception as exc:
            if not stdout_path.exists():
                _exclusive_write(stdout_path, b"")
            if not stderr_path.exists():
                _exclusive_write(
                    stderr_path,
                    ("PROCESS_EXECUTOR_EXCEPTION:%s:%s\n" % (type(exc).__name__, exc)).encode(
                        "utf-8", "replace"
                    ),
                )
            observation = ProcessObservation(
                127,
                _utc_now(),
                _utc_now(),
                0.0,
                tuple(),
            )
            raise ProcessFailure("OFFICIAL_PROCESS_EXECUTOR_EXCEPTION") from exc

        if observation.return_code != 0:
            raise ProcessFailure(
                "OFFICIAL_R2D2_RETURN_CODE_NONZERO:%d" % observation.return_code
            )
        try:
            archives = audit_archives(frames)
            _revalidate_images(frames_all)
            static_after = dict(static_identity_provider(config))
            _assert_static_identity_unchanged(static_before, static_after)
            after_seal = runtime_provider(
                python_executable, config.sequence_root, environment
            )
            runtime_after = validate_runtime_seal(
                after_seal, python_executable, environment
            )
            _assert_runtime_unchanged(runtime_before, runtime_after)
            _exclusive_write(
                after_probe_path, canonical_json(runtime_after).encode("utf-8")
            )
            _exclusive_write(after_freeze_path, after_seal.pip_freeze)
        except ProcessFailure:
            raise
        except (ContractError, materializer.ContractError, OSError, ValueError) as exc:
            raise ProcessFailure(
                "POST_PROCESS_DATA_OR_IDENTITY_CONTRACT:%s" % exc
            ) from exc

        image_list_binding = file_binding(image_list_path.resolve(), "IMAGE_LIST")
        image_list_binding.update({"count": len(entries), "entries": entries})
        invocation = {
            "working_directory": str(config.sequence_root.resolve()),
            "argv": argv,
            "argv_sha256": _hash_text_lines(argv),
            "flags": flags,
            "flags_sha256": sha256_bytes(canonical_json(flags).encode("utf-8")),
            "tag": "r2d2",
            "image_list": image_list_binding,
            "environment": {
                "execution": {
                    key: environment[key] for key in EXECUTION_ENVIRONMENT
                },
                "cache_variables": {
                    key: environment.get(key) for key in REQUIRED_CACHE_VARIABLES
                },
                "runtime_cpu_hook": file_binding(
                    RUNTIME_HOOK.resolve(), "RUNTIME_CPU_HOOK"
                ),
            },
        }
        runtime_manifest = {
            **runtime_before,
            "environment_lock": file_binding(
                before_freeze_path.resolve(), "ENVIRONMENT_LOCK"
            ),
            "pip_freeze": file_binding(
                before_freeze_path.resolve(), "PIP_FREEZE"
            ),
            "probe_before": file_binding(
                before_probe_path.resolve(), "RUNTIME_PROBE_BEFORE"
            ),
            "probe_after": file_binding(
                after_probe_path.resolve(), "RUNTIME_PROBE_AFTER"
            ),
            "pip_freeze_after": file_binding(
                after_freeze_path.resolve(), "PIP_FREEZE_AFTER"
            ),
            "probe_stderr": file_binding(
                probe_stderr_path.resolve(), "RUNTIME_PROBE_STDERR"
            ),
            "cpu_only_verified": True,
            "pre_post_identity_equal": True,
            "interpreter_materialization": interpreter_materialization,
        }
        manifest: Dict[str, Any] = {
            "schema": RUNNER_SCHEMA,
            "status": STATUS_COMPLETED,
            "runner": runner_identity(),
            "run_profile": {
                "name": config.profile.name,
                "sequence_profile": config.profile.sequence_profile,
                "sequence_count": config.profile.sequence_count,
                "inference_indices_inclusive": [
                    config.profile.inference_start,
                    config.profile.inference_stop,
                ],
                "inference_count": config.profile.inference_count,
                "prefix_reuse_count": config.profile.prefix_reuse_count,
            },
            "producer": static_before["producer"],
            "checkpoint": static_before["checkpoint"],
            "author_integration_context": static_before[
                "author_integration_context"
            ],
            "runtime": runtime_manifest,
            "invocation": invocation,
            "process": _process_block(observation, stdout_path, stderr_path),
            "images": _images_binding(frames),
            "archives": archives,
            "continuation": (
                None
                if prefix is None
                else {
                    key: value
                    for key, value in prefix.items()
                    if key != "manifest_value"
                }
            ),
            "claims": {
                "official_extract_py_executed": True,
                "cpu_only": True,
                "upstream_source_modified": False,
                "threshold_or_checkpoint_search": False,
                "prefix_inference_repeated": False,
                "anyfeature_slam_started": False,
            },
        }
        _exclusive_manifest(manifest_path, manifest)
        return RunResult(RC_COMPLETED, manifest)
    except ContractError:
        if not started:
            shutil.rmtree(evidence, ignore_errors=True)
        raise
    except ProcessFailure as exc:
        cleanup = _cleanup_archives(frames)
        if observation is None:
            observation = ProcessObservation(127, _utc_now(), _utc_now(), 0.0, tuple())
        if not stdout_path.exists():
            _exclusive_write(stdout_path, b"")
        if not stderr_path.exists():
            _exclusive_write(stderr_path, (str(exc) + "\n").encode("utf-8"))
        failed_entries = [frame.image_relative for frame in frames]
        failed_image_list_binding = file_binding(
            image_list_path.resolve(), "FAILED_IMAGE_LIST"
        )
        failed_image_list_binding.update(
            {"count": len(failed_entries), "entries": failed_entries}
        )
        failed_runtime = {
            **runtime_before,
            "environment_lock": file_binding(
                before_freeze_path.resolve(), "FAILED_ENVIRONMENT_LOCK"
            ),
            "pip_freeze": file_binding(
                before_freeze_path.resolve(), "FAILED_PIP_FREEZE"
            ),
            "probe_before": file_binding(
                before_probe_path.resolve(), "FAILED_RUNTIME_PROBE_BEFORE"
            ),
            "interpreter_materialization": interpreter_materialization,
            "cpu_only_verified_before_process": True,
        }
        failed_invocation = {
            "working_directory": str(config.sequence_root.resolve()),
            "argv": argv,
            "argv_sha256": _hash_text_lines(argv),
            "flags": flags,
            "flags_sha256": sha256_bytes(canonical_json(flags).encode("utf-8")),
            "tag": "r2d2",
            "image_list": failed_image_list_binding,
            "environment": {
                "execution": {
                    key: environment[key] for key in EXECUTION_ENVIRONMENT
                },
                "cache_variables": {
                    key: environment.get(key) for key in REQUIRED_CACHE_VARIABLES
                },
                "runtime_cpu_hook": file_binding(
                    RUNTIME_HOOK.resolve(), "FAILED_RUNTIME_CPU_HOOK"
                ),
            },
        }
        failure: Dict[str, Any] = {
            "schema": RUNNER_SCHEMA,
            "status": STATUS_FAILED,
            "runner": runner_identity(),
            "run_profile": {
                "name": config.profile.name,
                "sequence_profile": config.profile.sequence_profile,
                "sequence_count": config.profile.sequence_count,
                "inference_indices_inclusive": [
                    config.profile.inference_start,
                    config.profile.inference_stop,
                ],
                "inference_count": config.profile.inference_count,
                "prefix_reuse_count": config.profile.prefix_reuse_count,
            },
            "producer": static_before["producer"],
            "checkpoint": static_before["checkpoint"],
            "author_integration_context": static_before[
                "author_integration_context"
            ],
            "runtime": failed_runtime,
            "invocation": failed_invocation,
            "process": _process_block(observation, stdout_path, stderr_path),
            "failure": {"reason": str(exc), "archive_cleanup": cleanup},
            "images": _images_binding(frames),
            "archives": [],
            "continuation": (
                None
                if prefix is None
                else {
                    key: value
                    for key, value in prefix.items()
                    if key != "manifest_value"
                }
            ),
            "claims": {
                "official_extract_py_executed": started,
                "output_archives_retained": False,
                "upstream_source_modified": False,
                "anyfeature_slam_started": False,
            },
        }
        _exclusive_manifest(manifest_path, failure)
        return RunResult(RC_PROCESS_FAILED, failure)
    except Exception:
        if not started:
            shutil.rmtree(evidence, ignore_errors=True)
        else:
            _cleanup_archives(frames)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(FORMAL_PROFILES), required=True)
    parser.add_argument("--sequence-root", type=Path)
    parser.add_argument("--prefix-sequence-root", type=Path)
    parser.add_argument("--python-executable", type=Path, default=R2D2_PYTHON)
    parser.add_argument("--r2d2-repo", type=Path, default=R2D2_REPO)
    parser.add_argument("--checkpoint", type=Path, default=R2D2_CHECKPOINT)
    parser.add_argument("--anyfeature-repo", type=Path, default=ANYFEATURE_REPO)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    profile = FORMAL_PROFILES[args.profile]
    sequence_root = args.sequence_root or (
        PREFIX_SEQUENCE_ROOT
        if args.profile == "a02-prefix200"
        else FULL_SEQUENCE_ROOT
    )
    try:
        result = run_producer(
            RunConfig(
                profile=profile,
                sequence_root=sequence_root,
                python_executable=args.python_executable,
                r2d2_repo=args.r2d2_repo,
                checkpoint=args.checkpoint,
                anyfeature_repo=args.anyfeature_repo,
                prefix_sequence_root=args.prefix_sequence_root,
            )
        )
        rendered = {
            "runner_version": RUNNER_VERSION,
            "status": result.manifest["status"],
            "manifest": str(
                sequence_root / materializer.PRODUCER_RUN_MANIFEST_NAME
            ),
            "manifest_sha256": sha256_file(
                sequence_root / materializer.PRODUCER_RUN_MANIFEST_NAME
            ),
            "return_code": result.rc,
        }
        rc = result.rc
    except ContractError as exc:
        rendered = {
            "runner_version": RUNNER_VERSION,
            "status": STATUS_INTEGRITY_ERROR,
            "errors": [str(exc)],
            "return_code": RC_INTEGRITY_ERROR,
            "claims": {
                "official_extract_py_executed": False,
                "anyfeature_slam_started": False,
            },
        }
        rc = RC_INTEGRITY_ERROR
    except Exception as exc:
        rendered = {
            "runner_version": RUNNER_VERSION,
            "status": STATUS_INTEGRITY_ERROR,
            "errors": ["UNEXPECTED_%s:%s" % (type(exc).__name__, exc)],
            "return_code": RC_INTEGRITY_ERROR,
            "claims": {"anyfeature_slam_started": False},
        }
        rc = RC_INTEGRITY_ERROR
    sys.stdout.write(canonical_json(rendered))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
