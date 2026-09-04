#!/usr/bin/env python3
"""One-shot export-only A08 KLT and recovered-July XFeat controls."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time
from typing import Any, Iterable, Optional


WORKSPACE = Path("/home/ma/AQUA-FE_WS")
EXPERIMENT = Path("/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1")
OVERLAY = EXPERIMENT / "recovered_july_core_overlay_v1"
RUN_ROOT = OVERLAY / "logs/aqualoc_archaeo_vins"
FRONTEND_ROOT = EXPERIMENT / "frontends_v1"
TMP_ROOT = EXPERIMENT / "tmp/frontends_v1"
RAW_BAG = EXPERIMENT / "raw/archaeo08_0000_4660.bag"
SOURCE_ARCHIVE = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences/archaeo_sequence_8_raw_data.tar.gz"
)
GT = WORKSPACE / (
    "datasets/full_downloads/aqualoc/Archaeological_site_sequences/"
    "archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_08.txt"
)
PROTOCOL = WORKSPACE / "papers/a08_hfnet_history_matched_support_extension_v1_protocol.md"
MANIFEST = OVERLAY / "execution_tree_manifest_v1.json"
OVERLAY_RECEIPT = OVERLAY / "overlay_materialization_receipt_v1.json"
CUDA_PYTHON = Path("/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin/python3")
CUDA_BIN = CUDA_PYTHON.parent
VINS_BINARY = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node")
FRONTEND_CONFIG = OVERLAY / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml"

KLT_TAG = "a08_recoveredjuly_hist0000_4660_klt_export_v1"
KLT_RUN = RUN_ROOT / f"external_klt_every2_{KLT_TAG}"
XFEAT_TAG_BASE = "a08_recoveredjuly_hist0000_4660_oldarb_v1"

KLT_CLAIM = FRONTEND_ROOT / "klt_process_start_claim_v1.json"
KLT_RECEIPT = FRONTEND_ROOT / "klt_export_receipt_v1.json"
KLT_FAILURE = FRONTEND_ROOT / "klt_export_failure_v1.json"
KLT_LOG = FRONTEND_ROOT / "klt_supervisor_process.log"
XFEAT_CLAIM = FRONTEND_ROOT / "xfeat_process_start_claim_v1.json"
XFEAT_RECEIPT = FRONTEND_ROOT / "xfeat_export_receipt_v1.json"
XFEAT_FAILURE = FRONTEND_ROOT / "xfeat_export_failure_v1.json"
XFEAT_LOG = FRONTEND_ROOT / "xfeat_supervisor_process.log"

FIXED_IDENTITIES = {
    RAW_BAG: (
        1_242_450_892,
        "9f7d21f7fe45f12f72c7e922be39e9b48601006f14254a5355992aab17ee16c2",
    ),
    SOURCE_ARCHIVE: (
        2_316_571_070,
        "b45e4f6dbf852ff8d7e5c9386e3df2db4daa84d1841f1eafb01a4637d2fe9153",
    ),
    GT: (
        54_593,
        "519d27750efd7e53c27a2bc3ff35bc9cf5c9fd2b888184eefea284bcfe8f2b6c",
    ),
    PROTOCOL: (
        7_665,
        "2d202a342397e64b47a32a29834a59d76afaaae32002da7016373befc2fee466",
    ),
    MANIFEST: (
        49_774,
        "92e00b4634c9938400421148e0707c01a75d64ff5107f2aaa4ca574c1ac31b4e",
    ),
    OVERLAY_RECEIPT: (
        5_197,
        "e0713ebef5227f650abf7ab101f49d101947126292f7e9a2ae7cfcae02fd809d",
    ),
    VINS_BINARY: (
        13_104_360,
        "4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278",
    ),
}
EXPECTED_TREE_SHA256 = "654f3d921fdb5971ce1e4da04b367e6c987011eb5bb5d72ebb1805cb38b7f1c9"

CAMERA_TOPIC = "/camera/image_raw"
FEATURE_TOPIC = "/feature_tracker/feature"
IMU_TOPIC = "/rtimulib_node/imu"
GT_TOPIC = "/aqualoc/colmap_gt"
CHANNELS = (
    "id",
    "camera_id",
    "p_u",
    "p_v",
    "velocity_x",
    "velocity_y",
    "gx",
    "gy",
    "gz",
    "quality",
    "sigma",
    "source_code",
    "is_learned",
)
CAMERA_COUNT = 4_661
FEATURE_COUNT = 2_330
IMU_COUNT = 46_631
GT_COUNT = 226
SUPPORT_START = 4_000
POSITIVE_START = 4_500


class FrontendError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise FrontendError(code)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"NOT_REGULAR:{path}")
    return {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256(path)}


def require_identity(path: Path, expected: tuple[int, str]) -> dict[str, Any]:
    value = identity(path)
    require((value["size_bytes"], value["sha256"]) == expected, f"IDENTITY_DRIFT:{path}")
    return value


def tree_root(entries: Iterable[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: str(item["relative_path"])):
        digest.update(
            (
                f"{entry['relative_path']}\0{entry['size_bytes']}\0"
                f"{entry['sha256']}\n"
            ).encode("utf-8")
        )
    return digest.hexdigest()


def verify_execution_tree() -> dict[str, Any]:
    require_identity(MANIFEST, FIXED_IDENTITIES[MANIFEST])
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    require(value.get("status") == "PASS_EXECUTION_TREE_FROZEN_BEFORE_FRONTEND", "MANIFEST_STATUS")
    require(value.get("tree_sha256") == EXPECTED_TREE_SHA256, "MANIFEST_TREE_ROOT")
    entries = value.get("entries")
    require(isinstance(entries, list) and len(entries) == 192, "MANIFEST_ENTRIES")
    allowed_root_names = {
        "execution_tree_manifest_v1.json",
        "overlay_materialization_receipt_v1.json",
        "external_tools",
        "logs",
        "scripts",
        "uw_frontend",
    }
    require(
        {path.name for path in OVERLAY.iterdir()} == allowed_root_names,
        "OVERLAY_ROOT_CLOSURE",
    )
    for name in ("external_tools", "logs", "scripts", "uw_frontend"):
        path = OVERLAY / name
        require(path.is_dir() and not path.is_symlink(), f"OVERLAY_ROOT_DIR:{name}")
    observed: list[dict[str, Any]] = []
    for entry in entries:
        require(isinstance(entry, dict), "MANIFEST_ENTRY_TYPE")
        relative = str(entry.get("relative_path", ""))
        require(relative and not Path(relative).is_absolute() and ".." not in Path(relative).parts, "MANIFEST_PATH")
        path = OVERLAY / relative
        actual = identity(path)
        require(
            (actual["size_bytes"], actual["sha256"])
            == (entry.get("size_bytes"), entry.get("sha256")),
            f"EXECUTION_TREE_DRIFT:{relative}",
        )
        observed.append(
            {
                "relative_path": relative,
                "size_bytes": actual["size_bytes"],
                "sha256": actual["sha256"],
            }
        )
    expected_paths = {str(entry["relative_path"]) for entry in entries}
    actual_paths: set[str] = set()
    for root_name in ("external_tools", "scripts", "uw_frontend"):
        root = OVERLAY / root_name
        for directory, directory_names, file_names in os.walk(root, followlinks=False):
            directory_path = Path(directory)
            for name in directory_names:
                require(
                    not (directory_path / name).is_symlink(),
                    f"EXECUTION_TREE_SYMLINK_DIR:{directory_path / name}",
                )
            for name in file_names:
                path = directory_path / name
                require(not path.is_symlink(), f"EXECUTION_TREE_SYMLINK_FILE:{path}")
                require(path.is_file(), f"EXECUTION_TREE_NONREGULAR:{path}")
                actual_paths.add(str(path.relative_to(OVERLAY)))
    require(actual_paths == expected_paths, "EXECUTION_TREE_TRANSITIVE_CLOSURE")
    for name in ("sitecustomize.py", "usercustomize.py", "cv2.py", "torch.py"):
        require(not (OVERLAY / name).exists(), f"OVERLAY_IMPORT_SHADOW:{name}")
    require(tree_root(observed) == EXPECTED_TREE_SHA256, "OBSERVED_TREE_ROOT")
    return {
        "file_count": len(observed),
        "tree_sha256": EXPECTED_TREE_SHA256,
        "transitive_closure_exact": True,
        "ambient_extra_source_files": 0,
    }


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def write_exclusive(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json(value)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def exact_ns(stamp: Any) -> int:
    require(type(stamp.secs) is int and type(stamp.nsecs) is int, "STAMP_NOT_INTEGER")
    require(stamp.secs >= 0 and 0 <= stamp.nsecs < 1_000_000_000, "STAMP_RANGE")
    return stamp.secs * 1_000_000_000 + stamp.nsecs


def rosbag_module() -> Any:
    ros_path = "/opt/ros/noetic/lib/python3/dist-packages"
    if ros_path not in sys.path:
        sys.path.insert(0, ros_path)
    import rosbag  # type: ignore

    return rosbag


def add_serialized(digest: Any, message: Any, record_stamp: Any) -> None:
    stream = io.BytesIO()
    message.serialize(stream)
    payload = stream.getvalue()
    digest.update(exact_ns(record_stamp).to_bytes(8, "big"))
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)


def raw_contract() -> dict[str, Any]:
    rosbag = rosbag_module()
    counts = {CAMERA_TOPIC: 0, IMU_TOPIC: 0, GT_TOPIC: 0}
    cameras: list[int] = []
    streams = {IMU_TOPIC: hashlib.sha256(), GT_TOPIC: hashlib.sha256()}
    with rosbag.Bag(str(RAW_BAG), "r") as bag:
        for topic, message, record_stamp in bag.read_messages(
            topics=[CAMERA_TOPIC, IMU_TOPIC, GT_TOPIC]
        ):
            stamp = exact_ns(message.header.stamp)
            require(stamp == exact_ns(record_stamp), f"RAW_HEADER_RECORD:{topic}")
            counts[topic] += 1
            if topic == CAMERA_TOPIC:
                cameras.append(stamp)
            else:
                add_serialized(streams[topic], message, record_stamp)
    require(
        counts == {CAMERA_TOPIC: CAMERA_COUNT, IMU_TOPIC: IMU_COUNT, GT_TOPIC: GT_COUNT},
        "RAW_COUNTS",
    )
    require(all(right > left for left, right in zip(cameras, cameras[1:])), "RAW_CAMERA_ORDER")
    feature_stamps = cameras[1::2]
    require(len(feature_stamps) == FEATURE_COUNT, "RAW_FEATURE_COUNT")
    require(feature_stamps[-1] == cameras[4659], "RAW_FEATURE_END")
    return {
        "counts": counts,
        "camera_first_ns": cameras[0],
        "camera_last_ns": cameras[-1],
        "feature_stamps": feature_stamps,
        "copied_stream_sha256": {
            topic: digest.hexdigest() for topic, digest in streams.items()
        },
    }


def environment_updates() -> dict[str, str]:
    standard_path = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    return {
        # This is the complete child environment, not an overlay on the
        # supervisor's environment.  In particular, BASH_ENV, LD_PRELOAD and
        # ad-hoc exporter variables from an interactive shell cannot leak in.
        "HOME": "/home/ma",
        "USER": "ma",
        "LOGNAME": "ma",
        "SHELL": "/bin/bash",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "ROOT": str(OVERLAY),
        "VINS_WS": "/home/ma/SLAM/VINS-Fusion-origin",
        "AQUALOC_ROOT": str(SOURCE_ARCHIVE.parent),
        "RAW_TAR": str(SOURCE_ARCHIVE),
        "GT_TXT": str(GT),
        "RAW_BAG": str(RAW_BAG),
        "FRONTEND_CONFIG": str(FRONTEND_CONFIG),
        "AQUAFE_SEEDCHAIN_PROFILE": "lineage_early_seed_scan",
        "SEMIDENSE_FALLBACK_METHOD": "none",
        "MEASUREMENT_SELECTION": "0",
        "FORMAL_THREE_LAYER_EXPORT": "0",
        "VINS_SAFE_SOURCE_SELECTION": "0",
        "EXPORT_MAX_FEATURES": "350",
        "LEARNED_EXPORT_BENEFIT_GATE": "0",
        "PREPROCESS": "adaptive_clahe",
        "PROCESS_SKIPPED_FRAMES": "1",
        "FRAME_OFFSET": "1",
        "EXPORT_MIN_AGE": "2",
        "SELECTION_WARMUP_FRAMES": "0",
        "EXPORT_MIN_LEARNED_AGE": "0",
        "EXPORT_CLASSICAL_MIRROR_BACKBONE": "0",
        "RESET_RECOVERED_EXPORT_IDS": "0",
        "LEARNED_EXPORT_ONLINE_SEED_POST_QUALITY_CAP_PER_FRAME": "2",
        "RUN_VINS": "0",
        "FORCE_RAW": "0",
        "FORCE_EXPORT": "1",
        "VINS_MULTIPLE_THREAD": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "OMP_NUM_THREADS": "2",
        "MKL_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
        "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
        "CUDA_VISIBLE_DEVICES": "0",
        "TMPDIR": str(TMP_ROOT),
        "PATH": f"{CUDA_BIN}:{standard_path}",
        "PYTHONPATH": f"{OVERLAY}:/opt/ros/noetic/lib/python3/dist-packages",
    }


def effective_seedchain_environment() -> dict[str, str]:
    python_code = r'''
import json, os
exact = {
    "AQUAFE_SEEDCHAIN_PROFILE", "FRONTEND_CONFIG", "SEMIDENSE_FALLBACK_METHOD",
    "MEASUREMENT_SELECTION", "FORMAL_THREE_LAYER_EXPORT",
    "VINS_SAFE_SOURCE_SELECTION", "EXPORT_MAX_FEATURES",
    "LEARNED_EXPORT_BENEFIT_GATE", "PREPROCESS", "PROCESS_SKIPPED_FRAMES",
    "FRAME_OFFSET", "EXPORT_MIN_AGE", "SELECTION_WARMUP_FRAMES",
    "EXPORT_MIN_LEARNED_AGE", "EXPORT_CLASSICAL_MIRROR_BACKBONE",
    "RESET_RECOVERED_EXPORT_IDS",
}
value = {
    key: item for key, item in os.environ.items()
    if key in exact or key.startswith("LEARNED_EXPORT_ONLINE_SEED_")
}
print(json.dumps(value, sort_keys=True))
'''
    environment = environment_updates()
    environment["AQUAFE_EFFECTIVE_ENV_CODE"] = python_code
    process = subprocess.run(
        [
            "/usr/bin/bash",
            "-c",
            'source "$ROOT/scripts/learned_seedchain_env.sh"; '
            'python3 -c "$AQUAFE_EFFECTIVE_ENV_CODE"',
        ],
        cwd=str(OVERLAY),
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )
    require(
        process.returncode == 0,
        f"EFFECTIVE_ENV_RC:{process.returncode}:{process.stderr[-400:]}",
    )
    try:
        value = json.loads(process.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as error:
        raise FrontendError("EFFECTIVE_ENV_JSON") from error
    require(isinstance(value, dict), "EFFECTIVE_ENV_TYPE")
    expected = {
        "AQUAFE_SEEDCHAIN_PROFILE": "lineage_early_seed_scan",
        "FRONTEND_CONFIG": str(FRONTEND_CONFIG),
        "SEMIDENSE_FALLBACK_METHOD": "none",
        "MEASUREMENT_SELECTION": "0",
        "FORMAL_THREE_LAYER_EXPORT": "0",
        "VINS_SAFE_SOURCE_SELECTION": "0",
        "EXPORT_MAX_FEATURES": "350",
        "LEARNED_EXPORT_BENEFIT_GATE": "0",
        "PREPROCESS": "adaptive_clahe",
        "PROCESS_SKIPPED_FRAMES": "1",
        "FRAME_OFFSET": "1",
        "EXPORT_MIN_AGE": "2",
        "SELECTION_WARMUP_FRAMES": "0",
        "EXPORT_MIN_LEARNED_AGE": "0",
        "EXPORT_CLASSICAL_MIRROR_BACKBONE": "0",
        "RESET_RECOVERED_EXPORT_IDS": "0",
        "LEARNED_EXPORT_ONLINE_SEED_POST_QUALITY_CAP_PER_FRAME": "2",
        "LEARNED_EXPORT_ONLINE_SEED_WARMUP_FRAMES": "0",
        "LEARNED_EXPORT_ONLINE_SEED_SOURCES": "xfeat",
        "LEARNED_EXPORT_ONLINE_SEED_GATE": "1",
    }
    for key, expected_value in expected.items():
        require(value.get(key) == expected_value, f"EFFECTIVE_ENV_VALUE:{key}")
    return {str(key): str(item) for key, item in sorted(value.items())}


def environment_fingerprint() -> dict[str, Any]:
    code = r'''
import json, os, pathlib, sys
import cv2, numpy, rosbag, torch, yaml
import torch._C
import uw_frontend.ros.export_vins_features as exporter
if torch.cuda.is_available():
    layer = torch.nn.Conv2d(1, 1, 3, padding=1).cuda()
    output = layer(torch.zeros((1, 1, 8, 8), device="cuda"))
    torch.cuda.synchronize()
module_files = {
    "cv2": cv2.__file__,
    "numpy": numpy.__file__,
    "rosbag": rosbag.__file__,
    "torch": torch.__file__,
    "torch._C": torch._C.__file__,
    "yaml": yaml.__file__,
    "uw_frontend_exporter": exporter.__file__,
}
mapped_files = set()
for line in pathlib.Path("/proc/self/maps").read_text(encoding="utf-8").splitlines():
    fields = line.split(None, 5)
    if len(fields) != 6 or not fields[5].startswith("/"):
        continue
    path = pathlib.Path(fields[5])
    if path.is_file():
        mapped_files.add(str(path.resolve()))
result = {
    "sys_executable": sys.executable,
    "python_version": sys.version.split()[0],
    "cv2_version": cv2.__version__,
    "numpy_version": numpy.__version__,
    "torch_version": torch.__version__,
    "torch_cuda_version": torch.version.cuda,
    "torch_cuda_available": torch.cuda.is_available(),
    "cuda_device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    "yaml_version": yaml.__version__,
    "exporter_file": str(pathlib.Path(exporter.__file__).resolve()),
    "path_after_ros_vins_setup": os.environ.get("PATH"),
    "pythonpath_after_ros_vins_setup": os.environ.get("PYTHONPATH"),
    "module_files": {
        key: str(pathlib.Path(path).resolve()) for key, path in module_files.items()
    },
    "mapped_files": sorted(mapped_files),
}
print(json.dumps(result, sort_keys=True))
'''
    environment = environment_updates()
    environment["AQUAFE_RUNTIME_CODE"] = code
    process = subprocess.run(
        [
            "/usr/bin/bash",
            "-c",
            'source "$ROOT/scripts/learned_seedchain_env.sh"; '
            'source /opt/ros/noetic/setup.bash; '
            'source "$VINS_WS/devel/setup.bash"; '
            'python3 -c "$AQUAFE_RUNTIME_CODE"',
        ],
        cwd=str(OVERLAY),
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
    )
    require(process.returncode == 0, f"ENVIRONMENT_IMPORT_RC:{process.returncode}:{process.stderr[-400:]}")
    try:
        value = json.loads(process.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as error:
        raise FrontendError("ENVIRONMENT_FINGERPRINT_JSON") from error
    require(value.get("torch_cuda_available") is True, "CUDA_NOT_AVAILABLE")
    require(
        Path(str(value.get("sys_executable", ""))).resolve() == CUDA_PYTHON.resolve(),
        "WRONG_PYTHON_AFTER_SETUP",
    )
    require(
        value.get("exporter_file") == str((OVERLAY / "uw_frontend/ros/export_vins_features.py").resolve()),
        "WRONG_EXPORTER_IMPORTED",
    )
    module_files = value.pop("module_files", None)
    mapped_files = value.pop("mapped_files", None)
    require(isinstance(module_files, dict) and module_files, "RUNTIME_MODULE_FILES")
    require(isinstance(mapped_files, list) and mapped_files, "RUNTIME_MAPPED_FILES")
    module_identities = {
        str(name): identity(Path(str(path)).resolve())
        for name, path in sorted(module_files.items())
    }
    mapped_identities = {
        str(path): identity(Path(str(path)).resolve()) for path in sorted(set(mapped_files))
    }
    static_paths = (
        CUDA_PYTHON.resolve(),
        CUDA_PYTHON.parent.parent / "pyvenv.cfg",
        Path("/usr/bin/bash"),
        Path("/opt/ros/noetic/setup.bash"),
        Path("/opt/ros/noetic/_setup_util.py"),
        Path("/home/ma/SLAM/VINS-Fusion-origin/devel/setup.bash"),
        Path("/home/ma/SLAM/VINS-Fusion-origin/devel/_setup_util.py"),
    )
    static_identities = {
        str(path): identity(path.resolve()) for path in static_paths
    }
    package_process = subprocess.run(
        [str(CUDA_PYTHON), "-m", "pip", "freeze", "--all"],
        cwd=str(OVERLAY),
        env=environment_updates(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
    )
    require(
        package_process.returncode == 0,
        f"PACKAGE_LOCK_RC:{package_process.returncode}:{package_process.stderr[-400:]}",
    )
    package_lock = sorted(
        line.strip() for line in package_process.stdout.splitlines() if line.strip()
    )
    require(package_lock, "PACKAGE_LOCK_EMPTY")
    sealed_environment = environment_updates()
    manifest = {
        "runtime": value,
        "effective_seedchain_environment": effective_seedchain_environment(),
        "sealed_process_environment": sealed_environment,
        "sealed_process_environment_sha256": hashlib.sha256(
            canonical_json(sealed_environment)
        ).hexdigest(),
        "static_runtime_files": static_identities,
        "imported_module_files": module_identities,
        "mapped_runtime_files": mapped_identities,
        "package_lock": package_lock,
        "package_lock_sha256": hashlib.sha256(
            ("\n".join(package_lock) + "\n").encode("utf-8")
        ).hexdigest(),
        "ambient_environment_inherited": False,
    }
    manifest["runtime_environment_manifest_sha256"] = hashlib.sha256(
        canonical_json(manifest)
    ).hexdigest()
    return manifest


def fixed_inputs() -> dict[str, Any]:
    result = {
        str(path): require_identity(path, expected)
        for path, expected in FIXED_IDENTITIES.items()
    }
    result[str(Path(__file__).resolve())] = identity(Path(__file__).resolve())
    return result


def command_for(stage: str) -> tuple[list[str], dict[str, str]]:
    env = environment_updates()
    if stage == "klt":
        env["TAG"] = KLT_TAG
        command = [
            "/usr/bin/bash",
            str(OVERLAY / "scripts/run_learned_seedchain_eval.sh"),
            "aqualoc_archaeo",
            "8",
            "0",
            "4660",
            "klt",
            "2",
        ]
    else:
        env["TAG_BASE"] = XFEAT_TAG_BASE
        command = [
            "/usr/bin/bash",
            str(OVERLAY / "scripts/run_xfeat_seedchain_arbitrated_eval.sh"),
            "aqualoc_archaeo",
            "8",
            "0",
            "4660",
            "hybrid_xfeat",
            "2",
        ]
    return command, env


def parse_summary(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key] = value
    return values


def find_xfeat_runs() -> tuple[Path, Path, dict[str, str], Path]:
    summaries = sorted(
        RUN_ROOT.glob(f"*{XFEAT_TAG_BASE}*/arbitration_summary.txt")
    )
    require(len(summaries) == 1, f"XFEAT_SUMMARY_COUNT:{len(summaries)}")
    summary = summaries[0]
    require(summary.is_file() and not summary.is_symlink(), "XFEAT_SUMMARY_REGULAR")
    values = parse_summary(summary)
    require(values.get("dataset_family") == "aqualoc_archaeo", "XFEAT_DATASET_FAMILY")
    require(
        values.get("seedchain_profile") == "lineage_early_seed_scan",
        "XFEAT_SEEDCHAIN_PROFILE",
    )
    profile = values.get("profile")
    require(
        profile
        in {
            "degraded_mature_dense",
            "mature_lineage",
            "oldcontract_microburst",
            "late_dense_normal",
            "mirror_densecap",
            "klt_safe_fallback",
            "degraded_early_dense",
            "degraded_early_long",
            "degraded_early_sparse_mature",
            "low_grid_rejected_rich",
        },
        f"XFEAT_PROFILE:{profile}",
    )
    probe_run = Path(values.get("probe_run", ""))
    expected_probe = (
        RUN_ROOT
        / f"external_hybrid_xfeat_every2_{XFEAT_TAG_BASE}_probe_oldcontract_densecap"
    )
    require(probe_run == expected_probe, "XFEAT_PROBE_RUN_BINDING")
    final_run = Path(values.get("final_run", ""))
    feature_bag = Path(values.get("feature_bag", ""))
    require(final_run == summary.parent, "XFEAT_FINAL_RUN_BINDING")
    require(feature_bag == final_run / "features.bag", "XFEAT_FEATURE_BAG_BINDING")
    require(values.get("profile") not in (None, ""), "XFEAT_PROFILE_MISSING")
    for name, run_dir in (("PROBE", probe_run), ("FINAL", final_run)):
        require(run_dir.parent == RUN_ROOT, f"XFEAT_{name}_PARENT")
        require(run_dir.is_dir() and not run_dir.is_symlink(), f"XFEAT_{name}_DIR")
    return probe_run, final_run, values, summary


def channel_map(message: Any) -> dict[str, list[float]]:
    names = tuple(channel.name for channel in message.channels)
    require(names == CHANNELS, f"FEATURE_CHANNELS:{names}")
    values = {channel.name: list(channel.values) for channel in message.channels}
    require(all(len(column) == len(message.points) for column in values.values()), "CHANNEL_LENGTH")
    return values


def audit_feature_bag(
    run_dir: Path, raw: dict[str, Any], stage: str, summary: Optional[dict[str, str]] = None
) -> dict[str, Any]:
    rosbag = rosbag_module()
    bag_path = run_dir / "features.bag"
    metrics_path = run_dir / "frontend_metrics.csv"
    camera_path = run_dir / "aqualoc_archaeo08_pinhole.yaml"
    require(all(path.is_file() and not path.is_symlink() for path in (bag_path, metrics_path, camera_path)), "OUTPUT_MISSING")
    counts = {FEATURE_TOPIC: 0, IMU_TOPIC: 0, GT_TOPIC: 0}
    streams = {IMU_TOPIC: hashlib.sha256(), GT_TOPIC: hashlib.sha256()}
    stamps: list[int] = []
    total_points = 0
    point_count_histogram: dict[int, int] = {}
    learned_flags = 0
    xfeat_source_points = 0
    bag_learned_by_frame: list[int] = []
    bag_xfeat_by_frame: list[int] = []
    with rosbag.Bag(str(bag_path), "r") as bag:
        topics = bag.get_type_and_topic_info().topics
        require(set(topics) == {FEATURE_TOPIC, IMU_TOPIC, GT_TOPIC}, "FEATURE_TOPIC_SET")
        require(topics[FEATURE_TOPIC].msg_type == "sensor_msgs/PointCloud", "FEATURE_TYPE")
        for topic, message, record_stamp in bag.read_messages():
            stamp = exact_ns(message.header.stamp)
            require(stamp == exact_ns(record_stamp), f"FEATURE_HEADER_RECORD:{topic}")
            counts[topic] += 1
            if topic != FEATURE_TOPIC:
                add_serialized(streams[topic], message, record_stamp)
                continue
            require(message.header.frame_id == "world", "FEATURE_FRAME_ID")
            require(0 <= len(message.points) <= 350, "FEATURE_POINT_COUNT_RANGE")
            point_count_histogram[len(message.points)] = (
                point_count_histogram.get(len(message.points), 0) + 1
            )
            channels = channel_map(message)
            numeric = [value for column in channels.values() for value in column]
            require(all(math.isfinite(value) for value in numeric), "FEATURE_NONFINITE_CHANNEL")
            require(
                all(math.isfinite(value) for point in message.points for value in (point.x, point.y, point.z)),
                "FEATURE_NONFINITE_POINT",
            )
            require(all(abs(point.z - 1.0) <= 1e-7 for point in message.points), "FEATURE_POINT_Z")
            flags = [int(round(value)) for value in channels["is_learned"]]
            sources = [int(round(value)) for value in channels["source_code"]]
            require(all(abs(value - round(value)) <= 1e-6 for value in channels["is_learned"]), "LEARNED_FLAG_NONINTEGER")
            require(all(abs(value - round(value)) <= 1e-6 for value in channels["source_code"]), "SOURCE_CODE_NONINTEGER")
            require(all(value in (0, 1) for value in flags), "LEARNED_FLAG_RANGE")
            require(all(value in (1, 2, 20) for value in sources), "SOURCE_CODE_RANGE")
            require(
                all(flag == int(source == 20) for flag, source in zip(flags, sources)),
                "XFEAT_SOURCE_FLAG_PER_POINT",
            )
            learned_flags += sum(flags)
            frame_xfeat_points = sum(value == 20 for value in sources)
            xfeat_source_points += frame_xfeat_points
            bag_learned_by_frame.append(sum(flags))
            bag_xfeat_by_frame.append(frame_xfeat_points)
            require(sum(flags) == frame_xfeat_points, "BAG_XFEAT_LEARNED_FLAG_MISMATCH")
            if stage == "klt":
                require(sum(flags) == 0, "KLT_LEARNED_FLAG_NONZERO")
                require(all(value in (1, 2) for value in sources), "KLT_SOURCE_CODE")
            stamps.append(stamp)
            total_points += len(message.points)
    require(
        counts == {FEATURE_TOPIC: FEATURE_COUNT, IMU_TOPIC: IMU_COUNT, GT_TOPIC: GT_COUNT},
        "FEATURE_COUNTS",
    )
    require(stamps == raw["feature_stamps"], "FEATURE_ODD_FRAME_BINDING")
    require(total_points > 0, "FEATURE_TOTAL_POINTS_ZERO")
    for topic in (IMU_TOPIC, GT_TOPIC):
        require(
            streams[topic].hexdigest() == raw["copied_stream_sha256"][topic],
            f"COPIED_STREAM_DRIFT:{topic}",
        )

    with metrics_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames is not None, "METRICS_HEADER")
        rows = list(reader)
    require(len(rows) == FEATURE_COUNT, "METRICS_ROW_COUNT")
    required = {
        "frame_index",
        "selected_feature_index",
        "exported_learned_features",
        "exported_xfeat_features",
        "source_provenance_xfeat_count",
    }
    require(required.issubset(set(reader.fieldnames or [])), "METRICS_REQUIRED_COLUMNS")
    for index, row in enumerate(rows):
        require(int(row["frame_index"]) == 1 + 2 * index, f"METRICS_FRAME:{index}")
        require(int(row["selected_feature_index"]) == index, f"METRICS_SELECTED:{index}")

    metrics_learned_by_frame = [
        int(round(float(row.get("exported_learned_features") or 0))) for row in rows
    ]
    metrics_xfeat_by_frame = [
        int(round(float(row.get("exported_xfeat_features") or 0))) for row in rows
    ]
    require(
        bag_learned_by_frame == metrics_learned_by_frame,
        "BAG_METRICS_LEARNED_PER_FRAME",
    )
    require(
        bag_xfeat_by_frame == metrics_xfeat_by_frame,
        "BAG_METRICS_XFEAT_PER_FRAME",
    )

    def sum_column(name: str, minimum_frame: int = 0) -> int:
        return sum(
            int(round(float(row.get(name) or 0)))
            for row in rows
            if int(row["frame_index"]) >= minimum_frame
        )

    metrics_action = {
        "exported_learned_full": sum_column("exported_learned_features"),
        "exported_xfeat_full": sum_column("exported_xfeat_features"),
        "source_provenance_xfeat_full": sum_column("source_provenance_xfeat_count"),
        "exported_xfeat_support_4000_4660": sum_column("exported_xfeat_features", SUPPORT_START),
        "exported_xfeat_positive_4500_4660": sum_column("exported_xfeat_features", POSITIVE_START),
    }
    if stage == "klt":
        require(all(value == 0 for value in metrics_action.values()), "KLT_METRICS_LEARNED_NONZERO")
    require(
        learned_flags
        == xfeat_source_points
        == metrics_action["exported_learned_full"]
        == metrics_action["exported_xfeat_full"],
        "XFEAT_ACTION_TOTAL_MISMATCH",
    )
    run_files = sorted(path for path in run_dir.iterdir() if path.is_file())
    require(
        all(not path.is_symlink() for path in run_files),
        "RUN_ARTIFACT_SYMLINK",
    )
    expected_names = {
        "features.bag",
        "frontend_metrics.csv",
        "aqualoc_archaeo08_pinhole.yaml",
    }
    if summary is not None:
        expected_names.add("arbitration_summary.txt")
    require({path.name for path in run_files} == expected_names, "RUN_ARTIFACT_CLOSURE")
    require(
        all(path.is_file() and not path.is_symlink() for path in run_dir.iterdir()),
        "RUN_DIRECTORY_HAS_NONFILE",
    )
    return {
        "status": f"PASS_{stage.upper()}_EXPORT_AUDIT",
        "run_dir": str(run_dir),
        "topic_counts": counts,
        "feature_first_ns": stamps[0],
        "feature_last_ns": stamps[-1],
        "feature_messages": len(stamps),
        "total_points": total_points,
        "point_count_min": min(point_count_histogram),
        "point_count_max": max(point_count_histogram),
        "empty_feature_messages": point_count_histogram.get(0, 0),
        "point_count_histogram": {
            str(key): value for key, value in sorted(point_count_histogram.items())
        },
        "bag_learned_flags": learned_flags,
        "bag_xfeat_source_points": xfeat_source_points,
        "metrics_rows": len(rows),
        "metrics_columns": len(reader.fieldnames or []),
        "method_native_action": metrics_action,
        "arbitration": summary,
        "outputs": {
            "features_bag": identity(bag_path),
            "frontend_metrics": identity(metrics_path),
            "camera_config": identity(camera_path),
        },
        "all_generated_regular_files": {
            path.name: identity(path) for path in run_files
        },
        "copied_stream_sha256": {
            topic: digest.hexdigest() for topic, digest in streams.items()
        },
    }


def preflight(stage: str) -> dict[str, Any]:
    require(FRONTEND_CONFIG.is_file() and not FRONTEND_CONFIG.is_symlink(), "FRONTEND_CONFIG")
    tree = verify_execution_tree()
    inputs = fixed_inputs()
    environment = environment_fingerprint()
    command, env = command_for(stage)
    if stage == "klt":
        require(not KLT_CLAIM.exists() and not KLT_CLAIM.is_symlink(), "KLT_CLAIM_EXISTS")
        require(not KLT_RECEIPT.exists() and not KLT_RECEIPT.is_symlink(), "KLT_RECEIPT_EXISTS")
        require(not KLT_FAILURE.exists() and not KLT_FAILURE.is_symlink(), "KLT_FAILURE_EXISTS")
        require(not KLT_LOG.exists() and not KLT_LOG.is_symlink(), "KLT_LOG_EXISTS")
        require(not KLT_RUN.exists() and not KLT_RUN.is_symlink(), "KLT_RUN_EXISTS")
        raw = raw_contract()
    else:
        require(KLT_RECEIPT.is_file() and not KLT_RECEIPT.is_symlink(), "KLT_RECEIPT_MISSING")
        klt_receipt = json.loads(KLT_RECEIPT.read_text(encoding="utf-8"))
        require(klt_receipt.get("status") == "PASS_FRONTEND_EXPORT_ACCEPTED", "KLT_RECEIPT_STATUS")
        raw = klt_receipt.get("raw_contract")
        require(isinstance(raw, dict) and len(raw.get("feature_stamps", [])) == FEATURE_COUNT, "KLT_RAW_CONTRACT")
        require(not XFEAT_CLAIM.exists() and not XFEAT_CLAIM.is_symlink(), "XFEAT_CLAIM_EXISTS")
        require(not XFEAT_RECEIPT.exists() and not XFEAT_RECEIPT.is_symlink(), "XFEAT_RECEIPT_EXISTS")
        require(not XFEAT_FAILURE.exists() and not XFEAT_FAILURE.is_symlink(), "XFEAT_FAILURE_EXISTS")
        require(not XFEAT_LOG.exists() and not XFEAT_LOG.is_symlink(), "XFEAT_LOG_EXISTS")
        require(
            not any(RUN_ROOT.glob(f"*{XFEAT_TAG_BASE}*")),
            "XFEAT_RUN_PREFIX_EXISTS",
        )
        inputs[str(KLT_RECEIPT)] = identity(KLT_RECEIPT)
    require(shutil_disk_free(FRONTEND_ROOT.parent) >= 6_000_000_000, "INSUFFICIENT_SPACE")
    return {
        "status": f"READY_{stage.upper()}_EXPORT_ONLY",
        "stage": stage,
        "inputs": inputs,
        "execution_tree": tree,
        "environment_fingerprint": environment,
        "command": command,
        "environment": env,
        "raw_contract": raw,
        "vins_or_accuracy_executed": False,
    }


def shutil_disk_free(path: Path) -> int:
    path.mkdir(parents=True, exist_ok=True)
    return os.statvfs(path).f_bavail * os.statvfs(path).f_frsize


def terminate_group(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    for sig, wait_seconds in ((signal.SIGINT, 10), (signal.SIGTERM, 10), (signal.SIGKILL, 2)):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=wait_seconds)
            return
        except subprocess.TimeoutExpired:
            continue


def run_child(
    command: list[str],
    env: dict[str, str],
    log_path: Path,
    timeout: int,
    child_state: dict[str, Any],
) -> tuple[int, float]:
    started = time.monotonic()
    descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(descriptor, "wb") as log:
        process = subprocess.Popen(
            command,
            cwd=str(OVERLAY),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        child_state["popen_started"] = True
        child_state["pid"] = process.pid
        try:
            return_code = process.wait(timeout=timeout)
        except BaseException:
            terminate_group(process)
            raise
    return return_code, time.monotonic() - started


def execute(stage: str) -> dict[str, Any]:
    FRONTEND_ROOT.mkdir(parents=True, exist_ok=True)
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    ready = preflight(stage)
    claim_path = KLT_CLAIM if stage == "klt" else XFEAT_CLAIM
    receipt_path = KLT_RECEIPT if stage == "klt" else XFEAT_RECEIPT
    failure_path = KLT_FAILURE if stage == "klt" else XFEAT_FAILURE
    log_path = KLT_LOG if stage == "klt" else XFEAT_LOG
    started = datetime.now(timezone.utc)
    claim = {
        "schema_version": "aqua-fe-a08-recovered-july-frontend-process-start-claim-v1",
        "status": "CLAIMED_BEFORE_SINGLE_POPEN_NO_AUTOMATIC_RETRY",
        "stage": stage,
        "claimed_at_utc": started.isoformat(timespec="seconds"),
        "command": ready["command"],
        "environment": ready["environment"],
        "inputs": ready["inputs"],
        "execution_tree": ready["execution_tree"],
        "environment_fingerprint": ready["environment_fingerprint"],
        "vins_or_accuracy_executed": False,
    }
    write_exclusive(claim_path, claim)
    child_state: dict[str, Any] = {"popen_started": False, "pid": None}
    try:
        return_code, wall_time = run_child(
            ready["command"],
            ready["environment"],
            log_path,
            10_800 if stage == "klt" else 21_600,
            child_state,
        )
        require(return_code == 0, f"CHILD_RETURN_CODE:{return_code}")
        if stage == "klt":
            run_dir = KLT_RUN
            summary = None
            audit = audit_feature_bag(run_dir, ready["raw_contract"], stage, summary)
        else:
            probe_run, run_dir, summary, summary_path = find_xfeat_runs()
            probe_audit = audit_feature_bag(
                probe_run, ready["raw_contract"], "xfeat_probe"
            )
            final_audit = audit_feature_bag(
                run_dir, ready["raw_contract"], "xfeat", summary
            )
            klt_receipt = json.loads(KLT_RECEIPT.read_text(encoding="utf-8"))
            klt_camera = klt_receipt["artifact_audit"]["outputs"]["camera_config"]
            camera_identities = (
                klt_camera,
                probe_audit["outputs"]["camera_config"],
                final_audit["outputs"]["camera_config"],
            )
            require(
                len(
                    {
                        (item["size_bytes"], item["sha256"])
                        for item in camera_identities
                    }
                )
                == 1,
                "CONTROL_CAMERA_CONFIG_MISMATCH",
            )
            audit = {
                "status": "PASS_XFEAT_METHOD_NATIVE_PROBE_AND_FINAL_EXPORT_AUDIT",
                "probe": probe_audit,
                "final": final_audit,
                "arbitration_summary": identity(summary_path),
                "camera_config_matched_to_klt": True,
            }
        post_tree = verify_execution_tree()
        post_environment = environment_fingerprint()
        require(post_tree == ready["execution_tree"], "TREE_CHANGED_DURING_RUN")
        require(post_environment == ready["environment_fingerprint"], "ENVIRONMENT_CHANGED_DURING_RUN")
        post_inputs = fixed_inputs()
        for path, before in ready["inputs"].items():
            if path == str(KLT_RECEIPT):
                post_inputs[path] = identity(KLT_RECEIPT)
            require(path in post_inputs, f"POST_INPUT_MISSING:{path}")
            require(
                (before["size_bytes"], before["sha256"])
                == (post_inputs[path]["size_bytes"], post_inputs[path]["sha256"]),
                f"INPUT_CHANGED_DURING_RUN:{path}",
            )
        ended = datetime.now(timezone.utc)
        receipt = {
            "schema_version": "aqua-fe-a08-recovered-july-natural-history-frontend-receipt-v1",
            "status": "PASS_FRONTEND_EXPORT_ACCEPTED",
            "stage": stage,
            "started_at_utc": started.isoformat(timespec="seconds"),
            "ended_at_utc": ended.isoformat(timespec="seconds"),
            "wall_time_seconds_nonbenchmark": wall_time,
            "terminal_process": {
                "return_code": return_code,
                "single_supervisor_popen": True,
                "pid": child_state["pid"],
                "method_native_planned_export_count": 1 if stage == "klt" else 2,
                "automatic_retry_count": 0,
            },
            "process_start_claim": identity(claim_path),
            "supervisor_log": identity(log_path),
            "command": ready["command"],
            "environment": ready["environment"],
            "inputs_before": ready["inputs"],
            "inputs_after": post_inputs,
            "execution_tree_before": ready["execution_tree"],
            "execution_tree_after": post_tree,
            "environment_before": ready["environment_fingerprint"],
            "environment_after": post_environment,
            "raw_contract": ready["raw_contract"],
            "artifact_audit": audit,
            "claim_boundary": {
                "export_only": True,
                "vins_or_slam_executed": False,
                "ape_or_rpe_computed": False,
                "runtime_claim_permitted": False,
                "ambient_desktop_and_unrelated_jobs_allowed_by_user_waiver": True,
                "complete_july_environment_reproduction": False,
                "method_label": "recovered seven-file July core plus newly frozen transitive closure",
                "zero_learned_action_is_accepted": True,
                "rearm_at_source_4000_or_4500": False,
            },
        }
        write_exclusive(receipt_path, receipt)
        return {
            "status": receipt["status"],
            "stage": stage,
            "run_dir": str(run_dir),
            "artifact_audit": audit,
            "receipt": identity(receipt_path),
        }
    except BaseException as error:
        failure = {
            "schema_version": "aqua-fe-a08-recovered-july-frontend-failure-v1",
            "status": "FAILED_NO_AUTOMATIC_RETRY",
            "stage": stage,
            "failed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "error_type": type(error).__name__,
            "error": str(error),
            "popen_started": child_state["popen_started"],
            "popen_pid": child_state["pid"],
            "process_start_claim": identity(claim_path),
            "log": identity(log_path) if log_path.is_file() else None,
            "vins_or_accuracy_executed": False,
        }
        if not failure_path.exists() and not failure_path.is_symlink():
            write_exclusive(failure_path, failure)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("preflight-klt", "run-klt", "preflight-xfeat", "run-xfeat", "audit-all"),
    )
    args = parser.parse_args()
    try:
        if args.command == "preflight-klt":
            result = preflight("klt")
        elif args.command == "run-klt":
            result = execute("klt")
        elif args.command == "preflight-xfeat":
            result = preflight("xfeat")
        elif args.command == "run-xfeat":
            result = execute("xfeat")
        else:
            require(KLT_RECEIPT.is_file() and XFEAT_RECEIPT.is_file(), "RECEIPTS_MISSING")
            klt = json.loads(KLT_RECEIPT.read_text(encoding="utf-8"))
            xfeat = json.loads(XFEAT_RECEIPT.read_text(encoding="utf-8"))
            require(klt.get("status") == xfeat.get("status") == "PASS_FRONTEND_EXPORT_ACCEPTED", "RECEIPT_STATUS")
            require(klt.get("stage") == "klt" and xfeat.get("stage") == "xfeat", "RECEIPT_STAGE")
            require(klt.get("raw_contract") == xfeat.get("raw_contract"), "RECEIPT_RAW_CONTRACT")
            raw = klt["raw_contract"]
            probe_run, xfeat_run, summary, summary_path = find_xfeat_runs()
            live_klt = audit_feature_bag(KLT_RUN, raw, "klt")
            live_probe = audit_feature_bag(probe_run, raw, "xfeat_probe")
            live_final = audit_feature_bag(xfeat_run, raw, "xfeat", summary)
            live_xfeat = {
                "status": "PASS_XFEAT_METHOD_NATIVE_PROBE_AND_FINAL_EXPORT_AUDIT",
                "probe": live_probe,
                "final": live_final,
                "arbitration_summary": identity(summary_path),
                "camera_config_matched_to_klt": True,
            }
            require(live_klt == klt.get("artifact_audit"), "KLT_RECEIPT_ARTIFACT_DRIFT")
            require(live_xfeat == xfeat.get("artifact_audit"), "XFEAT_RECEIPT_ARTIFACT_DRIFT")
            camera_identities = (
                live_klt["outputs"]["camera_config"],
                live_probe["outputs"]["camera_config"],
                live_final["outputs"]["camera_config"],
            )
            require(
                len(
                    {
                        (item["size_bytes"], item["sha256"])
                        for item in camera_identities
                    }
                )
                == 1,
                "AUDIT_ALL_CAMERA_CONFIG_MISMATCH",
            )
            live_tree = verify_execution_tree()
            require(
                all(
                    receipt.get(key) == live_tree
                    for receipt in (klt, xfeat)
                    for key in ("execution_tree_before", "execution_tree_after")
                ),
                "RECEIPT_EXECUTION_TREE_DRIFT",
            )
            live_environment = environment_fingerprint()
            require(
                all(
                    receipt.get(key) == live_environment
                    for receipt in (klt, xfeat)
                    for key in ("environment_before", "environment_after")
                ),
                "RECEIPT_ENVIRONMENT_DRIFT",
            )
            for receipt, claim_path, log_path in (
                (klt, KLT_CLAIM, KLT_LOG),
                (xfeat, XFEAT_CLAIM, XFEAT_LOG),
            ):
                require(
                    receipt.get("process_start_claim") == identity(claim_path),
                    "RECEIPT_CLAIM_DRIFT",
                )
                require(
                    receipt.get("supervisor_log") == identity(log_path),
                    "RECEIPT_LOG_DRIFT",
                )
                runner_key = str(Path(__file__).resolve())
                require(
                    receipt.get("inputs_before", {}).get(runner_key)
                    == identity(Path(__file__).resolve()),
                    "RECEIPT_RUNNER_DRIFT",
                )
            result = {
                "status": "PASS_BOTH_FRONTEND_EXPORTS",
                "klt": live_klt,
                "xfeat_probe": live_probe,
                "xfeat_final": live_final,
                "arbitration_summary": identity(summary_path),
                "execution_tree": live_tree,
                "environment_manifest_sha256": live_environment[
                    "runtime_environment_manifest_sha256"
                ],
                "receipts_bound_to_live_artifacts": True,
            }
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))
        return 0
    except (FrontendError, OSError, ValueError, csv.Error, subprocess.SubprocessError) as error:
        print(f"FRONTEND_ERROR:{type(error).__name__}:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
