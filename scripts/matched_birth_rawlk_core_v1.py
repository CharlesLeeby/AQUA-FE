#!/usr/bin/env python3
"""Shared carrier for the post-result matched detector-birth experiment.

This module is additive.  It deliberately leaves the published SuperPoint and
XFeat carrier exporters byte-for-byte unchanged.  Both matched arms call this
module, which in turn reuses only the frozen carrier primitives while owning a
new message/publication contract, manifest schema, diagnostics stream, and
four-artifact no-clobber transaction inside a private work directory.

The only scientifically active implementation supplied by an arm is
``detector.detect(processed_mono8) -> (points_xy, scores)``.  Detector-specific
provenance channels are truthful but are proven inert for the frozen VINS
consumer; all carrier and numerical-runtime fields are shared.
"""

from __future__ import annotations

import copy
import ctypes
import csv
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import time
import types
from typing import Callable, Mapping, Sequence


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

import cv2
from geometry_msgs.msg import Point32
import numpy as np
import numpy.core._multiarray_umath as numpy_multiarray
import numpy.linalg._umath_linalg as numpy_linalg
from sensor_msgs.msg import ChannelFloat32, PointCloud

from scripts import export_superpoint_lk_carrier_v1 as primitive


SCHEMA_VERSION = "aqua-fe-detector-birth-rawlk-matched-export-v1"
COMMON_CONTRACT_SCHEMA = "aqua-fe-detector-birth-rawlk-common-contract-v1"
FEATURE_TOPIC_DEFAULT = "/feature_tracker/feature"
FEATURE_CAP = 350
MAX_CANDIDATES = 2048
PROVENANCE_CHANNELS = ("source_code", "is_learned")
EXPECTED_PYTHON = Path("/usr/bin/python3.8")
EXPECTED_NUMPY_VERSION = "1.24.4"
EXPECTED_OPENCV_VERSION = "4.2.0"
EXPECTED_NUMERIC_FILES = {
    "numpy_init": (
        "/home/ma/.local/lib/python3.8/site-packages/numpy/__init__.py",
        16174,
        "edd18feff93348beb02f392959e80b9fda1875a842d7f9760847f32386fdfd48",
    ),
    "numpy_multiarray": (
        "/home/ma/.local/lib/python3.8/site-packages/numpy/core/"
        "_multiarray_umath.cpython-38-x86_64-linux-gnu.so",
        6311424,
        "190fed599b26cf689e22f198faf97d632f1d19b8aa75fdf5ca7fb96d37d97e37",
    ),
    "numpy_linalg": (
        "/home/ma/.local/lib/python3.8/site-packages/numpy/linalg/"
        "_umath_linalg.cpython-38-x86_64-linux-gnu.so",
        230272,
        "77d989daf30e91b14b657f0a125377d1c5bf49d7d950522baefdce9a7a93f927",
    ),
    "opencv_binary": (
        "/usr/lib/python3/dist-packages/cv2.cpython-38-x86_64-linux-gnu.so",
        6970496,
        "00f302d1efe76049187e2e2c7a05262e883394f82316490e2f28adb807ac1833",
    ),
}
EXPECTED_NATIVE_NUMERIC_FILES = {
    "opencv_core": (
        "/usr/lib/x86_64-linux-gnu/libopencv_core.so.4.2.0",
        3840856,
        "7b40148fa383e73b3fd968a7cb9842dce2c9210a02bf2257f468c3df0c00cbb2",
    ),
    "opencv_imgproc": (
        "/usr/lib/x86_64-linux-gnu/libopencv_imgproc.so.4.2.0",
        5266136,
        "42746b815bd7d0b1755d95e41f80b5b36c606612cfbdb5858fdcf306866c4610",
    ),
    "opencv_video": (
        "/usr/lib/x86_64-linux-gnu/libopencv_video.so.4.2.0",
        494040,
        "7b239ead75acf14fc4c9d7c6219bcd551c885eb824e7400518e648eb5b73e2e4",
    ),
    "opencv_calib3d": (
        "/usr/lib/x86_64-linux-gnu/libopencv_calib3d.so.4.2.0",
        1907000,
        "953ebae257e70f28c9dd16c1aa8a7aba3833315aa16d918c35b723f00ff03df6",
    ),
    "numpy_openblas": (
        "/home/ma/.local/lib/python3.8/site-packages/numpy.libs/"
        "libopenblas64_p-r0-15028c96.3.21.so",
        32955056,
        "554bde1d8a0c71d8dc21ae74de05c44da4fff5dbc6791a819f6acf5adfe90bd9",
    ),
    "numpy_gfortran": (
        "/home/ma/.local/lib/python3.8/site-packages/numpy.libs/"
        "libgfortran-040039e1.so.5.0.0",
        2686064,
        "47ab3b68295b0a3ce8990a448de7fab11abddbc160f8895972ca9aa712cf86d0",
    ),
    "numpy_quadmath": (
        "/home/ma/.local/lib/python3.8/site-packages/numpy.libs/"
        "libquadmath-96973f99.so.0.0.0",
        247608,
        "97cda85ddb5163e2da6e1edb4e1d6b557833a99a40eda079ae37e5039465b65d",
    ),
}
EXPECTED_PYTHONPATH = (
    "/home/ma/AQUA-FE_WS:"
    "/home/ma/.local/lib/python3.8/site-packages:"
    "/opt/ros/noetic/lib/python3/dist-packages"
)
EXPECTED_SYS_PATH = [
    "/home/ma/AQUA-FE_WS",
    # ``python -m scripts.<entrypoint>`` contributes the exact working
    # directory once, while the frozen PYTHONPATH contributes the same
    # canonical workspace a second time.  This duplicate is intentional and
    # is part of the sealed module-entry runtime contract.
    "/home/ma/AQUA-FE_WS",
    "/home/ma/.local/lib/python3.8/site-packages",
    "/opt/ros/noetic/lib/python3/dist-packages",
    "/usr/lib/python38.zip",
    "/usr/lib/python3.8",
    "/usr/lib/python3.8/lib-dynload",
    "/usr/local/lib/python3.8/dist-packages",
    "/usr/lib/python3/dist-packages",
]
EXPECTED_ENV = {
    "HOME": "/home/ma",
    "USER": "ma",
    "LOGNAME": "ma",
    "SHELL": "/bin/bash",
    "PATH": (
        "/opt/ros/noetic/bin:/usr/local/sbin:/usr/local/bin:"
        "/usr/sbin:/usr/bin:/sbin:/bin"
    ),
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PYTHONPATH": EXPECTED_PYTHONPATH,
    "PYTHONNOUSERSITE": "1",
    "PYTHONHASHSEED": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "CUDA_VISIBLE_DEVICES": "",
    "LD_LIBRARY_PATH": (
        "/home/ma/SLAM/VINS-Fusion-origin/devel/lib:"
        "/opt/ros/noetic/lib:/opt/ros/noetic/lib/x86_64-linux-gnu"
    ),
}
EXPECTED_SHARED_PACKAGE_INITIALIZERS = {
    "uw_frontend": {
        "module": "uw_frontend",
        "path": "/home/ma/AQUA-FE_WS/uw_frontend/__init__.py",
        "size_bytes": 75,
        "sha256": "44c8ccc9ab0cd7e8637b0dd005f183fb7b250a539c8b22ea6d26889a394f0934",
        "package_path": ["/home/ma/AQUA-FE_WS/uw_frontend"],
    },
    "uw_frontend_quality": {
        "module": "uw_frontend.quality",
        "path": "/home/ma/AQUA-FE_WS/uw_frontend/quality/__init__.py",
        "size_bytes": 42,
        "sha256": "940c342bc9918992c9e53190993d1bff4f04970d3d0a9536d99f069a1b4a85fd",
        "package_path": ["/home/ma/AQUA-FE_WS/uw_frontend/quality"],
    },
}
_GENPY_TEMP_DIRECTORY_RE = re.compile(r"/tmp/genpy_[a-z0-9_]+")
_GENPY_TEMP_SOURCE_RE = re.compile(r"tmp[a-z0-9_]+\.py")
EXPECTED_MODULE_FILES = {
    "rosbag": (
        "/opt/ros/noetic/lib/python3/dist-packages/rosbag/__init__.py",
        1800,
        "a65e884f18df0e88ff7403b53d77ad9ac59bd24734d880e301f7afe68fec4a81",
    ),
    "rosbag.bag": (
        "/opt/ros/noetic/lib/python3/dist-packages/rosbag/bag.py",
        115356,
        "ce9e721c70fb0327e4db04b2e1e585636e3282275b7c8a62508166500d9c8206",
    ),
    "rosbag.migration": (
        "/opt/ros/noetic/lib/python3/dist-packages/rosbag/migration.py",
        56042,
        "95d2e63fce15b6da61ec223088763cfcb74b97ddc5ac78c6c8c81f75eb30da02",
    ),
    "geometry_msgs": (
        "/opt/ros/noetic/lib/python3/dist-packages/geometry_msgs/__init__.py",
        0,
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ),
    "geometry_msgs.msg": (
        "/opt/ros/noetic/lib/python3/dist-packages/geometry_msgs/msg/__init__.py",
        848,
        "d19edf818de477fe4555552190ee083ce4967320d3b0ce63a6e79b0eceff0cb2",
    ),
    "geometry_msgs.msg._Point32": (
        "/opt/ros/noetic/lib/python3/dist-packages/geometry_msgs/msg/_Point32.py",
        4251,
        "6ac077c397c9cf6bad39917b8325ae7807f4265c76399fea1081d14136fd85a9",
    ),
    "sensor_msgs.msg._Image": (
        "/opt/ros/noetic/lib/python3/dist-packages/sensor_msgs/msg/_Image.py",
        10705,
        "ea36643a165267e46fb5b5c227143d541d833b4f493c4077c77a799b8e41db2d",
    ),
    "sensor_msgs.msg._Imu": (
        "/opt/ros/noetic/lib/python3/dist-packages/sensor_msgs/msg/_Imu.py",
        13030,
        "da6283c0d88361f53d81f15e2ccd0ea55d32331f5e671d2d93bbe31690ae6386",
    ),
    "sensor_msgs": (
        "/opt/ros/noetic/lib/python3/dist-packages/sensor_msgs/__init__.py",
        0,
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ),
    "sensor_msgs.msg": (
        "/opt/ros/noetic/lib/python3/dist-packages/sensor_msgs/msg/__init__.py",
        762,
        "c34aa9962d67d308caafc5cf61acf0515c9ba4826f6de2dbfee3b50ca8a9128f",
    ),
    "sensor_msgs.msg._ChannelFloat32": (
        "/opt/ros/noetic/lib/python3/dist-packages/sensor_msgs/msg/_ChannelFloat32.py",
        6061,
        "911f546066708c69609b88f5aae2be7042890d9a29dbff9ad7560dc31b72a610",
    ),
    "sensor_msgs.msg._PointCloud": (
        "/opt/ros/noetic/lib/python3/dist-packages/sensor_msgs/msg/_PointCloud.py",
        12155,
        "ab1d8018476ccdf630506cbf12d35065be36ec4269ea97f12abdde52b2f50b0d",
    ),
    "std_msgs.msg._Header": (
        "/opt/ros/noetic/lib/python3/dist-packages/std_msgs/msg/_Header.py",
        5706,
        "a4171605d65979479a395892ca44d22d5bc6fac3ef184c9c8fe177ea914487e3",
    ),
    "nav_msgs.msg._Odometry": (
        "/opt/ros/noetic/lib/python3/dist-packages/nav_msgs/msg/_Odometry.py",
        13410,
        "ecfc2f41913b1f9cb513308985367c242de7483698a80305a1e3680430301174",
    ),
    "genpy": (
        "/opt/ros/noetic/lib/python3/dist-packages/genpy/__init__.py",
        1865,
        "824bdbe1bb1a7e25e46ef41108420cf3a781b76539cd3263037591a7890f3e39",
    ),
    "genpy.rostime": (
        "/opt/ros/noetic/lib/python3/dist-packages/genpy/rostime.py",
        14831,
        "424a3d4893c433991335e88f5e3ea1d960bd880c47754a99fa65dbf9006fa78c",
    ),
    "genpy.message": (
        "/opt/ros/noetic/lib/python3/dist-packages/genpy/message.py",
        29508,
        "1db78c2f9a2c0d18fdc3627e671034306da81b738cbc3659af52c500fe246e4a",
    ),
    "roslib.message": (
        "/opt/ros/noetic/lib/python3/dist-packages/roslib/message.py",
        4954,
        "7ae9d228479b83e1a31135c3b791f6dfa3cd0af9a120b8d9019d3c94a2a2e036",
    ),
    "yaml": (
        "/usr/lib/python3/dist-packages/yaml/__init__.py",
        13170,
        "5c550d6ca4e0e1a7c07740444e3190d66290f7bfe0e636c4d42d16a0a73be1d7",
    ),
    "yaml.parser": (
        "/usr/lib/python3/dist-packages/yaml/parser.py",
        25495,
        "8a55a9e6fbe0a07146cef3990c8b45a068c3e83e369e1959ad9ca30306b4a09a",
    ),
    "yaml.loader": (
        "/usr/lib/python3/dist-packages/yaml/loader.py",
        2061,
        "5156becc8aa6905482218abf3e04869b835226db4763645fff3438fdbd5f1cdd",
    ),
    "yaml.constructor": (
        "/usr/lib/python3/dist-packages/yaml/constructor.py",
        28639,
        "90d8247da78b524c10618fd0e857f54f3d97570fe91b5c5513d024ef3faf88b0",
    ),
    "yaml.resolver": (
        "/usr/lib/python3/dist-packages/yaml/resolver.py",
        8970,
        "0c90a3a50afc6100846188ca118a939741abb198a5d87e1a14e23d6f439ef94e",
    ),
    "yaml.scanner": (
        "/usr/lib/python3/dist-packages/yaml/scanner.py",
        51277,
        "29e4082863654b23c4f100f08a89c7c72f4281ba84e6d789133d39151f7e9c08",
    ),
}
EXPECTED_SITECUSTOMIZE = (
    "/usr/lib/python3.8/sitecustomize.py",
    "/etc/python3.8/sitecustomize.py",
    155,
    "43d81125d92376b1a69d53a71126a041cc9a18d8080e92dea0a2ae23be138b1e",
)
EXPECTED_SERIALIZATION_CLOSURE_COUNT = 46
EXPECTED_SERIALIZATION_CLOSURE_SHA256 = (
    "ba35e5ed1b714254df44947465f4946999dbf95d3fe1194c9d0382329584cfb5"
)
BACKEND_CONSUMER_SOURCE = Path(
    "/home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master/"
    "vins_estimator/src/rosNodeTest.cpp"
)
BACKEND_FEATURE_CALLBACK_SHA256 = (
    "3d6869d4f52759f63482ac671cb15e535aaa65a5ae535b6fe132474c379d53b5"
)
BACKEND_PINNED_FILES = {
    "consumer_source": (
        BACKEND_CONSUMER_SOURCE,
        8686,
        "6606e607df624f7411fcc513e94a42e98b671b8be33a6a4b17052f9ebc99db3a",
    ),
    "vins_node": (
        Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node"),
        13104360,
        "4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278",
    ),
    "libvins_lib": (
        Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libvins_lib.so"),
        165207064,
        "c1080aefdfd0eb3f011d491041c773649917a77923b97e24503bd90136bab467",
    ),
    "libcamera_models": (
        Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libcamera_models.so"),
        2970640,
        "6d7b261f12791b693f95aebea6a762a97bc3501f1f1f3c94a6af6e50f2e6690d",
    ),
}
LDD_PATH = Path("/usr/bin/ldd")
LDD_SIZE = 5428
LDD_SHA256 = "d089c1054925b1f1dc9b574c2e7fabf3a495a1ce2ef946cd66d507daf09b7b8f"
LDD_NORMALIZED_SHA256 = (
    "14eac9592c2a14acb93e60c0fc6834f646a477e161ce64df21a3fa3aaa2f11cc"
)

_CLI_PRODUCTION_FACTORY_TOKEN = object()
_RENAME_NOREPLACE = 1
_AT_FDCWD = -100
_AT_EMPTY_PATH = 0x1000
_LIBC = ctypes.CDLL(None, use_errno=True)
_RENAMEAT2 = getattr(_LIBC, "renameat2", None)
_LINKAT = getattr(_LIBC, "linkat", None)
if _RENAMEAT2 is not None:
    _RENAMEAT2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    _RENAMEAT2.restype = ctypes.c_int
if _LINKAT is not None:
    _LINKAT.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    _LINKAT.restype = ctypes.c_int


@dataclass(frozen=True)
class MatchedMethodSpec:
    """Frozen detector adapter identity; carrier behavior is not configurable."""

    arm_id: str
    detector_family: str
    detector_implementation_id: str
    detector_contract: Mapping[str, object]
    source_code: int
    is_learned: int
    detector_factory: Callable[[], object]
    wrapper_source: Path
    detector_code_artifacts: tuple[tuple[str, Path], ...]

    def validate(self) -> None:
        if not self.arm_id or not self.detector_family:
            raise ValueError("matched arm id and detector family must be nonempty")
        if not self.detector_implementation_id:
            raise ValueError("detector implementation id must be nonempty")
        if not isinstance(self.source_code, int) or isinstance(self.source_code, bool):
            raise ValueError("source_code must be an integer")
        if self.is_learned not in (0, 1):
            raise ValueError("is_learned must be exactly 0 or 1")
        if not callable(self.detector_factory):
            raise ValueError("detector_factory must be callable")
        if not Path(self.wrapper_source).is_file():
            raise FileNotFoundError(self.wrapper_source)
        labels = [str(label) for label, _path in self.detector_code_artifacts]
        if any(not label for label in labels) or len(labels) != len(set(labels)):
            raise ValueError("detector artifact labels must be unique and nonempty")
        if any(not Path(path).is_file() for _label, path in self.detector_code_artifacts):
            raise FileNotFoundError("a detector code artifact is missing")


@dataclass(frozen=True)
class MatchedRawStepDiagnostics:
    raw_index: int
    header_stamp_ns: int
    published: bool
    adaptive_clahe_applied: bool
    raw_image_sha256: str
    processed_image_sha256: str
    tracked_before: int
    tracked_after: int
    dropped: int
    slots_before_detect: int
    detector_called: bool
    detector_candidates: int
    births: int
    output_tracks: int
    fb_median_px: float
    fb_p95_px: float
    ncc_median: float


@dataclass(frozen=True)
class MatchedCarrierRun:
    published_frames: list[primitive.PublishedFrame]
    raw_diagnostics: list[MatchedRawStepDiagnostics]


@dataclass
class _OwnedFile:
    fd: int
    device: int
    inode: int

    @property
    def identity(self) -> tuple[int, int]:
        return self.device, self.inode

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular_identity_path(path: Path) -> Path:
    lexical = Path(path)
    if lexical.is_symlink():
        raise ValueError(f"identity target must not be a symlink: {lexical}")
    path = lexical.resolve(strict=True)
    stat_result = os.lstat(path)
    if not stat.S_ISREG(stat_result.st_mode):
        raise ValueError(f"identity target must be a regular file: {path}")
    if int(stat_result.st_nlink) != 1:
        raise ValueError(f"identity target must have exactly one hard link: {path}")
    return path


def _file_identity(path: Path, *, reported_path: Path | None = None) -> dict[str, object]:
    path = _regular_identity_path(path)
    return {
        "path": str(reported_path if reported_path is not None else path),
        "size_bytes": int(path.stat().st_size),
        "sha256": _sha256_file(path),
    }


def _shared_package_initializer_contract() -> dict[str, dict[str, object]]:
    """Bind the package initializers executed before the frozen primitive."""

    result: dict[str, dict[str, object]] = {}
    for label, expected in EXPECTED_SHARED_PACKAGE_INITIALIZERS.items():
        module_name = str(expected["module"])
        module = sys.modules.get(module_name)
        if module is None:
            raise RuntimeError(
                f"shared package initializer was not loaded: {module_name}"
            )
        expected_path = str(expected["path"])
        spec = getattr(module, "__spec__", None)
        module_file = getattr(module, "__file__", None)
        spec_origin = getattr(spec, "origin", None)
        loader = type(getattr(spec, "loader", None)).__name__
        package_path = list(getattr(module, "__path__", ()))
        if module_file != expected_path or spec_origin != expected_path:
            raise RuntimeError(
                f"shared package initializer origin drift: {module_name}"
            )
        if loader != "SourceFileLoader":
            raise RuntimeError(
                f"shared package initializer loader drift: {module_name}: {loader}"
            )
        if package_path != list(expected["package_path"]):
            raise RuntimeError(
                f"shared package initializer path drift: {module_name}"
            )
        identity = _file_identity(Path(expected_path))
        if (
            identity["size_bytes"] != int(expected["size_bytes"])
            or identity["sha256"] != str(expected["sha256"])
        ):
            raise RuntimeError(
                f"shared package initializer byte identity drift: {module_name}"
            )
        result[label] = {
            "module": module_name,
            "file": identity,
            "spec_origin": spec_origin,
            "loader": loader,
            "package_path": package_path,
        }
    return result


def _require_canonical_requested_inputs(
    requested_inputs: Mapping[str, object], canonical_inputs: Mapping[str, str]
) -> None:
    """Require CLI input spellings to match the identities used by evidence."""

    if dict(requested_inputs) != dict(canonical_inputs):
        raise ValueError(
            "formal input arguments must use their canonical resolved spellings: "
            f"requested={dict(requested_inputs)!r} canonical={dict(canonical_inputs)!r}"
        )


def _open_owned_existing(path: Path) -> _OwnedFile:
    descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        stat_result = os.fstat(descriptor)
        if not stat.S_ISREG(stat_result.st_mode):
            raise RuntimeError(f"owned work artifact is not regular: {path}")
        if int(stat_result.st_nlink) != 1:
            raise RuntimeError(f"owned work artifact has extra hard links: {path}")
        observed = os.lstat(path)
        identity = (int(stat_result.st_dev), int(stat_result.st_ino))
        if (int(observed.st_dev), int(observed.st_ino)) != identity:
            raise RuntimeError(f"work artifact path/FD identity mismatch: {path}")
        return _OwnedFile(descriptor, *identity)
    except BaseException:
        os.close(descriptor)
        raise


def _owned_file_identity(
    owned: _OwnedFile, *, reported_path: Path
) -> dict[str, object]:
    stat_result = os.fstat(owned.fd)
    if not stat.S_ISREG(stat_result.st_mode):
        raise RuntimeError(f"held artifact is not regular: {reported_path}")
    if int(stat_result.st_nlink) != 1:
        raise RuntimeError(f"held artifact has extra hard links: {reported_path}")
    if (int(stat_result.st_dev), int(stat_result.st_ino)) != owned.identity:
        raise RuntimeError(f"held artifact identity drift: {reported_path}")
    digest = hashlib.sha256()
    offset = 0
    while True:
        block = os.pread(owned.fd, 4 * 1024 * 1024, offset)
        if not block:
            break
        digest.update(block)
        offset += len(block)
    return {
        "path": str(reported_path),
        "size_bytes": int(stat_result.st_size),
        "sha256": digest.hexdigest(),
    }


def _canonical_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")


def _canonical_sha256(payload: object) -> str:
    return _sha256_bytes(_canonical_bytes(payload)[:-1])


def _code_constant_payload(value: object) -> object:
    """Return a deterministic, type-sensitive JSON form of code constants."""

    if isinstance(value, types.CodeType):
        return {"type": "code", "value": _code_payload(value)}
    if value is None:
        return {"type": "none", "value": None}
    if isinstance(value, bool):
        return {"type": "bool", "value": value}
    if isinstance(value, int):
        return {"type": "int", "value": str(value)}
    if isinstance(value, float):
        if not math.isfinite(value):
            return {"type": "float", "value": value.hex()}
        return {"type": "float", "value": value.hex()}
    if isinstance(value, complex):
        return {
            "type": "complex",
            "real": float(value.real).hex(),
            "imag": float(value.imag).hex(),
        }
    if isinstance(value, str):
        return {"type": "str", "value": value}
    if isinstance(value, bytes):
        return {"type": "bytes", "value": value.hex()}
    if isinstance(value, tuple):
        return {
            "type": "tuple",
            "value": [_code_constant_payload(item) for item in value],
        }
    if isinstance(value, frozenset):
        items = [_code_constant_payload(item) for item in value]
        return {
            "type": "frozenset",
            "value": sorted(items, key=lambda item: _canonical_bytes(item)),
        }
    raise TypeError(f"unsupported code constant type: {type(value).__name__}")


def _code_payload(code: types.CodeType) -> dict[str, object]:
    return {
        "argcount": code.co_argcount,
        "posonlyargcount": code.co_posonlyargcount,
        "kwonlyargcount": code.co_kwonlyargcount,
        "nlocals": code.co_nlocals,
        "stacksize": code.co_stacksize,
        "flags": code.co_flags,
        "code_hex": code.co_code.hex(),
        "consts": [_code_constant_payload(value) for value in code.co_consts],
        "names": list(code.co_names),
        "varnames": list(code.co_varnames),
        "freevars": list(code.co_freevars),
        "cellvars": list(code.co_cellvars),
    }


def _code_sha256(code: types.CodeType) -> str:
    return _canonical_sha256(_code_payload(code))


def _array_sha256(array: np.ndarray) -> str:
    contiguous = np.ascontiguousarray(array)
    return _sha256_bytes(contiguous.tobytes(order="C"))


def _safe_float(value: float) -> float | None:
    result = float(value)
    return result if math.isfinite(result) else None


def _configure_runtime() -> None:
    cv2.setNumThreads(1)
    cv2.setRNGSeed(0)
    cv2.ocl.setUseOpenCL(False)


def _validate_scoped_rosbag_sys_path_mutation(
    before: Sequence[str],
    observed: Sequence[str],
    *,
    original_list_preserved: bool,
) -> None:
    """Accept only genpy's exact, scoped append-only sys.path side effect.

    ROS1 ``rosbag`` dynamically compiles message classes into private
    ``/tmp/genpy_*`` directories and appends those directories to
    ``sys.path``.  The generated modules remain usable through
    ``sys.modules`` after the search paths are removed.  This validator is
    intentionally narrow: it does not make those temporary directories part
    of the formal runtime contract and it rejects every mutation other than
    direct append-only genpy directories with the observed filesystem shape.
    """

    baseline = list(before)
    live = list(observed)
    if not original_list_preserved:
        raise RuntimeError("trusted rosbag call replaced the sys.path list")
    if live[: len(baseline)] != baseline:
        raise RuntimeError("trusted rosbag call changed the sealed sys.path prefix")
    suffix = live[len(baseline) :]
    if len(suffix) != len(set(suffix)):
        raise RuntimeError("trusted rosbag call appended duplicate sys.path entries")
    for raw_path in suffix:
        if type(raw_path) is not str or _GENPY_TEMP_DIRECTORY_RE.fullmatch(raw_path) is None:
            raise RuntimeError(
                f"trusted rosbag call appended a non-genpy sys.path entry: {raw_path!r}"
            )
        path = Path(raw_path)
        if path.parent != Path("/tmp") or os.path.normpath(raw_path) != raw_path:
            raise RuntimeError(f"genpy path is not a direct canonical /tmp child: {raw_path}")
        try:
            before_stat = os.lstat(path)
        except OSError as exc:
            raise RuntimeError(f"genpy directory is unavailable: {raw_path}") from exc
        if (
            not stat.S_ISDIR(before_stat.st_mode)
            or stat.S_IMODE(before_stat.st_mode) != 0o700
            or int(before_stat.st_uid) != int(os.getuid())
            or int(before_stat.st_nlink) != 2
        ):
            raise RuntimeError(f"genpy directory filesystem contract failed: {raw_path}")
        try:
            entries = list(os.scandir(path))
        except OSError as exc:
            raise RuntimeError(f"cannot inspect genpy directory: {raw_path}") from exc
        if len(entries) != 1:
            raise RuntimeError(
                f"genpy directory must contain exactly one generated source: {raw_path}"
            )
        entry = entries[0]
        try:
            entry_stat = entry.stat(follow_symlinks=False)
        except OSError as exc:
            raise RuntimeError(f"cannot inspect genpy source: {entry.name}") from exc
        if (
            _GENPY_TEMP_SOURCE_RE.fullmatch(entry.name) is None
            or entry.is_symlink()
            or not stat.S_ISREG(entry_stat.st_mode)
            or stat.S_IMODE(entry_stat.st_mode) != 0o600
            or int(entry_stat.st_uid) != int(os.getuid())
            or int(entry_stat.st_nlink) != 1
        ):
            raise RuntimeError(f"genpy generated-source contract failed: {entry.name}")
        after_stat = os.lstat(path)
        if (
            int(after_stat.st_dev) != int(before_stat.st_dev)
            or int(after_stat.st_ino) != int(before_stat.st_ino)
            or int(after_stat.st_nlink) != int(before_stat.st_nlink)
            or stat.S_IMODE(after_stat.st_mode) != 0o700
        ):
            raise RuntimeError(f"genpy directory changed during validation: {raw_path}")


def _call_trusted_rosbag_scoped(
    function: Callable[..., object], *args, **kwargs
) -> object:
    """Run one trusted rosbag helper and restore sealed ``sys.path`` exactly."""

    original_object = sys.path
    before = list(original_object)
    try:
        return function(*args, **kwargs)
    finally:
        try:
            observed = list(sys.path)
            original_list_preserved = sys.path is original_object
        except BaseException as exc:
            sys.path = original_object
            original_object[:] = before
            raise RuntimeError("trusted rosbag call made sys.path unreadable") from exc
        sys.path = original_object
        original_object[:] = before
        if list(sys.path) != before:
            raise RuntimeError("failed to restore sealed sys.path after rosbag call")
        _validate_scoped_rosbag_sys_path_mutation(
            before,
            observed,
            original_list_preserved=original_list_preserved,
        )


def _module_identity(name: str) -> tuple[dict[str, object], list[str]]:
    failures: list[str] = []
    module = importlib.import_module(name)
    lexical_expected, size_expected, sha_expected = EXPECTED_MODULE_FILES[name]
    module_file = getattr(module, "__file__", None)
    spec = getattr(module, "__spec__", None)
    spec_origin = getattr(spec, "origin", None)
    if module_file != lexical_expected or spec_origin != lexical_expected:
        failures.append(
            f"module_origin:{name}:{module_file!r}:{spec_origin!r}"
        )
    identity = _file_identity(Path(lexical_expected))
    if identity["size_bytes"] != size_expected or identity["sha256"] != sha_expected:
        failures.append(f"module_identity:{name}")
    package_path = getattr(module, "__path__", None)
    return {
        "module": name,
        "file": identity,
        "spec_origin": spec_origin,
        "loader": type(getattr(spec, "loader", None)).__name__,
        "package_path": list(package_path) if package_path is not None else None,
    }, failures


def _sitecustomize_identity() -> tuple[dict[str, object], list[str]]:
    lexical, resolved_expected, size_expected, sha_expected = EXPECTED_SITECUSTOMIZE
    failures: list[str] = []
    module = sys.modules.get("sitecustomize")
    if module is None:
        failures.append("sitecustomize_not_loaded")
        return {}, failures
    origin = getattr(getattr(module, "__spec__", None), "origin", None)
    module_file = getattr(module, "__file__", None)
    if origin != lexical or module_file != lexical:
        failures.append(f"sitecustomize_origin:{module_file!r}:{origin!r}")
    lexical_path = Path(lexical)
    if not lexical_path.is_symlink():
        failures.append("sitecustomize_lexical_not_symlink")
    resolved = lexical_path.resolve(strict=True)
    if str(resolved) != resolved_expected:
        failures.append(f"sitecustomize_target:{resolved}")
    identity = _file_identity(resolved)
    if identity["size_bytes"] != size_expected or identity["sha256"] != sha_expected:
        failures.append("sitecustomize_identity")
    return {
        "lexical_path": lexical,
        "resolved_file": identity,
        "spec_origin": origin,
    }, failures


def _serialization_module_closure() -> tuple[list[dict[str, object]], list[str]]:
    """Bind the loaded bag/YAML serialization code used by both arms."""

    prefixes = ("rosbag", "genpy", "roslib", "yaml")
    direct = {
        "geometry_msgs.msg._Point32",
        "nav_msgs.msg._Odometry",
        "sensor_msgs.msg._ChannelFloat32",
        "sensor_msgs.msg._Image",
        "sensor_msgs.msg._Imu",
        "sensor_msgs.msg._PointCloud",
        "std_msgs.msg._Header",
    }
    rows: list[dict[str, object]] = []
    failures: list[str] = []
    for name in sorted(sys.modules):
        if not (
            name in prefixes
            or any(name.startswith(prefix + ".") for prefix in prefixes)
            or name in direct
        ):
            continue
        module = sys.modules[name]
        lexical = getattr(module, "__file__", None)
        if not lexical:
            continue
        spec = getattr(module, "__spec__", None)
        origin = getattr(spec, "origin", None)
        if origin != lexical:
            failures.append(f"serialization_module_origin:{name}")
        identity = _file_identity(Path(lexical))
        rows.append(
            {
                "module": name,
                "file": str(lexical),
                "resolved_path": identity["path"],
                "size_bytes": identity["size_bytes"],
                "sha256": identity["sha256"],
                "loader": type(getattr(spec, "loader", None)).__name__,
            }
        )
    encoded = _canonical_bytes(rows)
    if (
        len(rows) != EXPECTED_SERIALIZATION_CLOSURE_COUNT
        or _sha256_bytes(encoded) != EXPECTED_SERIALIZATION_CLOSURE_SHA256
    ):
        failures.append(
            "serialization_module_closure:"
            f"{len(rows)}:{_sha256_bytes(encoded)}"
        )
    return rows, failures


def _runtime_identity(*, strict: bool) -> dict[str, object]:
    executable = Path(sys.executable).resolve(strict=True)
    observed_env = {name: os.environ.get(name) for name in EXPECTED_ENV}
    pycache_prefix = os.environ.get("PYTHONPYCACHEPREFIX")
    failures: list[str] = []
    if executable != EXPECTED_PYTHON.resolve(strict=True):
        failures.append(f"python={executable}")
    python_identity = _file_identity(EXPECTED_PYTHON)
    if (
        python_identity["size_bytes"] != 5490456
        or python_identity["sha256"]
        != "298a9e830ed52f36c299427565485d717d1ce0179c0597cc16560513eb780b06"
    ):
        failures.append("python_identity")
    if list(sys.version_info[:3]) != [3, 8, 10]:
        failures.append(f"python_version={list(sys.version_info[:3])}")
    if str(np.__version__) != EXPECTED_NUMPY_VERSION:
        failures.append(f"numpy={np.__version__}")
    if str(cv2.__version__) != EXPECTED_OPENCV_VERSION:
        failures.append(f"opencv={cv2.__version__}")
    for name, expected in EXPECTED_ENV.items():
        if observed_env[name] != expected:
            failures.append(f"{name}={observed_env[name]!r}")
    forbidden_loader_env = sorted(
        name
        for name in os.environ
        if name.startswith("LD_") and name != "LD_LIBRARY_PATH"
    )
    if forbidden_loader_env:
        failures.append(f"forbidden_loader_env={forbidden_loader_env}")
    observed_sys_path = list(sys.path)
    if observed_sys_path != EXPECTED_SYS_PATH:
        failures.append(f"sys.path={observed_sys_path!r}")
    if not pycache_prefix:
        failures.append("PYTHONPYCACHEPREFIX is unset")
    elif Path(pycache_prefix).exists():
        failures.append(f"PYTHONPYCACHEPREFIX already exists: {pycache_prefix}")
    if int(cv2.getNumThreads()) != 1:
        failures.append(f"cv2_threads={cv2.getNumThreads()}")
    if bool(cv2.ocl.useOpenCL()):
        failures.append("opencv_opencl=true")
    expected_python_flags = {
        "no_user_site": 1,
        "no_site": 0,
        "ignore_environment": 0,
        "isolated": 0,
        "dont_write_bytecode": 1,
        "optimize": 0,
        "hash_randomization": 0,
    }
    observed_python_flags = {
        name: int(getattr(sys.flags, name)) for name in expected_python_flags
    }
    if observed_python_flags != expected_python_flags:
        failures.append(f"python_flags={observed_python_flags!r}")
    numeric_paths = {
        "numpy_init": Path(np.__file__),
        "numpy_multiarray": Path(numpy_multiarray.__file__),
        "numpy_linalg": Path(numpy_linalg.__file__),
        "opencv_binary": Path(cv2.__file__),
    }
    numeric_identities: dict[str, object] = {}
    for label, observed_path in numeric_paths.items():
        expected_path, expected_size, expected_sha = EXPECTED_NUMERIC_FILES[label]
        if str(observed_path) != expected_path:
            failures.append(f"numeric_origin:{label}:{observed_path}")
        identity = _file_identity(Path(expected_path))
        if identity["size_bytes"] != expected_size or identity["sha256"] != expected_sha:
            failures.append(f"numeric_identity:{label}")
        numeric_identities[label] = identity
    native_numeric_identities: dict[str, object] = {}
    for label, (expected_path, expected_size, expected_sha) in (
        EXPECTED_NATIVE_NUMERIC_FILES.items()
    ):
        identity = _file_identity(Path(expected_path))
        if identity["size_bytes"] != expected_size or identity["sha256"] != expected_sha:
            failures.append(f"native_numeric_identity:{label}")
        native_numeric_identities[label] = identity
    module_identities: dict[str, object] = {}
    for name in EXPECTED_MODULE_FILES:
        identity, module_failures = _module_identity(name)
        module_identities[name] = identity
        failures.extend(module_failures)
    sitecustomize, site_failures = _sitecustomize_identity()
    failures.extend(site_failures)
    serialization_closure, serialization_failures = (
        _serialization_module_closure()
    )
    failures.extend(serialization_failures)
    if "usercustomize" in sys.modules:
        failures.append("usercustomize_loaded")
    if importlib.util.find_spec("usercustomize") is not None:
        failures.append("usercustomize_discoverable")
    if strict and failures:
        raise RuntimeError("matched runtime contract mismatch: " + "; ".join(failures))
    return {
        "strict_formal_check": bool(strict),
        "contract_pass": not failures,
        "contract_failures": failures,
        "python": python_identity,
        "python_version": list(sys.version_info[:3]),
        "numpy_version": str(np.__version__),
        "numpy_init": numeric_identities["numpy_init"],
        "numpy_multiarray": numeric_identities["numpy_multiarray"],
        "numpy_linalg": numeric_identities["numpy_linalg"],
        "opencv_version": str(cv2.__version__),
        "opencv_binary": numeric_identities["opencv_binary"],
        "native_numeric_files": native_numeric_identities,
        "opencv_threads": int(cv2.getNumThreads()),
        "opencv_opencl": bool(cv2.ocl.useOpenCL()),
        "opencv_rng_seed_contract": 0,
        "environment": observed_env,
        "forbidden_loader_environment": forbidden_loader_env,
        "sys_path": observed_sys_path,
        "python_flags": observed_python_flags,
        "module_identities": module_identities,
        "serialization_module_closure": serialization_closure,
        "serialization_module_closure_sha256": _sha256_bytes(
            _canonical_bytes(serialization_closure)
        ),
        "sitecustomize": sitecustomize,
        "usercustomize_absent": (
            "usercustomize" not in sys.modules
            and importlib.util.find_spec("usercustomize") is None
        ),
        "pycache_prefix": pycache_prefix,
    }


def _backend_inert_provenance_contract() -> dict[str, object]:
    pinned: dict[str, object] = {}
    for label, (path, expected_size, expected_sha) in BACKEND_PINNED_FILES.items():
        identity = _file_identity(path)
        if (
            identity["size_bytes"] != expected_size
            or identity["sha256"] != expected_sha
        ):
            raise RuntimeError(f"frozen backend identity drift: {label}")
        pinned[label] = identity
    source = BACKEND_CONSUMER_SOURCE.resolve(strict=True)
    payload = source.read_bytes()
    start = payload.index(b"void feature_callback")
    end = payload.index(b"void restart_callback", start)
    callback = payload[start:end].rstrip(b"\n") + b"\n"
    callback_sha = _sha256_bytes(callback)
    if callback_sha != BACKEND_FEATURE_CALLBACK_SHA256:
        raise RuntimeError(
            "backend feature_callback identity drift: "
            f"{callback_sha} != {BACKEND_FEATURE_CALLBACK_SHA256}"
        )
    for forbidden in (b"source_code", b"is_learned", b'"sigma"'):
        if forbidden in callback:
            raise RuntimeError(
                f"backend-inert provenance assumption failed for {forbidden!r}"
            )
    ldd_identity = _file_identity(LDD_PATH)
    if (
        ldd_identity["size_bytes"] != LDD_SIZE
        or ldd_identity["sha256"] != LDD_SHA256
    ):
        raise RuntimeError("ldd resolver identity drift")
    ldd_result = subprocess.run(
        [str(LDD_PATH), str(BACKEND_PINNED_FILES["vins_node"][0])],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={
            "PATH": EXPECTED_ENV["PATH"],
            "LD_LIBRARY_PATH": EXPECTED_ENV["LD_LIBRARY_PATH"],
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        },
    )
    if ldd_result.returncode != 0 or ldd_result.stderr:
        raise RuntimeError(
            f"frozen VINS ldd failed: rc={ldd_result.returncode}:"
            f"{ldd_result.stderr!r}"
        )
    normalized_lines: list[str] = []
    soname_paths: dict[str, str] = {}
    for raw_line in ldd_result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            raise RuntimeError("ldd produced an empty record")
        address = line.rfind(" (0x")
        if address >= 0 and line.endswith(")"):
            line = line[:address]
        if "=> not found" in line:
            raise RuntimeError(f"ldd dependency not found: {line}")
        if " => " in line:
            soname, target = line.split(" => ", 1)
            if soname in soname_paths:
                raise RuntimeError(f"duplicate ldd soname: {soname}")
            soname_paths[soname] = target
            line = f"{soname}=>{target}"
        elif line == "linux-vdso.so.1":
            line = "linux-vdso.so.1=>#virtual"
        elif line.startswith("/lib") and "ld-linux" in line:
            line = f"ld-linux-x86-64.so.2=>{line}#loader"
        else:
            raise RuntimeError(f"unparsed ldd record: {line}")
        normalized_lines.append(line)
    if soname_paths.get("libvins_lib.so") != str(
        BACKEND_PINNED_FILES["libvins_lib"][0]
    ):
        raise RuntimeError("libvins_lib.so resolved outside frozen path")
    if soname_paths.get("libcamera_models.so") != str(
        BACKEND_PINNED_FILES["libcamera_models"][0]
    ):
        raise RuntimeError("libcamera_models.so resolved outside frozen path")
    normalized = ("\n".join(normalized_lines) + "\n").encode("utf-8")
    if len(normalized_lines) != 177 or _sha256_bytes(normalized) != LDD_NORMALIZED_SHA256:
        raise RuntimeError("frozen VINS ldd closure drift")
    return {
        "proof_scope": (
            "frozen_source_callback_primary_binaries_and_"
            "normalized_dependency_paths"
        ),
        "pinned_files": pinned,
        "feature_callback_size_bytes": len(callback),
        "feature_callback_sha256": callback_sha,
        "ignored_feature_channels": ["sigma", "source_code", "is_learned"],
        "quality_read_by_name": True,
        "numeric_tuple_channels": [
            "id",
            "camera_id",
            "point_x",
            "point_y",
            "point_z",
            "p_u",
            "p_v",
            "velocity_x",
            "velocity_y",
            "quality",
        ],
            "ldd": {
            "resolver": ldd_identity,
            "ordered_entry_count": len(normalized_lines),
            "normalized_sha256": _sha256_bytes(normalized),
            "critical_soname_paths": {
                "libvins_lib.so": soname_paths["libvins_lib.so"],
                "libcamera_models.so": soname_paths["libcamera_models.so"],
            },
            "closure_wording": (
                "exact_consumer_source_and_primary_binary_identities_plus_"
                "normalized_dependency_path_resolution; transitive_dependency_"
                "bytes_are_not_all_claimed_frozen"
            ),
        },
    }


def common_contract(*, strict_runtime: bool) -> dict[str, object]:
    """Return the complete shared behavior and implementation identity."""

    runtime = _runtime_identity(strict=strict_runtime)
    contract = {
        "schema_version": COMMON_CONTRACT_SCHEMA,
        "scientific_role": (
            "post_result_development_exploratory_detector_birth_ablation"
        ),
        "implementation": {
            "matched_core": _file_identity(Path(__file__)),
            "frozen_primitive_module": _file_identity(Path(primitive.__file__)),
            "package_initializers": _shared_package_initializer_contract(),
            "quality_reference_source": _file_identity(
                primitive.QUALITY_REFERENCE_SOURCE
            ),
            "klt_reference_source": _file_identity(primitive.KLT_REFERENCE_SOURCE),
        },
        "runtime": runtime,
        "preprocess": {
            "input": "raw_mono8",
            "mode": "adaptive_clahe",
            "quality_gate_source": "raw",
            "clahe_clip_limit": 2.0,
            "clahe_tile_grid": [8, 8],
            "gate": {
                "contrast_score_lt": 0.72,
                "grid_texture_score_lt": 0.58,
                "illumination_nonuniformity_gt": 0.18,
                "degradation_score_gt": 0.42,
                "logic": "any",
            },
        },
        "carrier": {
            "raw_frame_zero_initializes": True,
            "process_skipped_frames": True,
            "published_every_n": 2,
            "published_frame_offset": 1,
            "feature_cap": FEATURE_CAP,
            "detector_call_rule": "call_iff_slots_before_detect_gt_zero",
            "max_detector_candidates": MAX_CANDIDATES,
            "survivor_order": "age_desc_then_id_asc",
            "candidate_order": "score_desc_stable_input_index_tiebreak",
            "birth_min_distance_px": 18.0,
            "border_px": 8,
            "id_policy": "fresh_monotonic_no_reuse_no_revival",
            "lk_win_size": [21, 21],
            "lk_max_level": 3,
            "lk_criteria_count": 30,
            "lk_criteria_eps": 0.01,
            "lk_min_eig_threshold": 0.0001,
            "forward_backward_max_px": 1.0,
            "ncc_min": 0.65,
            "ncc_patch_radius": 5,
        },
        "publication": {
            "schedule": "source_feature_header_and_record_stamp_exact",
            "channel_names_in_order": list(primitive.CHANNEL_NAMES),
            "normalized": "camera_yaml_dispatch_undistortPoints",
            "velocity": "adjacent_published_normalized_delta_over_header_dt",
            "birth_velocity": 0.0,
            "quality": 1.0,
            "sigma": 1.0,
            "point_z": 1.0,
            "camera_id": 0.0,
            "gx_gy_gz": [0.0, 0.0, 0.0],
            "source_feature_observations_reused": False,
            "backend_inert_detector_provenance_channels": list(
                PROVENANCE_CHANNELS
            ),
        },
        "backend_inert_provenance_proof": _backend_inert_provenance_contract(),
    }
    return contract


def arm_contract(method_spec: MatchedMethodSpec) -> dict[str, object]:
    method_spec.validate()
    return {
        "arm_id": method_spec.arm_id,
        "detector": {
            "family": method_spec.detector_family,
            "implementation_id": method_spec.detector_implementation_id,
            "contract": copy.deepcopy(dict(method_spec.detector_contract)),
        },
        "provenance": {
            "source_code": method_spec.source_code,
            "is_learned": method_spec.is_learned,
            "backend_inert_for_frozen_consumer": True,
        },
    }


def _validate_formal_method_spec(method_spec: MatchedMethodSpec) -> None:
    expected: dict[str, object]
    if method_spec.arm_id == "XFEAT_BIRTH_RAWLK_MATCHED_V1":
        expected = {
            "detector_family": "learned_xfeat_sparse",
            "detector_implementation_id": (
                "official_verlab_XFeat_sparse_detectAndCompute_proposals_only"
            ),
            "source_code": 20,
            "is_learned": 1,
            "wrapper_name": "export_matched_xfeat_birth_rawlk_v1.py",
            "factory_module": "scripts.export_matched_xfeat_birth_rawlk_v1",
            "factory_qualname": "MatchedXFeatDetector",
            "arm_contract_sha256": (
                "dd6f2c47547e91754220f73ee64d3a48dfc5a8c62305c81f2905e4893fadfb8b"
            ),
            "wrapper_sha256": (
                "7ce1cea7bc0dbe650749c89ababd8e1aeee08e95a07f32a6b87f00213ea54a7a"
            ),
            "module_helper_name": "_assert_frozen_xfeat_definition",
            "module_helper_sha256": (
                "9192242dd6f769426cdcde5077104bd7e23b329a761610d999d0b7e578bb5dbb"
            ),
            "auxiliary_helper_code_sha256": {
                "static_xfeat_package_initializer_contract": (
                    "7179d5e33d404556c81100fdcf16f1c2ae59fef3098235445da9d18f64b222c3"
                ),
                "observed_xfeat_package_initializer_contract": (
                    "875054fb2ccacffffef7748eb6cf8105e06092164fcef1377dff7e976ca3a2d0"
                ),
                "static_tqdm_import_contract": (
                    "744e70ba76491de5f7b6fabaf7711baabbd1502bb12824ecf05c64ed9ff2c305"
                ),
                "observed_tqdm_import_contract": (
                    "c49e2135c045d304a69db5118849114e0a68c0b7fb7d8a18e7aaa0cb4313718c"
                ),
                "expected_optional_matcher_dependency_contract": (
                    "14244576191523de438a7ebb1861c1c0c7e83d10c2bd85db962e4fee08a2bb19"
                ),
            },
            "method_code_sha256": {
                "__init__": "7ad0ba254d4d863eaca6bbb516ab7e43d9ebd27b510e6e043a9e8fea4ceba182",
                "_load": "624d329725d6725ef3fa8ccbb20e1c43a962ea4ac00246b48a7b45a003bd413e",
                "detect": "9fc75de4b58f77b1b8d13be4776486914d937d15b80f014ce92c37fe67ead43c",
                "artifact_metadata": "a31070d468ecc5ee83ae2fa057237149cb71731805f05d760c7cfa9912bc9f31",
            },
            "detector_artifacts": (
                (
                    "legacy_detector_adapter",
                    "/home/ma/AQUA-FE_WS/scripts/export_xfeat_lk_carrier_v1.py",
                ),
                (
                    "xfeat_modules_initializer",
                    "/mnt/data/AQUA-FE_WS/external_tools/accelerated_features/modules/__init__.py",
                ),
                (
                    "xfeat_source",
                    "/mnt/data/AQUA-FE_WS/external_tools/accelerated_features/modules/xfeat.py",
                ),
                (
                    "xfeat_model_source",
                    "/mnt/data/AQUA-FE_WS/external_tools/accelerated_features/modules/model.py",
                ),
                (
                    "xfeat_interpolator_source",
                    "/mnt/data/AQUA-FE_WS/external_tools/accelerated_features/modules/interpolator.py",
                ),
                (
                    "xfeat_weight",
                    "/mnt/data/AQUA-FE_WS/external_tools/accelerated_features/weights/xfeat.pt",
                ),
                (
                    "xfeat_license",
                    "/mnt/data/AQUA-FE_WS/external_tools/accelerated_features/LICENSE",
                ),
                (
                    "tqdm_init",
                    "/home/ma/.local/lib/python3.8/site-packages/tqdm/__init__.py",
                ),
                (
                    "tqdm_monitor",
                    "/home/ma/.local/lib/python3.8/site-packages/tqdm/_monitor.py",
                ),
                (
                    "tqdm_pandas",
                    "/home/ma/.local/lib/python3.8/site-packages/tqdm/_tqdm_pandas.py",
                ),
                (
                    "tqdm_cli",
                    "/home/ma/.local/lib/python3.8/site-packages/tqdm/cli.py",
                ),
                (
                    "tqdm_gui",
                    "/home/ma/.local/lib/python3.8/site-packages/tqdm/gui.py",
                ),
                (
                    "tqdm_std",
                    "/home/ma/.local/lib/python3.8/site-packages/tqdm/std.py",
                ),
                (
                    "tqdm_utils",
                    "/home/ma/.local/lib/python3.8/site-packages/tqdm/utils.py",
                ),
                (
                    "tqdm_version",
                    "/home/ma/.local/lib/python3.8/site-packages/tqdm/version.py",
                ),
            ),
        }
    elif method_spec.arm_id == "GFTT_BIRTH_RAWLK_MATCHED_V1":
        expected = {
            "detector_family": "classical_gftt_shi_tomasi",
            "detector_implementation_id": (
                "opencv_GFTT_detector_only_matched_birth_v1"
            ),
            "source_code": 21,
            "is_learned": 0,
            "wrapper_name": "export_matched_gftt_birth_rawlk_v1.py",
            "factory_module": "scripts.export_matched_gftt_birth_rawlk_v1",
            "factory_qualname": "GFTTBirthDetector",
            "arm_contract_sha256": (
                "03d4ff2078fd8edab8a09a09a8eb482123c3d5419107670b1372e1e8566176bc"
            ),
            "wrapper_sha256": (
                "f8c858c9f97fd79a566bcb375bb3ac2803f357f948e23165ed0b54853e5fb6ee"
            ),
            "module_helper_name": "_assert_frozen_gftt_definition",
            "module_helper_sha256": (
                "2c8b593cb1b9824caa9971f323095da8a6ba4ec3fed9f40f4254bc42ebe2a609"
            ),
            "auxiliary_helper_code_sha256": {},
            "method_code_sha256": {
                "__init__": "5018a6e2faa34a83ab5f2f353890f0062756052d738c6a2947eee746c759e517",
                "detect": "e59c7eec3d8ea94ef078ead39ae2f95760b3de41fa464b27d6a02c6866253eaa",
                "artifact_metadata": "ff7039984645dbb94ab7e2f1a89c327a9c5dfbdd2da7df9c23d37be0ea9c4e3a",
            },
            "detector_artifacts": (),
        }
    else:
        raise RuntimeError(f"unrecognized formal matched arm: {method_spec.arm_id}")
    observed = {
        "detector_family": method_spec.detector_family,
        "detector_implementation_id": method_spec.detector_implementation_id,
        "source_code": method_spec.source_code,
        "is_learned": method_spec.is_learned,
        "wrapper_name": Path(method_spec.wrapper_source).name,
        "factory_module": getattr(method_spec.detector_factory, "__module__", None),
        "factory_qualname": getattr(method_spec.detector_factory, "__qualname__", None),
    }
    expected_scalar = {
        key: value
        for key, value in expected.items()
        if key not in {
            "arm_contract_sha256",
            "wrapper_sha256",
            "module_helper_name",
            "module_helper_sha256",
            "auxiliary_helper_code_sha256",
            "method_code_sha256",
            "detector_artifacts",
        }
    }
    if observed != expected_scalar:
        raise RuntimeError(f"formal matched method identity mismatch: {observed!r}")
    wrapper = Path(method_spec.wrapper_source).resolve(strict=True)
    if wrapper.parent != WORKSPACE_ROOT / "scripts":
        raise RuntimeError("formal matched wrapper resolved outside workspace scripts")
    if _sha256_file(wrapper) != expected["wrapper_sha256"]:
        raise RuntimeError("formal matched wrapper byte identity drift")
    if _canonical_sha256(arm_contract(method_spec)) != expected["arm_contract_sha256"]:
        raise RuntimeError("formal matched arm contract drift")
    module = importlib.import_module(str(expected["factory_module"]))
    canonical_spec = getattr(
        module,
        "XFEAT_METHOD_SPEC"
        if method_spec.arm_id.startswith("XFEAT")
        else "GFTT_METHOD_SPEC",
    )
    if method_spec is not canonical_spec:
        raise RuntimeError("formal matched method must be the canonical wrapper spec")
    if method_spec.detector_factory is not getattr(
        module, str(expected["factory_qualname"])
    ):
        raise RuntimeError("formal matched detector factory callable drift")
    observed_artifacts = tuple(
        (str(label), str(Path(path).resolve(strict=True)))
        for label, path in method_spec.detector_code_artifacts
    )
    if observed_artifacts != expected["detector_artifacts"]:
        raise RuntimeError("formal matched detector artifact closure drift")
    helper = getattr(module, str(expected["module_helper_name"]), None)
    helper_code = getattr(helper, "__code__", None)
    if (
        helper_code is None
        or _code_sha256(helper_code) != expected["module_helper_sha256"]
    ):
        raise RuntimeError("formal matched detector definition helper drift")
    for helper_name, expected_sha in expected[
        "auxiliary_helper_code_sha256"
    ].items():
        auxiliary = getattr(module, helper_name, None)
        code = getattr(auxiliary, "__code__", None)
        if code is None or _code_sha256(code) != expected_sha:
            raise RuntimeError(
                f"formal matched auxiliary helper drift: {helper_name}"
            )
    for method_name, expected_sha in expected["method_code_sha256"].items():
        method = getattr(method_spec.detector_factory, method_name)
        code = getattr(method, "__code__", None)
        if code is None or _code_sha256(code) != expected_sha:
            raise RuntimeError(
                f"formal matched detector method code drift: {method_name}"
            )


def build_feature_message(
    schedule_frame: primitive.ScheduleFrame,
    frame: primitive.PublishedFrame,
    normalized: np.ndarray,
    velocities: np.ndarray,
    *,
    source_code: int,
    is_learned: int,
) -> PointCloud:
    count = len(frame.ids)
    if not (
        frame.pixels.shape == (count, 2)
        and normalized.shape == (count, 2)
        and velocities.shape == (count, 2)
    ):
        raise ValueError("published feature arrays have inconsistent shapes")
    if count > FEATURE_CAP or len(np.unique(frame.ids)) != count:
        raise ValueError("published feature IDs violate uniqueness or cap")
    if is_learned not in (0, 1):
        raise ValueError("is_learned must be 0 or 1")
    message = PointCloud()
    message.header = copy.deepcopy(schedule_frame.header)
    if int(message.header.stamp.to_nsec()) != schedule_frame.header_stamp_ns:
        raise ValueError("schedule header object/stamp mismatch")
    message.channels = [
        ChannelFloat32(name=name) for name in primitive.CHANNEL_NAMES
    ]
    for index in range(count):
        message.points.append(
            Point32(
                float(normalized[index, 0]),
                float(normalized[index, 1]),
                1.0,
            )
        )
        values = (
            float(int(frame.ids[index])),
            0.0,
            float(frame.pixels[index, 0]),
            float(frame.pixels[index, 1]),
            float(velocities[index, 0]),
            float(velocities[index, 1]),
            0.0,
            0.0,
            0.0,
            1.0,
            1.0,
            float(source_code),
            float(is_learned),
        )
        for channel, value in zip(message.channels, values):
            channel.values.append(value)
    return message


def run_carrier(
    schedule: Sequence[primitive.ScheduleFrame],
    raw_frames: Sequence[primitive.RawFrame],
    detector,
    *,
    tracker: Callable = primitive.track_points_lk,
    preprocess: Callable = primitive.adaptive_clahe,
    max_candidates: int = MAX_CANDIDATES,
) -> MatchedCarrierRun:
    publish_indices = primitive._schedule_raw_indices(schedule, raw_frames)
    schedule_by_raw = {
        int(raw_index): schedule_index
        for schedule_index, raw_index in enumerate(publish_indices)
    }
    state = primitive.CarrierState.empty()
    published: list[primitive.PublishedFrame] = []
    diagnostics: list[MatchedRawStepDiagnostics] = []
    previous_processed = None
    for raw_index, raw_frame in enumerate(raw_frames):
        raw_image = np.asarray(raw_frame.image, dtype=np.uint8)
        raw_hash_before = _array_sha256(raw_image)
        processed, enhanced = preprocess(raw_image)
        processed = np.asarray(processed, dtype=np.uint8)
        if processed.ndim != 2 or processed.shape != raw_image.shape:
            raise ValueError("preprocessing must preserve mono image shape")
        raw_hash_after_preprocess = _array_sha256(raw_image)
        if raw_hash_after_preprocess != raw_hash_before:
            raise RuntimeError("preprocess modified the frozen raw image in place")
        processed_hash_before = _array_sha256(processed)
        tracked_before = len(state.ids)
        tracked_after = tracked_before
        fb = np.empty((0,), dtype=np.float32)
        ncc = np.empty((0,), dtype=np.float32)
        if previous_processed is not None:
            track_result = primitive.advance_state(
                state,
                previous_processed,
                processed,
                tracker=tracker,
            )
            tracked_after = len(state.ids)
            valid = np.asarray(track_result.valid, dtype=bool)
            fb = np.asarray(track_result.fb_errors, dtype=np.float32)[valid]
            ncc = np.asarray(track_result.ncc_scores, dtype=np.float32)[valid]
        slots = FEATURE_CAP - tracked_after
        detector_called = slots > 0
        detector_image = processed.copy()
        candidate_count, births = primitive.replenish_state(
            state,
            detector_image,
            detector,
            max_candidates=max_candidates,
        )
        if _array_sha256(raw_image) != raw_hash_before:
            raise RuntimeError("detector modified the frozen raw image")
        if _array_sha256(processed) != processed_hash_before:
            raise RuntimeError("detector modified the common processed image")
        is_published = raw_index in schedule_by_raw
        if is_published:
            if len(np.unique(state.ids)) != len(state.ids):
                raise AssertionError("carrier produced duplicate IDs")
            published.append(
                primitive.PublishedFrame(
                    ids=state.ids.copy(),
                    pixels=state.points.copy(),
                    ages=state.ages.copy(),
                )
            )
        diagnostics.append(
            MatchedRawStepDiagnostics(
                raw_index=raw_index,
                header_stamp_ns=int(raw_frame.header_stamp_ns),
                published=is_published,
                adaptive_clahe_applied=bool(enhanced),
                raw_image_sha256=raw_hash_before,
                processed_image_sha256=processed_hash_before,
                tracked_before=tracked_before,
                tracked_after=tracked_after,
                dropped=tracked_before - tracked_after,
                slots_before_detect=slots,
                detector_called=detector_called,
                detector_candidates=candidate_count,
                births=births,
                output_tracks=len(state.ids),
                fb_median_px=primitive._percentile(fb, 50.0),
                fb_p95_px=primitive._percentile(fb, 95.0),
                ncc_median=primitive._percentile(ncc, 50.0),
            )
        )
        previous_processed = processed.copy()
    if len(published) != len(schedule):
        raise AssertionError(
            f"published {len(published)} frames for {len(schedule)} schedule entries"
        )
    return MatchedCarrierRun(published, diagnostics)


def _diagnostics_common_stream(rows: Sequence[Mapping[str, object]]) -> str:
    digest = hashlib.sha256()
    common_fields = (
        "raw_index",
        "header_stamp_ns",
        "published",
        "adaptive_clahe_applied",
        "raw_image_sha256",
        "processed_image_sha256",
    )
    for row in rows:
        payload = {field: row[field] for field in common_fields}
        digest.update(_canonical_bytes(payload))
    return digest.hexdigest()


def _diagnostics_schedule_stream(rows: Sequence[Mapping[str, object]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        payload = {
            "raw_index": row["raw_index"],
            "header_stamp_ns": row["header_stamp_ns"],
            "published": row["published"],
        }
        digest.update(_canonical_bytes(payload))
    return digest.hexdigest()


def _validate_detector_runtime(
    detector_runtime: Mapping[str, object],
    rows: Sequence[Mapping[str, object]],
) -> None:
    calls = sum(bool(row["detector_called"]) for row in rows)
    candidates = sum(int(row["detector_candidates"]) for row in rows)
    if set(detector_runtime) < {"detect_calls", "candidate_total", "input_shapes"}:
        raise RuntimeError("detector runtime metadata is incomplete")
    for key, expected in (
        ("detect_calls", calls),
        ("candidate_total", candidates),
    ):
        observed = detector_runtime[key]
        if not isinstance(observed, int) or isinstance(observed, bool):
            raise RuntimeError(f"detector runtime {key} must be an integer")
        if observed != expected:
            raise RuntimeError(
                f"detector runtime {key} mismatch: {observed} != {expected}"
            )
    shapes = detector_runtime["input_shapes"]
    if (
        not isinstance(shapes, list)
        or len(shapes) != 1
        or not isinstance(shapes[0], list)
        or len(shapes[0]) != 2
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in shapes[0]
        )
    ):
        raise RuntimeError("detector runtime input_shapes must contain one HxW")


DIAGNOSTIC_FIELDS = tuple(field.name for field in MatchedRawStepDiagnostics.__dataclass_fields__.values())


def _write_diagnostics_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(DIAGNOSTIC_FIELDS))
        writer.writeheader()
        for row in rows:
            safe = {
                key: "" if isinstance(value, float) and not math.isfinite(value) else value
                for key, value in row.items()
            }
            writer.writerow(safe)


def _rename_noreplace(source: Path, destination: Path) -> None:
    if _RENAMEAT2 is None:
        raise RuntimeError("renameat2(RENAME_NOREPLACE) is unavailable")
    result = _RENAMEAT2(
        _AT_FDCWD,
        os.fsencode(source),
        _AT_FDCWD,
        os.fsencode(destination),
        _RENAME_NOREPLACE,
    )
    if result != 0:
        error = ctypes.get_errno()
        if error == 17:
            raise FileExistsError(error, os.strerror(error), str(destination))
        raise OSError(error, os.strerror(error), str(destination))


def _assert_private_work_directory(
    path: Path, expected_identity: tuple[int, int]
) -> None:
    """Revalidate the mode-0700 directory that contains primitive work files."""

    observed = os.lstat(path)
    if (
        not stat.S_ISDIR(observed.st_mode)
        or stat.S_IMODE(observed.st_mode) != 0o700
        or int(observed.st_uid) != os.getuid()
        or (int(observed.st_dev), int(observed.st_ino)) != expected_identity
        or path.is_symlink()
    ):
        raise RuntimeError("matched private work directory identity drift")


def _publish_owned(
    work_path: Path,
    final_path: Path,
    ownership: dict[Path, _OwnedFile | None],
    *,
    work_ownership: _OwnedFile | None = None,
    expected_identity: Mapping[str, object] | None = None,
    before_publish_hook: Callable[[], None] | None = None,
    after_replace_hook: Callable[[], None] | None = None,
) -> None:
    """Replace our placeholder and rebind rollback ownership to the new inode."""

    if ownership.get(final_path) is not None:
        raise RuntimeError(f"final output must be absent before publication: {final_path}")
    if os.path.lexists(final_path):
        raise FileExistsError(f"matched output already exists: {final_path}")
    opened_here = work_ownership is None
    work_owned = work_ownership or _open_owned_existing(work_path)
    try:
        work_stat = os.fstat(work_owned.fd)
        if not stat.S_ISREG(work_stat.st_mode) or int(work_stat.st_nlink) != 1:
            raise RuntimeError(f"matched work artifact is not regular: {work_path}")
        work_identity = (int(work_stat.st_dev), int(work_stat.st_ino))
        if work_identity != work_owned.identity:
            raise RuntimeError(f"matched held work identity drift: {work_path}")
        observed_work = os.lstat(work_path)
        if (int(observed_work.st_dev), int(observed_work.st_ino)) != work_identity:
            raise RuntimeError(f"matched work path was replaced: {work_path}")
        held_identity = _owned_file_identity(
            work_owned, reported_path=final_path
        )
        if expected_identity is not None and dict(expected_identity) != held_identity:
            raise RuntimeError(f"matched held work bytes drift: {work_path}")
        if before_publish_hook is not None:
            before_publish_hook()
        # The work path lives inside a mode-0700 private directory.  Within
        # that declared same-UID trust boundary it cannot be replaced by an
        # unrelated process; RENAME_NOREPLACE atomically protects the final.
        _rename_noreplace(work_path, final_path)
        ownership[final_path] = work_owned
        if after_replace_hook is not None:
            after_replace_hook()
        stat_result = os.lstat(final_path)
        if (
            not stat.S_ISREG(stat_result.st_mode)
            or int(stat_result.st_nlink) != 1
            or final_path.is_symlink()
        ):
            raise RuntimeError(f"published matched artifact is not regular: {final_path}")
        observed_after = (int(stat_result.st_dev), int(stat_result.st_ino))
        if observed_after != work_identity:
            raise RuntimeError("published path no longer names held work inode")
    finally:
        if opened_here and ownership.get(final_path) is not work_owned:
            work_owned.close()


def _reserve_permanent_attempt(
    path: Path,
    *,
    method_spec: MatchedMethodSpec,
    source_feature_bag: Path,
    raw_image_bag: Path,
    camera_yaml: Path,
    output_bag: Path,
    manifest_path: Path,
    diagnostics_path: Path,
    legacy_manifest_path: Path,
    work_directory: Path,
    prefix_mode: bool,
) -> dict[str, object]:
    """Consume the process namespace before any fallible formal validation."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "aqua-fe-detector-birth-rawlk-attempt-v1",
        "status": "ATTEMPT_CONSUMED_PROCESS_ENTERED_PRECHECK",
        "attempt_count": 1,
        "process_start_count": 1,
        "no_retry": True,
        "arm_id": method_spec.arm_id,
        "prefix_nonformal": bool(prefix_mode),
        "requested_inputs": {
            "source_feature_bag": str(source_feature_bag),
            "raw_image_bag": str(raw_image_bag),
            "camera_yaml": str(camera_yaml),
        },
        "reserved_outputs": {
            "feature_bag": str(output_bag),
            "manifest_json": str(manifest_path),
            "diagnostics_csv": str(diagnostics_path),
            "legacy_primitive_manifest": str(legacy_manifest_path),
            "private_work_directory": str(work_directory),
        },
        "producer": {
            "matched_core_requested": str(Path(__file__).resolve(strict=False)),
            "wrapper_requested": str(
                Path(method_spec.wrapper_source).resolve(strict=False)
            ),
        },
    }
    encoded = _canonical_bytes(payload)
    descriptor = os.open(
        str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444
    )
    try:
        os.fchmod(descriptor, 0o444)
        receipt_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(receipt_stat.st_mode)
            or stat.S_IMODE(receipt_stat.st_mode) != 0o444
            or int(receipt_stat.st_nlink) != 1
        ):
            raise RuntimeError("attempt receipt filesystem contract failed")
        written = 0
        while written < len(encoded):
            count = os.write(descriptor, encoded[written:])
            if count <= 0:
                raise OSError("attempt receipt write made no progress")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return payload


def _work_path(final_path: Path, role: str) -> Path:
    return final_path.with_name(
        f".{final_path.name}.{role}.{os.getpid()}.{secrets.token_hex(8)}"
    )


@contextmanager
def _patched_primitive(method_spec: MatchedMethodSpec, common: Mapping[str, object]):
    original_run = primitive.run_carrier
    original_message = primitive.build_feature_message
    original_contract = primitive._algorithm_contract
    original_read_source_schedule = primitive.read_source_schedule
    original_read_raw_frames = primitive.read_raw_frames
    original_nonfeature_digest = primitive._nonfeature_digest
    original_write_candidate_bag = primitive._write_candidate_bag
    original_verify_output_schedule = primitive._verify_output_schedule

    def scoped_rosbag(function):
        def wrapped(*args, **kwargs):
            return _call_trusted_rosbag_scoped(function, *args, **kwargs)

        return wrapped

    def patched_message(
        schedule_frame,
        frame,
        normalized,
        velocities,
        source_code=method_spec.source_code,
    ):
        if int(source_code) != method_spec.source_code:
            raise ValueError("primitive attempted to change matched source_code")
        return build_feature_message(
            schedule_frame,
            frame,
            normalized,
            velocities,
            source_code=method_spec.source_code,
            is_learned=method_spec.is_learned,
        )

    def patched_contract(_legacy_spec=None):
        return {
            "common_contract": copy.deepcopy(dict(common)),
            "common_contract_sha256": _canonical_sha256(common),
            "arm_contract": arm_contract(method_spec),
            "arm_contract_sha256": _canonical_sha256(arm_contract(method_spec)),
        }

    primitive.run_carrier = run_carrier
    primitive.build_feature_message = patched_message
    primitive._algorithm_contract = patched_contract
    primitive.read_source_schedule = scoped_rosbag(original_read_source_schedule)
    primitive.read_raw_frames = scoped_rosbag(original_read_raw_frames)
    primitive._nonfeature_digest = scoped_rosbag(original_nonfeature_digest)
    primitive._write_candidate_bag = scoped_rosbag(original_write_candidate_bag)
    primitive._verify_output_schedule = scoped_rosbag(original_verify_output_schedule)
    try:
        yield
    finally:
        primitive.run_carrier = original_run
        primitive.build_feature_message = original_message
        primitive._algorithm_contract = original_contract
        primitive.read_source_schedule = original_read_source_schedule
        primitive.read_raw_frames = original_read_raw_frames
        primitive._nonfeature_digest = original_nonfeature_digest
        primitive._write_candidate_bag = original_write_candidate_bag
        primitive._verify_output_schedule = original_verify_output_schedule


def _legacy_method_spec(method_spec: MatchedMethodSpec) -> primitive.DetectorMethodSpec:
    return primitive.DetectorMethodSpec(
        algorithm_name="detector_birth_rawlk_matched_v1",
        detector_key="detector",
        detector_contract=copy.deepcopy(dict(method_spec.detector_contract)),
        source_code=method_spec.source_code,
        max_candidates=MAX_CANDIDATES,
        manifest_schema_version=SCHEMA_VERSION,
        detector_factory=method_spec.detector_factory,
        entrypoint_source=Path(method_spec.wrapper_source).resolve(strict=True),
        static_code_artifacts=tuple(method_spec.detector_code_artifacts),
        production_detector_identity=method_spec.detector_implementation_id,
    )


def export_bag(
    source_feature_bag: str | Path,
    raw_image_bag: str | Path,
    camera_yaml: str | Path,
    output_bag: str | Path,
    *,
    image_topic: str,
    feature_topic: str = FEATURE_TOPIC_DEFAULT,
    manifest_json: str | Path,
    diagnostics_csv: str | Path,
    legacy_manifest_json: str | Path,
    work_directory: str | Path,
    attempt_json: str | Path,
    method_spec: MatchedMethodSpec,
    max_published_frames: int | None = None,
    detector=None,
    _cli_production_factory_token: object | None = None,
) -> dict[str, object]:
    """Export one arm through the shared matched transaction."""

    cli_formal = _cli_production_factory_token is _CLI_PRODUCTION_FACTORY_TOKEN
    if _cli_production_factory_token is not None and not cli_formal:
        raise ValueError("invalid matched CLI production token")
    if detector is not None and cli_formal:
        raise ValueError("formal CLI may not inject a detector")
    prefix_mode = max_published_frames is not None
    # Preserve lexical requested paths in the immutable invocation receipt.
    source_feature_bag = Path(source_feature_bag)
    raw_image_bag = Path(raw_image_bag)
    camera_yaml = Path(camera_yaml)
    output_bag = Path(output_bag).resolve(strict=False)
    manifest_path = Path(manifest_json).resolve(strict=False)
    diagnostics_path = Path(diagnostics_csv).resolve(strict=False)
    legacy_manifest_path = Path(legacy_manifest_json).resolve(strict=False)
    work_directory = Path(work_directory).resolve(strict=False)
    attempt_path = Path(attempt_json).resolve(strict=False)
    if len(
        {
            output_bag,
            manifest_path,
            diagnostics_path,
            legacy_manifest_path,
            work_directory,
            attempt_path,
        }
    ) != 6:
        raise ValueError("attempt and output paths must be distinct")
    attempt_payload = _reserve_permanent_attempt(
        attempt_path,
        method_spec=method_spec,
        source_feature_bag=source_feature_bag,
        raw_image_bag=raw_image_bag,
        camera_yaml=camera_yaml,
        output_bag=output_bag,
        manifest_path=manifest_path,
        diagnostics_path=diagnostics_path,
        legacy_manifest_path=legacy_manifest_path,
        work_directory=work_directory,
        prefix_mode=prefix_mode,
    )
    if cli_formal:
        _validate_formal_method_spec(method_spec)
    method_spec.validate()
    _configure_runtime()
    common = common_contract(strict_runtime=cli_formal)
    arm = arm_contract(method_spec)
    source_feature_bag = source_feature_bag.resolve(strict=True)
    raw_image_bag = raw_image_bag.resolve(strict=True)
    camera_yaml = camera_yaml.resolve(strict=True)
    requested_inputs = attempt_payload["requested_inputs"]
    canonical_inputs = {
        "source_feature_bag": str(source_feature_bag),
        "raw_image_bag": str(raw_image_bag),
        "camera_yaml": str(camera_yaml),
    }
    _require_canonical_requested_inputs(requested_inputs, canonical_inputs)
    inputs = {source_feature_bag, raw_image_bag, camera_yaml}
    finals = (output_bag, manifest_path, diagnostics_path, legacy_manifest_path)
    run_parent = output_bag.parent
    if any(path.parent != run_parent for path in finals + (attempt_path,)):
        raise ValueError("attempt and all published artifacts must share one run directory")
    if work_directory.parent != run_parent:
        raise ValueError("private work directory must be inside the matched run directory")
    if any(path in inputs for path in finals + (attempt_path,)):
        raise ValueError("outputs must be distinct and must not alias inputs")
    if any(path.is_symlink() for path in finals + (attempt_path,) if path.exists()):
        raise ValueError("matched outputs may not be symlinks")

    ownership: dict[Path, _OwnedFile | None] = {path: None for path in finals}
    if os.path.lexists(work_directory):
        raise FileExistsError(f"matched private work directory exists: {work_directory}")
    work_directory.parent.mkdir(parents=True, exist_ok=True)
    os.mkdir(work_directory, 0o700)
    os.chmod(work_directory, 0o700)
    work_stat = os.lstat(work_directory)
    work_directory_identity = (int(work_stat.st_dev), int(work_stat.st_ino))
    if (
        not stat.S_ISDIR(work_stat.st_mode)
        or stat.S_IMODE(work_stat.st_mode) != 0o700
        or int(work_stat.st_uid) != os.getuid()
        or any(work_directory.iterdir())
    ):
        raise RuntimeError("matched private work directory contract failed")
    work_bag = work_directory / "primitive_features.bag"
    work_legacy_manifest = work_directory / "primitive_manifest.json"
    work_manifest = work_directory / "matched_manifest.json"
    work_diagnostics = work_directory / "raw_diagnostics.csv"
    work_ownership: dict[Path, _OwnedFile | None] = {
        work_bag: None,
        work_legacy_manifest: None,
        work_manifest: None,
        work_diagnostics: None,
    }
    started = time.perf_counter()
    try:
        if any(os.path.lexists(path) for path in finals):
            raise FileExistsError("matched formal output appeared before publication")
        detector_instance = method_spec.detector_factory() if detector is None else detector
        runtime_after_factory = _runtime_identity(strict=cli_formal)
        if runtime_after_factory != common["runtime"]:
            raise RuntimeError("detector factory changed the common runtime identity")
        with _patched_primitive(method_spec, common):
            legacy_manifest = primitive.export_bag(
                source_feature_bag,
                raw_image_bag,
                camera_yaml,
                work_bag,
                image_topic=image_topic,
                feature_topic=feature_topic,
                max_published_frames=max_published_frames,
                manifest_json=work_legacy_manifest,
                detector=detector_instance,
                method_spec=_legacy_method_spec(method_spec),
                _wrapped_factory_token=(
                    primitive._WRAPPED_CLI_PRODUCTION_FACTORY_TOKEN
                    if cli_formal
                    else primitive._WRAPPED_PYTHON_FACTORY_TOKEN
                ),
            )
        rows = list(legacy_manifest["raw_frame_diagnostics"])
        runtime_after_carrier = _runtime_identity(strict=cli_formal)
        if runtime_after_carrier != common["runtime"]:
            raise RuntimeError("detector/carrier changed the common runtime identity")
        _write_diagnostics_csv(work_diagnostics, rows)
        work_ownership[work_bag] = _open_owned_existing(work_bag)
        work_ownership[work_legacy_manifest] = _open_owned_existing(
            work_legacy_manifest
        )
        work_ownership[work_diagnostics] = _open_owned_existing(work_diagnostics)
        output_identity = _owned_file_identity(
            work_ownership[work_bag], reported_path=output_bag
        )
        diagnostics_identity = _owned_file_identity(
            work_ownership[work_diagnostics], reported_path=diagnostics_path
        )
        legacy_identity = _owned_file_identity(
            work_ownership[work_legacy_manifest],
            reported_path=legacy_manifest_path,
        )
        legacy_output_identity = dict(legacy_manifest["output_bag"])
        legacy_prepublication_path = str(legacy_output_identity["path"])
        legacy_output_identity["path"] = str(output_bag)
        if legacy_output_identity != output_identity:
            raise RuntimeError("legacy exporter output identity/held FD mismatch")
        detector_metadata = legacy_manifest["code_artifacts"]["detector"]
        runtime_after_metadata = _runtime_identity(strict=cli_formal)
        if runtime_after_metadata != common["runtime"]:
            raise RuntimeError("detector metadata changed the common runtime identity")
        detector_runtime = detector_metadata.get("runtime", {})
        if not isinstance(detector_runtime, Mapping):
            raise RuntimeError("detector runtime metadata must be a mapping")
        _validate_detector_runtime(detector_runtime, rows)
        if method_spec.is_learned == 1:
            matched_runtime = detector_metadata.get("matched_runtime_contract")
            if matched_runtime != {
                "device": "cpu",
                "torch_num_threads": 1,
                "torch_num_interop_threads": 1,
                "deterministic_algorithms": True,
            }:
                raise RuntimeError(
                    "learned detector did not satisfy matched CPU runtime contract"
                )
            if str(detector_runtime.get("device")) != "cpu":
                raise RuntimeError("learned matched detector ran outside CPU")
        else:
            if str(detector_runtime.get("opencv_version")) != EXPECTED_OPENCV_VERSION:
                raise RuntimeError("classical detector OpenCV runtime drift")
            if str(detector_runtime.get("numpy_version")) != EXPECTED_NUMPY_VERSION:
                raise RuntimeError("classical detector NumPy runtime drift")
        code_artifacts = {
            "matched_core": _file_identity(Path(__file__)),
            "frozen_primitive_module": _file_identity(Path(primitive.__file__)),
            "wrapper": _file_identity(Path(method_spec.wrapper_source)),
            "detector_dependencies": {
                str(label): _file_identity(Path(path))
                for label, path in method_spec.detector_code_artifacts
            },
            "detector_runtime": detector_metadata,
        }
        formal_eligible = bool(cli_formal and not prefix_mode)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": "FULL" if not prefix_mode else "PREFIX_NONFORMAL",
            "formal_eligible": formal_eligible,
            "formal_eligibility_reason": (
                "full_export_from_frozen_matched_cli_factory"
                if formal_eligible
                else "explicit_prefix_is_nonformal"
                if prefix_mode
                else "python_api_export_is_nonformal"
            ),
            "scientific_role": (
                "post_result_development_exploratory_detector_birth_ablation"
            ),
            "prefix": copy.deepcopy(legacy_manifest["prefix"]),
            "attempt": {
                "identity": _file_identity(attempt_path),
                "payload": attempt_payload,
            },
            "inputs": copy.deepcopy(legacy_manifest["inputs"]),
            "common_contract": common,
            "common_contract_sha256": _canonical_sha256(common),
            "arm_contract": arm,
            "arm_contract_sha256": _canonical_sha256(arm),
            "pair_difference_policy": {
                "no_wildcard_allowlist": True,
                "freeze_must_pin_every_detector_specific_leaf": True,
                "only_semantic_categories": [
                    "detector_adapter_identity_and_frozen_parameters",
                    "truthful_backend_inert_detector_provenance",
                    "detector_candidates_births_survival_ids_and_trajectory_outcomes",
                    "detector_runtime_and_output_artifact_identity",
                ],
                "posthoc_candidate_or_observation_dose_matching_forbidden": True,
            },
            "code_artifacts": code_artifacts,
            "outputs": {
                "feature_bag": output_identity,
                "raw_diagnostics_csv": diagnostics_identity,
                "legacy_primitive_manifest": legacy_identity,
            },
            "legacy_prepublication_rebind": {
                "primitive_reported_work_bag_path": legacy_prepublication_path,
                "primitive_reported_output_identity_after_path_rebind": (
                    legacy_output_identity
                ),
                "published_feature_bag_identity": output_identity,
                "reason": (
                    "frozen_primitive_writes_inside_private_work_directory; "
                    "matched_transaction_publishes_the_identical_held_inode"
                ),
            },
            "nonfeature_stream_before": copy.deepcopy(
                legacy_manifest["nonfeature_stream_before"]
            ),
            "nonfeature_stream_after": copy.deepcopy(
                legacy_manifest["nonfeature_stream_after"]
            ),
            "metrics": copy.deepcopy(legacy_manifest["metrics"]),
            "diagnostics_streams": {
                "row_count": len(rows),
                "raw_schedule_sha256": _diagnostics_schedule_stream(rows),
                "raw_and_processed_pixels_sha256": _diagnostics_common_stream(rows),
                "common_row_fields": [
                    "raw_index",
                    "header_stamp_ns",
                    "published",
                    "adaptive_clahe_applied",
                    "raw_image_sha256",
                    "processed_image_sha256",
                ],
            },
            "raw_frame_diagnostics": rows,
            "runtime": {
                "elapsed_wall_ms": (time.perf_counter() - started) * 1000.0,
                "common_runtime": copy.deepcopy(common["runtime"]),
                "post_factory_runtime": runtime_after_factory,
                "post_carrier_runtime": runtime_after_carrier,
                "post_metadata_runtime": runtime_after_metadata,
            },
        }
        with work_manifest.open("xb") as handle:
            handle.write(_canonical_bytes(payload))
            handle.flush()
            os.fsync(handle.fileno())
        work_ownership[work_manifest] = _open_owned_existing(work_manifest)
        manifest_identity = _owned_file_identity(
            work_ownership[work_manifest], reported_path=manifest_path
        )
        _assert_private_work_directory(work_directory, work_directory_identity)
        _publish_owned(
            work_bag,
            output_bag,
            ownership,
            work_ownership=work_ownership[work_bag],
            expected_identity=output_identity,
        )
        work_ownership[work_bag] = None
        _assert_private_work_directory(work_directory, work_directory_identity)
        _publish_owned(
            work_diagnostics,
            diagnostics_path,
            ownership,
            work_ownership=work_ownership[work_diagnostics],
            expected_identity=diagnostics_identity,
        )
        work_ownership[work_diagnostics] = None
        _assert_private_work_directory(work_directory, work_directory_identity)
        _publish_owned(
            work_legacy_manifest,
            legacy_manifest_path,
            ownership,
            work_ownership=work_ownership[work_legacy_manifest],
            expected_identity=legacy_identity,
        )
        work_ownership[work_legacy_manifest] = None
        # The matched manifest is the commit marker and is always published
        # last, after every artifact it claims has become visible.
        _assert_private_work_directory(work_directory, work_directory_identity)
        _publish_owned(
            work_manifest,
            manifest_path,
            ownership,
            work_ownership=work_ownership[work_manifest],
            expected_identity=manifest_identity,
        )
        work_ownership[work_manifest] = None
        for owned in ownership.values():
            if owned is not None:
                owned.close()
        return payload
    except BaseException:
        # Failures are permanent, non-retryable scientific outcomes.  Do not
        # unlink either published or private work names here: even an
        # inode-checked unlink has a check/delete race that could remove a
        # foreign replacement.  The immutable attempt receipt plus retained
        # artifacts make the failed transaction auditable.
        for owned in work_ownership.values():
            if owned is not None:
                owned.close()
        for owned in ownership.values():
            if owned is not None:
                owned.close()
        raise


def cli_summary(manifest: Mapping[str, object]) -> dict[str, object]:
    return {
        "status": manifest["status"],
        "formal_eligible": manifest["formal_eligible"],
        "arm_id": manifest["arm_contract"]["arm_id"],
        "common_contract_sha256": manifest["common_contract_sha256"],
        "outputs": manifest["outputs"],
        "metrics": manifest["metrics"],
    }
