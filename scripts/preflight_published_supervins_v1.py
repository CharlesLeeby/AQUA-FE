#!/usr/bin/env python3
"""Read-only, fail-closed preflight for the published SuperVINS 1.0 baseline.

The checker never installs, downloads, builds, creates an output directory, or
modifies the official checkout.  Its sole output on a normal invocation is one
canonical JSON document on stdout.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]

SCHEMA_VERSION = "aqua-fe-published-supervins-v1-preflight-v1"
PUBLISHED_DOI = "10.1109/JSEN.2025.3556257"
OFFICIAL_REPOSITORY = "https://github.com/luohongk/SuperVINS.git"
PAPER_COMMIT = "91e85d72a3828844538715cc4b1cd4b86a2620db"

DEFAULT_REPOSITORY = Path("/home/ma/SLAM/SuperVINS-paper-1.0-r1")
DEFAULT_A02_RAW = ROOT / "datasets/aqualoc/rosbags/archaeo02_4500_5400.bag"
DEFAULT_A02_CAMERA = (
    ROOT
    / "datasets/full_downloads/aqualoc/Archaeological_site_sequences"
    / "archaeo_calibration_files/archaeo_camera_calib.yaml"
)
DEFAULT_ONNXRUNTIME_ROOT = Path("/opt/onnxruntime")
DEFAULT_OUTPUT_DIRECTORY = (
    ROOT / "logs/published_supervins_v1/aqualoc_archaeology_A02_0005"
)

CUDA_SOURCE = "supervins_estimator/src/featureTracker/extractor_matcher_dpl.cpp"
CUDA_PROVIDER_TOKEN = "AppendExecutionProvider_CUDA"
CUDA_ZERO_MEMORY_LIMIT_PATTERN = re.compile(
    rb"\bcuda_options\s*\.\s*gpu_mem_limit\s*=\s*0\s*;"
)
UPSTREAM_CUDA_MEMORY_LIMIT_ZERO = "UPSTREAM_CUDA_MEMORY_LIMIT_ZERO"
PAPER_COMMIT_ZERO_MEMORY_LIMIT_OCCURRENCES = 2

# These digests were computed from the byte contents at PAPER_COMMIT.  The CPU
# matcher export is intentionally not one of the four required paper/GPU model
# files because the unmodified 1.0 source registers the CUDA provider.
OFFICIAL_FILE_SHA256: Mapping[str, str] = {
    CUDA_SOURCE: "dfae6b3fdcb0a588d26d527ef0043c1a77f089305523f02f9bcc0b16ba88428f",
    "supervins_estimator/weights_dpl/disk.onnx": (
        "f02f18e254bd52d978981c715a4e7961f15afaa23290379b9b357f6745df12c4"
    ),
    "supervins_estimator/weights_dpl/disk_lightglue_fused.onnx": (
        "eff867103123a64720a1209218ff4bfa351a2d9b21a04b667265d794e9462cc9"
    ),
    "supervins_estimator/weights_dpl/superpoint.onnx": (
        "234d12c9f523292efb34e0ca513b011050b0c052700da9c01787b9356a1138d2"
    ),
    "supervins_estimator/weights_dpl/superpoint_lightglue_fused.onnx": (
        "8463182c165254b8cf182def813160691a5f3a455d95b4346e1b3ebf8a7709cf"
    ),
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

ONNXRUNTIME_GPU_LIBRARIES = (
    "lib/libonnxruntime.so",
    "lib/libonnxruntime_providers_shared.so",
    "lib/libonnxruntime_providers_cuda.so",
)
ONNXRUNTIME_EXPECTED_VERSION = "1.16.3"
ROS1_DISTRIBUTIONS = frozenset(
    {"boxer", "hydro", "indigo", "jade", "kinetic", "lunar", "melodic", "noetic"}
)

RC_READY = 0
RC_RUNTIME_BLOCKED = 1
RC_INTEGRITY_ERROR = 2


@dataclass(frozen=True)
class CommandResult:
    """Small subprocess result type used to make probes mockable in tests."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


CommandRunner = Callable[[Sequence[str], Optional[Path]], CommandResult]
LibraryProbe = Callable[
    [Sequence[Tuple[str, Path]]], Mapping[str, Mapping[str, object]]
]


_OrtGetApi = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_uint32)
_OrtGetVersionString = ctypes.CFUNCTYPE(ctypes.c_char_p)


class _OrtApiBase(ctypes.Structure):
    _fields_ = [
        ("GetApi", _OrtGetApi),
        ("GetVersionString", _OrtGetVersionString),
    ]


def _default_runner(command: Sequence[str], cwd: Path | None) -> CommandResult:
    env = dict(os.environ)
    # Prevent read-only Git probes such as status from opportunistically
    # refreshing or locking the external repository index.
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


def _missing_shared_object(error: str) -> str | None:
    match = re.search(
        r"(?P<name>[^\s/:]+\.so(?:\.[^\s/:]+)*): cannot open shared object file",
        error,
    )
    return match.group("name") if match is not None else None


def _ort_version_from_library(library: object) -> tuple[str | None, str | None]:
    try:
        get_api_base = library.OrtGetApiBase  # type: ignore[attr-defined]
        get_api_base.restype = ctypes.POINTER(_OrtApiBase)
        base = get_api_base()
        if not base:
            return None, "OrtGetApiBase returned null"
        raw = base.contents.GetVersionString()
        if not raw:
            return None, "GetVersionString returned null"
        return raw.decode("utf-8", errors="strict"), None
    except Exception as exc:  # ctypes exposes several exception subclasses.
        return None, f"{type(exc).__name__}:{exc}"[:400]


def _default_library_probe(
    libraries: Sequence[Tuple[str, Path]],
) -> Mapping[str, Mapping[str, object]]:
    """Dlopen ORT libraries in dependency order without creating a session."""

    observations: dict[str, dict[str, object]] = {}
    loaded_libraries: list[object] = []
    mode = getattr(ctypes, "RTLD_GLOBAL", 0)
    for relative_path, path in libraries:
        observation: dict[str, object] = {
            "error": None,
            "loaded": False,
            "missing_dependency": None,
            "version": None,
            "version_error": None,
        }
        try:
            library = ctypes.CDLL(str(path), mode=mode)
            loaded_libraries.append(library)
            observation["loaded"] = True
            if relative_path == "lib/libonnxruntime.so":
                version, version_error = _ort_version_from_library(library)
                observation["version"] = version
                observation["version_error"] = version_error
        except OSError as exc:
            error = str(exc)[:400]
            observation["error"] = error
            observation["missing_dependency"] = _missing_shared_object(error)
        except Exception as exc:
            observation["error"] = f"{type(exc).__name__}:{exc}"[:400]
        observations[relative_path] = observation
    # Keep handles alive until every provider has been probed; the CUDA provider
    # may resolve symbols from the previously loaded shared provider.
    del loaded_libraries
    return observations


def _extract_semver(value: str) -> str | None:
    match = re.search(r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)", value)
    return match.group(1) if match is not None else None


def _onnxruntime_version_sources(
    root: Path, library_observations: Mapping[str, Mapping[str, object]]
) -> dict[str, str]:
    sources: dict[str, str] = {}
    core = library_observations.get("lib/libonnxruntime.so")
    if core is not None:
        raw_version = core.get("version")
        if isinstance(raw_version, str):
            version = _extract_semver(raw_version)
            if version is not None:
                sources["OrtGetApiBase.GetVersionString"] = version

    metadata_paths = (
        root / "VERSION_NUMBER",
        root / "VERSION",
        root / "version.txt",
        root / "lib/pkgconfig/libonnxruntime.pc",
    )
    for path in metadata_paths:
        if not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace") as stream:
                content = stream.read(16384)
        except OSError:
            continue
        version = _extract_semver(content)
        if version is not None:
            sources["metadata:" + str(path.relative_to(root))] = version

    library_dir = root / "lib"
    if library_dir.is_dir():
        try:
            candidates = sorted(library_dir.glob("libonnxruntime.so.*"))
        except OSError:
            candidates = []
        for path in candidates:
            version = _extract_semver(path.name)
            if version is not None:
                sources["filename:" + path.name] = version
    return sources


def _sha256(path: Path) -> tuple[str | None, str | None]:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        return None, type(exc).__name__
    return digest.hexdigest(), None


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


def evaluate_preflight(
    *,
    repository: Path,
    a02_raw: Path,
    a02_camera: Path,
    onnxruntime_root: Path,
    output_directory: Path,
    runner: CommandRunner = _default_runner,
    expected_files: Mapping[str, str] = OFFICIAL_FILE_SHA256,
    expected_inputs: Mapping[str, Mapping[str, object]] = OFFICIAL_INPUT_IDENTITY,
    library_probe: LibraryProbe = _default_library_probe,
) -> dict[str, object]:
    """Evaluate the frozen identity and runtime without changing any path."""

    repository = _absolute(repository)
    a02_raw = _absolute(a02_raw)
    a02_camera = _absolute(a02_camera)
    onnxruntime_root = _absolute(onnxruntime_root)
    output_directory = _absolute(output_directory)

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
        check = {
            "expected": expected,
            "observed": observed,
            "ok": bool(ok),
        }
        if reason is not None:
            check["reason"] = reason
        target[check_id] = check

    repo_exists = repository.is_dir()
    add(
        integrity,
        "repository_exists",
        repo_exists,
        expected=True,
        observed=repo_exists,
    )

    git_worktree = CommandResult(125, "", "repository missing")
    git_head = CommandResult(125, "", "repository missing")
    git_origin = CommandResult(125, "", "repository missing")
    git_status = CommandResult(125, "", "repository missing")
    if repo_exists:
        git_prefix = ["git", "-C", str(repository)]
        git_worktree = runner([*git_prefix, "rev-parse", "--is-inside-work-tree"], None)
        git_head = runner([*git_prefix, "rev-parse", "HEAD"], None)
        git_origin = runner([*git_prefix, "config", "--get", "remote.origin.url"], None)
        git_status = runner(
            [
                *git_prefix,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--ignore-submodules=none",
            ],
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
        git_head.returncode == 0 and observed_head == PAPER_COMMIT,
        expected=PAPER_COMMIT,
        observed=observed_head if observed_head is not None else _command_observation(git_head),
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
        observed=(
            observed_origin if observed_origin is not None else _command_observation(git_origin)
        ),
    )

    dirty_lines = [line for line in git_status.stdout.splitlines() if line.strip()]
    clean = git_status.returncode == 0 and not dirty_lines
    status_observed: object
    if git_status.returncode == 0:
        status_observed = {"entries": dirty_lines[:20], "entry_count": len(dirty_lines)}
    else:
        status_observed = _command_observation(git_status)
    add(
        integrity,
        "repository_clean",
        clean,
        expected={"entry_count": 0},
        observed=status_observed,
    )

    for relative_path, expected_sha in sorted(expected_files.items()):
        path = repository / relative_path
        check_id = "file_sha256:" + relative_path
        if not path.is_file():
            add(
                integrity,
                check_id,
                False,
                expected=expected_sha,
                observed=None,
            )
            continue
        observed_sha, read_error = _sha256(path)
        observed: object = observed_sha
        if read_error is not None:
            observed = {"error": read_error, "sha256": None}
        add(
            integrity,
            check_id,
            observed_sha == expected_sha,
            expected=expected_sha,
            observed=observed,
        )

    source_path = repository / CUDA_SOURCE
    provider_count: int | None = None
    zero_memory_limit_count: int | None = None
    source_error: str | None = None
    try:
        source_bytes = source_path.read_bytes()
        provider_count = source_bytes.count(CUDA_PROVIDER_TOKEN.encode("ascii"))
        zero_memory_limit_count = len(CUDA_ZERO_MEMORY_LIMIT_PATTERN.findall(source_bytes))
    except OSError as exc:
        source_error = type(exc).__name__
    add(
        integrity,
        "official_source_registers_cuda_provider",
        provider_count is not None and provider_count > 0,
        expected={"minimum_occurrences": 1, "token": CUDA_PROVIDER_TOKEN},
        observed=(
            {"occurrences": provider_count}
            if source_error is None
            else {"error": source_error, "occurrences": None}
        ),
    )

    upstream_zero_limit_defect = (
        zero_memory_limit_count is not None and zero_memory_limit_count > 0
    )
    add(
        runtime,
        "upstream_runtime_defect",
        zero_memory_limit_count == 0,
        expected={"gpu_mem_limit_zero_occurrences": 0},
        observed=(
            {
                "gpu_mem_limit_zero_occurrences": zero_memory_limit_count,
                "paper_commit_occurrences": PAPER_COMMIT_ZERO_MEMORY_LIMIT_OCCURRENCES,
            }
            if source_error is None
            else {
                "error": source_error,
                "gpu_mem_limit_zero_occurrences": None,
                "paper_commit_occurrences": PAPER_COMMIT_ZERO_MEMORY_LIMIT_OCCURRENCES,
            }
        ),
        reason=(
            UPSTREAM_CUDA_MEMORY_LIMIT_ZERO if upstream_zero_limit_defect else None
        ),
    )

    def add_input_identity(input_id: str, path: Path) -> None:
        oracle = expected_inputs.get(input_id)
        expected_size = oracle.get("size_bytes") if oracle is not None else None
        expected_sha = oracle.get("sha256") if oracle is not None else None
        exists = path.is_file()
        add(
            integrity,
            "input_identity:" + input_id + ":exists",
            exists,
            expected=True,
            observed=exists,
        )
        observed_size: int | None = None
        observed_sha: str | None = None
        read_error: str | None = None
        if exists:
            try:
                observed_size = path.stat().st_size
            except OSError as exc:
                read_error = type(exc).__name__
            observed_sha, hash_error = _sha256(path)
            if hash_error is not None:
                read_error = hash_error
        add(
            integrity,
            "input_identity:" + input_id + ":size_bytes",
            isinstance(expected_size, int) and observed_size == expected_size,
            expected=expected_size,
            observed=(
                observed_size
                if read_error is None
                else {"error": read_error, "size_bytes": observed_size}
            ),
        )
        add(
            integrity,
            "input_identity:" + input_id + ":sha256",
            isinstance(expected_sha, str) and observed_sha == expected_sha,
            expected=expected_sha,
            observed=(
                observed_sha
                if read_error is None
                else {"error": read_error, "sha256": observed_sha}
            ),
        )

    add_input_identity("a02_raw", a02_raw)
    add_input_identity("a02_camera", a02_camera)

    ros = runner(["rosversion", "-d"], None)
    ros_distro = ros.stdout.strip().lower()
    ros_ok = ros.returncode == 0 and ros_distro in ROS1_DISTRIBUTIONS
    add(
        runtime,
        "ros1_available",
        ros_ok,
        expected=sorted(ROS1_DISTRIBUTIONS),
        observed=(ros_distro if ros.returncode == 0 else _command_observation(ros)),
    )

    gpu = runner(
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], None
    )
    gpu_names = [line.strip() for line in gpu.stdout.splitlines() if line.strip()]
    gpu_ok = gpu.returncode == 0 and bool(gpu_names)
    add(
        runtime,
        "nvidia_gpu_available",
        gpu_ok,
        expected={"minimum_gpu_count": 1},
        observed=(
            {"gpu_count": len(gpu_names), "names": gpu_names}
            if gpu.returncode == 0
            else _command_observation(gpu)
        ),
    )

    nvcc = runner(["nvcc", "--version"], None)
    nvcc_ok = nvcc.returncode == 0 and "release" in nvcc.stdout.lower()
    add(
        informational,
        "nvcc_available",
        nvcc_ok,
        expected={"returncode": 0, "version_contains": "release"},
        observed=_command_observation(nvcc),
    )

    ort_root_exists = onnxruntime_root.is_dir()
    add(
        runtime,
        "onnxruntime_gpu_root_exists",
        ort_root_exists,
        expected=True,
        observed=ort_root_exists,
    )
    library_paths = [
        (relative_path, onnxruntime_root / relative_path)
        for relative_path in ONNXRUNTIME_GPU_LIBRARIES
    ]
    for relative_path, library in library_paths:
        exists = library.is_file()
        add(
            runtime,
            "onnxruntime_gpu_library:" + relative_path,
            exists,
            expected=True,
            observed=exists,
        )

    try:
        library_observations = library_probe(library_paths)
    except Exception as exc:
        library_observations = {
            relative_path: {
                "error": f"{type(exc).__name__}:{exc}"[:400],
                "loaded": False,
                "missing_dependency": None,
                "version": None,
                "version_error": None,
            }
            for relative_path, _ in library_paths
        }
    for relative_path, library in library_paths:
        observation = dict(library_observations.get(relative_path, {}))
        loaded = observation.get("loaded") is True
        add(
            runtime,
            "onnxruntime_gpu_dlopen:" + relative_path,
            library.is_file() and loaded,
            expected={"dlopen": True},
            observed=observation,
        )

    version_sources = _onnxruntime_version_sources(
        onnxruntime_root, library_observations
    )
    unique_versions = sorted(set(version_sources.values()))
    version_ok = bool(unique_versions) and unique_versions == [
        ONNXRUNTIME_EXPECTED_VERSION
    ]
    add(
        runtime,
        "onnxruntime_gpu_version",
        version_ok,
        expected=ONNXRUNTIME_EXPECTED_VERSION,
        observed={
            "sources": version_sources,
            "unique_versions": unique_versions,
        },
    )

    output_exists = output_directory.exists() or output_directory.is_symlink()
    add(
        runtime,
        "output_directory_unreserved",
        not output_exists,
        expected={"exists": False},
        observed={"exists": output_exists},
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
        "baseline": {
            "doi": PUBLISHED_DOI,
            "paper_commit": PAPER_COMMIT,
            "repository": OFFICIAL_REPOSITORY,
        },
        "checks": {
            "informational": informational,
            "integrity": integrity,
            "runtime": runtime,
        },
        "integrity_errors": integrity_errors,
        "paths": {
            "a02_camera": str(a02_camera),
            "a02_raw": str(a02_raw),
            "onnxruntime_root": str(onnxruntime_root),
            "output_directory": str(output_directory),
            "repository": str(repository),
        },
        "ready": status == "READY",
        "probe_boundary": {
            "preflight_scope": "identity_version_and_dlopen_only",
            "session_smoke_required_after_ready": True,
            "session_smoke_scope": "official_model_OrtSession_construction_and_inference",
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
        description="Read-only preflight for the official published SuperVINS 1.0 baseline."
    )
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPOSITORY)
    parser.add_argument("--a02-raw", type=Path, default=DEFAULT_A02_RAW)
    parser.add_argument("--a02-camera", type=Path, default=DEFAULT_A02_CAMERA)
    parser.add_argument(
        "--onnxruntime-root", type=Path, default=DEFAULT_ONNXRUNTIME_ROOT
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIRECTORY
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: CommandRunner = _default_runner,
    expected_files: Mapping[str, str] = OFFICIAL_FILE_SHA256,
    expected_inputs: Mapping[str, Mapping[str, object]] = OFFICIAL_INPUT_IDENTITY,
    library_probe: LibraryProbe = _default_library_probe,
) -> int:
    args = build_argument_parser().parse_args(argv)
    decision = evaluate_preflight(
        repository=args.repo,
        a02_raw=args.a02_raw,
        a02_camera=args.a02_camera,
        onnxruntime_root=args.onnxruntime_root,
        output_directory=args.output_dir,
        runner=runner,
        expected_files=expected_files,
        expected_inputs=expected_inputs,
        library_probe=library_probe,
    )
    print(canonical_json(decision))
    return int(decision["return_code"])


if __name__ == "__main__":
    raise SystemExit(main())
