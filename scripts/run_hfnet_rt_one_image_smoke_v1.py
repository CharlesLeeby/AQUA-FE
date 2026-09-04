#!/usr/bin/env python3
"""Fail-closed runner for one official HFNet-SLAM TensorRT extraction.

The CLI deliberately exposes only the no-clobber result directory.  Source,
shared library, harness, model, image, detector parameters, GPU index, and
timeout are frozen here.  A run creates no trajectory and is never an
evaluable SLAM result.

Return codes are part of the experiment contract:

* 0: the four official models initialized and one official HFextractor call
  returned valid local/global descriptors;
* 1: execution started, but TensorRT/model/Detect/output postconditions failed;
* 2: no-clobber, identity, provenance, linkage, or preflight contract blocked
  execution (or immutable inputs drifted while execution was in flight).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import stat
import struct
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]

SCHEMA_VERSION = "aqua-fe-published-hfnet-rt-one-image-smoke-v1"
RAW_SCHEMA_VERSION = "aqua-fe-published-hfnet-rt-one-image-smoke-raw-v1"
BUILD_SCHEMA_VERSION = "aqua-fe-published-hfnet-rt-one-image-smoke-build-v1"
PUBLISHED_DOI = "10.3390/s23042113"
OFFICIAL_REPOSITORY = "https://github.com/LiuLimingCode/HFNet_SLAM.git"
EXECUTION_COMMIT = "c354c72588a97bb6f6a9c7c8317530795956ec80"
EXECUTION_TREE = "6619814aed4cd0e4baa2501341a48f753f8ba196"

DEFAULT_OFFICIAL_ROOT = Path("/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1")
DEFAULT_OFFICIAL_LIBRARY = DEFAULT_OFFICIAL_ROOT / "lib/libHFNet_SLAM.so"
DEFAULT_RUNTIME_ROOT = Path("/home/ma/opt/hfnet_cuda116_trt851_r1")
DEFAULT_PANGOLIN_ROOT = Path("/home/ma/SLAM/aqua_deps/install")
DEFAULT_MODEL_DIRECTORY = Path(
    "/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT"
)
DEFAULT_ONNX_MODEL = DEFAULT_MODEL_DIRECTORY / "HF-Net.onnx"
DEFAULT_MODEL_CACHE = DEFAULT_MODEL_DIRECTORY / "HF-Net.cache"
DEFAULT_INPUT_IMAGE = (
    ROOT
    / "logs/hfnet_slam_adapter/aqualoc_a02_0005_prefix200_euroc_v1"
    / "mav0/cam0/data/1542829016700435392.png"
)
DEFAULT_HARNESS_SOURCE = (
    ROOT / "scripts/harnesses/hfnet_rt_one_image_smoke_v1.cc"
)
DEFAULT_BUILD_DIRECTORY = (
    ROOT / "build/published_baselines/hfnet_rt_one_image_smoke_v1"
)
DEFAULT_HARNESS_BINARY = (
    DEFAULT_BUILD_DIRECTORY / "hfnet_rt_one_image_smoke_v1"
)
DEFAULT_BUILD_MANIFEST = DEFAULT_BUILD_DIRECTORY / "build_manifest.json"
DEFAULT_OUTPUT_ROOT = ROOT / "logs/published_hfnet_slam_v1/model_smokes"
DEFAULT_OUTPUT_DIRECTORY = DEFAULT_OUTPUT_ROOT / "aqualoc_a02_0005_frame000_r1"

EXPECTED_IMAGE_IDENTITY = {
    "size_bytes": 223593,
    "sha256": "4e325724a707046af87f9290c1da9fda32f74885532046b497b008f1b853f95a",
}
EXPECTED_ONNX_IDENTITY = {
    "size_bytes": 132238602,
    "sha256": "354a23f9c28b75ea9056a8eb5586e3b13191426521fd3f5556e5bfd670fc39b5",
}
EXPECTED_IMAGE_PNG = {
    "bit_depth": 8,
    "color_type": 0,
    "height": 608,
    "width": 968,
}

OFFICIAL_SOURCE_SHA256: Mapping[str, str] = {
    "CMakeLists.txt": "8f51fbcb9ed8182e5ab6998d1ad73aec0df685759174f9c910636d2c971b259e",
    "include/Extractors/BaseModel.h": "df1f8e44d22fd6601d25bda4313c06ec1a8fb7527b6b3ff29b85fbab0cc21097",
    "include/Extractors/HFNetRTModel.h": "219c8329ff07fe0e778de070d56651042f8206a918b0d260db3dce7f16187b98",
    "include/Extractors/HFextractor.h": "19ede41c601ad7012bd8a669f48afbb5c548a0b73c620a2a731a6bb1468d2d63",
    "src/Extractors/BaseModel.cc": "677628c45e1c1707d8bdc82a7fffc51dc1ea0f852c4338dfe13c138cddde74ae",
    "src/Extractors/HFNetRTModel.cc": "a903a8ac84ad9f7c14e707091acf5fee25ab511607b9377baffebad8df135155",
    "src/Extractors/HFextractor.cc": "7aa8f0a3b00930fdbd6f18f6433b721d2f148f60df77c5c51ae8337b389821c8",
}

RUNTIME_REQUIRED_RELATIVE = (
    "usr/local/cuda-11.6/include/cuda_runtime_api.h",
    "usr/local/cuda-11.6/lib64/libcudart.so.11.0",
    "usr/local/cuda-11.8/lib64/libcublas.so.11",
    "usr/local/cuda-11.8/lib64/libcublasLt.so.11",
    "usr/include/x86_64-linux-gnu/NvInfer.h",
    "usr/include/x86_64-linux-gnu/NvOnnxParser.h",
    "usr/lib/x86_64-linux-gnu/libnvinfer.so",
    "usr/lib/x86_64-linux-gnu/libnvinfer.so.8.5.1",
    "usr/lib/x86_64-linux-gnu/libnvinfer_plugin.so.8.5.1",
    "usr/lib/x86_64-linux-gnu/libnvonnxparser.so",
    "usr/lib/x86_64-linux-gnu/libnvonnxparser.so.8.5.1",
    "usr/lib/x86_64-linux-gnu/libcudnn.so.8.4.1",
    "usr/lib/x86_64-linux-gnu/libcudnn_adv_infer.so.8.4.1",
    "usr/lib/x86_64-linux-gnu/libcudnn_cnn_infer.so.8.4.1",
    "usr/lib/x86_64-linux-gnu/libcudnn_ops_infer.so.8.4.1",
)

LEVELS = 4
FEATURES = 675
SCALE_FACTOR = 1.2
THRESHOLD = 0.01
GPU_INDEX = "0"
GPU_NAME_TOKEN = "GTX 1650"
TIMEOUT_SECONDS = 1800

RC_PASS = 0
RC_EXECUTION_FAILED = 1
RC_CONTRACT_BLOCKED = 2


@dataclass(frozen=True)
class SmokeContract:
    official_root: Path
    official_library: Path
    runtime_root: Path
    pangolin_root: Path
    model_directory: Path
    onnx_model: Path
    model_cache: Path
    input_image: Path
    harness_source: Path
    harness_binary: Path
    build_manifest: Path
    allowed_output_root: Path
    expected_commit: str = EXECUTION_COMMIT
    expected_tree: str = EXECUTION_TREE
    expected_image: Mapping[str, object] = None  # type: ignore[assignment]
    expected_onnx: Mapping[str, object] = None  # type: ignore[assignment]
    expected_png: Mapping[str, object] = None  # type: ignore[assignment]
    expected_source_sha256: Mapping[str, str] = None  # type: ignore[assignment]
    gpu_name_token: str = GPU_NAME_TOKEN

    def __post_init__(self) -> None:
        if self.expected_image is None:
            object.__setattr__(self, "expected_image", EXPECTED_IMAGE_IDENTITY)
        if self.expected_onnx is None:
            object.__setattr__(self, "expected_onnx", EXPECTED_ONNX_IDENTITY)
        if self.expected_png is None:
            object.__setattr__(self, "expected_png", EXPECTED_IMAGE_PNG)
        if self.expected_source_sha256 is None:
            object.__setattr__(
                self, "expected_source_sha256", OFFICIAL_SOURCE_SHA256
            )


DEFAULT_CONTRACT = SmokeContract(
    official_root=DEFAULT_OFFICIAL_ROOT,
    official_library=DEFAULT_OFFICIAL_LIBRARY,
    runtime_root=DEFAULT_RUNTIME_ROOT,
    pangolin_root=DEFAULT_PANGOLIN_ROOT,
    model_directory=DEFAULT_MODEL_DIRECTORY,
    onnx_model=DEFAULT_ONNX_MODEL,
    model_cache=DEFAULT_MODEL_CACHE,
    input_image=DEFAULT_INPUT_IMAGE,
    harness_source=DEFAULT_HARNESS_SOURCE,
    harness_binary=DEFAULT_HARNESS_BINARY,
    build_manifest=DEFAULT_BUILD_MANIFEST,
    allowed_output_root=DEFAULT_OUTPUT_ROOT,
)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


ProbeRunner = Callable[
    [Sequence[str], Optional[Mapping[str, str]], Optional[Path]], CommandResult
]
ExecuteRunner = Callable[
    [Sequence[str], Mapping[str, str], Optional[Path], int], CommandResult
]
Clock = Callable[[], str]


def canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ) + "\n"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


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


def _identity(path: Path) -> dict[str, object]:
    return {
        "path": str(_absolute(path)),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _identity_matches(
    observed: Mapping[str, object] | None, expected: Mapping[str, object]
) -> bool:
    return observed is not None and all(
        observed.get(key) == value for key, value in expected.items()
    )


def _safe_identity(path: Path) -> tuple[dict[str, object] | None, str | None]:
    try:
        if not path.is_file() or path.is_symlink():
            return None, "not_regular_nonsymlink_file"
        return _identity(path), None
    except OSError as error:
        return None, f"{type(error).__name__}:{error}"


def _png_header(path: Path) -> tuple[dict[str, int] | None, str | None]:
    try:
        with path.open("rb") as stream:
            header = stream.read(33)
    except OSError as error:
        return None, f"{type(error).__name__}:{error}"
    if len(header) < 33 or header[:8] != b"\x89PNG\r\n\x1a\n":
        return None, "not_png"
    length = struct.unpack(">I", header[8:12])[0]
    if length != 13 or header[12:16] != b"IHDR":
        return None, "invalid_ihdr"
    width, height = struct.unpack(">II", header[16:24])
    return {
        "bit_depth": header[24],
        "color_type": header[25],
        "height": height,
        "width": width,
    }, None


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


def _runtime_library_paths(contract: SmokeContract) -> tuple[Path, ...]:
    return (
        contract.official_root / "lib",
        contract.official_root / "Thirdparty/g2o/lib",
        contract.pangolin_root / "lib",
        contract.runtime_root / "usr/lib/x86_64-linux-gnu",
        contract.runtime_root / "usr/local/cuda-11.6/lib64",
        contract.runtime_root
        / "usr/local/cuda-11.6/targets/x86_64-linux/lib",
        contract.runtime_root / "usr/local/cuda-11.8/lib64",
        contract.runtime_root
        / "usr/local/cuda-11.8/targets/x86_64-linux/lib",
    )


def _runtime_environment(contract: SmokeContract) -> dict[str, str]:
    preserved = ("HOME", "LANG", "LC_ALL", "PATH", "TMPDIR", "USER")
    environment = {
        name: os.environ[name] for name in preserved if name in os.environ
    }
    environment.setdefault("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
    environment["CUDA_VISIBLE_DEVICES"] = GPU_INDEX
    environment["LANG"] = "C"
    environment["LC_ALL"] = "C"
    environment["LD_LIBRARY_PATH"] = ":".join(
        str(_absolute(path)) for path in _runtime_library_paths(contract)
    )
    return environment


def _parse_ldd(value: str) -> tuple[dict[str, str], list[str]]:
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "=> not found" in line:
            missing.append(line.split("=>", 1)[0].strip())
            continue
        if "=>" in line:
            name, remainder = line.split("=>", 1)
            path = remainder.strip().split(" ", 1)[0]
            resolved[name.strip()] = path
    return resolved, missing


def _write_exclusive(path: Path, payload: bytes, mode: int = 0o444) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    os.chmod(path, mode)


def _copy_exclusive(source: Path, destination: Path) -> None:
    descriptor = os.open(
        destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400
    )
    try:
        with source.open("rb") as input_stream, os.fdopen(
            descriptor, "wb", closefd=False
        ) as output_stream:
            shutil.copyfileobj(input_stream, output_stream, 1024 * 1024)
            output_stream.flush()
            os.fsync(output_stream.fileno())
    finally:
        os.close(descriptor)
    os.chmod(destination, 0o444)


def _load_canonical_json(path: Path) -> tuple[object | None, str | None]:
    try:
        content = path.read_text(encoding="utf-8")
        value = json.loads(content)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return None, f"{type(error).__name__}:{error}"
    if content != canonical_json(value):
        return None, "json_not_canonical"
    return value, None


def _command_observation(result: CommandResult) -> dict[str, object]:
    return {
        "returncode": result.returncode,
        "stderr": result.stderr.strip()[:800],
        "stdout": result.stdout.strip()[:800],
        "timed_out": result.timed_out,
    }


def _validate_raw_result(value: object) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if not isinstance(value, dict):
        return False, ["raw_result_not_object"]
    if value.get("schema_version") != RAW_SCHEMA_VERSION:
        failures.append("raw_schema_mismatch")
    if value.get("ok") is not True:
        failures.append("raw_ok_not_true")
    if value.get("frontend_invocations") != 1:
        failures.append("frontend_invocation_count_not_one")
    if value.get("official_level_detect_invocations") != 4:
        failures.append("official_level_detect_count_not_four")
    parameters = value.get("fixed_parameters")
    if not isinstance(parameters, dict):
        failures.append("fixed_parameters_missing")
    else:
        if parameters.get("features") != FEATURES:
            failures.append("features_drift")
        if parameters.get("levels") != LEVELS:
            failures.append("levels_drift")
        scale = parameters.get("scale_factor")
        if not isinstance(scale, (int, float)) or not math.isclose(
            float(scale), SCALE_FACTOR, rel_tol=0.0, abs_tol=1e-6
        ):
            failures.append("scale_factor_drift")
        threshold = parameters.get("threshold")
        if not isinstance(threshold, (int, float)) or not math.isclose(
            float(threshold), THRESHOLD, rel_tol=0.0, abs_tol=1e-8
        ):
            failures.append("threshold_drift")
    output = value.get("detect_output")
    if not isinstance(output, dict):
        failures.append("detect_output_missing")
    else:
        count = output.get("keypoint_count")
        if not isinstance(count, int) or not 1 <= count <= FEATURES:
            failures.append("keypoint_count_invalid")
        if output.get("local_descriptor_rows") != count:
            failures.append("local_descriptor_rows_invalid")
        if output.get("local_descriptor_cols") != 256:
            failures.append("local_descriptor_cols_invalid")
        if output.get("global_descriptor_rows") != 4096:
            failures.append("global_descriptor_rows_invalid")
        if output.get("global_descriptor_cols") != 1:
            failures.append("global_descriptor_cols_invalid")
    return not failures, failures


def _validate_build_manifest(
    value: object,
    contract: SmokeContract,
    harness_identity: Mapping[str, object] | None,
    harness_source_identity: Mapping[str, object] | None,
    official_library_identity: Mapping[str, object] | None,
) -> bool:
    if not isinstance(value, dict):
        return False
    binary = value.get("binary")
    harness_source = value.get("harness_source")
    official_library = value.get("official_library")
    official_source = value.get("official_source")
    runtime_roots = value.get("runtime_roots")
    compile_contract = value.get("compile_contract")
    if not all(
        isinstance(item, dict)
        for item in (
            binary,
            harness_source,
            official_library,
            official_source,
            runtime_roots,
            compile_contract,
        )
    ):
        return False
    assert isinstance(binary, dict)
    assert isinstance(harness_source, dict)
    assert isinstance(official_library, dict)
    assert isinstance(official_source, dict)
    assert isinstance(runtime_roots, dict)
    assert isinstance(compile_contract, dict)
    source_files = official_source.get("files")
    if not isinstance(source_files, dict):
        return False
    for relative, expected_hash in contract.expected_source_sha256.items():
        entry = source_files.get(relative)
        if not isinstance(entry, dict):
            return False
        if entry.get("sha256") != expected_hash:
            return False
        if _absolute(Path(str(entry.get("path", "")))) != _absolute(
            contract.official_root / relative
        ):
            return False
    return (
        value.get("schema_version") == BUILD_SCHEMA_VERSION
        and binary.get("sha256") == (harness_identity or {}).get("sha256")
        and binary.get("size_bytes")
        == (harness_identity or {}).get("size_bytes")
        and _absolute(Path(str(binary.get("path", ""))))
        == _absolute(contract.harness_binary)
        and harness_source.get("sha256")
        == (harness_source_identity or {}).get("sha256")
        and _absolute(Path(str(harness_source.get("path", ""))))
        == _absolute(contract.harness_source)
        and official_library.get("sha256")
        == (official_library_identity or {}).get("sha256")
        and _absolute(Path(str(official_library.get("path", ""))))
        == _absolute(contract.official_library)
        and official_source.get("commit") == contract.expected_commit
        and official_source.get("tree") == contract.expected_tree
        and official_source.get("tracked_worktree_clean") is True
        and _absolute(Path(str(official_source.get("root", ""))))
        == _absolute(contract.official_root)
        and runtime_roots.get("isolated_cuda_tensorrt")
        == str(contract.runtime_root)
        and runtime_roots.get("pangolin") == str(contract.pangolin_root)
        and compile_contract
        == {
            "defines": ["NDEBUG", "USE_TENSORRT"],
            "direct_shared_library": "libHFNet_SLAM.so",
            "language_standard": "c++14",
            "optimization": "O2",
        }
    )


def _base_result(contract: SmokeContract, output_directory: Path, started: str) -> dict[str, object]:
    return {
        "artifacts": {},
        "baseline": {
            "implementation": "author_official_HFNet_SLAM",
            "official_repository": OFFICIAL_REPOSITORY,
            "paper_doi": PUBLISHED_DOI,
            "source_commit": contract.expected_commit,
            "source_tree": contract.expected_tree,
        },
        "checks": {},
        "contract": {
            "detect_scope": "one_frozen_image_one_official_frontend_invocation",
            "features": FEATURES,
            "gpu_index": int(GPU_INDEX),
            "input_image": str(_absolute(contract.input_image)),
            "levels": LEVELS,
            "model_directory": str(_absolute(contract.model_directory)),
            "onnx_only_before_execution": True,
            "scale_factor": SCALE_FACTOR,
            "threshold": THRESHOLD,
            "timeout_seconds": TIMEOUT_SECONDS,
        },
        "evaluable": False,
        "execution": {
            "command_started": False,
            "returncode": None,
            "timed_out": False,
        },
        "finished_utc": None,
        "harness_boundary": {
            "algorithm_or_official_source_modified": False,
            "external_harness_reason": [
                "official_test_extractors_randomly_selects_images",
                "official_random_index_distribution_includes_files_size",
                "official_test_extractors_uses_GUI_and_waitKey",
                "official_test_extractors_waits_for_interactive_input",
                "official_test_extractors_continues_over_the_dataset",
            ],
            "official_calls": [
                "ORB_SLAM3::InitAllModels(kHFNetRTModel,levels=4,scale=1.2)",
                "ORB_SLAM3::HFextractor(features=675,threshold=0.01)",
            ],
            "official_utility_reused": False,
            "official_utility_reviewed": "Examples/Utility/test_extractors.cc",
        },
        "hashes": {},
        "output_directory": str(_absolute(output_directory)),
        "return_code": None,
        "schema_version": SCHEMA_VERSION,
        "scope": "MODEL_RUNTIME_SMOKE_ONLY",
        "started_utc": started,
        "status": "IN_PROGRESS",
        "trajectory_generated": False,
    }


def run_smoke(
    *,
    contract: SmokeContract = DEFAULT_CONTRACT,
    output_directory: Path = DEFAULT_OUTPUT_DIRECTORY,
    probe_runner: ProbeRunner = _default_probe,
    execute_runner: ExecuteRunner = _default_execute,
    clock: Clock = _utc_now,
) -> dict[str, object]:
    """Evaluate the frozen contract and, only if ready, invoke the harness."""

    output_directory = _absolute(output_directory)
    started = clock()
    result = _base_result(contract, output_directory, started)
    checks = result["checks"]
    assert isinstance(checks, dict)
    failures: list[str] = []
    runner_log: list[str] = ["scope=MODEL_RUNTIME_SMOKE_ONLY"]
    output_owned = False

    def add_check(
        name: str,
        ok: bool,
        *,
        expected: object = None,
        observed: object = None,
    ) -> None:
        checks[name] = {
            "expected": expected,
            "observed": observed,
            "ok": bool(ok),
        }
        if not ok:
            failures.append(name)
            runner_log.append("FAIL " + name)
        else:
            runner_log.append("PASS " + name)

    def finalize(status_value: str, return_code: int) -> dict[str, object]:
        result["finished_utc"] = clock()
        result["return_code"] = return_code
        result["status"] = status_value
        result["failures"] = list(failures)
        if output_owned:
            for filename in ("harness.stdout.log", "harness.stderr.log"):
                path = output_directory / filename
                if not path.exists():
                    _write_exclusive(path, b"")
            runner_log_path = output_directory / "runner.log"
            if not runner_log_path.exists():
                _write_exclusive(
                    runner_log_path,
                    ("\n".join(runner_log) + "\n").encode("utf-8"),
                )
            artifacts = result["artifacts"]
            assert isinstance(artifacts, dict)
            for key, filename in (
                ("harness_stdout", "harness.stdout.log"),
                ("harness_stderr", "harness.stderr.log"),
                ("runner_log", "runner.log"),
                ("raw_harness_result", "raw_harness_result.json"),
                ("timing_cache", "HF-Net.cache"),
            ):
                path = output_directory / filename
                if path.is_file() and not path.is_symlink():
                    artifacts[key] = _identity(path)
            result_path = output_directory / "result.json"
            if not result_path.exists():
                _write_exclusive(result_path, canonical_json(result).encode("utf-8"))
        return result

    allowed_root = _absolute(contract.allowed_output_root)
    add_check(
        "output_within_frozen_root",
        _is_within(output_directory, allowed_root)
        and output_directory != allowed_root,
        expected=str(allowed_root),
        observed=str(output_directory),
    )
    if failures:
        return finalize("CONTRACT_BLOCKED", RC_CONTRACT_BLOCKED)
    try:
        allowed_root.mkdir(parents=True, exist_ok=True)
        output_directory.mkdir(mode=0o755, parents=False, exist_ok=False)
        output_owned = True
    except FileExistsError:
        failures.append("output_directory_no_clobber")
        checks["output_directory_no_clobber"] = {
            "expected": "absent",
            "observed": "exists",
            "ok": False,
        }
        return finalize("NO_CLOBBER_BLOCKED", RC_CONTRACT_BLOCKED)
    except OSError as error:
        failures.append("output_directory_creation")
        checks["output_directory_creation"] = {
            "expected": "new_writable_directory",
            "observed": f"{type(error).__name__}:{error}",
            "ok": False,
        }
        return finalize("CONTRACT_BLOCKED", RC_CONTRACT_BLOCKED)
    add_check(
        "output_directory_no_clobber", True, expected="absent", observed="created"
    )

    image_identity, image_error = _safe_identity(contract.input_image)
    add_check(
        "fixed_input_identity",
        _identity_matches(image_identity, contract.expected_image),
        expected=dict(contract.expected_image),
        observed=image_identity or image_error,
    )
    png_observed, png_error = _png_header(contract.input_image)
    add_check(
        "fixed_input_png_contract",
        png_observed == dict(contract.expected_png),
        expected=dict(contract.expected_png),
        observed=png_observed or png_error,
    )

    onnx_identity, onnx_error = _safe_identity(contract.onnx_model)
    add_check(
        "verified_onnx_identity",
        _identity_matches(onnx_identity, contract.expected_onnx),
        expected=dict(contract.expected_onnx),
        observed=onnx_identity or onnx_error,
    )
    try:
        model_entries = sorted(path.name for path in contract.model_directory.iterdir())
    except OSError as error:
        model_entries = [f"{type(error).__name__}:{error}"]
    add_check(
        "onnx_only_model_directory",
        model_entries == ["HF-Net.onnx"]
        and contract.onnx_model.parent == contract.model_directory
        and not contract.model_cache.exists(),
        expected=["HF-Net.onnx"],
        observed=model_entries,
    )
    add_check(
        "model_directory_writable",
        contract.model_directory.is_dir()
        and os.access(contract.model_directory, os.W_OK),
        expected=True,
        observed=(
            contract.model_directory.is_dir()
            and os.access(contract.model_directory, os.W_OK)
        ),
    )

    git_results = {
        "commit": probe_runner(
            ["git", "-C", str(contract.official_root), "rev-parse", "HEAD^{commit}"],
            None,
            None,
        ),
        "tree": probe_runner(
            ["git", "-C", str(contract.official_root), "rev-parse", "HEAD^{tree}"],
            None,
            None,
        ),
        "status": probe_runner(
            [
                "git",
                "-C",
                str(contract.official_root),
                "status",
                "--porcelain=v1",
                "--untracked-files=no",
            ],
            None,
            None,
        ),
    }
    source_observed = {
        name: _command_observation(command_result)
        for name, command_result in git_results.items()
    }
    source_ok = (
        git_results["commit"].returncode == 0
        and git_results["commit"].stdout.strip() == contract.expected_commit
        and git_results["tree"].returncode == 0
        and git_results["tree"].stdout.strip() == contract.expected_tree
        and git_results["status"].returncode == 0
        and git_results["status"].stdout == ""
    )
    add_check(
        "clean_official_execution_source",
        source_ok,
        expected={
            "commit": contract.expected_commit,
            "status": "",
            "tree": contract.expected_tree,
        },
        observed=source_observed,
    )

    source_identities: dict[str, object] = {}
    source_hashes_ok = True
    for relative, expected_hash in contract.expected_source_sha256.items():
        identity, error = _safe_identity(contract.official_root / relative)
        source_identities[relative] = identity or error
        if identity is None or identity.get("sha256") != expected_hash:
            source_hashes_ok = False
    add_check(
        "official_source_file_hashes",
        source_hashes_ok,
        expected=dict(contract.expected_source_sha256),
        observed=source_identities,
    )

    official_library_identity, library_error = _safe_identity(
        contract.official_library
    )
    add_check(
        "official_shared_library_present",
        official_library_identity is not None
        and contract.official_library.parent
        == contract.official_root / "lib",
        expected=str(contract.official_root / "lib/libHFNet_SLAM.so"),
        observed=official_library_identity or library_error,
    )
    harness_identity, harness_error = _safe_identity(contract.harness_binary)
    harness_executable = (
        harness_identity is not None
        and bool(contract.harness_binary.stat().st_mode & stat.S_IXUSR)
    )
    add_check(
        "project_harness_binary_present",
        harness_executable,
        expected="regular_executable",
        observed=harness_identity or harness_error,
    )
    harness_source_identity, harness_source_error = _safe_identity(
        contract.harness_source
    )
    add_check(
        "project_harness_source_present",
        harness_source_identity is not None,
        expected=str(_absolute(contract.harness_source)),
        observed=harness_source_identity or harness_source_error,
    )

    manifest_value, manifest_error = _load_canonical_json(contract.build_manifest)
    manifest_ok = _validate_build_manifest(
        manifest_value,
        contract,
        harness_identity,
        harness_source_identity,
        official_library_identity,
    )
    add_check(
        "canonical_build_manifest_matches_artifacts",
        manifest_ok,
        expected=BUILD_SCHEMA_VERSION,
        observed=(manifest_value if manifest_value is not None else manifest_error),
    )
    manifest_identity, _ = _safe_identity(contract.build_manifest)

    runtime_artifacts = {
        relative: {
            "exists": (contract.runtime_root / relative).exists(),
            "path": str(_absolute(contract.runtime_root / relative)),
            "within_runtime_root": _is_within(
                contract.runtime_root / relative, contract.runtime_root
            ),
        }
        for relative in RUNTIME_REQUIRED_RELATIVE
    }
    add_check(
        "isolated_runtime_artifact_closure",
        all(
            observation["exists"] and observation["within_runtime_root"]
            for observation in runtime_artifacts.values()
        ),
        expected=list(RUNTIME_REQUIRED_RELATIVE),
        observed=runtime_artifacts,
    )

    runtime_environment = _runtime_environment(contract)
    readelf_result = probe_runner(
        ["readelf", "-dW", str(contract.harness_binary)],
        {"LANG": "C", "LC_ALL": "C"},
        None,
    )
    add_check(
        "direct_official_library_dependency",
        readelf_result.returncode == 0
        and "(NEEDED)" in readelf_result.stdout
        and "[libHFNet_SLAM.so]" in readelf_result.stdout,
        expected="DT_NEEDED libHFNet_SLAM.so",
        observed=_command_observation(readelf_result),
    )
    ldd_result = probe_runner(
        ["ldd", str(contract.harness_binary)], runtime_environment, None
    )
    resolved, missing = _parse_ldd(ldd_result.stdout)
    hfnet_resolved = resolved.get("libHFNet_SLAM.so")
    required_runtime_names = (
        "libnvinfer.so",
        "libnvonnxparser.so",
        "libcudart.so",
    )
    runtime_resolution_ok = all(
        any(
            name.startswith(prefix)
            and _is_within(Path(path), contract.runtime_root)
            for name, path in resolved.items()
        )
        for prefix in required_runtime_names
    )
    pangolin_libraries = {
        name: path
        for name, path in resolved.items()
        if name.startswith("libpango_")
    }
    g2o_paths = [
        path for name, path in resolved.items() if name.startswith("libg2o")
    ]
    resolved_paths_exist = all(Path(path).exists() for path in resolved.values())
    ldd_ok = (
        ldd_result.returncode == 0
        and not missing
        and resolved_paths_exist
        and hfnet_resolved is not None
        and _absolute(Path(hfnet_resolved)) == _absolute(contract.official_library)
        and runtime_resolution_ok
        and any(name.startswith("libpango_core.so") for name in pangolin_libraries)
        and all(
            _is_within(Path(path), contract.pangolin_root)
            for path in pangolin_libraries.values()
        )
        and bool(g2o_paths)
        and all(
            _is_within(Path(path), contract.official_root / "Thirdparty/g2o")
            for path in g2o_paths
        )
    )
    add_check(
        "isolated_runtime_linkage",
        ldd_ok,
        expected={
            "libHFNet_SLAM.so": str(_absolute(contract.official_library)),
            "runtime_root": str(_absolute(contract.runtime_root)),
        },
        observed={
            "command": _command_observation(ldd_result),
            "missing": missing,
            "resolved": resolved,
        },
    )

    gpu_result = probe_runner(
        [
            "nvidia-smi",
            "--query-gpu=index,name,uuid,driver_version,memory.total",
            "--format=csv,noheader,nounits",
        ],
        None,
        None,
    )
    gpu_lines = [line.strip() for line in gpu_result.stdout.splitlines() if line.strip()]
    gpu_ok = (
        gpu_result.returncode == 0
        and bool(gpu_lines)
        and gpu_lines[0].split(",", 1)[0].strip() == GPU_INDEX
        and contract.gpu_name_token in gpu_lines[0]
    )
    add_check(
        "frozen_gpu_zero_available",
        gpu_ok,
        expected={"index": 0, "name_contains": contract.gpu_name_token},
        observed=_command_observation(gpu_result),
    )

    result_hashes = result["hashes"]
    assert isinstance(result_hashes, dict)
    result_hashes.update(
        {
            "build_manifest": manifest_identity,
            "harness_binary": harness_identity,
            "harness_source": harness_source_identity,
            "input_image": image_identity,
            "official_library": official_library_identity,
            "official_source_files": source_identities,
            "onnx_model": onnx_identity,
            "runner_source": _identity(Path(__file__)),
        }
    )

    if failures:
        return finalize("CONTRACT_BLOCKED", RC_CONTRACT_BLOCKED)

    immutable_paths = {
        "build_manifest": contract.build_manifest,
        "harness_binary": contract.harness_binary,
        "harness_source": contract.harness_source,
        "input_image": contract.input_image,
        "official_library": contract.official_library,
        "onnx_model": contract.onnx_model,
        "runner_source": Path(__file__),
        **{
            "official_source:" + relative: contract.official_root / relative
            for relative in contract.expected_source_sha256
        },
    }
    immutable_before = {
        name: _sha256(path) for name, path in immutable_paths.items()
    }
    raw_result_path = output_directory / "raw_harness_result.json"
    command = [
        str(_absolute(contract.harness_binary)),
        str(_absolute(contract.input_image)),
        str(_absolute(contract.model_directory)),
        str(raw_result_path),
    ]
    result["execution"] = {
        "command": command,
        "command_started": True,
        "environment": {
            "CUDA_VISIBLE_DEVICES": runtime_environment["CUDA_VISIBLE_DEVICES"],
            "LD_LIBRARY_PATH": runtime_environment["LD_LIBRARY_PATH"],
        },
        "returncode": None,
        "timed_out": False,
    }
    runner_log.append("START official_hfnet_rt_detect")
    execution_result = execute_runner(
        command, runtime_environment, contract.official_root, TIMEOUT_SECONDS
    )
    result["execution"] = {
        **result["execution"],  # type: ignore[arg-type]
        "returncode": execution_result.returncode,
        "timed_out": execution_result.timed_out,
    }
    _write_exclusive(
        output_directory / "harness.stdout.log",
        execution_result.stdout.encode("utf-8", errors="replace"),
    )
    _write_exclusive(
        output_directory / "harness.stderr.log",
        execution_result.stderr.encode("utf-8", errors="replace"),
    )
    runner_log.append(
        "END official_hfnet_rt_detect returncode="
        + str(execution_result.returncode)
    )

    immutable_after: dict[str, str | None] = {}
    for name, path in immutable_paths.items():
        try:
            immutable_after[name] = _sha256(path)
        except OSError:
            immutable_after[name] = None
    immutable_drift = sorted(
        name
        for name, before_hash in immutable_before.items()
        if immutable_after.get(name) != before_hash
    )
    post_git_results = {
        "commit": probe_runner(
            ["git", "-C", str(contract.official_root), "rev-parse", "HEAD^{commit}"],
            None,
            None,
        ),
        "tree": probe_runner(
            ["git", "-C", str(contract.official_root), "rev-parse", "HEAD^{tree}"],
            None,
            None,
        ),
        "status": probe_runner(
            [
                "git",
                "-C",
                str(contract.official_root),
                "status",
                "--porcelain=v1",
                "--untracked-files=no",
            ],
            None,
            None,
        ),
    }
    post_git_ok = (
        post_git_results["commit"].returncode == 0
        and post_git_results["commit"].stdout.strip() == contract.expected_commit
        and post_git_results["tree"].returncode == 0
        and post_git_results["tree"].stdout.strip() == contract.expected_tree
        and post_git_results["status"].returncode == 0
        and post_git_results["status"].stdout == ""
    )
    if not post_git_ok:
        immutable_drift.append("official_git_state")
    add_check(
        "immutable_hashes_unchanged_after_execution",
        not immutable_drift,
        expected=[],
        observed=immutable_drift,
    )
    add_check(
        "clean_official_execution_source_after_execution",
        post_git_ok,
        expected={
            "commit": contract.expected_commit,
            "status": "",
            "tree": contract.expected_tree,
        },
        observed={
            name: _command_observation(command_result)
            for name, command_result in post_git_results.items()
        },
    )

    try:
        post_model_entries = sorted(
            path.name for path in contract.model_directory.iterdir()
        )
    except OSError as error:
        post_model_entries = [f"{type(error).__name__}:{error}"]
    cache_identity, cache_error = _safe_identity(contract.model_cache)
    cache_ok = (
        cache_identity is not None
        and int(cache_identity["size_bytes"]) > 0
        and post_model_entries == ["HF-Net.cache", "HF-Net.onnx"]
    )
    add_check(
        "new_local_timing_cache_generated",
        cache_ok,
        expected=["HF-Net.cache", "HF-Net.onnx"],
        observed={
            "cache": cache_identity or cache_error,
            "model_directory_entries": post_model_entries,
        },
    )
    if cache_identity is not None:
        copied_cache = output_directory / "HF-Net.cache"
        _copy_exclusive(contract.model_cache, copied_cache)
        copied_identity = _identity(copied_cache)
        add_check(
            "timing_cache_artifact_copy_exact",
            copied_identity["sha256"] == cache_identity["sha256"],
            expected=cache_identity["sha256"],
            observed=copied_identity["sha256"],
        )
        result_hashes["generated_model_cache"] = cache_identity

    raw_value: object | None = None
    raw_error: str | None = None
    if raw_result_path.is_file() and not raw_result_path.is_symlink():
        raw_value, raw_error = _load_canonical_json(raw_result_path)
    else:
        raw_error = "missing_regular_raw_result"
    raw_ok, raw_failures = _validate_raw_result(raw_value)
    add_check(
        "official_detect_raw_result_contract",
        raw_ok,
        expected=RAW_SCHEMA_VERSION,
        observed=(raw_value if raw_value is not None else raw_error),
    )
    if raw_failures:
        runner_log.extend("RAW_FAIL " + failure for failure in raw_failures)

    execution_ok = (
        execution_result.returncode == 0
        and not execution_result.timed_out
        and raw_ok
        and cache_ok
    )
    add_check(
        "official_harness_execution",
        execution_ok,
        expected={"returncode": 0, "timed_out": False},
        observed=_command_observation(execution_result),
    )

    if immutable_drift:
        return finalize("POST_EXECUTION_INTEGRITY_ERROR", RC_CONTRACT_BLOCKED)
    if failures:
        return finalize("EXECUTION_FAILED", RC_EXECUTION_FAILED)
    return finalize("PASS_MODEL_DETECT_SMOKE", RC_PASS)


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
        help=(
            "new result directory under "
            + str(DEFAULT_OUTPUT_ROOT)
            + "; existing directories are never reused"
        ),
    )
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    contract: SmokeContract = DEFAULT_CONTRACT,
    probe_runner: ProbeRunner = _default_probe,
    execute_runner: ExecuteRunner = _default_execute,
    clock: Clock = _utc_now,
) -> int:
    arguments = _parse_arguments(argv)
    try:
        decision = run_smoke(
            contract=contract,
            output_directory=arguments.output_dir,
            probe_runner=probe_runner,
            execute_runner=execute_runner,
            clock=clock,
        )
    except Exception as error:  # Last-resort fail-closed CLI boundary.
        decision = {
            "evaluable": False,
            "error": f"{type(error).__name__}:{error}",
            "output_directory": str(_absolute(arguments.output_dir)),
            "return_code": RC_CONTRACT_BLOCKED,
            "schema_version": SCHEMA_VERSION,
            "scope": "MODEL_RUNTIME_SMOKE_ONLY",
            "status": "INTERNAL_CONTRACT_ERROR",
            "trajectory_generated": False,
        }
    print(canonical_json(decision), end="")
    return int(decision["return_code"])


if __name__ == "__main__":
    raise SystemExit(main())
