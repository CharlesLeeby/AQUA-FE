#!/usr/bin/env python3
"""Read-only, fail-closed preflight for the published HFNet-SLAM baseline.

The checker does not clone, download, install, build, create an output
directory, load TensorRT, construct an HF-Net engine, or execute the SLAM
binary.  A normal invocation emits exactly one canonical JSON document.

Exit codes are part of the experiment contract:

* 0: frozen identities and the read-only runtime probes are ready;
* 1: identities are intact, but the runtime or reserved output is not ready;
* 2: source, author-repair, model, or A02 input identity drifted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]

SCHEMA_VERSION = "aqua-fe-published-hfnet-slam-v1-preflight-v1"
PUBLISHED_DOI = "10.3390/s23042113"
OFFICIAL_REPOSITORY = "https://github.com/LiuLimingCode/HFNet_SLAM.git"

# Last author commit available before the 2023-02-13 paper publication.
PAPER_COMMIT = "ecb8018f443e66aacf910bc9aaf17e308bc55570"
PAPER_TREE = "4953b8850afc5a94a13e094ea5ae8a52083f5505"

# The two later official commits repair omitted files and namespace/build
# failures.  The audited diff changes no Tracking/Matcher/HFextractor/backend
# arithmetic, thresholds, or control flow.
AUTHOR_BUILD_REPAIR_COMMIT = "4073335ad10b913ff64b5c41576b3d8a0decfcce"
AUTHOR_BUILD_REPAIR_TREE = "ebe0e036f3958c121c7f7cf9f1ba399a34ac85f5"
EXECUTION_COMMIT = "c354c72588a97bb6f6a9c7c8317530795956ec80"
EXECUTION_TREE = "6619814aed4cd0e4baa2501341a48f753f8ba196"

AUTHOR_BUILD_REPAIR_PATHS = (
    ".gitignore",
    "CMakeLists.txt",
    "Comparison/Thirdparty/DBoW2/DUtils/Timestamp.cpp",
    "Comparison/Thirdparty/DBoW2/DUtils/Timestamp.h",
    "README.md",
    "Thirdparty/g2o/g2o/stuff/timeutil.cpp",
    "Thirdparty/g2o/g2o/stuff/timeutil.h",
    "src/Extractors/HFNetRTModel.cc",
    "src/Extractors/HFNetTFModel.cc",
    "src/Extractors/HFNetTFModelV2.cc",
    "src/Extractors/HFNetVINOModel.cc",
)

FROZEN_BUILD_DIRECTORY = "build-aquafe-runtime-r1"
OFFICIAL_CMAKE_OUTPUT_PATHS = (
    "lib/libHFNet_SLAM.so",
    "Examples/Utility/test_extractors",
    "Examples/Utility/test_match_global_feats",
    "Examples/Utility/test_match_local_feats",
    "Examples/Monocular/mono_euroc",
    "Examples/Monocular/mono_tum_vi",
    "Examples/Monocular-Inertial/mono_inertial_euroc",
    "Examples/Monocular-Inertial/mono_inertial_tum_vi",
    "Examples/RGB-D/rgbd_tum",
)

DEFAULT_REPOSITORY = Path("/home/ma/SLAM/HFNet-SLAM-paper-2023-r1")
DEFAULT_MODEL_ROOT = Path("/home/ma/SLAM/HFNet-SLAM-model-2022-r1")
DEFAULT_MODEL_ARCHIVE = DEFAULT_MODEL_ROOT / "hfnet-rt.tar.xz"
DEFAULT_ONNX_MODEL = DEFAULT_MODEL_ROOT / "HFNet-RT/HF-Net.onnx"
DEFAULT_RUNTIME_ROOT = Path("/home/ma/opt/hfnet_cuda116_trt851_r1")
DEFAULT_PANGOLIN_ROOT = Path("/home/ma/SLAM/aqua_deps/install")
DEFAULT_BINARY = (
    DEFAULT_REPOSITORY
    / "Examples/Monocular-Inertial/mono_inertial_euroc"
)
DEFAULT_A02_RAW = ROOT / "datasets/aqualoc/rosbags/archaeo02_4500_5400.bag"
DEFAULT_A02_CAMERA = (
    ROOT
    / "datasets/full_downloads/aqualoc/Archaeological_site_sequences"
    / "archaeo_calibration_files/archaeo_camera_calib.yaml"
)
DEFAULT_OUTPUT_DIRECTORY = (
    ROOT / "logs/published_hfnet_slam_v1/aqualoc_archaeology_A02_0005"
)

OFFICIAL_MODEL_IDENTITY: Mapping[str, Mapping[str, object]] = {
    "model_archive": {
        "size_bytes": 121971956,
        "sha256": "137ac22e866e4b87e35affe9a8e908d8d38a5ea247e7811e72c9486e21c7c1a3",
    },
    "onnx_model": {
        "size_bytes": 132238602,
        "sha256": "354a23f9c28b75ea9056a8eb5586e3b13191426521fd3f5556e5bfd670fc39b5",
    },
}

# The archive also contains an author-generated TensorRT timing cache.  It is
# recorded for provenance but is deliberately not accepted as a runtime-ready
# GTX-1650 cache; a later smoke stage must start from the frozen ONNX in a new
# writable directory.
OFFICIAL_ARCHIVE_CACHE_IDENTITY = {
    "relative_path": "HFNet-RT/HF-Net.cache",
    "size_bytes": 1970277,
    "sha256": "047d3cf9616d95ba1b02f91a92ac7ad3fb8ea6f0660a2431ed5648f901812423",
}

OFFICIAL_INPUT_IDENTITY: Mapping[str, Mapping[str, object]] = {
    "a02_raw": {
        "size_bytes": 222477260,
        "sha256": "8cceb4c76065f3862e60428b14ba10f9a26fc7249e11e9e9d090fed2437238a8",
    },
    "a02_camera": {
        "size_bytes": 337,
        "sha256": "e8ce9ad65d82ae563c676689444abd210f81c362586473c5752ee5f9bf2c32e2",
    },
}

A02_PREFIX_CONTRACT = {
    "camera_count": 200,
    "camera_first_ns": 1542829016700435392,
    "camera_last_ns": 1542829026649564544,
    "duration_ns": 9949129152,
    "image_encoding": "mono8",
    "image_height": 608,
    "image_width": 968,
    "imu_count": 1990,
    "imu_first_raw_ns": 1542829016645312000,
    "imu_first_corrected_ns": 1542829016699006112,
    "imu_last_raw_ns": 1542829026596966304,
    "imu_last_corrected_ns": 1542829026650660416,
    "imu_raw_index_first_zero_based": 38,
    "imu_raw_index_last_zero_based": 2027,
    "kalibr_timeshift_cam_imu_s": -0.053694112369382575,
    "raw_imu_to_camera_clock_offset_ns": 53694112,
}

CUDA_EXPECTED_RELEASE = "11.6"
CUDA_EXPECTED_NVCC_BUILD = "11.6.124"
CUDNN_EXPECTED_VERSION = (8, 4, 1)
CUDNN_OFFICIAL_PACKAGE_VERSION = "8.4.1.50"
TENSORRT_EXPECTED_VERSION = (8, 5, 1)
PANGOLIN_MINIMUM_VERSION = (0, 6, 0)

CUDA_NVCC_RELATIVE = "usr/local/cuda-11.6/bin/nvcc"
CUDA_HEADER_CANDIDATES = (
    "usr/local/cuda-11.6/include/cuda_runtime_api.h",
    "usr/local/cuda-11.6/targets/x86_64-linux/include/cuda_runtime_api.h",
)
CUDA_RUNTIME_CANDIDATES = (
    "usr/local/cuda-11.6/lib64/libcudart.so.11.0",
    "usr/local/cuda-11.6/targets/x86_64-linux/lib/libcudart.so.11.0",
)
CUDA118_CUBLAS_CANDIDATES = (
    (
        "usr/local/cuda-11.8/lib64/libcublas.so.11",
        "usr/local/cuda-11.8/targets/x86_64-linux/lib/libcublas.so.11",
    ),
    (
        "usr/local/cuda-11.8/lib64/libcublasLt.so.11",
        "usr/local/cuda-11.8/targets/x86_64-linux/lib/libcublasLt.so.11",
    ),
)
CUDNN_VERSION_HEADER_CANDIDATES = (
    "usr/include/cudnn_version_v8.h",
    "usr/include/cudnn_version.h",
    "usr/include/x86_64-linux-gnu/cudnn_version_v8.h",
    "usr/include/x86_64-linux-gnu/cudnn_version.h",
)
CUDNN_LIBRARY_NAMES = (
    "libcudnn.so.8.4.1",
    "libcudnn_adv_infer.so.8.4.1",
    "libcudnn_adv_train.so.8.4.1",
    "libcudnn_cnn_infer.so.8.4.1",
    "libcudnn_cnn_train.so.8.4.1",
    "libcudnn_ops_infer.so.8.4.1",
    "libcudnn_ops_train.so.8.4.1",
)
TENSORRT_VERSION_HEADER_CANDIDATES = (
    "usr/include/x86_64-linux-gnu/NvInferVersion.h",
    "usr/include/NvInferVersion.h",
)
TENSORRT_REQUIRED_FILES = (
    "usr/include/x86_64-linux-gnu/NvInfer.h",
    "usr/include/x86_64-linux-gnu/NvOnnxParser.h",
    "usr/lib/x86_64-linux-gnu/libnvinfer.so",
    "usr/lib/x86_64-linux-gnu/libnvinfer.so.8.5.1",
    "usr/lib/x86_64-linux-gnu/libnvinfer_plugin.so.8.5.1",
    "usr/lib/x86_64-linux-gnu/libnvonnxparser.so",
    "usr/lib/x86_64-linux-gnu/libnvonnxparser.so.8.5.1",
)
PANGOLIN_VERSION_CANDIDATES = (
    "lib/cmake/Pangolin/PangolinConfigVersion.cmake",
    "share/Pangolin/cmake/PangolinConfigVersion.cmake",
)

RC_READY = 0
RC_RUNTIME_BLOCKED = 1
RC_INTEGRITY_ERROR = 2


@dataclass(frozen=True)
class CommandResult:
    """Small subprocess result used to keep every probe mockable."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


CommandRunner = Callable[[Sequence[str], Optional[Path]], CommandResult]


def _default_runner(command: Sequence[str], cwd: Path | None) -> CommandResult:
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        completed = subprocess.run(
            list(command),
            cwd=str(cwd) if cwd is not None else None,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError as exc:
        return CommandResult(127, "", f"{type(exc).__name__}:{exc}")
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return CommandResult(124, stdout, f"TimeoutExpired:{stderr}")
    except OSError as exc:
        return CommandResult(126, "", f"{type(exc).__name__}:{exc}")
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _absolute(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _normalize_repository_url(value: str) -> str:
    normalized = value.strip().lower()
    if normalized.startswith("git@github.com:"):
        normalized = "https://github.com/" + normalized[len("git@github.com:") :]
    if normalized.startswith("ssh://git@github.com/"):
        normalized = "https://github.com/" + normalized[len("ssh://git@github.com/") :]
    normalized = normalized.rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized


def _command_observation(result: CommandResult) -> dict[str, object]:
    return {
        "returncode": result.returncode,
        "stderr": result.stderr.strip()[:400],
        "stdout": result.stdout.strip()[:400],
    }


def _sha256(path: Path) -> tuple[str | None, str | None]:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        return None, type(exc).__name__
    return digest.hexdigest(), None


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, ValueError):
        return False
    return True


def _first_file(root: Path, candidates: Sequence[str]) -> Path | None:
    for relative_path in candidates:
        candidate = root / relative_path
        if candidate.is_file():
            return candidate
    return None


def _read_define_version(
    path: Path | None, names: Sequence[str]
) -> tuple[tuple[int, ...] | None, str | None]:
    if path is None:
        return None, "header_missing"
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, type(exc).__name__
    values: list[int] = []
    for name in names:
        match = re.search(
            r"^\s*#\s*define\s+" + re.escape(name) + r"\s+(\d+)\b",
            content,
            flags=re.MULTILINE,
        )
        if match is None:
            return None, "macro_missing:" + name
        values.append(int(match.group(1)))
    return tuple(values), None


def _read_pangolin_version(path: Path | None) -> tuple[tuple[int, ...] | None, str | None]:
    if path is None:
        return None, "config_missing"
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, type(exc).__name__
    match = re.search(r"PACKAGE_VERSION\s+\"(\d+)(?:\.(\d+))?(?:\.(\d+))?", content)
    if match is None:
        return None, "PACKAGE_VERSION_missing"
    return tuple(int(value or 0) for value in match.groups()), None


def _parse_commit_object(value: str) -> dict[str, object]:
    trees = re.findall(r"^tree ([0-9a-f]{40})$", value, flags=re.MULTILINE)
    parents = re.findall(r"^parent ([0-9a-f]{40})$", value, flags=re.MULTILINE)
    return {
        "parents": parents,
        "tree": trees[0] if len(trees) == 1 else None,
    }


def _parse_ldd(value: str) -> tuple[dict[str, str], list[str]]:
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        not_found = re.match(r"^(\S+)\s+=>\s+not found$", line)
        if not_found is not None:
            missing.append(not_found.group(1))
            continue
        mapped = re.match(r"^(\S+)\s+=>\s+(\S+)\s+\(", line)
        if mapped is not None:
            resolved[mapped.group(1)] = mapped.group(2)
            continue
        direct = re.match(r"^(/\S+)\s+\(", line)
        if direct is not None:
            path = direct.group(1)
            resolved[Path(path).name] = path
    return resolved, sorted(missing)


def _library_directory(runtime_root: Path) -> Path:
    return runtime_root / "usr/lib/x86_64-linux-gnu"


def evaluate_preflight(
    *,
    repository: Path,
    model_archive: Path,
    onnx_model: Path,
    a02_raw: Path,
    a02_camera: Path,
    runtime_root: Path,
    pangolin_root: Path,
    binary: Path,
    output_directory: Path,
    runner: CommandRunner = _default_runner,
    environment: Mapping[str, str] | None = None,
    expected_models: Mapping[str, Mapping[str, object]] = OFFICIAL_MODEL_IDENTITY,
    expected_inputs: Mapping[str, Mapping[str, object]] = OFFICIAL_INPUT_IDENTITY,
) -> dict[str, object]:
    """Evaluate frozen identities and read-only runtime availability."""

    repository = _absolute(repository)
    model_archive = _absolute(model_archive)
    onnx_model = _absolute(onnx_model)
    a02_raw = _absolute(a02_raw)
    a02_camera = _absolute(a02_camera)
    runtime_root = _absolute(runtime_root)
    pangolin_root = _absolute(pangolin_root)
    binary = _absolute(binary)
    output_directory = _absolute(output_directory)
    environment = dict(os.environ if environment is None else environment)

    integrity: dict[str, dict[str, object]] = {}
    runtime: dict[str, dict[str, object]] = {}
    informational: dict[str, dict[str, object]] = {}

    def add(
        target: dict[str, dict[str, object]],
        check_id: str,
        ok: bool,
        *,
        expected: object,
        observed: object,
        reason: str | None = None,
    ) -> None:
        check: dict[str, object] = {
            "expected": expected,
            "observed": observed,
            "ok": bool(ok),
        }
        if reason is not None:
            check["reason"] = reason
        target[check_id] = check

    repo_exists = repository.is_dir()
    add(integrity, "repository_exists", repo_exists, expected=True, observed=repo_exists)

    unavailable = CommandResult(125, "", "repository missing")
    git_worktree = git_head = git_tree = git_origin = git_status = unavailable
    commit_objects: dict[str, CommandResult] = {}
    diff_paths = unavailable
    if repo_exists:
        prefix = ["git", "-C", str(repository)]
        git_worktree = runner([*prefix, "rev-parse", "--is-inside-work-tree"], None)
        git_head = runner([*prefix, "rev-parse", "HEAD"], None)
        git_tree = runner([*prefix, "rev-parse", "HEAD^{tree}"], None)
        git_origin = runner([*prefix, "config", "--get", "remote.origin.url"], None)
        git_status = runner(
            [
                *prefix,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--ignore-submodules=none",
            ],
            None,
        )
        for commit in (PAPER_COMMIT, AUTHOR_BUILD_REPAIR_COMMIT, EXECUTION_COMMIT):
            commit_objects[commit] = runner([*prefix, "cat-file", "-p", commit], None)
        diff_paths = runner(
            [*prefix, "diff", "--name-only", PAPER_COMMIT, EXECUTION_COMMIT],
            None,
        )

    inside = git_worktree.returncode == 0 and git_worktree.stdout.strip() == "true"
    add(
        integrity,
        "repository_is_git_worktree",
        inside,
        expected="true",
        observed=_command_observation(git_worktree),
    )
    observed_head = git_head.stdout.strip() if git_head.returncode == 0 else None
    add(
        integrity,
        "repository_head",
        observed_head == EXECUTION_COMMIT,
        expected=EXECUTION_COMMIT,
        observed=observed_head if observed_head is not None else _command_observation(git_head),
    )
    observed_tree = git_tree.stdout.strip() if git_tree.returncode == 0 else None
    add(
        integrity,
        "repository_tree",
        observed_tree == EXECUTION_TREE,
        expected=EXECUTION_TREE,
        observed=observed_tree if observed_tree is not None else _command_observation(git_tree),
    )
    observed_origin = git_origin.stdout.strip() if git_origin.returncode == 0 else None
    origin_ok = (
        observed_origin is not None
        and _normalize_repository_url(observed_origin)
        == _normalize_repository_url(OFFICIAL_REPOSITORY)
    )
    add(
        integrity,
        "repository_origin",
        origin_ok,
        expected=OFFICIAL_REPOSITORY,
        observed=observed_origin if observed_origin is not None else _command_observation(git_origin),
    )
    status_lines = [line for line in git_status.stdout.splitlines() if line.strip()]
    tracked_or_index_entries: list[str] = []
    allowed_generated_entries: list[str] = []
    unexpected_untracked_entries: list[str] = []
    for line in status_lines:
        if not line.startswith("?? "):
            tracked_or_index_entries.append(line)
            continue
        path = line[3:]
        allowed_build_path = path == FROZEN_BUILD_DIRECTORY or path.startswith(
            FROZEN_BUILD_DIRECTORY + "/"
        )
        if allowed_build_path or path in OFFICIAL_CMAKE_OUTPUT_PATHS:
            allowed_generated_entries.append(path)
        else:
            unexpected_untracked_entries.append(path)
    clean = (
        git_status.returncode == 0
        and not tracked_or_index_entries
        and not unexpected_untracked_entries
    )
    generated_entries_sorted = sorted(allowed_generated_entries)
    generated_entries_sha256 = hashlib.sha256(
        ("\n".join(generated_entries_sorted) + ("\n" if generated_entries_sorted else "")).encode(
            "utf-8"
        )
    ).hexdigest()
    add(
        integrity,
        "repository_clean",
        clean,
        expected={
            "allowed_generated_build_directory": FROZEN_BUILD_DIRECTORY,
            "allowed_generated_exact_paths": list(OFFICIAL_CMAKE_OUTPUT_PATHS),
            "tracked_or_index_entry_count": 0,
            "unexpected_untracked_entry_count": 0,
        },
        observed=(
            {
                "allowed_generated_entry_count": len(allowed_generated_entries),
                "tracked_or_index_entries": tracked_or_index_entries,
                "unexpected_untracked_entries": unexpected_untracked_entries,
            }
            if git_status.returncode == 0
            else _command_observation(git_status)
        ),
    )
    add(
        informational,
        "repository_allowed_generated_inventory",
        git_status.returncode == 0,
        expected={"record_allowed_generated_entries": True},
        observed={
            "entries": generated_entries_sorted,
            "entry_count": len(generated_entries_sorted),
            "entries_sha256": generated_entries_sha256,
        },
    )

    expected_commit_objects = {
        PAPER_COMMIT: {"parents": ["4e97abf00316139c6c3f6e714d965aa00ecc08ab"], "tree": PAPER_TREE},
        AUTHOR_BUILD_REPAIR_COMMIT: {"parents": [PAPER_COMMIT], "tree": AUTHOR_BUILD_REPAIR_TREE},
        EXECUTION_COMMIT: {"parents": [AUTHOR_BUILD_REPAIR_COMMIT], "tree": EXECUTION_TREE},
    }
    observed_commit_objects: dict[str, object] = {}
    commit_objects_ok = True
    for commit, expected_object in expected_commit_objects.items():
        result = commit_objects.get(commit, unavailable)
        if result.returncode == 0:
            observed_object: object = _parse_commit_object(result.stdout)
        else:
            observed_object = _command_observation(result)
        observed_commit_objects[commit] = observed_object
        commit_objects_ok &= result.returncode == 0 and observed_object == expected_object
    add(
        integrity,
        "author_build_repair_commit_chain",
        commit_objects_ok,
        expected=expected_commit_objects,
        observed=observed_commit_objects,
    )

    observed_paths = (
        tuple(line for line in diff_paths.stdout.splitlines() if line)
        if diff_paths.returncode == 0
        else ()
    )
    add(
        integrity,
        "author_build_repair_changed_paths",
        diff_paths.returncode == 0 and observed_paths == AUTHOR_BUILD_REPAIR_PATHS,
        expected=list(AUTHOR_BUILD_REPAIR_PATHS),
        observed=(
            list(observed_paths)
            if diff_paths.returncode == 0
            else _command_observation(diff_paths)
        ),
    )

    def add_identity(
        check_prefix: str,
        identity_id: str,
        path: Path,
        oracle: Mapping[str, Mapping[str, object]],
    ) -> None:
        expected = oracle.get(identity_id)
        expected_size = expected.get("size_bytes") if expected is not None else None
        expected_sha = expected.get("sha256") if expected is not None else None
        exists = path.is_file()
        add(
            integrity,
            f"{check_prefix}:{identity_id}:exists",
            exists,
            expected=True,
            observed=exists,
        )
        observed_size: int | None = None
        stat_error: str | None = None
        if exists:
            try:
                observed_size = path.stat().st_size
            except OSError as exc:
                stat_error = type(exc).__name__
        add(
            integrity,
            f"{check_prefix}:{identity_id}:size_bytes",
            isinstance(expected_size, int) and observed_size == expected_size,
            expected=expected_size,
            observed=(
                observed_size
                if stat_error is None
                else {"error": stat_error, "size_bytes": observed_size}
            ),
        )
        observed_sha, hash_error = _sha256(path) if exists else (None, "missing")
        add(
            integrity,
            f"{check_prefix}:{identity_id}:sha256",
            isinstance(expected_sha, str) and observed_sha == expected_sha,
            expected=expected_sha,
            observed=(
                observed_sha
                if hash_error is None
                else {"error": hash_error, "sha256": observed_sha}
            ),
        )

    add_identity("model_identity", "model_archive", model_archive, expected_models)
    add_identity("model_identity", "onnx_model", onnx_model, expected_models)
    add_identity("input_identity", "a02_raw", a02_raw, expected_inputs)
    add_identity("input_identity", "a02_camera", a02_camera, expected_inputs)

    isolated_root_ok = runtime_root.is_dir() and runtime_root not in {
        Path("/"),
        Path("/usr"),
        Path("/usr/local"),
        Path("/opt"),
    }
    add(
        runtime,
        "isolated_runtime_root",
        isolated_root_ok,
        expected={"dedicated_directory": True},
        observed={"exists": runtime_root.is_dir(), "path": str(runtime_root)},
    )

    gpu = runner(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total",
            "--format=csv,noheader",
        ],
        None,
    )
    gpu_lines = [line.strip() for line in gpu.stdout.splitlines() if line.strip()]
    add(
        runtime,
        "nvidia_gpu_available",
        gpu.returncode == 0 and bool(gpu_lines),
        expected={"minimum_gpu_count": 1},
        observed=(
            {"gpu_count": len(gpu_lines), "gpus": gpu_lines}
            if gpu.returncode == 0
            else _command_observation(gpu)
        ),
    )

    nvcc_path = runtime_root / CUDA_NVCC_RELATIVE
    cuda_header = _first_file(runtime_root, CUDA_HEADER_CANDIDATES)
    cuda_runtime = _first_file(runtime_root, CUDA_RUNTIME_CANDIDATES)
    cuda_layout_ok = (
        nvcc_path.is_file()
        and os.access(str(nvcc_path), os.X_OK)
        and cuda_header is not None
        and cuda_runtime is not None
        and _is_within(nvcc_path, runtime_root)
        and _is_within(cuda_header, runtime_root)
        and _is_within(cuda_runtime, runtime_root)
    )
    add(
        runtime,
        "cuda_layout_isolated",
        cuda_layout_ok,
        expected={"release": CUDA_EXPECTED_RELEASE, "within_runtime_root": True},
        observed={
            "header": str(cuda_header) if cuda_header is not None else None,
            "libcudart": str(cuda_runtime) if cuda_runtime is not None else None,
            "nvcc": str(nvcc_path),
            "nvcc_executable": nvcc_path.is_file() and os.access(str(nvcc_path), os.X_OK),
        },
    )
    nvcc = runner([str(nvcc_path), "--version"], None) if nvcc_path.is_file() else CommandResult(127, "", "nvcc missing")
    nvcc_text = nvcc.stdout + "\n" + nvcc.stderr
    cuda_version_ok = (
        nvcc.returncode == 0
        and ("release " + CUDA_EXPECTED_RELEASE) in nvcc_text
        and ("V" + CUDA_EXPECTED_NVCC_BUILD) in nvcc_text
    )
    add(
        runtime,
        "cuda_version",
        cuda_version_ok,
        expected={"nvcc_build": CUDA_EXPECTED_NVCC_BUILD, "release": CUDA_EXPECTED_RELEASE},
        observed=_command_observation(nvcc),
    )

    cublas_libraries = [
        _first_file(runtime_root, candidates)
        for candidates in CUDA118_CUBLAS_CANDIDATES
    ]
    cublas_layout_ok = all(
        path is not None and _is_within(path, runtime_root)
        for path in cublas_libraries
    )
    add(
        runtime,
        "cuda118_cublas_layout_isolated",
        cublas_layout_ok,
        expected={
            "libraries": ["libcublas.so.11", "libcublasLt.so.11"],
            "within_runtime_root": True,
        },
        observed={
            "libraries": [str(path) if path is not None else None for path in cublas_libraries]
        },
    )

    runtime_library_dir = _library_directory(runtime_root)
    cudnn_header = _first_file(runtime_root, CUDNN_VERSION_HEADER_CANDIDATES)
    cudnn_version, cudnn_version_error = _read_define_version(
        cudnn_header,
        ("CUDNN_MAJOR", "CUDNN_MINOR", "CUDNN_PATCHLEVEL"),
    )
    cudnn_libraries = [runtime_library_dir / name for name in CUDNN_LIBRARY_NAMES]
    cudnn_layout_ok = all(
        path.is_file() and _is_within(path, runtime_root) for path in cudnn_libraries
    ) and cudnn_header is not None and _is_within(cudnn_header, runtime_root)
    add(
        runtime,
        "cudnn_layout_isolated",
        cudnn_layout_ok,
        expected={"libraries": list(CUDNN_LIBRARY_NAMES), "within_runtime_root": True},
        observed={
            "header": str(cudnn_header) if cudnn_header is not None else None,
            "libraries": {path.name: path.is_file() for path in cudnn_libraries},
        },
    )
    add(
        runtime,
        "cudnn_version",
        cudnn_version == CUDNN_EXPECTED_VERSION,
        expected={
            "header_version": list(CUDNN_EXPECTED_VERSION),
            "official_package_version": CUDNN_OFFICIAL_PACKAGE_VERSION,
        },
        observed={
            "error": cudnn_version_error,
            "header_version": list(cudnn_version) if cudnn_version is not None else None,
        },
    )

    tensorrt_header = _first_file(runtime_root, TENSORRT_VERSION_HEADER_CANDIDATES)
    tensorrt_version, tensorrt_version_error = _read_define_version(
        tensorrt_header,
        ("NV_TENSORRT_MAJOR", "NV_TENSORRT_MINOR", "NV_TENSORRT_PATCH"),
    )
    tensorrt_files = [runtime_root / relative_path for relative_path in TENSORRT_REQUIRED_FILES]
    tensorrt_layout_ok = (
        tensorrt_header is not None
        and _is_within(tensorrt_header, runtime_root)
        and all(path.is_file() and _is_within(path, runtime_root) for path in tensorrt_files)
    )
    add(
        runtime,
        "tensorrt_layout_isolated",
        tensorrt_layout_ok,
        expected={"files": list(TENSORRT_REQUIRED_FILES), "within_runtime_root": True},
        observed={
            "files": {str(path.relative_to(runtime_root)): path.is_file() for path in tensorrt_files},
            "version_header": str(tensorrt_header) if tensorrt_header is not None else None,
        },
    )
    add(
        runtime,
        "tensorrt_version",
        tensorrt_version == TENSORRT_EXPECTED_VERSION,
        expected=list(TENSORRT_EXPECTED_VERSION),
        observed={
            "error": tensorrt_version_error,
            "version": list(tensorrt_version) if tensorrt_version is not None else None,
        },
    )

    pangolin_version_file = _first_file(pangolin_root, PANGOLIN_VERSION_CANDIDATES)
    pangolin_version, pangolin_error = _read_pangolin_version(pangolin_version_file)
    try:
        pangolin_libraries = sorted(pangolin_root.joinpath("lib").glob("libpango_*.so*"))
        pangolin_libraries += sorted(pangolin_root.joinpath("lib").glob("libpangolin.so*"))
    except OSError:
        pangolin_libraries = []
    pangolin_layout_ok = (
        pangolin_root.is_dir()
        and pangolin_version_file is not None
        and _is_within(pangolin_version_file, pangolin_root)
        and bool(pangolin_libraries)
        and all(_is_within(path, pangolin_root) for path in pangolin_libraries)
    )
    add(
        runtime,
        "pangolin_layout_isolated",
        pangolin_layout_ok,
        expected={"minimum_version": list(PANGOLIN_MINIMUM_VERSION), "within_pangolin_root": True},
        observed={
            "library_count": len(pangolin_libraries),
            "path": str(pangolin_root),
            "version_file": str(pangolin_version_file) if pangolin_version_file is not None else None,
        },
    )
    pangolin_version_ok = (
        pangolin_version is not None and pangolin_version >= PANGOLIN_MINIMUM_VERSION
    )
    add(
        runtime,
        "pangolin_version",
        pangolin_version_ok,
        expected={"minimum": list(PANGOLIN_MINIMUM_VERSION)},
        observed={
            "error": pangolin_error,
            "version": list(pangolin_version) if pangolin_version is not None else None,
        },
    )

    binary_sha, binary_hash_error = _sha256(binary) if binary.is_file() else (None, "missing")
    elf_magic: bytes | None = None
    elf_error: str | None = None
    if binary.is_file():
        try:
            with binary.open("rb") as stream:
                elf_magic = stream.read(4)
        except OSError as exc:
            elf_error = type(exc).__name__
    binary_ok = (
        binary.is_file()
        and os.access(str(binary), os.X_OK)
        and elf_magic == b"\x7fELF"
        and _is_within(binary, repository)
    )
    add(
        runtime,
        "build_binary",
        binary_ok,
        expected={"elf": True, "executable": True, "within_official_repository": True},
        observed={
            "elf_magic_hex": elf_magic.hex() if elf_magic is not None else None,
            "error": elf_error,
            "executable": binary.is_file() and os.access(str(binary), os.X_OK),
            "path": str(binary),
            "sha256": binary_sha,
        },
    )
    add(
        informational,
        "build_binary_sha256",
        binary_sha is not None,
        expected={"record_observed_hash": True},
        observed={"error": binary_hash_error, "sha256": binary_sha},
    )

    library_dirs = (
        runtime_library_dir,
        runtime_root / "usr/local/cuda-11.6/lib64",
        runtime_root / "usr/local/cuda-11.6/targets/x86_64-linux/lib",
        runtime_root / "usr/local/cuda-11.8/lib64",
        runtime_root / "usr/local/cuda-11.8/targets/x86_64-linux/lib",
        pangolin_root / "lib",
        repository / "lib",
        repository / "Thirdparty/g2o/lib",
    )
    ld_library_path = ":".join(str(path) for path in library_dirs)
    if binary_ok:
        ldd = runner(
            [
                "/usr/bin/env",
                "-i",
                "PATH=/usr/bin:/bin",
                "LD_LIBRARY_PATH=" + ld_library_path,
                "/usr/bin/ldd",
                str(binary),
            ],
            None,
        )
    else:
        ldd = CommandResult(125, "", "binary unavailable")
    resolved, missing = _parse_ldd(ldd.stdout)
    dependency_groups = {
        "hfnet": any(name.startswith("libHFNet_SLAM.so") for name in resolved),
        "pangolin": any(
            name.startswith("libpango_") or name.startswith("libpangolin.so")
            for name in resolved
        ),
        "tensorrt": any(name.startswith("libnvinfer.so") for name in resolved),
        "tensorrt_plugin": any(
            name.startswith("libnvinfer_plugin.so") for name in resolved
        ),
        "onnx_parser": any(name.startswith("libnvonnxparser.so") for name in resolved),
        "cuda_runtime": any(name.startswith("libcudart.so") for name in resolved),
        "cublas": any(name.startswith("libcublas.so") for name in resolved),
        "cublas_lt": any(name.startswith("libcublasLt.so") for name in resolved),
        "cudnn": any(name.startswith("libcudnn.so") for name in resolved),
    }
    isolation_violations: dict[str, str] = {}
    for name, path_text in resolved.items():
        path = Path(path_text)
        if name.startswith(("libnvinfer.so", "libnvinfer_plugin.so", "libnvonnxparser.so", "libcudart.so", "libcudnn", "libcublas")):
            if not _is_within(path, runtime_root):
                isolation_violations[name] = path_text
        elif name.startswith(("libpango_", "libpangolin.so")):
            if not _is_within(path, pangolin_root):
                isolation_violations[name] = path_text
        elif name.startswith(("libHFNet_SLAM.so", "libg2o.so")):
            if not _is_within(path, repository):
                isolation_violations[name] = path_text
    ldd_ok = (
        ldd.returncode == 0
        and not missing
        and all(dependency_groups.values())
        and not isolation_violations
    )
    add(
        runtime,
        "build_binary_dependency_isolation",
        ldd_ok,
        expected={
            "all_dependencies_found": True,
            "groups": {name: True for name in dependency_groups},
            "nvidia_dependencies_within_runtime_root": True,
            "pangolin_dependencies_within_pangolin_root": True,
        },
        observed={
            "command": _command_observation(ldd),
            "groups": dependency_groups,
            "isolation_violations": isolation_violations,
            "missing": missing,
        },
    )

    display = environment.get("DISPLAY", "").strip()
    add(
        runtime,
        "viewer_display_declared",
        bool(display),
        expected={"DISPLAY_nonempty": True},
        observed={"DISPLAY": display or None},
    )

    output_exists = output_directory.exists() or output_directory.is_symlink()
    add(
        runtime,
        "output_directory_unreserved",
        not output_exists,
        expected={"exists": False},
        observed={"exists": output_exists, "path": str(output_directory)},
    )

    integrity_errors = sorted(
        check_id for check_id, check in integrity.items() if not check["ok"]
    )
    runtime_blockers = sorted(
        str(check.get("reason") or check_id)
        for check_id, check in runtime.items()
        if not check["ok"]
    )
    if integrity_errors:
        status = "INTEGRITY_ERROR"
        return_code = RC_INTEGRITY_ERROR
    elif runtime_blockers:
        status = "RUNTIME_BLOCKED"
        return_code = RC_RUNTIME_BLOCKED
    else:
        status = "READY"
        return_code = RC_READY

    return {
        "a02_prefix_adapter_contract": A02_PREFIX_CONTRACT,
        "baseline": {
            "doi": PUBLISHED_DOI,
            "execution_commit": EXECUTION_COMMIT,
            "execution_tree": EXECUTION_TREE,
            "official_repository": OFFICIAL_REPOSITORY,
            "paper_commit": PAPER_COMMIT,
            "paper_tree": PAPER_TREE,
            "postpublication_delta_classification": "official_author_build_repair_algorithm_equivalent",
        },
        "checks": {
            "informational": informational,
            "integrity": integrity,
            "runtime": runtime,
        },
        "integrity_errors": integrity_errors,
        "model_contract": {
            "archive_cache": OFFICIAL_ARCHIVE_CACHE_IDENTITY,
            "expected_onnx_filename": "HF-Net.onnx",
            "official_drive_file_id": "1P-mji-Ey2XnxFo7ZtLbBAfVoRL5t0SxY",
            "runtime_cache_policy": "do_not_reuse_archive_cache_on_new_gpu;copy_verified_onnx_to_fresh_writable_runtime_dir",
        },
        "paths": {
            "a02_camera": str(a02_camera),
            "a02_raw": str(a02_raw),
            "binary": str(binary),
            "model_archive": str(model_archive),
            "onnx_model": str(onnx_model),
            "output_directory": str(output_directory),
            "pangolin_root": str(pangolin_root),
            "repository": str(repository),
            "runtime_root": str(runtime_root),
        },
        "probe_boundary": {
            "compile_or_build_performed": False,
            "model_or_engine_loaded": False,
            "official_tree_modified": False,
            "preflight_scope": "identity_versions_elf_and_ldd_only",
            "short_prefix_materialization_allowed_before_runtime_ready": True,
            "slam_smoke_required_after_ready": True,
        },
        "ready": status == "READY",
        "repair_contract": {
            "changed_paths": list(AUTHOR_BUILD_REPAIR_PATHS),
            "first_repair_commit": AUTHOR_BUILD_REPAIR_COMMIT,
            "semantic_boundary": "build_files_missing_time_utilities_and_conditional_namespace_wrappers_only",
        },
        "return_code": return_code,
        "runtime_blockers": runtime_blockers,
        "schema_version": SCHEMA_VERSION,
        "status": status,
    }


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only preflight for official published HFNet-SLAM on A02."
    )
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPOSITORY)
    parser.add_argument("--model-archive", type=Path, default=DEFAULT_MODEL_ARCHIVE)
    parser.add_argument("--onnx-model", type=Path, default=DEFAULT_ONNX_MODEL)
    parser.add_argument("--a02-raw", type=Path, default=DEFAULT_A02_RAW)
    parser.add_argument("--a02-camera", type=Path, default=DEFAULT_A02_CAMERA)
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--pangolin-root", type=Path, default=DEFAULT_PANGOLIN_ROOT)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: CommandRunner = _default_runner,
    environment: Mapping[str, str] | None = None,
    expected_models: Mapping[str, Mapping[str, object]] = OFFICIAL_MODEL_IDENTITY,
    expected_inputs: Mapping[str, Mapping[str, object]] = OFFICIAL_INPUT_IDENTITY,
) -> int:
    args = build_argument_parser().parse_args(argv)
    decision = evaluate_preflight(
        repository=args.repo,
        model_archive=args.model_archive,
        onnx_model=args.onnx_model,
        a02_raw=args.a02_raw,
        a02_camera=args.a02_camera,
        runtime_root=args.runtime_root,
        pangolin_root=args.pangolin_root,
        binary=args.binary,
        output_directory=args.output_dir,
        runner=runner,
        environment=environment,
        expected_models=expected_models,
        expected_inputs=expected_inputs,
    )
    print(canonical_json(decision))
    return int(decision["return_code"])


if __name__ == "__main__":
    raise SystemExit(main())
