#!/usr/bin/env python3
"""Fail-closed compile preflight for the disclosed SuperVINS 1.0 repair.

This checker is deliberately bounded before OrtSession construction.  It reads
and hashes source/model artifacts, probes shared-library loading, and inspects
the compiled ELF.  It never constructs an ONNX Runtime session, runs a model,
starts a ROS node, or opens/replays ROS data.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


SCHEMA_VERSION = "aqua-fe-published-supervins-v1-devrepair-preflight-r1"
OFFICIAL = Path("/home/ma/SLAM/SuperVINS-paper-1.0-r1")
WORKSPACE = Path("/home/ma/SLAM/SuperVINS-v1-devrepair-ws-20260816-r1")
PRIVATE = WORKSPACE / "src/SuperVINS"
DEPENDENCIES = Path("/home/ma/opt/supervins_v1_devrepair_20260816_r1")
EVIDENCE = Path(
    "/home/ma/AQUA-FE_WS/experiments/"
    "published_supervins_v1_devrepair_20260816_r1"
)
PROTOCOL = Path(
    "/home/ma/AQUA-FE_WS/papers/"
    "2026-08-16--supervins-v1-development-runtime-repair-r1.md"
)
CONTRACT = EVIDENCE / "development_contract.json"

COMMIT = "91e85d72a3828844538715cc4b1cd4b86a2620db"
TREE = "036391d321d4ea9a914739a454c20976f01f7bd7"
ORIGIN = "https://github.com/luohongk/SuperVINS.git"
CERES_COMMIT = "f68321e7de8929fbcdb95dd42877531e64f72f66"
DIFF_SHA256 = "94379f74e31417f883f499a6a8fd4591e93bf24429c852ff83de1ef20a3c75a0"

CPP = "supervins_estimator/src/featureTracker/extractor_matcher_dpl.cpp"
CMAKE = "supervins_estimator/CMakeLists.txt"
EXPECTED_CHANGED_PATHS = [CMAKE, CPP]
EXPECTED_STATUS = [" M " + CMAKE, " M " + CPP]
EXPECTED_NUMSTAT = ["1\t1\t" + CMAKE, "2\t2\t" + CPP]

STOCK_SHA256 = {
    CMAKE: "253eb7247b84fe9735c4be200ba7f431f3dab0e37bb1efccd97a7543ad9a132a",
    CPP: "dfae6b3fdcb0a588d26d527ef0043c1a77f089305523f02f9bcc0b16ba88428f",
}
REPAIRED_SHA256 = {
    CMAKE: "372508e93580c8ea6c3465543d909da9530e814e484d286e6ce59445b44c4338",
    CPP: "43367b8b72e60a951a3c1a79504b1fc8cd3c9bde72f271a6a86da4efd5ed08f0",
}
GOVERNANCE_SHA256 = {
    str(PROTOCOL): "74f8daf4ee254015b263d3039e16c2cb02c53d26ca95e79bc8ea44e133a7d989",
    str(CONTRACT): "b535d039ead04697ffc6989a921d970dc19ec07f22862d45a32c1a81a22899af",
}

MODEL_PINS = {
    "supervins_estimator/weights_dpl/superpoint.onnx": {
        "size": 5272808,
        "sha256": "234d12c9f523292efb34e0ca513b011050b0c052700da9c01787b9356a1138d2",
    },
    "supervins_estimator/weights_dpl/superpoint_lightglue_fused_cpu.onnx": {
        "size": 45634561,
        "sha256": "4f44f440bc08f71afc2ba619d33154d395284001c1387b14a3b58a3224f9490e",
    },
}

ORT = DEPENDENCIES / "onnxruntime-linux-x64-gpu-1.16.3"
CERES_SOURCE = DEPENDENCIES / "src/ceres-solver-2.1.0"
CERES_INSTALL = DEPENDENCIES / "install/ceres-2.1.0"
EXTRA_CUDA = (
    DEPENDENCIES
    / "cuda-runtime-11.6-extra/usr/local/cuda-11.6/targets/x86_64-linux/lib"
)
HFNET_ASSET = Path("/home/ma/opt/hfnet_cuda116_trt851_r1")
CUDNN = HFNET_ASSET / "usr/lib/x86_64-linux-gnu"
CUBLAS = HFNET_ASSET / "usr/local/cuda-11.8/targets/x86_64-linux/lib"
CUDA116 = HFNET_ASSET / "usr/local/cuda-11.6"
CUDART = CUDA116 / "targets/x86_64-linux/lib"

ARCHIVE_PINS = {
    "onnxruntime-linux-x64-gpu-1.16.3.tgz": {
        "size": 136722770,
        "sha256": "bbdc33367c056029b3ac0c042cbca2236b8f59a3a53b4daf23432ef1d8bf52de",
    },
    "libcufft-11-6_10.7.2.124-1_amd64.deb": {
        "size": 68318462,
        "sha256": "6dbabc24ebed5278e944f22fa56ec05b9775bf7923dfd3c3a3c40e612bea21f6",
    },
    "libcurand-11-6_10.2.9.124-1_amd64.deb": {
        "size": 41536854,
        "sha256": "e9493f2b87ebd66f50d3f9479a5af458a04bbf5e2b87d9dd8ec18ac1f7c45bb9",
    },
}
LIBRARY_PINS = {
    str(ORT / "lib/libonnxruntime.so"): (
        "b122d45bc0a2110c183784f383060bd897b8424184b31f646ebce1ca8a5c8956"
    ),
    str(ORT / "lib/libonnxruntime_providers_shared.so"): (
        "bb0836da2a05ccd946fcef9258201cb85eecf20b9f230f256ac90b0caaa9c04a"
    ),
    str(ORT / "lib/libonnxruntime_providers_cuda.so"): (
        "676e0d95d5eb0dd1d602c5d42ba320240a25d9342b9ae1dc9d3e838be01f844b"
    ),
    str(EXTRA_CUDA / "libcufft.so.10"): (
        "4d9ac8220c4bb8a9c6d82363c2f412b6fb00929bd82825d00134a848e6b51bb5"
    ),
    str(EXTRA_CUDA / "libcurand.so.10"): (
        "a1c4dd8e8b56b8856b5d2a0d4fc7c69b669268f5d05b8c453916a49ea3236c47"
    ),
    str(CERES_INSTALL / "lib/libceres.so.2.1.0"): (
        "73e07e5202548ef25c8899b2715e6094cff24030b815ece64b2278f01e6bae1f"
    ),
}

BINARY = WORKSPACE / "devel/lib/supervins/supervins_node"
SUPERVINS_LIBRARY = WORKSPACE / "devel/lib/libsupervins_lib.so"
BINARY_PINS = {
    str(BINARY): {
        "size": 13269280,
        "sha256": "5aaec22bb03da92f2b48aaff037646d9cd06ab87fd67c594c6dbb005da5ed2e3",
    },
    str(SUPERVINS_LIBRARY): {
        "size": 168386832,
        "sha256": "42e84ffb781ed2f15582aa487be1e62a315ed9bb54d9db51176c2f5c1a97db22",
    },
}


def sha256(path):
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        return None, type(exc).__name__ + ":" + str(exc)[:300]
    return digest.hexdigest(), None


def command(argv, cwd=None, env=None, binary=False):
    probe_env = dict(os.environ if env is None else env)
    probe_env["GIT_OPTIONAL_LOCKS"] = "0"
    probe_env["LC_ALL"] = "C"
    try:
        result = subprocess.run(
            [str(value) for value in argv],
            cwd=str(cwd) if cwd else None,
            env=probe_env,
            check=False,
            capture_output=True,
            text=not binary,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "returncode": 124 if isinstance(exc, subprocess.TimeoutExpired) else 126,
            "stdout": b"" if binary else "",
            "stderr": type(exc).__name__ + ":" + str(exc)[:300],
        }
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def git(repo, *args, binary=False):
    return command(["git", "-C", repo, *args], binary=binary)


def normalized_url(value):
    normalized = value.strip().lower().rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized


def main():
    groups = {"build": {}, "dependencies": {}, "governance": {}, "source": {}}

    def add(group, check_id, ok, expected, observed):
        groups[group][check_id] = {
            "expected": expected,
            "observed": observed,
            "ok": bool(ok),
        }

    for path_text, expected in GOVERNANCE_SHA256.items():
        path = Path(path_text)
        observed, error = sha256(path)
        add(
            "governance",
            "sha256:" + path.name,
            observed == expected,
            expected,
            observed if error is None else {"sha256": observed, "error": error},
        )

    try:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        boundary = contract.get("claim_boundary", {})
        forbidden_flags = {
            key: value for key, value in boundary.items() if value is not False
        }
        contract_observed = {
            "authorized_terminal_stage": contract.get("authorized_terminal_stage"),
            "forbidden_flags_not_false": forbidden_flags,
            "schema_version": contract.get("schema_version"),
        }
        contract_ok = (
            not forbidden_flags
            and contract.get("authorized_source_change_count") == 3
            and contract.get("authorized_terminal_stage")
            == "COMPILE_AND_PREFLIGHT_CHECKPOINT_BEFORE_SESSION_CONSTRUCTION"
        )
    except (OSError, ValueError) as exc:
        contract_ok = False
        contract_observed = {"error": type(exc).__name__ + ":" + str(exc)[:300]}
    add("governance", "development_only_contract", contract_ok, True, contract_observed)

    for label, repo, clean_expected in (
        ("official", OFFICIAL, True),
        ("private", PRIVATE, False),
    ):
        head = git(repo, "rev-parse", "HEAD")
        tree = git(repo, "rev-parse", "HEAD^{tree}")
        origin = git(repo, "config", "--get", "remote.origin.url")
        status = git(
            repo,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignore-submodules=none",
        )
        head_value = head["stdout"].strip() if head["returncode"] == 0 else None
        tree_value = tree["stdout"].strip() if tree["returncode"] == 0 else None
        origin_value = origin["stdout"].strip() if origin["returncode"] == 0 else None
        status_lines = status["stdout"].splitlines() if status["returncode"] == 0 else []
        add("source", label + "_head", head_value == COMMIT, COMMIT, head_value)
        add("source", label + "_tree", tree_value == TREE, TREE, tree_value)
        add(
            "source",
            label + "_origin",
            origin_value is not None
            and normalized_url(origin_value) == normalized_url(ORIGIN),
            ORIGIN,
            origin_value,
        )
        expected_status = [] if clean_expected else EXPECTED_STATUS
        add(
            "source",
            label + "_status",
            status["returncode"] == 0 and status_lines == expected_status,
            expected_status,
            status_lines,
        )

    for relative, expected in STOCK_SHA256.items():
        observed, error = sha256(OFFICIAL / relative)
        add(
            "source",
            "official_sha256:" + relative,
            observed == expected,
            expected,
            observed if error is None else {"sha256": observed, "error": error},
        )
    for relative, expected in REPAIRED_SHA256.items():
        observed, error = sha256(PRIVATE / relative)
        add(
            "source",
            "repaired_sha256:" + relative,
            observed == expected,
            expected,
            observed if error is None else {"sha256": observed, "error": error},
        )

    diff = git(PRIVATE, "diff", "--no-ext-diff", "--no-color", binary=True)
    diff_bytes = diff["stdout"] if isinstance(diff["stdout"], bytes) else b""
    observed_diff_sha = hashlib.sha256(diff_bytes).hexdigest()
    add(
        "source",
        "allowlisted_diff_sha256",
        diff["returncode"] == 0 and observed_diff_sha == DIFF_SHA256,
        DIFF_SHA256,
        observed_diff_sha,
    )
    names = git(PRIVATE, "diff", "--name-only")
    name_lines = names["stdout"].splitlines() if names["returncode"] == 0 else []
    add(
        "source",
        "allowlisted_changed_paths",
        name_lines == EXPECTED_CHANGED_PATHS,
        EXPECTED_CHANGED_PATHS,
        name_lines,
    )
    numstat = git(PRIVATE, "diff", "--numstat")
    numstat_lines = (
        numstat["stdout"].splitlines() if numstat["returncode"] == 0 else []
    )
    add(
        "source",
        "allowlisted_line_replacements",
        numstat_lines == EXPECTED_NUMSTAT,
        EXPECTED_NUMSTAT,
        numstat_lines,
    )

    try:
        cpp_bytes = (PRIVATE / CPP).read_bytes()
        zero_count = len(
            re.findall(rb"gpu_mem_limit\s*=\s*0\s*;", cpp_bytes)
        )
        size_max_count = len(
            re.findall(rb"gpu_mem_limit\s*=\s*SIZE_MAX\s*;", cpp_bytes)
        )
        provider_count = cpp_bytes.count(b"AppendExecutionProvider_CUDA")
        cpp_observed = {
            "cuda_provider_registrations": provider_count,
            "gpu_mem_limit_SIZE_MAX": size_max_count,
            "gpu_mem_limit_zero": zero_count,
        }
        cpp_ok = zero_count == 0 and size_max_count == 2 and provider_count == 2
    except OSError as exc:
        cpp_ok = False
        cpp_observed = {"error": type(exc).__name__ + ":" + str(exc)[:300]}
    add(
        "source",
        "cuda_memory_limit_repair",
        cpp_ok,
        {
            "cuda_provider_registrations": 2,
            "gpu_mem_limit_SIZE_MAX": 2,
            "gpu_mem_limit_zero": 0,
        },
        cpp_observed,
    )

    try:
        cmake_text = (PRIVATE / CMAKE).read_text(encoding="utf-8")
        injectable_count = cmake_text.count(
            'set(ONNXRUNTIME_ROOTDIR "" CACHE PATH '
            '"Path to ONNX Runtime GPU release root")'
        )
        hardcoded_count = cmake_text.count(
            'set(ONNXRUNTIME_ROOTDIR "/home/lhk/Thirdparty/onnxruntime")'
        )
        cmake_observed = {
            "hardcoded_author_path": hardcoded_count,
            "injectable_cache_path": injectable_count,
        }
        cmake_ok = injectable_count == 1 and hardcoded_count == 0
    except OSError as exc:
        cmake_ok = False
        cmake_observed = {"error": type(exc).__name__ + ":" + str(exc)[:300]}
    add(
        "source",
        "onnxruntime_path_injection_repair",
        cmake_ok,
        {"hardcoded_author_path": 0, "injectable_cache_path": 1},
        cmake_observed,
    )

    config_path = PRIVATE / "config/euroc/euroc_mono_imu_config.yaml"
    try:
        config_text = config_path.read_text(encoding="utf-8")
        config_models = {
            "extractor": re.search(
                r'^extractor_weight_path:\s*"([^"]+)"', config_text, re.MULTILINE
            ).group(1),
            "matcher": re.search(
                r'^matcher_weight_path:\s*"([^"]+)"', config_text, re.MULTILINE
            ).group(1),
        }
        config_ok = config_models == {
            "extractor": "SuperVINS/supervins_estimator/weights_dpl/superpoint.onnx",
            "matcher": (
                "SuperVINS/supervins_estimator/weights_dpl/"
                "superpoint_lightglue_fused_cpu.onnx"
            ),
        }
    except (OSError, AttributeError) as exc:
        config_ok = False
        config_models = {"error": type(exc).__name__ + ":" + str(exc)[:300]}
    add("source", "actual_euroc_model_selection", config_ok, True, config_models)
    for relative, pin in MODEL_PINS.items():
        path = PRIVATE / relative
        observed_sha, error = sha256(path)
        try:
            observed_size = path.stat().st_size
        except OSError:
            observed_size = None
        observed = {"size": observed_size, "sha256": observed_sha}
        if error:
            observed["error"] = error
        add(
            "source",
            "model_pin:" + relative,
            observed_size == pin["size"] and observed_sha == pin["sha256"],
            pin,
            observed,
        )

    for name, pin in ARCHIVE_PINS.items():
        path = DEPENDENCIES / "downloads" / name
        observed_sha, error = sha256(path)
        try:
            observed_size = path.stat().st_size
        except OSError:
            observed_size = None
        observed = {"size": observed_size, "sha256": observed_sha}
        if error:
            observed["error"] = error
        add(
            "dependencies",
            "archive_pin:" + name,
            observed_size == pin["size"] and observed_sha == pin["sha256"],
            pin,
            observed,
        )

    for path_text, expected in LIBRARY_PINS.items():
        path = Path(path_text)
        observed, error = sha256(path)
        add(
            "dependencies",
            "library_sha256:" + path.name,
            observed == expected,
            expected,
            observed if error is None else {"sha256": observed, "error": error},
        )

    try:
        ort_version = (ORT / "VERSION_NUMBER").read_text(encoding="utf-8").strip()
    except OSError as exc:
        ort_version = type(exc).__name__ + ":" + str(exc)[:300]
    add("dependencies", "onnxruntime_version_file", ort_version == "1.16.3", "1.16.3", ort_version)

    runtime_env = dict(os.environ)
    runtime_paths = [
        ORT / "lib",
        EXTRA_CUDA,
        CUDNN,
        CUBLAS,
        CUDART,
        CERES_INSTALL / "lib",
        WORKSPACE / "devel/lib",
        Path("/opt/ros/noetic/lib"),
    ]
    runtime_env["LD_LIBRARY_PATH"] = ":".join(str(path) for path in runtime_paths)

    provider = ORT / "lib/libonnxruntime_providers_cuda.so"
    provider_ldd = command(["ldd", provider], env=runtime_env)
    provider_ldd_text = provider_ldd["stdout"]
    provider_ldd_ok = (
        provider_ldd["returncode"] == 0
        and "not found" not in provider_ldd_text
        and str(EXTRA_CUDA / "libcufft.so.10") in provider_ldd_text
        and str(EXTRA_CUDA / "libcurand.so.10") in provider_ldd_text
        and str(CUBLAS / "libcublas.so.11") in provider_ldd_text
        and str(CUDNN / "libcudnn.so.8") in provider_ldd_text
        and str(CUDART / "libcudart.so.11.0") in provider_ldd_text
    )
    add(
        "dependencies",
        "onnxruntime_cuda_provider_ldd",
        provider_ldd_ok,
        {"missing": [], "isolated_runtime_paths": True},
        {
            "missing_lines": [
                line.strip()
                for line in provider_ldd_text.splitlines()
                if "not found" in line
            ],
            "returncode": provider_ldd["returncode"],
        },
    )

    probe_code = r'''
import ctypes, json, sys
GetApi = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_uint32)
GetVersion = ctypes.CFUNCTYPE(ctypes.c_char_p)
class Base(ctypes.Structure):
    _fields_ = [("GetApi", GetApi), ("GetVersionString", GetVersion)]
observed = {}
handles = []
for index, path in enumerate(sys.argv[1:]):
    item = {"loaded": False, "error": None, "version": None}
    try:
        lib = ctypes.CDLL(path, mode=getattr(ctypes, "RTLD_GLOBAL", 0))
        handles.append(lib)
        item["loaded"] = True
        if index == 0:
            get_base = lib.OrtGetApiBase
            get_base.restype = ctypes.POINTER(Base)
            item["version"] = get_base().contents.GetVersionString().decode("utf-8")
    except Exception as exc:
        item["error"] = type(exc).__name__ + ":" + str(exc)[:300]
    observed[path] = item
print(json.dumps(observed, sort_keys=True))
'''
    # The CUDA provider is not a standalone plugin: its global constructor
    # requires a host injected by ORT core's provider-loading path.  A naked
    # dlopen therefore is not a valid probe.  Core/shared are safe to load
    # here; the CUDA provider itself is checked above with ldd and is only
    # initialized later by the separately authorized OrtSession smoke.
    ort_libraries = [
        ORT / "lib/libonnxruntime.so",
        ORT / "lib/libonnxruntime_providers_shared.so",
    ]
    dlopen = command(
        [sys.executable, "-c", probe_code, *ort_libraries], env=runtime_env
    )
    try:
        dlopen_observed = json.loads(dlopen["stdout"])
        dlopen_ok = (
            dlopen["returncode"] == 0
            and all(
                dlopen_observed[str(path)]["loaded"] for path in ort_libraries
            )
            and dlopen_observed[str(ort_libraries[0])]["version"] == "1.16.3"
        )
    except (KeyError, TypeError, ValueError):
        dlopen_ok = False
        dlopen_observed = {
            "returncode": dlopen["returncode"],
            "stderr": str(dlopen["stderr"])[:300],
            "stdout": str(dlopen["stdout"])[:300],
        }
    add(
        "dependencies",
        "onnxruntime_core_shared_dlopen_without_session",
        dlopen_ok,
        {
            "all_loaded": True,
            "core_version": "1.16.3",
            "cuda_provider_probe": "ldd_only_until_OrtSession_smoke",
            "session_created": False,
        },
        dlopen_observed,
    )

    ceres_head = git(CERES_SOURCE, "rev-parse", "HEAD")
    ceres_status = git(CERES_SOURCE, "status", "--porcelain=v1", "--untracked-files=all")
    ceres_observed = {
        "head": ceres_head["stdout"].strip(),
        "status": ceres_status["stdout"].splitlines(),
    }
    add(
        "dependencies",
        "ceres_official_source",
        ceres_head["returncode"] == 0
        and ceres_status["returncode"] == 0
        and ceres_observed["head"] == CERES_COMMIT
        and not ceres_observed["status"],
        {"head": CERES_COMMIT, "status": []},
        ceres_observed,
    )
    ceres_config = CERES_INSTALL / "lib/cmake/Ceres/CeresConfigVersion.cmake"
    try:
        ceres_config_text = ceres_config.read_text(encoding="utf-8")
        ceres_version_ok = 'set(PACKAGE_VERSION "2.1.0")' in ceres_config_text
    except OSError:
        ceres_version_ok = False
    add("dependencies", "ceres_installed_version", ceres_version_ok, "2.1.0", "2.1.0" if ceres_version_ok else None)
    ceres_ldd = command(["ldd", CERES_INSTALL / "lib/libceres.so.2.1.0"])
    add(
        "dependencies",
        "ceres_ldd",
        ceres_ldd["returncode"] == 0 and "not found" not in ceres_ldd["stdout"],
        {"missing": []},
        {
            "missing_lines": [
                line.strip()
                for line in ceres_ldd["stdout"].splitlines()
                if "not found" in line
            ],
            "returncode": ceres_ldd["returncode"],
        },
    )

    nvcc = command([CUDA116 / "bin/nvcc", "--version"])
    add(
        "dependencies",
        "cuda_compiler_asset",
        nvcc["returncode"] == 0 and "release 11.6" in nvcc["stdout"],
        "release 11.6",
        nvcc["stdout"].strip()[-300:],
    )
    gpu = command(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"])
    add(
        "dependencies",
        "nvidia_gpu_visible",
        gpu["returncode"] == 0 and bool(gpu["stdout"].strip()),
        {"minimum_gpu_count": 1},
        gpu["stdout"].splitlines(),
    )

    for path_text, pin in BINARY_PINS.items():
        path = Path(path_text)
        observed_sha, error = sha256(path)
        try:
            observed_size = path.stat().st_size
        except OSError:
            observed_size = None
        observed = {"size": observed_size, "sha256": observed_sha}
        if error:
            observed["error"] = error
        add(
            "build",
            "binary_pin:" + path.name,
            observed_size == pin["size"] and observed_sha == pin["sha256"],
            pin,
            observed,
        )

    cache_path = WORKSPACE / "build/CMakeCache.txt"
    try:
        cache_text = cache_path.read_text(encoding="utf-8")
        cache_expected = [
            "CMAKE_BUILD_TYPE:STRING=Release",
            "Ceres_DIR:UNINITIALIZED=" + str(CERES_INSTALL / "lib/cmake/Ceres"),
            "ONNXRUNTIME_ROOTDIR:PATH=" + str(ORT),
        ]
        cache_present = [line for line in cache_expected if line in cache_text]
    except OSError:
        cache_expected = []
        cache_present = []
    add(
        "build",
        "isolated_cmake_cache",
        cache_present == cache_expected and len(cache_expected) == 3,
        cache_expected,
        cache_present,
    )
    build_log = EVIDENCE / "supervins_catkin_make.log"
    try:
        build_log_text = build_log.read_text(encoding="utf-8", errors="replace")
        build_log_ok = (
            "CMAKE_PREFIX_PATH=/opt/ros/noetic" in build_log_text
            and "SUPERVINS_COMPILE_OK" in build_log_text
            and "Found Ceres version: 2.1.0 installed in: " + str(CERES_INSTALL)
            in build_log_text
        )
    except OSError:
        build_log_ok = False
    build_log_sha, build_log_error = sha256(build_log)
    add(
        "build",
        "compile_log",
        build_log_ok,
        {"compile_marker": "SUPERVINS_COMPILE_OK", "prefix": "/opt/ros/noetic"},
        {"sha256": build_log_sha, "error": build_log_error},
    )

    file_probe = command(["file", BINARY])
    add(
        "build",
        "supervins_node_is_elf",
        file_probe["returncode"] == 0
        and "ELF 64-bit" in file_probe["stdout"]
        and "x86-64" in file_probe["stdout"],
        "ELF 64-bit x86-64",
        file_probe["stdout"].strip(),
    )
    binary_ldd = command(["ldd", BINARY], env=runtime_env)
    binary_ldd_text = binary_ldd["stdout"]
    binary_ldd_ok = (
        binary_ldd["returncode"] == 0
        and "not found" not in binary_ldd_text
        and str(ORT / "lib/libonnxruntime.so.1.16.3") in binary_ldd_text
        and str(CERES_INSTALL / "lib/libceres.so.3") in binary_ldd_text
        and str(SUPERVINS_LIBRARY) in binary_ldd_text
    )
    add(
        "build",
        "supervins_node_ldd",
        binary_ldd_ok,
        {
            "ceres_root": str(CERES_INSTALL),
            "missing": [],
            "onnxruntime_root": str(ORT),
        },
        {
            "missing_lines": [
                line.strip()
                for line in binary_ldd_text.splitlines()
                if "not found" in line
            ],
            "returncode": binary_ldd["returncode"],
            "uses_isolated_ceres": str(CERES_INSTALL) in binary_ldd_text,
            "uses_isolated_onnxruntime": str(ORT) in binary_ldd_text,
        },
    )
    readelf = command(["readelf", "-d", BINARY])
    add(
        "build",
        "supervins_node_needed_and_runpath",
        readelf["returncode"] == 0
        and "libonnxruntime.so.1.16.3" in readelf["stdout"]
        and str(ORT / "lib") in readelf["stdout"]
        and str(CERES_INSTALL / "lib") in readelf["stdout"],
        {"needed": "libonnxruntime.so.1.16.3", "isolated_runpath": True},
        {"returncode": readelf["returncode"]},
    )

    running_nodes = []
    for comm in Path("/proc").glob("[0-9]*/comm"):
        try:
            if comm.read_text(encoding="utf-8").strip() == "supervins_node":
                running_nodes.append(comm.parent.name)
        except OSError:
            pass
    add("build", "supervins_node_not_running", not running_nodes, [], running_nodes)

    failures = sorted(
        group + ":" + check_id
        for group, checks in groups.items()
        for check_id, result in checks.items()
        if not result["ok"]
    )
    status = (
        "READY_FOR_ORTSESSION_SMOKE_NOT_EXECUTED"
        if not failures
        else "COMPILE_PREFLIGHT_BLOCKED"
    )
    try:
        stat = os.statvfs(str(DEPENDENCIES))
        free_bytes = stat.f_bavail * stat.f_frsize
    except OSError:
        free_bytes = None
    result = {
        "checks": groups,
        "failures": failures,
        "paths": {
            "dependency_root": str(DEPENDENCIES),
            "evidence_root": str(EVIDENCE),
            "official_checkout": str(OFFICIAL),
            "private_worktree": str(PRIVATE),
            "private_workspace": str(WORKSPACE),
        },
        "probe_boundary": {
            "accuracy_claim_authorized": False,
            "formal_baseline_authorized": False,
            "model_inference_run": False,
            "ort_session_created": False,
            "ros_data_opened_or_replayed": False,
            "ros_node_started": False,
            "scope": "identity_hash_dlopen_and_compiled_elf_only",
        },
        "ready_for_ortsession_smoke": not failures,
        "return_code": 0 if not failures else 1,
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "storage": {"free_bytes_after_compile": free_bytes},
    }
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
    return int(result["return_code"])


if __name__ == "__main__":
    raise SystemExit(main())
