#!/usr/bin/env python3
"""Fail-closed runner for the frozen RSS-2024 AnyFeature-VSLAM binary.

The formal command line intentionally exposes only a run profile and the two
profile-bound paths.  Feature type, settings, vocabulary, visualization,
resize policy, repository, binary, environment, and experiment id are derived
from the frozen contract and cannot be overridden.

This runner does not decide the preregistered ORB32 -> R2D2 ordering and does
not evaluate accuracy.  The external experiment contract owns ordering and the
pairwise common-support evaluator owns accuracy.  Here, a full run is usable
when the official process returns zero, the startup/argument echoes are exact,
and a nonempty finite keyframe trajectory has strictly increasing timestamps.
The number and span of those keyframes are reported separately and never turn
a syntactically valid sparse trajectory into a process failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    # ``python3 scripts/run_...py`` otherwise exposes only ``scripts/`` as
    # sys.path[0], while the audited adapter is imported as ``scripts.*``.
    sys.path.insert(0, str(WORKSPACE_ROOT))


RUNNER_SCHEMA = "aqua-fe-anyfeature-official-run-v1"
INPUT_SCHEMA = "aqua-fe-anyfeature-official-input-v1"
ARGV_SCHEMA = "aqua-fe-anyfeature-official-argv-v1"
ENVIRONMENT_SCHEMA = "aqua-fe-anyfeature-official-environment-v1"
RUNNER_RELATIVE = "scripts/run_anyfeature_vslam_official_v1.py"

RC_SUCCESS = 0
RC_RUNTIME_OR_USABILITY = 1
RC_CONTRACT = 2

ANYFEATURE_ORIGIN = "https://github.com/alejandrofontan/AnyFeature-VSLAM.git"
ANYFEATURE_COMMIT = "6aa014b724f7a61bcbff2f8f28f20836986a43dc"
ANYFEATURE_TREE = "36b264e1da05c6fe9cd987965e9a75ba96930b63"
DBOW2_COMMIT = "f4d585b45237836dbde757c0c8ec8b098ad1164a"

REPO = Path("/mnt/data/SLAM/AnyFeature-VSLAM-paper-2024-r3")
RUNTIME_ROOT = Path("/mnt/data/opt/anyfeature-paper-2024-r3")
BINARY = REPO / "bin/mono"
CORE_LIBRARY = REPO / "lib/libAnyFeature-VSLAM.so"
DBOW2_LIBRARY = REPO / "Thirdparty/DBoW2/lib/libDBoW2.so"
ENV_EXPLICIT_LOCK = RUNTIME_ROOT / "evidence/anyfeature_env_explicit.txt"
PROVISIONING_RESULT = (
    Path(__file__).resolve().parents[1]
    / "papers/anyfeature_vslam_provisioning_r3_result.json"
)
PREREGISTRATION = (
    Path(__file__).resolve().parents[1]
    / "papers/anyfeature_vslam_r2d2_a02_preregistration.md"
)
VOCABULARY_FOLDER = Path(
    "/mnt/data/opt/anyfeature-paper-2024-r1/vocabulary"
)
PREFIX_SEQUENCE = Path(
    "/mnt/data/AQUA-FE_WS/anyfeature_adapter/"
    "aqualoc_a02_0005_prefix200_r1"
)
SMOKE_SEQUENCE = Path(
    "/mnt/data/AQUA-FE_WS/anyfeature_adapter/"
    "aqualoc_a02_0005_frame000_smoke_view_r1"
)
FULL_SEQUENCE = Path(
    "/mnt/data/AQUA-FE_WS/anyfeature_adapter/"
    "aqualoc_a02_0005_full_r1"
)
SMOKE_EXPERIMENT = Path(
    "/mnt/data/AQUA-FE_WS/published_anyfeature_vslam_v1/"
    "model_smokes/a02_frame000_r1"
)
ORB_EXPERIMENT = Path(
    "/mnt/data/AQUA-FE_WS/published_anyfeature_vslam_v1/"
    "full_runs/a02_orb32_r1"
)
R2D2_EXPERIMENT = Path(
    "/mnt/data/AQUA-FE_WS/published_anyfeature_vslam_v1/"
    "full_runs/a02_r2d2_r1"
)

EXPECTED_BINARY_SHA256 = (
    "9adb623fc8d83ce35297be7a7d810d269cd65273bd0f4fb1bddebbec0b8bdd59"
)
EXPECTED_CORE_LIBRARY_SHA256 = (
    "eea4a5a6c5dccb5825a8e6a1a3249c6b808881a22c7fe301d0a2a90efaa99954"
)
EXPECTED_DBOW2_LIBRARY_SHA256 = (
    "7215c8425e3620834ef24ea17f26fd0635b15d9d85b0093b00220e553a40c8c5"
)
EXPECTED_ENV_LOCK_SHA256 = (
    "12656125f716a449af782fbbde07e49d8a20139e529e3d55c0a6c436c1236d0b"
)
EXPECTED_PREREGISTRATION_SHA256 = (
    "74eb99a57aee660270561850a0b72f288951a80082b9c7a6200ecfed60a3c680"
)
EXPECTED_PROVISIONING_RESULT_SHA256 = (
    "cd74fc9cf16ab89ab02429031901590e9ee347e1197756286a05cb7c9edc3442"
)
EXPECTED_CONFIGS = {
    "orb32": (
        "settings/orb32_settings.yaml",
        "38a19b5f45863f64ee81b3306b3c66b43c4f587712fdda8babaef9b5f04c9647",
    ),
    "r2d2_128": (
        "settings/r2d2_128_settings.yaml",
        "375ae1bdcfe92068a665f16b9943b09fb0c830be471f675ddb85289442526878",
    ),
}
EXPECTED_VOCABS = {
    "ORBvoc.txt": (
        145_250_924,
        "f8dd027f7a6cb88129821341194d7f2c75b77b3394257ddd0d2229863d1a3570",
    ),
    "R2d2_DBoW2_voc.txt": (
        1_393_396_568,
        "b169095f0ef57eaf5e6556db68f9df4eddd56970c35f983c7d00f5d3fa8bce73",
    ),
}
EXPECTED_SOURCE_BAG = Path(
    "/home/ma/AQUA-FE_WS/datasets/aqualoc/rosbags/archaeo02_4500_5400.bag"
)
EXPECTED_SOURCE_BAG_SHA256 = (
    "8cceb4c76065f3862e60428b14ba10f9a26fc7249e11e9e9d090fed2437238a8"
)
EXPECTED_SOURCE_CALIBRATION = Path(
    "/home/ma/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences/archaeo_calibration_files/"
    "archaeo_camera_calib.yaml"
)
EXPECTED_SOURCE_CALIBRATION_SHA256 = (
    "e8ce9ad65d82ae563c676689444abd210f81c362586473c5752ee5f9bf2c32e2"
)
EXPECTED_FIRST_NS = 1_542_829_016_700_435_392
EXPECTED_PREFIX_LAST_NS = 1_542_829_026_649_564_544

RGB_ROW_RE = re.compile(r"^([0-9]+)\.([0-9]{9}) (rgb/([0-9]+)\.png)$")
NUMERIC_NONFINITE_RE = re.compile(
    r"(?<![A-Za-z])(?:nan|[-+]?inf(?:inity)?)(?![A-Za-z])", re.IGNORECASE
)
FATAL_DIAGNOSTICS = (
    ("segmentation_fault", re.compile(r"segmentation fault|core dumped", re.I)),
    ("terminate_or_abort", re.compile(r"terminate called|\baborted\b", re.I)),
    ("uncaught_exception", re.compile(r"uncaught exception|opencv\([^\n]*error", re.I)),
    ("vocabulary_load_failed", re.compile(r"vocabulary loading failed", re.I)),
    (
        "reader_failure",
        re.compile(
            r"(?:(?:failed|failure|unable)\s+to\s+|"
            r"(?:cannot|can't|could\s+not)\s+|error\s+)"
            r"(?:open|opening|read|reading|load|loading)"
            r"[^\n]*(?:r2d2|keypoint|descriptor|score|\.bin|image)",
            re.I,
        ),
    ),
    ("out_of_bounds", re.compile(r"out[- ]of[- ]bounds", re.I)),
)


class ContractError(RuntimeError):
    """Frozen identity, path, input, or no-clobber contract failed."""


@dataclass(frozen=True)
class RunProfile:
    name: str
    sequence_path: Path
    experiment_folder: Path
    feature: str
    frame_count: int
    input_profile: str
    r2d2_required: bool
    smoke_only: bool
    evaluation_eligible: bool
    order_position: int | None


PROFILES: dict[str, RunProfile] = {
    "r2d2-smoke": RunProfile(
        "r2d2-smoke",
        SMOKE_SEQUENCE,
        SMOKE_EXPERIMENT,
        "r2d2_128",
        1,
        "a02-prefix200-index0-smoke-view",
        True,
        True,
        False,
        None,
    ),
    "orb32-full": RunProfile(
        "orb32-full",
        FULL_SEQUENCE,
        ORB_EXPERIMENT,
        "orb32",
        901,
        "a02-full",
        False,
        False,
        True,
        1,
    ),
    "r2d2-full": RunProfile(
        "r2d2-full",
        FULL_SEQUENCE,
        R2D2_EXPERIMENT,
        "r2d2_128",
        901,
        "a02-full",
        True,
        False,
        True,
        2,
    ),
}


@dataclass(frozen=True)
class FrozenAssets:
    repo: Path
    runtime_root: Path
    binary: Path
    core_library: Path
    dbow2_library: Path
    env_lock: Path
    vocabulary_folder: Path
    provisioning_result: Path
    preregistration: Path
    expected_binary_sha256: str
    expected_core_library_sha256: str
    expected_dbow2_library_sha256: str
    expected_env_lock_sha256: str
    expected_configs: Mapping[str, tuple[str, str]]
    expected_vocabs: Mapping[str, tuple[int, str]]
    enforce_git: bool = True


FORMAL_ASSETS = FrozenAssets(
    REPO,
    RUNTIME_ROOT,
    BINARY,
    CORE_LIBRARY,
    DBOW2_LIBRARY,
    ENV_EXPLICIT_LOCK,
    VOCABULARY_FOLDER,
    PROVISIONING_RESULT,
    PREREGISTRATION,
    EXPECTED_BINARY_SHA256,
    EXPECTED_CORE_LIBRARY_SHA256,
    EXPECTED_DBOW2_LIBRARY_SHA256,
    EXPECTED_ENV_LOCK_SHA256,
    EXPECTED_CONFIGS,
    EXPECTED_VOCABS,
)


@dataclass(frozen=True)
class PreflightBundle:
    profile: RunProfile
    assets: FrozenAssets
    official: Mapping[str, Any]
    input_manifest: Mapping[str, Any]
    argv: tuple[str, ...]
    environment: Mapping[str, str]
    ldd_text: str
    preflight_summary: Mapping[str, Any]


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"


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


def aggregate_hash(rows: Sequence[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for relative, file_hash in rows:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def file_binding(path: Path, label: str, expected_hash: str | None = None) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ContractError(f"{label}_MISSING_OR_SYMLINK:{path}")
    digest = sha256_file(path)
    if expected_hash is not None and digest != expected_hash:
        raise ContractError(f"{label}_SHA256_MISMATCH:{digest}")
    return {
        "path": str(path.resolve()),
        "sha256": digest,
        "size_bytes": path.stat().st_size,
    }


def regular_directory(path: Path, label: str) -> None:
    if not path.is_dir() or path.is_symlink():
        raise ContractError(f"{label}_MISSING_OR_SYMLINK:{path}")


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    file_binding(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label}_INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label}_ROOT_NOT_OBJECT")
    return value


def write_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    write_exclusive(path, canonical_json(value).encode("utf-8"))


def runner_identity() -> dict[str, Any]:
    return file_binding(Path(__file__).resolve(), "RUNNER_SCRIPT")


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["/usr/bin/git", "-C", str(repo), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ContractError(
            f"GIT_COMMAND_FAILED:{' '.join(arguments)}:{result.stderr.strip()}"
        )
    return result.stdout.strip()


def _verify_git_source(assets: FrozenAssets) -> dict[str, Any]:
    origin = _git(assets.repo, "remote", "get-url", "origin")
    head = _git(assets.repo, "rev-parse", "HEAD")
    tree = _git(assets.repo, "rev-parse", "HEAD^{tree}")
    gitlink = _git(assets.repo, "rev-parse", "HEAD:Thirdparty/DBoW2")
    submodule = assets.repo / "Thirdparty/DBoW2"
    submodule_head = _git(submodule, "rev-parse", "HEAD")
    if origin != ANYFEATURE_ORIGIN:
        raise ContractError(f"SOURCE_ORIGIN_DRIFT:{origin}")
    if head != ANYFEATURE_COMMIT:
        raise ContractError(f"SOURCE_COMMIT_DRIFT:{head}")
    if tree != ANYFEATURE_TREE:
        raise ContractError(f"SOURCE_TREE_DRIFT:{tree}")
    if gitlink != DBOW2_COMMIT:
        raise ContractError(f"DBOW2_GITLINK_DRIFT:{gitlink}")
    if submodule_head != DBOW2_COMMIT:
        raise ContractError(f"DBOW2_CHECKOUT_DRIFT:{submodule_head}")
    if _git(assets.repo, "diff", "--name-only", "--"):
        raise ContractError("SOURCE_TRACKED_DIFF_NOT_EMPTY")
    if _git(assets.repo, "diff", "--cached", "--name-only", "--"):
        raise ContractError("SOURCE_STAGED_DIFF_NOT_EMPTY")
    if _git(submodule, "diff", "--name-only", "--"):
        raise ContractError("DBOW2_TRACKED_DIFF_NOT_EMPTY")
    if _git(submodule, "diff", "--cached", "--name-only", "--"):
        raise ContractError("DBOW2_STAGED_DIFF_NOT_EMPTY")
    return {
        "origin": origin,
        "commit": head,
        "tree": tree,
        "dbow2_submodule_commit": gitlink,
        "dbow2_checkout_commit": submodule_head,
        "tracked_diff_empty": True,
        "staged_diff_empty": True,
    }


def _verify_provisioning_result(assets: FrozenAssets) -> dict[str, Any]:
    value = load_json_object(assets.provisioning_result, "PROVISIONING_RESULT")
    official = value.get("official_system")
    environment = value.get("environment")
    build = value.get("build")
    link = value.get("runtime_link_gate")
    if not all(isinstance(x, Mapping) for x in (official, environment, build, link)):
        raise ContractError("PROVISIONING_RESULT_REQUIRED_BLOCK_MISSING")
    mono = build.get("mono_binary")  # type: ignore[union-attr]
    expected = {
        "status": "READY_FOR_ADAPTER_AND_MODEL_CLOSURE",
        "commit": ANYFEATURE_COMMIT,
        "tree": ANYFEATURE_TREE,
        "lock": assets.expected_env_lock_sha256,
        "binary": assets.expected_binary_sha256,
    }
    if value.get("status") != expected["status"]:
        raise ContractError("PROVISIONING_RESULT_STATUS_MISMATCH")
    if official.get("commit") != expected["commit"] or official.get("tree") != expected["tree"]:  # type: ignore[union-attr]
        raise ContractError("PROVISIONING_RESULT_SOURCE_IDENTITY_MISMATCH")
    if environment.get("explicit_lock_sha256") != expected["lock"]:  # type: ignore[union-attr]
        raise ContractError("PROVISIONING_RESULT_LOCK_MISMATCH")
    if not isinstance(mono, Mapping) or mono.get("sha256") != expected["binary"]:
        raise ContractError("PROVISIONING_RESULT_BINARY_MISMATCH")
    if link.get("passed") is not True or link.get("not_found_count") != 0:  # type: ignore[union-attr]
        raise ContractError("PROVISIONING_RESULT_LINK_GATE_NOT_PASSED")
    return file_binding(
        assets.provisioning_result,
        "PROVISIONING_RESULT",
        EXPECTED_PROVISIONING_RESULT_SHA256,
    )


def verify_official_assets(profile: RunProfile, assets: FrozenAssets) -> dict[str, Any]:
    regular_directory(assets.repo, "OFFICIAL_REPOSITORY")
    regular_directory(assets.runtime_root, "OFFICIAL_RUNTIME_ROOT")
    regular_directory(assets.vocabulary_folder, "VOCABULARY_FOLDER")
    source_identity: Mapping[str, Any]
    if assets.enforce_git:
        source_identity = _verify_git_source(assets)
    else:
        source_identity = {
            "origin": "synthetic-test-only",
            "commit": "synthetic",
            "tree": "synthetic",
            "dbow2_submodule_commit": "synthetic",
            "tracked_diff_empty": True,
            "staged_diff_empty": True,
        }

    binary = file_binding(
        assets.binary, "OFFICIAL_MONO_BINARY", assets.expected_binary_sha256
    )
    if not os.access(assets.binary, os.X_OK):
        raise ContractError("OFFICIAL_MONO_BINARY_NOT_EXECUTABLE")
    core = file_binding(
        assets.core_library,
        "OFFICIAL_CORE_LIBRARY",
        assets.expected_core_library_sha256,
    )
    dbow2 = file_binding(
        assets.dbow2_library,
        "OFFICIAL_DBOW2_LIBRARY",
        assets.expected_dbow2_library_sha256,
    )
    lock = file_binding(
        assets.env_lock, "OFFICIAL_ENV_EXPLICIT_LOCK", assets.expected_env_lock_sha256
    )
    config_relative, config_hash = assets.expected_configs[profile.feature]
    config = file_binding(
        assets.repo / config_relative, "OFFICIAL_FEATURE_SETTINGS", config_hash
    )

    observed_vocab_names = {
        path.name for path in assets.vocabulary_folder.iterdir()
    }
    if observed_vocab_names != set(assets.expected_vocabs):
        raise ContractError(
            "VOCABULARY_FOLDER_ENTRY_SET_MISMATCH:"
            + ",".join(sorted(observed_vocab_names))
        )
    vocab_bindings: dict[str, Any] = {}
    for name, (expected_size, expected_hash) in assets.expected_vocabs.items():
        binding = file_binding(
            assets.vocabulary_folder / name,
            f"VOCABULARY_{name}",
            expected_hash,
        )
        if binding["size_bytes"] != expected_size:
            raise ContractError(f"VOCABULARY_SIZE_MISMATCH:{name}")
        vocab_bindings[name] = binding

    provisioning = (
        _verify_provisioning_result(assets)
        if assets.enforce_git
        else file_binding(assets.provisioning_result, "PROVISIONING_RESULT")
    )
    preregistration = file_binding(
        assets.preregistration,
        "PREREGISTRATION",
        EXPECTED_PREREGISTRATION_SHA256 if assets.enforce_git else None,
    )
    return {
        "source": source_identity,
        "binary": binary,
        "core_library": core,
        "dbow2_library": dbow2,
        "environment_explicit_lock": lock,
        "feature_settings": config,
        "vocabulary_folder": str(assets.vocabulary_folder.resolve()),
        "vocabularies": vocab_bindings,
        "provisioning_result": provisioning,
        "preregistration": preregistration,
        "source_modified_by_runner": False,
    }


def child_environment(assets: FrozenAssets) -> dict[str, str]:
    env_root = assets.runtime_root / "env"
    values = {
        "HOME": str((assets.runtime_root / "home").resolve()),
        "PATH": f"{env_root.resolve()}/bin:/usr/bin:/bin",
        "LD_LIBRARY_PATH": ":".join(
            [
                str((env_root / "lib").resolve()),
                str((assets.repo / "lib").resolve()),
                str((assets.repo / "Thirdparty/DBoW2/lib").resolve()),
            ]
        ),
        "CONDA_PREFIX": str(env_root.resolve()),
        "MAMBA_ROOT_PREFIX": str((assets.runtime_root / "mamba-root").resolve()),
        "CONDA_PKGS_DIRS": str((assets.runtime_root / "pkgs").resolve()),
        "PIP_CACHE_DIR": str((assets.runtime_root / "pip-cache").resolve()),
        "HF_HOME": str((assets.runtime_root / "hf-cache").resolve()),
        "XDG_CACHE_HOME": str((assets.runtime_root / "xdg-cache").resolve()),
        "TMPDIR": str((assets.runtime_root / "tmp").resolve()),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    for key in (
        "HOME",
        "CONDA_PREFIX",
        "MAMBA_ROOT_PREFIX",
        "CONDA_PKGS_DIRS",
        "PIP_CACHE_DIR",
        "HF_HOME",
        "XDG_CACHE_HOME",
        "TMPDIR",
    ):
        path = Path(values[key])
        if not path.is_dir() or path.is_symlink():
            raise ContractError(f"CHILD_ENV_DIRECTORY_MISSING_OR_SYMLINK:{key}:{path}")
    return values


def audit_ldd(assets: FrozenAssets, environment: Mapping[str, str]) -> str:
    result = subprocess.run(
        ["/usr/bin/ldd", str(assets.binary)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=dict(environment),
        cwd=str(assets.repo),
        check=False,
    )
    if result.returncode != 0:
        raise ContractError(f"LDD_RETURN_CODE_NOT_ZERO:{result.returncode}")
    text = result.stdout
    if "not found" in text.lower():
        raise ContractError("LDD_CONTAINS_NOT_FOUND")
    if assets.enforce_git:
        required_resolutions = (
            str(assets.core_library.resolve()),
            str(assets.dbow2_library.resolve()),
            str((assets.runtime_root / "env/lib/libopencv_core.so.409").resolve()),
        )
        for required in required_resolutions:
            if required not in text:
                raise ContractError(f"LDD_REQUIRED_RESOLUTION_MISSING:{required}")
        for line in text.splitlines():
            if "libopencv_" in line and "=>" in line:
                resolved = line.split("=>", 1)[1].strip().split(" ", 1)[0]
                env_lib = str((assets.runtime_root / "env/lib").resolve()) + "/"
                if not resolved.startswith(env_lib):
                    raise ContractError(f"LDD_OPENCV_OUTSIDE_FROZEN_ENV:{resolved}")
    return text


def _parse_rgb(sequence: Path, expected_count: int) -> tuple[tuple[int, str], ...]:
    rgb_txt = sequence / "rgb.txt"
    file_binding(rgb_txt, "RGB_TXT")
    payload = rgb_txt.read_bytes()
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ContractError("RGB_TXT_NOT_ASCII") from exc
    if not text.endswith("\n") or "\r" in text:
        raise ContractError("RGB_TXT_NOT_CANONICAL_NEWLINE")
    lines = text[:-1].split("\n")
    if len(lines) != expected_count or any(not line for line in lines):
        raise ContractError(
            f"PROFILE_FRAME_COUNT_MISMATCH:{len(lines)}:{expected_count}"
        )
    rows: list[tuple[int, str]] = []
    previous: int | None = None
    for index, line in enumerate(lines):
        match = RGB_ROW_RE.fullmatch(line)
        if match is None:
            raise ContractError(f"RGB_TXT_ROW_NOT_CANONICAL:{index}")
        seconds, nanos, relative, basename_ns = match.groups()
        stamp = int(seconds) * 1_000_000_000 + int(nanos)
        expected_line = (
            f"{stamp // 1_000_000_000}.{stamp % 1_000_000_000:09d} "
            f"rgb/{stamp}.png"
        )
        if line != expected_line or int(basename_ns) != stamp:
            raise ContractError(f"RGB_TXT_TIMESTAMP_PATH_MISMATCH:{index}")
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts or len(pure.parts) != 2:
            raise ContractError(f"RGB_TXT_UNSAFE_PATH:{index}")
        if previous is not None and stamp <= previous:
            raise ContractError(f"RGB_TXT_TIMESTAMPS_NOT_STRICT:{index}")
        previous = stamp
        rows.append((stamp, relative))
    return tuple(rows)


def _png_contract(path: Path, label: str) -> None:
    file_binding(path, label)
    with path.open("rb") as handle:
        header = handle.read(33)
    if len(header) != 33 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ContractError(f"{label}_NOT_PNG")
    if header[12:16] != b"IHDR":
        raise ContractError(f"{label}_IHDR_MISSING")
    width, height, bit_depth, color_type = struct.unpack(">IIBB", header[16:26])
    if (width, height, bit_depth, color_type) != (968, 608, 8, 0):
        raise ContractError(
            f"{label}_PNG_SCHEMA_MISMATCH:{width}x{height}:"
            f"depth{bit_depth}:color{color_type}"
        )


def _camera_sequence_manifest(
    profile: RunProfile, *, verify_frozen_source_files: bool
) -> dict[str, Any]:
    sequence = profile.sequence_path
    regular_directory(sequence, "SEQUENCE_ROOT")
    regular_directory(sequence / "rgb", "RGB_DIRECTORY")
    allowed = {
        "rgb",
        "rgb.txt",
        "calibration.yaml",
        "conversion_manifest.json",
        "r2d2",
        "producer_run_manifest.json",
        "producer_evidence",
    }
    observed = {path.name for path in sequence.iterdir()}
    required = {"rgb", "rgb.txt", "calibration.yaml", "conversion_manifest.json"}
    if not required.issubset(observed) or not observed.issubset(allowed):
        raise ContractError(
            "SEQUENCE_ROOT_ENTRY_SET_MISMATCH:" + ",".join(sorted(observed))
        )
    if any(path.is_symlink() for path in sequence.iterdir()):
        raise ContractError("SEQUENCE_ROOT_CONTAINS_SYMLINK")
    rows = _parse_rgb(sequence, profile.frame_count)
    if profile.input_profile in ("a02-prefix200", "a02-full"):
        if rows[0][0] != EXPECTED_FIRST_NS:
            raise ContractError("A02_FIRST_TIMESTAMP_MISMATCH")
        if (
            profile.input_profile == "a02-prefix200"
            and rows[-1][0] != EXPECTED_PREFIX_LAST_NS
        ):
            raise ContractError("A02_PREFIX_LAST_TIMESTAMP_MISMATCH")

    conversion_path = sequence / "conversion_manifest.json"
    conversion = load_json_object(conversion_path, "CONVERSION_MANIFEST")
    if (
        conversion.get("adapter_version") != "aqualoc-anyfeature-camera-v1"
        or conversion.get("status") != "EXPORTED"
        or conversion.get("profile") != profile.input_profile
    ):
        raise ContractError("CONVERSION_MANIFEST_PROFILE_OR_IDENTITY_MISMATCH")
    adapter_identity = conversion.get("adapter_identity")
    if not isinstance(adapter_identity, Mapping):
        raise ContractError("CONVERSION_MANIFEST_ADAPTER_IDENTITY_MISSING")
    adapter_path_text = adapter_identity.get("resolved_script")
    if not isinstance(adapter_path_text, str) or not Path(adapter_path_text).is_absolute():
        raise ContractError("CONVERSION_MANIFEST_ADAPTER_PATH_INVALID")
    adapter_path = Path(adapter_path_text)
    expected_adapter_path = Path(__file__).resolve().with_name(
        "export_aqualoc_to_anyfeature_v1.py"
    )
    if (
        str(adapter_path.resolve()) != adapter_path_text
        or adapter_path.resolve() != expected_adapter_path
    ):
        raise ContractError("CONVERSION_MANIFEST_ADAPTER_PATH_DRIFT")
    adapter_binding = file_binding(adapter_path, "CAMERA_EXPORT_ADAPTER")
    if (
        adapter_identity.get("script")
        != "scripts/export_aqualoc_to_anyfeature_v1.py"
        or adapter_identity.get("sha256") != adapter_binding["sha256"]
    ):
        raise ContractError("CONVERSION_MANIFEST_ADAPTER_DRIFT")

    source = conversion.get("source")
    camera = conversion.get("camera")
    calibration = conversion.get("calibration")
    if not all(isinstance(x, Mapping) for x in (source, camera, calibration)):
        raise ContractError("CONVERSION_MANIFEST_REQUIRED_BLOCK_MISSING")
    source_calibration = source.get("calibration")  # type: ignore[union-attr]
    if not isinstance(source_calibration, Mapping):
        raise ContractError("CONVERSION_MANIFEST_SOURCE_CALIBRATION_MISSING")
    if profile.input_profile in ("a02-prefix200", "a02-full"):
        if source.get("sha256") != EXPECTED_SOURCE_BAG_SHA256:  # type: ignore[union-attr]
            raise ContractError("CONVERSION_MANIFEST_SOURCE_BAG_MISMATCH")
        if source_calibration.get("sha256") != EXPECTED_SOURCE_CALIBRATION_SHA256:
            raise ContractError("CONVERSION_MANIFEST_SOURCE_CALIBRATION_MISMATCH")
    if verify_frozen_source_files:
        file_binding(EXPECTED_SOURCE_BAG, "A02_SOURCE_BAG", EXPECTED_SOURCE_BAG_SHA256)
        file_binding(
            EXPECTED_SOURCE_CALIBRATION,
            "A02_SOURCE_CALIBRATION",
            EXPECTED_SOURCE_CALIBRATION_SHA256,
        )

    expected_schema = {
        "topic": "/camera/image_raw",
        "message_type": "sensor_msgs/Image",
        "width": 968,
        "height": 608,
        "encoding": "mono8",
        "nominal_fps": 20.0,
    }
    if camera.get("schema") != expected_schema:  # type: ignore[union-attr]
        raise ContractError("CONVERSION_MANIFEST_CAMERA_SCHEMA_MISMATCH")
    if camera.get("count") != profile.frame_count:  # type: ignore[union-attr]
        raise ContractError("CONVERSION_MANIFEST_CAMERA_COUNT_MISMATCH")
    if camera.get("source_indices_inclusive") != [0, profile.frame_count - 1]:  # type: ignore[union-attr]
        raise ContractError("CONVERSION_MANIFEST_CAMERA_INDICES_MISMATCH")
    if camera.get("selected_header_ns_inclusive") != [rows[0][0], rows[-1][0]]:  # type: ignore[union-attr]
        raise ContractError("CONVERSION_MANIFEST_TIMESTAMP_RANGE_MISMATCH")
    rgb_meta = camera.get("rgb_txt")  # type: ignore[union-attr]
    image_rows = camera.get("images")  # type: ignore[union-attr]
    if not isinstance(rgb_meta, Mapping) or not isinstance(image_rows, list):
        raise ContractError("CONVERSION_MANIFEST_CAMERA_ROWS_MISSING")
    rgb_hash = sha256_file(sequence / "rgb.txt")
    if rgb_meta.get("sha256") != rgb_hash or rgb_meta.get("row_count") != profile.frame_count:
        raise ContractError("CONVERSION_MANIFEST_RGB_TXT_BINDING_MISMATCH")
    if len(image_rows) != profile.frame_count:
        raise ContractError("CONVERSION_MANIFEST_IMAGE_ROW_COUNT_MISMATCH")

    calibration_binding = file_binding(sequence / "calibration.yaml", "CALIBRATION")
    if calibration.get("output_sha256") != calibration_binding["sha256"]:  # type: ignore[union-attr]
        raise ContractError("CONVERSION_MANIFEST_CALIBRATION_HASH_MISMATCH")

    files: list[dict[str, Any]] = [
        {
            "role": "rgb_index",
            **file_binding(sequence / "rgb.txt", "RGB_TXT"),
            "relative_path": "rgb.txt",
        },
        {
            "role": "calibration",
            **calibration_binding,
            "relative_path": "calibration.yaml",
        },
        {
            "role": "conversion_manifest",
            **file_binding(conversion_path, "CONVERSION_MANIFEST"),
            "relative_path": "conversion_manifest.json",
        },
    ]
    camera_tree: list[tuple[str, str]] = [
        ("rgb.txt", rgb_hash),
        ("calibration.yaml", str(calibration_binding["sha256"])),
    ]
    png_names: set[str] = set()
    for index, ((stamp, relative), manifest_row) in enumerate(zip(rows, image_rows)):
        if not isinstance(manifest_row, Mapping):
            raise ContractError(f"CONVERSION_MANIFEST_IMAGE_ROW_NOT_OBJECT:{index}")
        path = sequence / relative
        _png_contract(path, f"PNG:{index}")
        binding = file_binding(path, f"PNG:{index}")
        expected = {
            "source_index": index,
            "raw_header_ns": stamp,
            "relative_path": relative,
            "png_sha256": binding["sha256"],
            "png_size_bytes": binding["size_bytes"],
            "pixel_identity_verified": True,
        }
        for key, value in expected.items():
            if manifest_row.get(key) != value:
                raise ContractError(f"CONVERSION_MANIFEST_IMAGE_{key.upper()}_MISMATCH:{index}")
        source_pixel_hash = manifest_row.get("source_pixel_sha256")
        if (
            not isinstance(source_pixel_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", source_pixel_hash) is None
        ):
            raise ContractError(
                f"CONVERSION_MANIFEST_SOURCE_PIXEL_HASH_INVALID:{index}"
            )
        png_names.add(Path(relative).name)
        camera_tree.append((relative, str(binding["sha256"])))
        files.append(
            {
                "role": "image",
                "source_index": index,
                "timestamp_ns": stamp,
                "relative_path": relative,
                **binding,
            }
        )
    observed_png_names = {path.name for path in (sequence / "rgb").iterdir() if path.suffix == ".png"}
    if observed_png_names != png_names:
        raise ContractError("RGB_DIRECTORY_PNG_SET_MISMATCH")
    if any(path.is_symlink() for path in (sequence / "rgb").iterdir()):
        raise ContractError("RGB_DIRECTORY_CONTAINS_SYMLINK")
    if conversion.get("payload_tree_sha256_excluding_manifest") != aggregate_hash(
        sorted(camera_tree)
    ):
        raise ContractError("CONVERSION_MANIFEST_CAMERA_TREE_HASH_MISMATCH")

    sequence_identity = conversion.get("sequence_identity")
    if not isinstance(sequence_identity, Mapping):
        raise ContractError("CONVERSION_MANIFEST_SEQUENCE_IDENTITY_MISSING")
    expected_identity_record = {
        "schema": "aqualoc-anyfeature-sequence-identity-v1",
        "adapter_version": "aqualoc-anyfeature-camera-v1",
        "adapter_sha256": adapter_identity["sha256"],
        "profile": profile.input_profile,
        "source_bag_sha256": source.get("sha256"),  # type: ignore[union-attr]
        "source_calibration_sha256": source_calibration.get("sha256"),
        "rgb_txt_sha256": rgb_hash,
        "output_calibration_sha256": calibration_binding["sha256"],
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
    expected_identity_hash = sha256_bytes(
        canonical_json(expected_identity_record).encode("utf-8")
    )
    if (
        sequence_identity.get("schema")
        != "aqualoc-anyfeature-sequence-identity-v1"
        or sequence_identity.get("record") != expected_identity_record
        or sequence_identity.get("sha256") != expected_identity_hash
    ):
        raise ContractError("CONVERSION_MANIFEST_SEQUENCE_IDENTITY_MISMATCH")

    result: dict[str, Any] = {
        "schema": INPUT_SCHEMA,
        "profile": profile.input_profile,
        "sequence_path": str(sequence.resolve()),
        "frame_count": profile.frame_count,
        "first_timestamp_ns": rows[0][0],
        "last_timestamp_ns": rows[-1][0],
        "conversion_manifest_sha256": sha256_file(conversion_path),
        "camera_payload_tree_sha256": aggregate_hash(sorted(camera_tree)),
        "files": files,
    }
    if profile.input_profile == "a02-full":
        prefix_profile = RunProfile(
            "internal-a02-prefix-camera-audit",
            PREFIX_SEQUENCE,
            profile.experiment_folder,
            "orb32",
            200,
            "a02-prefix200",
            False,
            False,
            False,
            None,
        )
        prefix = _camera_sequence_manifest(
            prefix_profile,
            verify_frozen_source_files=False,
        )
        prefix_conversion_path = PREFIX_SEQUENCE / "conversion_manifest.json"
        prefix_conversion = load_json_object(
            prefix_conversion_path, "PREFIX_CONVERSION_MANIFEST"
        )
        prefix_identity = prefix_conversion.get("sequence_identity")
        reuse = conversion.get("prefix_reuse")
        if not isinstance(prefix_identity, Mapping) or not isinstance(reuse, Mapping):
            raise ContractError("FULL_PREFIX_REUSE_BINDING_MISSING")
        expected_reuse = {
            "required": True,
            "count": 200,
            "source_indices_inclusive": [0, 199],
            "prefix_root": str(PREFIX_SEQUENCE.resolve()),
            "prefix_conversion_manifest": str(prefix_conversion_path.resolve()),
            "prefix_conversion_manifest_sha256": sha256_file(
                prefix_conversion_path
            ),
            "prefix_sequence_identity_sha256": prefix_identity.get("sha256"),
            "rgb_txt_prefix_bytes_sha256": sha256_file(
                PREFIX_SEQUENCE / "rgb.txt"
            ),
            "png_byte_identity": True,
            "calibration_byte_identity": True,
            "newly_encoded_source_indices_inclusive": [200, 900],
        }
        for key, value in expected_reuse.items():
            if reuse.get(key) != value:
                raise ContractError(f"FULL_PREFIX_REUSE_{key.upper()}_MISMATCH")
        prefix_images = [
            row for row in prefix["files"] if row.get("role") == "image"
        ]
        full_images = [row for row in files if row.get("role") == "image"]
        for index, (prefix_row, full_row) in enumerate(
            zip(prefix_images, full_images[:200])
        ):
            if (
                prefix_row["timestamp_ns"] != full_row["timestamp_ns"]
                or prefix_row["sha256"] != full_row["sha256"]
                or prefix_row["size_bytes"] != full_row["size_bytes"]
                or image_rows[index].get("reused_from_prefix") is not True
            ):
                raise ContractError(f"FULL_PREFIX_PNG_BYTE_REUSE_MISMATCH:{index}")
        if any(
            row.get("reused_from_prefix") is not False
            for row in image_rows[200:]
        ):
            raise ContractError("FULL_POSTPREFIX_ROW_MARKED_REUSED")
        if prefix["files"][1]["sha256"] != calibration_binding["sha256"]:
            raise ContractError("FULL_PREFIX_CALIBRATION_BYTE_REUSE_MISMATCH")
        result["prefix_reuse"] = {
            "prefix_sequence_path": str(PREFIX_SEQUENCE.resolve()),
            "prefix_conversion_manifest_sha256": sha256_file(
                prefix_conversion_path
            ),
            "prefix_sequence_identity_sha256": prefix_identity.get("sha256"),
            "prefix_camera_payload_tree_sha256": prefix[
                "camera_payload_tree_sha256"
            ],
            "reused_image_count": 200,
            "all_prefix_png_bytes_equal": True,
            "calibration_bytes_equal": True,
        }
    return result


def _append_consumed_r2d2_files(
    manifest: dict[str, Any], profile: RunProfile
) -> None:
    rows = _parse_rgb(profile.sequence_path, profile.frame_count)
    files = manifest["files"]
    tree: list[tuple[str, str]] = []
    for index, (stamp, _) in enumerate(rows):
        for column in ("keypoints", "descriptors", "scores"):
            relative = f"r2d2/{column}/{stamp}.bin"
            binding = file_binding(
                profile.sequence_path / relative,
                f"R2D2_BIN:{column}:{index}",
            )
            files.append(
                {
                    "role": f"r2d2_{column}",
                    "source_index": index,
                    "timestamp_ns": stamp,
                    "relative_path": relative,
                    **binding,
                }
            )
            tree.append((relative, str(binding["sha256"])))
    manifest["r2d2_consumed_tree_sha256"] = aggregate_hash(sorted(tree))
    manifest["r2d2_consumed_file_count"] = len(tree)


def _audit_r2d2_materialization(profile: RunProfile, manifest: dict[str, Any]) -> None:
    try:
        from scripts import materialize_anyfeature_r2d2_bins_v1 as adapter
    except Exception as exc:  # pragma: no cover - environment-specific import failure
        raise ContractError(f"R2D2_ADAPTER_IMPORT_FAILED:{exc}") from exc
    try:
        if profile.smoke_only:
            result = adapter.validate_smoke_view(
                PREFIX_SEQUENCE,
                profile.sequence_path,
                profile.experiment_folder,
                preregistration_path=PREREGISTRATION,
            )
            smoke_manifest = profile.sequence_path / "smoke_view_manifest.json"
            manifest["r2d2_contract"] = {
                "validator_status": result["status"],
                "validator_adapter_sha256": sha256_file(Path(adapter.__file__).resolve()),
                "smoke_view_manifest": file_binding(
                    smoke_manifest, "SMOKE_VIEW_MANIFEST"
                ),
                "index0_nonempty_reader_exercised": True,
            }
        else:
            result = adapter.validate_materialized_output(
                profile.sequence_path,
                profile.sequence_path,
                adapter.PROFILES["a02-full"],
                PREFIX_SEQUENCE,
            )
            materialization = profile.sequence_path / "r2d2/materialization_manifest.json"
            manifest["r2d2_contract"] = {
                "validator_status": result["status"],
                "validator_adapter_sha256": sha256_file(Path(adapter.__file__).resolve()),
                "materialization_manifest": file_binding(
                    materialization, "R2D2_MATERIALIZATION_MANIFEST"
                ),
                "all_roundtrip_exact": result["all_roundtrip_exact"],
                "all_finite": result["all_finite"],
            }
    except adapter.ContractError as exc:
        raise ContractError(f"R2D2_INPUT_CONTRACT_FAILED:{exc}") from exc
    _append_consumed_r2d2_files(manifest, profile)


def build_input_manifest(profile: RunProfile, *, formal: bool) -> dict[str, Any]:
    if profile.smoke_only:
        # The independently audited smoke view is not a camera conversion
        # artifact itself; validate it first, then bind its exact one-row view.
        regular_directory(profile.sequence_path, "SMOKE_SEQUENCE_ROOT")
        rows = _parse_rgb(profile.sequence_path, 1)
        _png_contract(profile.sequence_path / rows[0][1], "SMOKE_PNG")
        files = [
            {
                "role": "rgb_index",
                "relative_path": "rgb.txt",
                **file_binding(profile.sequence_path / "rgb.txt", "SMOKE_RGB_TXT"),
            },
            {
                "role": "calibration",
                "relative_path": "calibration.yaml",
                **file_binding(profile.sequence_path / "calibration.yaml", "SMOKE_CALIBRATION"),
            },
            {
                "role": "image",
                "source_index": 0,
                "timestamp_ns": rows[0][0],
                "relative_path": rows[0][1],
                **file_binding(profile.sequence_path / rows[0][1], "SMOKE_PNG"),
            },
        ]
        manifest: dict[str, Any] = {
            "schema": INPUT_SCHEMA,
            "profile": profile.input_profile,
            "sequence_path": str(profile.sequence_path.resolve()),
            "frame_count": 1,
            "first_timestamp_ns": rows[0][0],
            "last_timestamp_ns": rows[0][0],
            "files": files,
        }
    else:
        manifest = _camera_sequence_manifest(
            profile, verify_frozen_source_files=formal
        )
    if profile.r2d2_required:
        _audit_r2d2_materialization(profile, manifest)
    all_rows = sorted(
        (str(row["relative_path"]), str(row["sha256"]))
        for row in manifest["files"]
    )
    manifest["consumed_payload_tree_sha256"] = aggregate_hash(all_rows)
    manifest["consumed_file_count"] = len(manifest["files"])
    return manifest


def official_argv(
    profile: RunProfile, assets: FrozenAssets
) -> tuple[str, ...]:
    config_relative, _ = assets.expected_configs[profile.feature]
    repo_with_slash = str(assets.repo.resolve()).rstrip("/") + "/"
    return (
        str(assets.binary.resolve()),
        f"anyfeat:{repo_with_slash}",
        f"Voc:{assets.vocabulary_folder.resolve()}",
        f"FeatSet:{(assets.repo / config_relative).resolve()}",
        "Vis:0",
        f"sequence_path:{profile.sequence_path.resolve()}",
        f"exp_folder:{profile.experiment_folder.resolve()}",
        "exp_id:0",
        f"Feat:{profile.feature}",
        "FixRes:0",
    )


def validate_profile_paths(
    profile: RunProfile, sequence_path: Path, experiment_folder: Path
) -> None:
    if str(sequence_path) != str(profile.sequence_path):
        raise ContractError(
            f"UNKNOWN_OR_NONFROZEN_SEQUENCE_PATH:{sequence_path}:"
            f"expected={profile.sequence_path}"
        )
    if str(experiment_folder) != str(profile.experiment_folder):
        raise ContractError(
            f"UNKNOWN_OR_NONFROZEN_EXPERIMENT_FOLDER:{experiment_folder}:"
            f"expected={profile.experiment_folder}"
        )
    if sequence_path.resolve() != profile.sequence_path.resolve():
        raise ContractError("SEQUENCE_PATH_RESOLUTION_MISMATCH")
    if experiment_folder.resolve() != profile.experiment_folder.resolve():
        raise ContractError("EXPERIMENT_FOLDER_RESOLUTION_MISMATCH")
    if experiment_folder.exists() or experiment_folder.is_symlink():
        raise ContractError(f"OUTPUT_ALREADY_EXISTS:{experiment_folder}")
    sequence_resolved = sequence_path.resolve()
    experiment_resolved = experiment_folder.resolve()
    if (
        sequence_resolved == experiment_resolved
        or sequence_resolved in experiment_resolved.parents
        or experiment_resolved in sequence_resolved.parents
    ):
        raise ContractError("SEQUENCE_AND_OUTPUT_PATHS_OVERLAP")


def preflight(
    profile: RunProfile,
    assets: FrozenAssets = FORMAL_ASSETS,
    *,
    formal: bool = True,
) -> PreflightBundle:
    if sys.byteorder != "little":
        raise ContractError(f"HOST_BYTEORDER_NOT_LITTLE:{sys.byteorder}")
    validate_profile_paths(profile, profile.sequence_path, profile.experiment_folder)
    official = verify_official_assets(profile, assets)
    environment = child_environment(assets)
    ldd_text = audit_ldd(assets, environment)
    input_manifest = build_input_manifest(profile, formal=formal)
    argv = official_argv(profile, assets)
    semantic_fields = {
        "anyfeat": str(assets.repo.resolve()).rstrip("/") + "/",
        "Voc": str(assets.vocabulary_folder.resolve()),
        "FeatSet": str((assets.repo / assets.expected_configs[profile.feature][0]).resolve()),
        "Vis": 0,
        "sequence_path": str(profile.sequence_path.resolve()),
        "exp_folder": str(profile.experiment_folder.resolve()),
        "exp_id": 0,
        "Feat": profile.feature,
        "FixRes": 0,
    }
    summary = {
        "schema": RUNNER_SCHEMA,
        "status": "PREFLIGHT_READY",
        "profile": profile.name,
        "scientific_role": (
            "non-scientific one-image R2D2 ingestion smoke"
            if profile.smoke_only
            else "camera-only monocular full-window comparison arm"
        ),
        "frame_count": profile.frame_count,
        "feature": profile.feature,
        "semantic_fields": semantic_fields,
        "official_binary_sha256": official["binary"]["sha256"],
        "environment_explicit_lock_sha256": official["environment_explicit_lock"]["sha256"],
        "input_consumed_payload_tree_sha256": input_manifest["consumed_payload_tree_sha256"],
        "input_consumed_file_count": input_manifest["consumed_file_count"],
        "output_absent": True,
        "execution_order": {
            "enforced_by_runner": False,
            "authority": "external frozen preregistration/orchestrator",
            "full_arm_position": profile.order_position,
            "fixed_full_order": ["orb32-full", "r2d2-full"],
        },
        "accuracy_evaluated": False,
        "claims": {
            "official_source_modified": False,
            "official_process_started": False,
            "trajectory_generated": False,
        },
    }
    return PreflightBundle(
        profile,
        assets,
        official,
        input_manifest,
        argv,
        environment,
        ldd_text,
        summary,
    )


def _stdout_contract(
    profile: RunProfile,
    assets: FrozenAssets,
    stdout: str,
    stderr: str,
) -> dict[str, Any]:
    config_relative, _ = assets.expected_configs[profile.feature]
    expected_lines = (
        f"AnyFeature path = {str(assets.repo.resolve()).rstrip('/')}/",
        f"Path to vocabulary folder = {assets.vocabulary_folder.resolve()}",
        f"Feature settings yaml file = {(assets.repo / config_relative).resolve()}",
        "Activate Visualization = 0",
        f"Path to sequence = {profile.sequence_path.resolve()}",
        f"Path to output = {profile.experiment_folder.resolve()}",
        "Exp id = 0",
        f"Feature = {profile.feature}",
        "Fix image size = 0",
        f"Images in the sequence: {profile.frame_count}",
    )
    missing_echoes = [line for line in expected_lines if line not in stdout]
    budget_2000 = len(
        re.findall(r"(?m)^\s*-\s*Number of Features:\s*2000\s*$", stdout)
    )
    budget_4000 = len(
        re.findall(r"(?m)^\s*-\s*Number of Features:\s*4000\s*$", stdout)
    )
    combined = stdout + "\n" + stderr
    diagnostics = [
        {"code": name, "matched": pattern.search(combined).group(0)}
        for name, pattern in FATAL_DIAGNOSTICS
        if pattern.search(combined) is not None
    ]
    numeric_nonfinite = NUMERIC_NONFINITE_RE.search(combined)
    if numeric_nonfinite is not None:
        diagnostics.append(
            {"code": "stdout_or_stderr_nonfinite", "matched": numeric_nonfinite.group(0)}
        )
    return {
        "expected_argument_echoes": list(expected_lines),
        "missing_argument_echoes": missing_echoes,
        "feature_budget": {
            "normal_target": 2000,
            "initialization_target": 4000,
            "normal_echo_count": budget_2000,
            "initialization_echo_count": budget_4000,
            "passed": budget_2000 >= 1 and budget_4000 >= 1,
        },
        "prohibited_diagnostics": diagnostics,
        "passed": not missing_echoes
        and budget_2000 >= 1
        and budget_4000 >= 1
        and not diagnostics,
        "known_empty_statistics_nan_policy": (
            "NaN/Inf is allowed only inside one-image 00000_statistics files; "
            "stdout, stderr, reader diagnostics, and trajectory remain gated."
        ),
    }


def audit_trajectory(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "present": False,
            "nonempty": False,
            "syntax_usable": False,
            "reason": "KEYFRAME_TRAJECTORY_MISSING",
            "pose_count": 0,
            "span_seconds": 0.0,
        }
    if not path.is_file() or path.is_symlink():
        return {
            "present": True,
            "nonempty": False,
            "syntax_usable": False,
            "reason": "KEYFRAME_TRAJECTORY_NOT_REGULAR_FILE",
            "pose_count": 0,
            "span_seconds": 0.0,
        }
    try:
        text = path.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError):
        return {
            "present": True,
            "nonempty": path.stat().st_size > 0,
            "syntax_usable": False,
            "reason": "KEYFRAME_TRAJECTORY_NOT_ASCII",
            "pose_count": 0,
            "span_seconds": 0.0,
        }
    lines = text.splitlines()
    if not lines:
        return {
            "present": True,
            "nonempty": False,
            "syntax_usable": False,
            "reason": "KEYFRAME_TRAJECTORY_EMPTY",
            "pose_count": 0,
            "span_seconds": 0.0,
        }
    timestamps: list[float] = []
    for index, line in enumerate(lines):
        parts = line.split()
        if len(parts) != 8:
            return {
                "present": True,
                "nonempty": True,
                "syntax_usable": False,
                "reason": f"TRAJECTORY_COLUMN_COUNT_MISMATCH:{index}",
                "pose_count": index,
                "span_seconds": 0.0,
            }
        try:
            values = [float(token) for token in parts]
        except ValueError:
            return {
                "present": True,
                "nonempty": True,
                "syntax_usable": False,
                "reason": f"TRAJECTORY_NONNUMERIC:{index}",
                "pose_count": index,
                "span_seconds": 0.0,
            }
        if not all(math.isfinite(value) for value in values):
            return {
                "present": True,
                "nonempty": True,
                "syntax_usable": False,
                "reason": f"TRAJECTORY_NONFINITE:{index}",
                "pose_count": index,
                "span_seconds": 0.0,
            }
        if timestamps and values[0] <= timestamps[-1]:
            return {
                "present": True,
                "nonempty": True,
                "syntax_usable": False,
                "reason": f"TRAJECTORY_TIMESTAMPS_NOT_STRICT:{index}",
                "pose_count": index,
                "span_seconds": timestamps[-1] - timestamps[0],
            }
        timestamps.append(values[0])
    return {
        "present": True,
        "nonempty": True,
        "syntax_usable": True,
        "reason": "VALID_FINITE_STRICT_TUM",
        "pose_count": len(timestamps),
        "first_timestamp": timestamps[0],
        "last_timestamp": timestamps[-1],
        "span_seconds": timestamps[-1] - timestamps[0],
        "sparse_pose_count_changes_runtime_classification": False,
    }


def _artifact_bindings(output: Path, exclude: set[str]) -> tuple[list[dict[str, Any]], str]:
    rows: list[dict[str, Any]] = []
    hash_rows: list[tuple[str, str]] = []
    for path in sorted(output.iterdir(), key=lambda item: item.name):
        if path.name in exclude:
            continue
        if path.is_symlink() or not path.is_file():
            raise ContractError(f"OUTPUT_NONREGULAR_ARTIFACT:{path.name}")
        binding = file_binding(path, f"OUTPUT_ARTIFACT:{path.name}")
        row = {"relative_path": path.name, **binding}
        rows.append(row)
        hash_rows.append((path.name, str(binding["sha256"])))
    return rows, aggregate_hash(hash_rows)


def _environment_record(environment: Mapping[str, str]) -> dict[str, Any]:
    return {
        "schema": ENVIRONMENT_SCHEMA,
        "values": dict(environment),
        "secret_bearing_inherited_environment_recorded": False,
        "environment_sha256": sha256_bytes(
            canonical_json({"values": dict(environment)}).encode("utf-8")
        ),
    }


def _argv_record(argv: Sequence[str]) -> dict[str, Any]:
    return {
        "schema": ARGV_SCHEMA,
        "argv": list(argv),
        "argv_sha256": sha256_bytes(("\n".join(argv) + "\n").encode("utf-8")),
    }


def execute_run(bundle: PreflightBundle) -> tuple[int, dict[str, Any]]:
    profile, assets = bundle.profile, bundle.assets
    output = profile.experiment_folder
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise ContractError(f"OUTPUT_ALREADY_EXISTS:{output}") from exc

    argv_path = output / "argv.json"
    environment_path = output / "environment.json"
    input_path = output / "input_manifest.json"
    ldd_path = output / "ldd.txt"
    stdout_path = output / "stdout.log"
    stderr_path = output / "stderr.log"
    time_path = output / "time-v.txt"
    rc_path = output / "return_code.txt"
    manifest_path = output / "run_manifest.json"
    write_json_exclusive(argv_path, _argv_record(bundle.argv))
    write_json_exclusive(environment_path, _environment_record(bundle.environment))
    write_json_exclusive(input_path, bundle.input_manifest)
    write_exclusive(ldd_path, bundle.ldd_text.encode("utf-8"))

    time_binary = Path("/usr/bin/time")
    time_binding = file_binding(time_binary, "GNU_TIME_BINARY")
    command = [
        str(time_binary),
        "-v",
        "-o",
        str(time_path),
        "--",
        *bundle.argv,
    ]
    started_at = datetime.now(timezone.utc).isoformat()
    started_monotonic = time.monotonic()
    launch_error: str | None = None
    raw_return_code: int | None = None
    stdout_fd = os.open(stdout_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    stderr_fd = os.open(stderr_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(stdout_fd, "wb") as stdout_handle, os.fdopen(
            stderr_fd, "wb"
        ) as stderr_handle:
            try:
                process = subprocess.run(
                    command,
                    cwd=str(assets.repo),
                    env=dict(bundle.environment),
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    check=False,
                )
                raw_return_code = process.returncode
            except OSError as exc:
                launch_error = f"{type(exc).__name__}:{exc}"
                stderr_handle.write((launch_error + "\n").encode("utf-8"))
    finally:
        elapsed = time.monotonic() - started_monotonic
    ended_at = datetime.now(timezone.utc).isoformat()
    write_exclusive(
        rc_path,
        ((str(raw_return_code) if raw_return_code is not None else "LAUNCH_ERROR") + "\n").encode(
            "ascii"
        ),
    )
    if not time_path.exists():
        write_exclusive(time_path, b"")

    stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace")
    stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
    stdout_contract = _stdout_contract(profile, assets, stdout_text, stderr_text)
    trajectory_path = output / "00000_KeyFrameTrajectory.txt"
    trajectory = audit_trajectory(trajectory_path)
    process_rc_zero = raw_return_code == 0 and launch_error is None
    if profile.smoke_only:
        smoke_trajectory_interface_ok = (
            not bool(trajectory["nonempty"])
            or bool(trajectory["syntax_usable"])
        )
        usable = (
            process_rc_zero
            and bool(stdout_contract["passed"])
            and smoke_trajectory_interface_ok
        )
        status = "SMOKE_R2D2_INGESTION_CLOSURE_PASSED" if usable else "SMOKE_R2D2_INGESTION_CLOSURE_FAILED"
        trajectory_requirement = "not required; an empty one-image map is expected/permitted"
    else:
        usable = (
            process_rc_zero
            and bool(stdout_contract["passed"])
            and bool(trajectory["syntax_usable"])
        )
        status = "FULL_RUN_SYNTACTICALLY_USABLE" if usable else "FULL_RUN_UNUSABLE_RETAINED"
        trajectory_requirement = "present, nonempty, finite 8-column TUM, strictly increasing timestamps"

    artifact_rows, artifact_tree = _artifact_bindings(output, {manifest_path.name})
    manifest: dict[str, Any] = {
        "schema": RUNNER_SCHEMA,
        "status": status,
        "profile": profile.name,
        "scientific_role": (
            "non-scientific one-image R2D2 ingestion smoke"
            if profile.smoke_only
            else "camera-only monocular full-window comparison arm"
        ),
        "evaluation_eligible": profile.evaluation_eligible,
        "runner": runner_identity(),
        "official": bundle.official,
        "invocation": {
            "argv_file": file_binding(argv_path, "ARGV_FILE"),
            "argv": list(bundle.argv),
            "wrapper_argv": command,
            "working_directory": str(assets.repo.resolve()),
            "semantic_fields": bundle.preflight_summary["semantic_fields"],
            "gnu_time_binary": time_binding,
        },
        "environment": {
            "file": file_binding(environment_path, "ENVIRONMENT_FILE"),
            "values": dict(bundle.environment),
            "explicit_lock": bundle.official["environment_explicit_lock"],
        },
        "runtime_link": {
            "ldd_file": file_binding(ldd_path, "LDD_FILE"),
            "not_found_count": bundle.ldd_text.lower().count("not found"),
            "passed": "not found" not in bundle.ldd_text.lower(),
        },
        "input": {
            "manifest": file_binding(input_path, "INPUT_MANIFEST"),
            "profile": bundle.input_manifest["profile"],
            "frame_count": bundle.input_manifest["frame_count"],
            "consumed_file_count": bundle.input_manifest["consumed_file_count"],
            "consumed_payload_tree_sha256": bundle.input_manifest[
                "consumed_payload_tree_sha256"
            ],
        },
        "process": {
            "started_at_utc": started_at,
            "ended_at_utc": ended_at,
            "elapsed_seconds": elapsed,
            "raw_return_code": raw_return_code,
            "launch_error": launch_error,
            "stdout": file_binding(stdout_path, "STDOUT"),
            "stderr": file_binding(stderr_path, "STDERR"),
            "return_code_file": file_binding(rc_path, "RETURN_CODE_FILE"),
            "gnu_time_v": file_binding(time_path, "GNU_TIME_OUTPUT"),
        },
        "stdout_contract": stdout_contract,
        "trajectory_syntax": {
            **trajectory,
            "path": str(trajectory_path.resolve()),
            "requirement_for_this_profile": trajectory_requirement,
        },
        "runtime_usability": {
            "process_rc_zero": process_rc_zero,
            "argument_and_feature_budget_contract_passed": stdout_contract["passed"],
            "trajectory_syntax_required": not profile.smoke_only,
            "trajectory_syntax_passed": trajectory["syntax_usable"],
            "smoke_trajectory_interface_passed": (
                not bool(trajectory["nonempty"])
                or bool(trajectory["syntax_usable"])
            ),
            "usable": usable,
            "low_keyframe_count_is_not_a_process_failure": True,
        },
        "accuracy_support": {
            "evaluated_by_runner": False,
            "reason": (
                "Pairwise accuracy requires both sealed full attempts, the fixed 46-pose "
                "reference proxy, identical common mask, and separate Sim(3) fits."
            ),
            "trajectory_pose_count_reported_only": trajectory["pose_count"],
            "trajectory_span_seconds_reported_only": trajectory["span_seconds"],
            "sparse_but_syntactically_valid_trajectory_reclassified_as_runtime_failure": False,
        },
        "execution_order": bundle.preflight_summary["execution_order"],
        "artifacts_excluding_run_manifest": artifact_rows,
        "artifact_tree_sha256_excluding_run_manifest": artifact_tree,
        "claims": {
            "official_source_modified": False,
            "official_process_attempted": raw_return_code is not None,
            "accuracy_read_or_computed": False,
            "rerun_authorized": False,
        },
    }
    write_json_exclusive(manifest_path, manifest)
    if launch_error is not None:
        return RC_CONTRACT, manifest
    return (RC_SUCCESS if usable else RC_RUNTIME_OR_USABILITY), manifest


def _path_within(path: Path, root: Path) -> bool:
    resolved, parent = path.resolve(), root.resolve()
    return resolved == parent or parent in resolved.parents


def validate_report_path(path: Path, profile: RunProfile, assets: FrozenAssets) -> None:
    if path.exists() or path.is_symlink():
        raise ContractError(f"REPORT_ALREADY_EXISTS:{path}")
    forbidden = (
        profile.sequence_path,
        profile.experiment_folder,
        assets.repo,
        assets.runtime_root,
        assets.vocabulary_folder,
    )
    for root in forbidden:
        if _path_within(path, root):
            raise ContractError(f"REPORT_INSIDE_FORBIDDEN_ROOT:{root}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("preflight", "run"), default="preflight")
    parser.add_argument("--profile", choices=tuple(PROFILES), required=True)
    parser.add_argument("--sequence-path", type=Path, required=True)
    parser.add_argument("--exp-folder", type=Path, required=True)
    parser.add_argument(
        "--report-json",
        type=Path,
        help="Optional no-clobber preflight report outside source/input/output roots",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    profile = PROFILES[args.profile]
    try:
        validate_profile_paths(profile, args.sequence_path, args.exp_folder)
        if args.action == "run" and args.report_json is not None:
            raise ContractError("REPORT_JSON_ONLY_ALLOWED_FOR_PREFLIGHT")
        if args.report_json is not None:
            validate_report_path(args.report_json, profile, FORMAL_ASSETS)
        bundle = preflight(profile)
        if args.action == "preflight":
            result = dict(bundle.preflight_summary)
            if args.report_json is not None:
                write_json_exclusive(args.report_json, result)
            sys.stdout.write(canonical_json(result))
            return RC_SUCCESS
        rc, result = execute_run(bundle)
        sys.stdout.write(
            canonical_json(
                {
                    "schema": RUNNER_SCHEMA,
                    "status": result["status"],
                    "profile": profile.name,
                    "return_code": rc,
                    "run_manifest": str(
                        (profile.experiment_folder / "run_manifest.json").resolve()
                    ),
                    "runtime_usable": result["runtime_usability"]["usable"],
                    "accuracy_evaluated": False,
                }
            )
        )
        return rc
    except ContractError as exc:
        result = {
            "schema": RUNNER_SCHEMA,
            "status": "INTEGRITY_ERROR",
            "profile": profile.name,
            "error": str(exc),
            "official_process_started": (
                (profile.experiment_folder / "return_code.txt").is_file()
                if profile.experiment_folder.is_dir()
                else False
            ),
            "accuracy_evaluated": False,
        }
        failure_path = profile.experiment_folder / "runner_integrity_failure.json"
        if profile.experiment_folder.is_dir() and not profile.experiment_folder.is_symlink():
            try:
                write_json_exclusive(failure_path, result)
            except (ContractError, OSError):
                pass
        if args.report_json is not None:
            try:
                validate_report_path(args.report_json, profile, FORMAL_ASSETS)
                write_json_exclusive(args.report_json, result)
            except ContractError:
                pass
        sys.stderr.write(canonical_json(result))
        return RC_CONTRACT
    except Exception as exc:  # unexpected failures still obey the RC=2 contract
        result = {
            "schema": RUNNER_SCHEMA,
            "status": "RUNNER_INTERNAL_ERROR",
            "profile": profile.name,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "official_process_started": (
                (profile.experiment_folder / "return_code.txt").is_file()
                if profile.experiment_folder.is_dir()
                else False
            ),
            "accuracy_evaluated": False,
        }
        failure_path = profile.experiment_folder / "runner_integrity_failure.json"
        if profile.experiment_folder.is_dir() and not profile.experiment_folder.is_symlink():
            try:
                write_json_exclusive(failure_path, result)
            except (ContractError, OSError):
                pass
        sys.stderr.write(canonical_json(result))
        return RC_CONTRACT


if __name__ == "__main__":
    raise SystemExit(main())
