#!/usr/bin/env python3
"""Build the late-bound A09 warm-history backend execution lock.

This builder is intentionally inert unless ``build`` is requested with the
exact authorization token.  The two frontend authorities are discovered only
at that time, after their canonical directories and accepted receipts exist.
Importing this module performs no filesystem reads and starts no process.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any, Iterator, Mapping


ROOT = Path("/home/ma/AQUA-FE_WS")
EXP_ROOT = Path("/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1")
LOCK_PATH = ROOT / "papers/a09_samehistory_warmstart_v1_backend_execution_lock.json"
PROTOCOL_PATH = ROOT / "papers/a09_samehistory_warmstart_v1_backend_protocol.md"
RUNNER_PATH = ROOT / "scripts/run_a09_samehistory_warmstart_v1_backends.py"
BUILDER_PATH = Path(__file__).absolute()
FRONTEND_RUNNER = ROOT / "scripts/run_a09_samehistory_warmstart_v1_frontends.py"
FRONTEND_PROTOCOL = ROOT / "papers/a09_samehistory_warmstart_v1_frontends_protocol.md"
FRONTEND_FLOCK = EXP_ROOT / ".frontend_supervisor.flock"
BACKEND_FLOCK = EXP_ROOT / ".backend_supervisor.flock"
STORAGE_ROOT = Path("/mnt/data")
FUSEBLK_STATFS_MAGIC = 0x65735546
REQUESTED_SEAL_MODE = 0o444
FUSEBLK_OBSERVED_FILE_MODE = 0o755

SCHEMA = "aqua-fe-a09-samehistory-warmstart-backend-lock-v1"
AUTHORIZATION_TOKEN = "A09_WARMSTART_V1_BUILD_BACKEND_LOCK_EXACTLY_ONCE"
ITEM_ORDER = (
    "vanilla_origin_native_image_context",
    "klt_external_feature_context",
    "aquafe_external_feature_context",
)

RAW_BAG = EXP_ROOT / "raw/archaeo09_0000_4400.bag"
RAW_RECEIPT = EXP_ROOT / "raw/raw_materialization_receipt_v1.json"
RAW_ADDENDUM = EXP_ROOT / "raw/raw_materialization_canonicalization_addendum_v1.json"
RAW_FREEZE = ROOT / "papers/a09_samehistory_warmstart_v1_raw_materialization_freeze.json"
SOURCE_ARCHIVE = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences/archaeo_sequence_9_raw_data.tar.gz"
)
GROUND_TRUTH = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences/archaeo_groundtruth_files/"
    "new_archaeo_colmap_traj_sequence_09.txt"
)

KLT_DIR = EXP_ROOT / "frontends/klt_export"
AQUA_DIR = EXP_ROOT / "frontends/aquafe_finalonline"
AQUA_V2_STAGE = EXP_ROOT / "frontends/.aquafe_finalonline.stage_v2"
KLT_WORKSPACE = (
    ROOT / "logs/aqualoc_archaeo_vins/"
    "external_klt_every2_systemfair_a09_warmstart_v1_feed0000_4400_klt_export"
)
KLT_STRENGTH_ADDENDUM = (
    ROOT / "papers/a09_samehistory_warmstart_v1_klt_execution_strength_addendum.json"
)
AQUA_V2_EXECUTION_LOCK = (
    ROOT / "papers/a09_samehistory_warmstart_v2_aquafe_execution_lock.json"
)
AQUA_V2_RUNNER = ROOT / "scripts/run_a09_samehistory_warmstart_v2_aquafe.py"
AQUA_V2_BUILDER = ROOT / "scripts/build_a09_samehistory_warmstart_v2_aquafe_lock.py"
AQUA_V2_PROTOCOL = ROOT / "papers/a09_samehistory_warmstart_v2_aquafe_protocol.md"
KLT_ADDENDUM_SCHEMA = (
    "aqua-fe-a09-samehistory-warmstart-klt-execution-strength-addendum-v1"
)
KLT_ADDENDUM_STATUSES = {
    "PASS_POSTHOC_KLT_EXECUTION_STRENGTH_AUDIT",
    "PASS_KLT_EXECUTION_STRENGTH_NARROWED_AND_EXTERNALLY_VERIFIED",
}
KLT_ADDENDUM_LIMITATIONS = {
    "old_receipt_waited_session_leader_only": True,
    "old_receipt_process_group_claim_is_not_strong_proof": True,
    "cannot_retroactively_prove_descendants_empty_at_leader_exit": True,
    "old_receipt_environment_records_overrides_only": True,
    "full_effective_environment_not_proven": True,
    "old_claim_was_plain_write_not_durable_or_exclusive": True,
    "exactly_once_execution_not_proven": True,
    "addendum_is_posthoc_evidence_only": True,
    "runtime_or_paper_performance_claim_permitted": False,
}
FRONTEND_SPECS: dict[str, dict[str, Any]] = {
    "klt": {
        "authority_version": "klt-v1-plus-external-strength-addendum-v1",
        "directory": KLT_DIR,
        "receipt": "formal_run_receipt_v1.json",
        "claim": "process_start_claim_v1.json",
        "required_outputs": (
            "features.bag",
            "frontend_metrics.csv",
            "aqualoc_archaeo09_pinhole.yaml",
            "supervisor_process.log",
        ),
    },
    "aquafe": {
        "authority_version": "aquafe-v2",
        "directory": AQUA_DIR,
        "receipt": "formal_run_receipt_v2.json",
        "claim": "process_start_claim_v2.json",
        "required_outputs": (
            "full_merged.bag",
            "sidecar.bag",
            "stats.csv",
            "supervisor_process.log",
        ),
    },
}

SAFETY_BASE = ROOT / "scripts/run_samehistory_system_a10_finalonline_v4_backend_recovery.py"
BACKEND_SHELL = ROOT / "scripts/run_aqualoc_archaeo_vins_eval_v4_backend_recovery.sh"
NETNS_ENTRY = ROOT / "scripts/enter_samehistory_backend_netns_v4.py"
VINS_WS = Path("/home/ma/SLAM/VINS-Fusion-origin")

STATIC_IDENTITY_PATHS: dict[str, Path] = {
    "lock_builder": BUILDER_PATH,
    "backend_supervisor": RUNNER_PATH,
    "backend_protocol": PROTOCOL_PATH,
    "frontend_runner": FRONTEND_RUNNER,
    "frontend_protocol": FRONTEND_PROTOCOL,
    "a10_v4_safety_base": SAFETY_BASE,
    "dedicated_archaeology_runner": BACKEND_SHELL,
    "network_namespace_entry": NETNS_ENTRY,
    "raw_bag": RAW_BAG,
    "raw_receipt": RAW_RECEIPT,
    "raw_addendum": RAW_ADDENDUM,
    "raw_freeze": RAW_FREEZE,
    "raw_tar": SOURCE_ARCHIVE,
    "ground_truth": GROUND_TRUTH,
    "record_vins_env": ROOT / "scripts/record_vins_env.sh",
    "wait_for_subscribers": ROOT / "scripts/wait_for_ros_subscribers.py",
    "legacy_ape_evaluator": ROOT / "scripts/evaluate_vins_sim_ape.py",
    "common_support_evaluator": ROOT / "scripts/evaluate_vins_common_support_epoch_v2.py",
    "common_support_evaluator_base": ROOT / "scripts/evaluate_vins_common_support.py",
    "common_support_evaluator_core": ROOT / "scripts/trajectory_eval_core.py",
    "vins_node": VINS_WS / "devel/lib/vins/vins_node",
    "vins_library": VINS_WS / "devel/lib/libvins_lib.so",
    "vins_camera_models_library": VINS_WS / "devel/lib/libcamera_models.so",
    "vins_setup_bash": VINS_WS / "devel/setup.bash",
    "vins_setup_sh": VINS_WS / "devel/setup.sh",
    "vins_setup_utility": VINS_WS / "devel/_setup_util.py",
    "ros_setup_bash": Path("/opt/ros/noetic/setup.bash"),
    "ros_setup_sh": Path("/opt/ros/noetic/setup.sh"),
    "ros_setup_utility": Path("/opt/ros/noetic/_setup_util.py"),
    "ros_catkin_marker": Path("/opt/ros/noetic/.catkin"),
    "vins_catkin_marker": VINS_WS / "devel/.catkin",
    "dave_catkin_marker": Path("/home/ma/dave_ws/devel/.catkin"),
    "uuv_catkin_marker": Path("/home/ma/uuv_ws/devel/.catkin"),
    "rosbag_cli": Path("/opt/ros/noetic/bin/rosbag"),
    "roscore_cli": Path("/opt/ros/noetic/bin/roscore"),
    "rosmaster_cli": Path("/opt/ros/noetic/bin/rosmaster"),
    "rosparam_cli": Path("/opt/ros/noetic/bin/rosparam"),
    "rosrun_cli": Path("/opt/ros/noetic/bin/rosrun"),
    "rosout_node": Path("/opt/ros/noetic/lib/rosout/rosout"),
    "unshare": Path("/usr/bin/unshare"),
    "ip": Path("/usr/bin/ip"),
    "setsid": Path("/usr/bin/setsid"),
    "sleep": Path("/usr/bin/sleep"),
    "readlink": Path("/usr/bin/readlink"),
    "bash": Path("/usr/bin/bash"),
    "python3_8": Path("/usr/bin/python3.8"),
    "coreutils_cp": Path("/usr/bin/cp"),
    "coreutils_realpath": Path("/usr/bin/realpath"),
    "coreutils_rm": Path("/usr/bin/rm"),
    "coreutils_mkdir": Path("/usr/bin/mkdir"),
    "coreutils_cat": Path("/usr/bin/cat"),
    "coreutils_basename": Path("/usr/bin/basename"),
    "coreutils_dirname": Path("/usr/bin/dirname"),
    "coreutils_tee": Path("/usr/bin/tee"),
    "coreutils_date": Path("/usr/bin/date"),
    "hostname": Path("/usr/bin/hostname"),
    "rospack_cli": Path("/opt/ros/noetic/bin/rospack"),
    "coreutils_stat": Path("/usr/bin/stat"),
    "coreutils_md5sum": Path("/usr/bin/md5sum"),
    "sed": Path("/usr/bin/sed"),
    "coreutils_uname": Path("/usr/bin/uname"),
    "coreutils_mktemp": Path("/usr/bin/mktemp"),
    "grep": Path("/usr/bin/grep"),
    "awk": Path("/usr/bin/mawk"),
    "rosbash_source": Path("/opt/ros/noetic/share/rosbash/rosbash"),
}

# These immutable authorities are known before the late-bound frontend stage.
# Other tools are frozen dynamically by the execution lock.
EXPECTED_FIXED: dict[str, tuple[int, str]] = {
    "a10_v4_safety_base": (
        253_456,
        "4ac06b942a38f0074df6d2193d17d634673bc360865cee752f5732241224c277",
    ),
    "dedicated_archaeology_runner": (
        54_870,
        "d9d805943a230f5fddf7be2262cfb63316ab0958f1e7aa35a94602571783ab9c",
    ),
    "network_namespace_entry": (
        8_527,
        "e37e9371e970f167ef13de62f67c026d2eb098d7ec79af77dc409a4af14520ee",
    ),
    "raw_bag": (
        1_187_038_470,
        "a4a24bd0c2451f4996d39f635e55fd99730698bf704c4e7dc81729070d0dca97",
    ),
    "raw_receipt": (
        7_199,
        "b6f0ec00f04d5c62514b96b3ce591bc561221227ea05163793fc68d8c4d3cf91",
    ),
    "raw_addendum": (
        2_717,
        "86e82d58dbd85f39907144aa1098352b97282c143fef5259cacd2974c4ca0956",
    ),
    "raw_freeze": (
        2_422,
        "d72dcef75052194a8e48a8e14da5233412345b66a60b7c53e93e4650779cfa57",
    ),
    "raw_tar": (
        1_722_658_380,
        "4d20237571928067cfe4dbb813224cfd2277270c424a6ef97ef50d2933da2901",
    ),
    "ground_truth": (
        45_197,
        "b732a68ec354cb66d36b1a9f708d614c70e884d4c167f8940f9601cfce69ac17",
    ),
    "record_vins_env": (
        2_049,
        "577e17acb5e8df1a4a6d8d5b6ed531103adb984a5c7cb1cc8523f95d6e695ad3",
    ),
    "wait_for_subscribers": (
        1_993,
        "5b1c98907651122439aa4d31bd90fea7fcc44a5a35557ceda5131f9c3d84eaa5",
    ),
    "legacy_ape_evaluator": (
        10_127,
        "ef68c19a0af6c06598bb473f57c581a7bb874b68cdccc95f4c85905bb9219d33",
    ),
    "common_support_evaluator": (
        5_447,
        "3c455299b23157cc749b474b9460ca4a408b3bee516e9d1bf2109f253cf89f91",
    ),
    "common_support_evaluator_base": (
        27_933,
        "ab6f2b5c1a10a41463657edee2724c022fc0248dc885096acb336e602384c110",
    ),
    "common_support_evaluator_core": (
        27_945,
        "aa9ac4da81df7298d1f1c369548ca98a57235916004337cad66f4cf331560635",
    ),
    "vins_node": (
        13_104_360,
        "4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278",
    ),
    "vins_library": (
        165_205_008,
        "4ea9a556f004ecd01ae1aedc1b3abc6ed90ae915acd2916a288601a4375353bc",
    ),
    "vins_camera_models_library": (
        2_970_640,
        "6d7b261f12791b693f95aebea6a762a97bc3501f1f1f3c94a6af6e50f2e6690d",
    ),
    "bash": (
        1_183_448,
        "025cf78cd9d276019e916b97b0decd10cacb14902db8eb9f28233019babfb331",
    ),
    "python3_8": (
        5_490_456,
        "298a9e830ed52f36c299427565485d717d1ce0179c0597cc16560513eb780b06",
    ),
    "unshare": (
        43_448,
        "ce0d8955cbaa0d22b6b0a9de8f616165ef46a4d392ac8baf1ae732697979e787",
    ),
    "setsid": (
        14_568,
        "50c286699e7a33cccc6f1495a583d7956825bd3c73195c5def6b46d2fa377254",
    ),
}

ROS_PROFILE_DIR = Path("/opt/ros/noetic/etc/catkin/profile.d")
ROS_HOOK_NAMES = (
    "05.catkin_make.bash",
    "05.catkin_make_isolated.bash",
    "1.ros_distro.sh",
    "1.ros_etc_dir.sh",
    "1.ros_package_path.sh",
    "1.ros_python_version.sh",
    "1.ros_version.sh",
    "10.rosbuild.sh",
    "10.roslaunch.sh",
    "15.rosbash.bash",
    "15.rosbash.fish",
    "15.rosbash.tcsh",
    "15.rosbash.zsh",
    "20.transform.bash",
    "99.roslisp.sh",
)
ABSENT_WORKSPACE_PROFILE_DIRS = (
    VINS_WS / "devel/etc/catkin/profile.d",
    Path("/home/ma/dave_ws/devel/etc/catkin/profile.d"),
    Path("/home/ma/uuv_ws/devel/etc/catkin/profile.d"),
)

BASE_ENVIRONMENT = {
    "HOME": "/home/ma",
    "USER": "ma",
    "LOGNAME": "ma",
    "LANG": "zh_CN.UTF-8",
    "LANGUAGE": "zh_CN:zh",
    "PATH": "/opt/ros/noetic/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "CMAKE_PREFIX_PATH": "/home/ma/dave_ws/devel:/home/ma/uuv_ws/devel:/opt/ros/noetic",
    "LD_LIBRARY_PATH": "/home/ma/dave_ws/devel/lib:/home/ma/uuv_ws/devel/lib:/opt/ros/noetic/lib:/opt/ros/noetic/lib/x86_64-linux-gnu",
    "PKG_CONFIG_PATH": "/home/ma/dave_ws/devel/lib/pkgconfig:/home/ma/uuv_ws/devel/lib/pkgconfig:/opt/ros/noetic/lib/pkgconfig:/opt/ros/noetic/lib/x86_64-linux-gnu/pkgconfig",
    "PYTHONPATH": "/home/ma/dave_ws/devel/lib/python3/dist-packages:/home/ma/uuv_ws/devel/lib/python3/dist-packages:/opt/ros/noetic/lib/python3/dist-packages",
    "ROS_DISTRO": "noetic",
    "ROS_ETC_DIR": "/opt/ros/noetic/etc/ros",
    "ROS_PACKAGE_PATH": "/home/ma/dave_ws/src:/home/ma/uuv_ws/src:/opt/ros/noetic/share",
    "ROS_PYTHON_VERSION": "3",
    "ROS_ROOT": "/opt/ros/noetic/share/ros",
    "ROS_VERSION": "1",
    "ROS_MASTER_URI": "http://localhost:11311",
}

COMMON_ITEM_ENVIRONMENT = {
    "ROOT": str(ROOT),
    "VINS_WS": str(VINS_WS),
    "AQUALOC_ROOT": str(SOURCE_ARCHIVE.parent),
    "RAW_TAR": str(SOURCE_ARCHIVE),
    "GT_TXT": str(GROUND_TRUTH),
    "RAW_BAG": str(RAW_BAG),
    "RUN_VINS": "1",
    "FORCE_RAW": "0",
    "FORCE_EXPORT": "0",
    "VINS_NODE_BIN": str(STATIC_IDENTITY_PATHS["vins_node"]),
    "WAIT_FOR_VINS_SUBSCRIBERS": "1",
    "WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT": "20",
    "VINS_MULTIPLE_THREAD": "1",
    "AQUALOC_BODY_T_CAM0_MODE": "imu_cam",
    "VINS_TD": "-0.053694112369382575",
    "VINS_ESTIMATE_TD": "0",
    "VINS_MAX_SOLVER_TIME": "0.04",
    "VINS_MAX_NUM_ITERATIONS": "8",
    "PLAY_RATE": "1.0",
    "ROSBAG_PLAY_DELAY": "3",
    "ROSBAG_WAIT_FOR_SUBSCRIBERS": "0",
    "POST_PLAY_SLEEP": "8",
    "BACKEND_REPLAY_ONLY": "0",
    "PORT": "11981",
}

ARM_SPECS: dict[str, dict[str, str]] = {
    "vanilla_origin_native_image_context": {
        "mode": "origin",
        "method": "klt",
        "every_n": "1",
        "tag": "systemfair_a09_warmstart_v1_feed0000_4400_score4000_4400_vanilla_origin",
        "run_leaf": "origin_klt_every1_systemfair_a09_warmstart_v1_feed0000_4400_score4000_4400_vanilla_origin",
        "config_name": "vins_aqualoc_archaeo_origin.yaml",
        "config_size": "990",
        "config_sha256": "eafd7e6f22e573c4e0d7b5e36f2550938029456fc75ad55bd741c1d000016ff7",
    },
    "klt_external_feature_context": {
        "mode": "external",
        "method": "klt",
        "every_n": "2",
        "tag": "systemfair_a09_warmstart_v1_feed0000_4400_score4000_4400_external_klt",
        "run_leaf": "external_klt_every2_systemfair_a09_warmstart_v1_feed0000_4400_score4000_4400_external_klt",
        "config_name": "vins_aqualoc_archaeo_external.yaml",
        "config_size": "986",
        "config_sha256": "b928b31af629bddd9ff677953c185778a2172a0f946fce71bfa1e08b5d879178",
        "feature_bag": str(KLT_DIR / "features.bag"),
    },
    "aquafe_external_feature_context": {
        "mode": "external",
        "method": "hybrid_xfeat",
        "every_n": "2",
        "tag": "systemfair_a09_warmstart_v1_feed0000_4400_score4000_4400_aquafe_finalonline_xfeat_lineage",
        "run_leaf": "external_hybrid_xfeat_every2_systemfair_a09_warmstart_v1_feed0000_4400_score4000_4400_aquafe_finalonline_xfeat_lineage",
        "config_name": "vins_aqualoc_archaeo_external.yaml",
        "config_size": "1015",
        "config_sha256": "4b58c2e422fcce4dfecfc6ffbb227fe979e641923a378bbaa227f0baa22894ed",
        "feature_bag": str(AQUA_DIR / "full_merged.bag"),
    },
}

CAMERA_CONFIG_IDENTITY = {
    "size_bytes": 357,
    "sha256": "045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5",
}


class LockBuildError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise LockBuildError(code)


class _StatFS(ctypes.Structure):
    _fields_ = [
        ("f_type", ctypes.c_long),
        ("f_bsize", ctypes.c_long),
        ("f_blocks", ctypes.c_ulong),
        ("f_bfree", ctypes.c_ulong),
        ("f_bavail", ctypes.c_ulong),
        ("f_files", ctypes.c_ulong),
        ("f_ffree", ctypes.c_ulong),
        ("f_fsid", ctypes.c_int * 2),
        ("f_namelen", ctypes.c_long),
        ("f_frsize", ctypes.c_long),
        ("f_flags", ctypes.c_long),
        ("f_spare", ctypes.c_long * 4),
    ]


def _mountinfo_unescape(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return chr(int(match.group(1), 8))

    decoded = re.sub(r"\\([0-7]{3})", replace, value)
    require("\\" not in decoded, f"MOUNTINFO_UNRECOGNIZED_ESCAPE:{value}")
    return decoded


def _effective_mountinfo(path: Path) -> dict[str, Any]:
    path = path.absolute()
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise LockBuildError(f"MOUNTINFO_READ_FAILED:{type(error).__name__}:{error}") from error
    candidates: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        fields = line.split()
        require(len(fields) >= 10, f"MOUNTINFO_FIELDS:{line_number}")
        try:
            separator = fields.index("-")
        except ValueError as error:
            raise LockBuildError(f"MOUNTINFO_SEPARATOR:{line_number}") from error
        require(separator >= 6 and len(fields) >= separator + 4, f"MOUNTINFO_LAYOUT:{line_number}")
        mount_point = Path(_mountinfo_unescape(fields[4])).absolute()
        if mount_point != path:
            continue
        try:
            mount_id = int(fields[0])
            parent_id = int(fields[1])
        except ValueError as error:
            raise LockBuildError(f"MOUNTINFO_ID:{line_number}") from error
        candidates.append(
            {
                "mount_id": mount_id,
                "parent_id": parent_id,
                "major_minor": fields[2],
                "root": _mountinfo_unescape(fields[3]),
                "mount_point": str(mount_point),
                "mount_options": fields[5].split(","),
                "optional_fields": fields[6:separator],
                "filesystem_type": fields[separator + 1],
                "source": _mountinfo_unescape(fields[separator + 2]),
                "super_options": fields[separator + 3].split(","),
            }
        )
    require(candidates, f"MOUNTINFO_PATH_NOT_FOUND:{path}")
    covered_mount_ids = {row["parent_id"] for row in candidates}
    effective = [row for row in candidates if row["mount_id"] not in covered_mount_ids]
    require(len(effective) == 1, f"MOUNTINFO_EFFECTIVE_AMBIGUOUS:{path}:{candidates}")
    return effective[0]


def _statfs_magic(path: Path) -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    function = libc.statfs
    function.argtypes = [ctypes.c_char_p, ctypes.POINTER(_StatFS)]
    function.restype = ctypes.c_int
    result = _StatFS()
    encoded = os.fsencode(str(path.absolute()))
    if function(encoded, ctypes.byref(result)) != 0:
        error_number = ctypes.get_errno()
        raise LockBuildError(f"STATFS_FAILED:{path}:{error_number}:{os.strerror(error_number)}")
    return int(result.f_type) & ((1 << (8 * ctypes.sizeof(ctypes.c_long))) - 1)


def validate_storage_permission_semantics(value: Mapping[str, Any]) -> None:
    require(value.get("storage_root") == str(STORAGE_ROOT), "STORAGE_ROOT_POLICY")
    require(isinstance(value.get("storage_device"), int), "STORAGE_DEVICE_POLICY")
    require(value.get("effective_mount_point") == str(STORAGE_ROOT), "STORAGE_MOUNT_POINT_POLICY")
    require(value.get("filesystem_type") == "fuseblk", "STORAGE_FILESYSTEM_POLICY")
    require(value.get("statfs_magic_hex") == "0x65735546", "STORAGE_MAGIC_POLICY")
    require(value.get("requested_mode") == "0444", "STORAGE_REQUESTED_MODE_POLICY")
    require(value.get("observed_mode") == "0755", "STORAGE_OBSERVED_MODE_POLICY")
    require(value.get("posix_readonly_enforced") is False, "STORAGE_READONLY_POLICY")
    require(value.get("permission_bits_are_integrity_basis") is False, "STORAGE_MODE_BASIS_POLICY")
    require(value.get("fchmod_and_fsync_required") is True, "STORAGE_FCHMOD_FSYNC_POLICY")
    require(
        value.get("integrity_basis")
        == "no_replace_hardlink+fsync+exact_inode_size_sha256+postreceipt_rehash",
        "STORAGE_INTEGRITY_BASIS_POLICY",
    )
    mountinfo = value.get("effective_mountinfo")
    require(
        isinstance(mountinfo, dict)
        and isinstance(mountinfo.get("mount_id"), int)
        and isinstance(mountinfo.get("parent_id"), int)
        and mountinfo.get("filesystem_type") == "fuseblk"
        and mountinfo.get("mount_point") == str(STORAGE_ROOT),
        "STORAGE_MOUNTINFO_POLICY",
    )


def storage_permission_semantics() -> dict[str, Any]:
    mountinfo = _effective_mountinfo(STORAGE_ROOT)
    magic = _statfs_magic(STORAGE_ROOT)
    root_info = STORAGE_ROOT.lstat()
    require(stat.S_ISDIR(root_info.st_mode) and not STORAGE_ROOT.is_symlink(), "STORAGE_ROOT_KIND")
    require(mountinfo["filesystem_type"] == "fuseblk", "STORAGE_NOT_FUSEBLK")
    require(magic == FUSEBLK_STATFS_MAGIC, f"STORAGE_STATFS_MAGIC:{magic:#x}")
    require(stat.S_IMODE(root_info.st_mode) == FUSEBLK_OBSERVED_FILE_MODE, "STORAGE_ROOT_MODE")
    value: dict[str, Any] = {
        "storage_root": str(STORAGE_ROOT),
        "storage_device": int(root_info.st_dev),
        "effective_mount_point": mountinfo["mount_point"],
        "filesystem_type": mountinfo["filesystem_type"],
        "statfs_magic_hex": f"0x{magic:08x}",
        "mount_root_observed_mode": f"{stat.S_IMODE(root_info.st_mode):04o}",
        "requested_mode": f"{REQUESTED_SEAL_MODE:04o}",
        "observed_mode": f"{FUSEBLK_OBSERVED_FILE_MODE:04o}",
        "posix_readonly_enforced": False,
        "permission_bits_are_integrity_basis": False,
        "fchmod_and_fsync_required": True,
        "fchmod_success_may_leave_projected_mode_unchanged": True,
        "integrity_basis": (
            "no_replace_hardlink+fsync+exact_inode_size_sha256+postreceipt_rehash"
        ),
        "effective_mountinfo": mountinfo,
    }
    validate_storage_permission_semantics(value)
    return value


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def compact_sha256(value: Any) -> str:
    data = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular_file(path: Path, context: str) -> None:
    require(path.exists() and not path.is_symlink(), f"NOT_REGULAR:{context}:{path}")
    observed = path.lstat()
    require(stat.S_ISREG(observed.st_mode), f"NOT_REGULAR:{context}:{path}")


def identity(path: Path) -> dict[str, Any]:
    path = path.absolute()
    regular_file(path, "identity")
    before = path.stat()
    digest = sha256_file(path)
    after = path.stat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    require(
        all(getattr(before, name) == getattr(after, name) for name in fields),
        f"FILE_CHANGED_DURING_HASH:{path}",
    )
    return {"path": str(path), "size_bytes": after.st_size, "sha256": digest}


def require_identity_matches(actual: Mapping[str, Any], expected: Mapping[str, Any], code: str) -> None:
    require(
        actual.get("path") == expected.get("path")
        and actual.get("size_bytes") == expected.get("size_bytes")
        and actual.get("sha256") == expected.get("sha256"),
        code,
    )


def load_json_bound(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    before = identity(path)
    try:
        data = path.read_bytes()
        value = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LockBuildError(f"JSON_READ_FAILED:{path}:{type(error).__name__}:{error}") from error
    require(isinstance(value, dict), f"JSON_ROOT_NOT_OBJECT:{path}")
    after = identity(path)
    require(before == after, f"JSON_CHANGED_DURING_READ:{path}")
    require(hashlib.sha256(data).hexdigest() == after["sha256"], f"JSON_HASH_MISMATCH:{path}")
    return value, after


def canonical_directory(path: Path, context: str) -> None:
    require(path.exists() and not path.is_symlink(), f"DIRECTORY_NOT_CANONICAL:{context}:{path}")
    require(path.is_dir(), f"DIRECTORY_NOT_CANONICAL:{context}:{path}")
    require(path.resolve(strict=True) == path.absolute(), f"DIRECTORY_RESOLVES_ELSEWHERE:{context}:{path}")


def resolve_frontend_input_key(stage: str, recorded_key: str) -> Path:
    require(
        isinstance(recorded_key, str) and recorded_key and "\x00" not in recorded_key,
        f"FRONTEND_INPUT_KEY:{stage}",
    )
    recorded_path = Path(recorded_key)
    if recorded_path.is_absolute():
        require(recorded_key == str(recorded_path), f"FRONTEND_INPUT_ABSOLUTE_GRAMMAR:{stage}")
        resolved = recorded_path.absolute()
    else:
        require(recorded_key == recorded_path.as_posix(), f"FRONTEND_INPUT_RELATIVE_GRAMMAR:{stage}")
        require(
            recorded_path.parts
            and all(part not in {"", ".", ".."} for part in recorded_path.parts),
            f"FRONTEND_INPUT_RELATIVE_TRAVERSAL:{stage}:{recorded_key}",
        )
        resolved = (ROOT / recorded_path).absolute()
        require(
            os.path.commonpath((str(resolved), str(ROOT))) == str(ROOT),
            f"FRONTEND_INPUT_RELATIVE_ESCAPE:{stage}:{recorded_key}",
        )
    try:
        canonical = resolved.resolve(strict=True)
    except OSError as error:
        raise LockBuildError(
            f"FRONTEND_INPUT_RESOLVE_FAILED:{stage}:{recorded_key}:{type(error).__name__}:{error}"
        ) from error
    require(canonical == resolved, f"FRONTEND_INPUT_SYMLINK_OR_ALIAS:{stage}:{recorded_key}")
    return resolved


def validate_recorded_identity(
    actual: Mapping[str, Any], recorded: Any, code: str,
) -> None:
    require(isinstance(recorded, dict), code)
    require_identity_matches(actual, recorded, code)


def validate_recorded_identity_with_path_rewrite(
    actual: Mapping[str, Any], recorded: Any, source_path: Path,
    committed_path: Path, code: str,
) -> None:
    require(isinstance(recorded, dict), code)
    require(
        recorded.get("path") == str(source_path.absolute())
        and actual.get("path") == str(committed_path.absolute())
        and recorded.get("size_bytes") == actual.get("size_bytes")
        and recorded.get("sha256") == actual.get("sha256"),
        code,
    )


def validate_aquafe_v2_claim_commit(
    receipt: Mapping[str, Any], directory: Path,
    claim_identity: Mapping[str, Any],
) -> dict[str, Any]:
    directory = directory.absolute()
    validate_recorded_identity_with_path_rewrite(
        claim_identity,
        receipt.get("claim"),
        AQUA_V2_STAGE / "process_start_claim_v2.json",
        directory / "process_start_claim_v2.json",
        "AQUAFE_V2_RECEIPT_CLAIM_COMMIT_REWRITE",
    )
    directory_info = directory.lstat()
    require(
        stat.S_ISDIR(directory_info.st_mode)
        and not directory.is_symlink()
        and not AQUA_V2_STAGE.exists()
        and not AQUA_V2_STAGE.is_symlink(),
        "AQUAFE_V2_COMMITTED_DIRECTORY_STATE",
    )
    expected_committed = {
        "device": int(directory_info.st_dev),
        "inode": int(directory_info.st_ino),
        "is_symlink": False,
        "path": str(directory),
    }
    commit = receipt.get("commit_invariant")
    symlink_before = commit.get("symlink_before_commit") if isinstance(commit, dict) else None
    require(
        isinstance(commit, dict)
        and set(commit) == {
            "committed_directory", "postcommit_rehash_equal", "symlink_before_commit",
        }
        and commit.get("committed_directory") == expected_committed
        and commit.get("postcommit_rehash_equal") is True
        and isinstance(symlink_before, dict)
        and set(symlink_before) == {
            "canonical", "link_device", "link_inode", "stage_device", "stage_inode", "target",
        }
        and symlink_before.get("canonical") == str(directory)
        and symlink_before.get("target") == str(AQUA_V2_STAGE)
        and symlink_before.get("stage_device") == int(directory_info.st_dev)
        and symlink_before.get("stage_inode") == int(directory_info.st_ino)
        and isinstance(symlink_before.get("link_device"), int)
        and isinstance(symlink_before.get("link_inode"), int)
        and symlink_before["link_inode"] > 0,
        "AQUAFE_V2_COMMIT_INVARIANT",
    )
    return {
        "receipt_precommit_path": str(AQUA_V2_STAGE / "process_start_claim_v2.json"),
        "canonical_postcommit": dict(claim_identity),
        "size_and_sha256_equal_across_path_rewrite": True,
        "committed_directory": expected_committed,
    }


def frontend_storage_binding(directory: Path) -> dict[str, Any]:
    semantics = storage_permission_semantics()
    info = directory.lstat()
    require(int(info.st_dev) == semantics["storage_device"], f"FRONTEND_STORAGE_DEVICE:{directory}")
    return {
        "storage_device": int(info.st_dev),
        "filesystem_type": semantics["filesystem_type"],
        "statfs_magic_hex": semantics["statfs_magic_hex"],
        "observed_mode": semantics["observed_mode"],
        "posix_readonly_enforced": False,
        "mode_0755_has_no_science_execution_semantics": True,
    }


def fuse_projected_file_mode(path: Path, binding: Mapping[str, Any]) -> str:
    info = path.lstat()
    observed = f"{stat.S_IMODE(info.st_mode):04o}"
    require(
        stat.S_ISREG(info.st_mode)
        and not path.is_symlink()
        and int(info.st_dev) == binding.get("storage_device")
        and observed == binding.get("observed_mode") == "0755",
        f"FRONTEND_FUSE_PROJECTED_FILE:{path}:{observed}",
    )
    return observed


def verify_klt_strength_addendum(
    receipt_identity: Mapping[str, Any], artifacts: Mapping[str, Mapping[str, Any]],
    claim_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind the post-hoc KLT evidence without upgrading its old receipt."""
    addendum, addendum_identity = load_json_bound(KLT_STRENGTH_ADDENDUM)
    require(addendum.get("schema_version") == KLT_ADDENDUM_SCHEMA, "KLT_ADDENDUM_SCHEMA")
    require(addendum.get("status") in KLT_ADDENDUM_STATUSES, "KLT_ADDENDUM_STATUS")
    observed_at = addendum.get("observed_at_utc")
    require(isinstance(observed_at, str), "KLT_ADDENDUM_OBSERVED_AT")
    try:
        observed_time = datetime.fromisoformat(observed_at)
    except ValueError as error:
        raise LockBuildError("KLT_ADDENDUM_OBSERVED_AT_GRAMMAR") from error
    require(observed_time.utcoffset() == timezone.utc.utcoffset(observed_time), "KLT_ADDENDUM_NOT_UTC")
    require(addendum.get("limitations") == KLT_ADDENDUM_LIMITATIONS, "KLT_ADDENDUM_LIMITATIONS")
    process_tree = addendum.get("posthoc_process_tree")
    require(
        isinstance(process_tree, dict)
        and process_tree.get("status") == "PASS_POSTHOC_EMPTY_SNAPSHOT"
        and process_tree.get("process_group_empty") is True
        and process_tree.get("owned_descendants_empty") is True
        and process_tree.get("evidence_scope")
        == "POSTHOC_SNAPSHOT_NOT_CONTINUOUS_OWNERSHIP_PROOF",
        "KLT_ADDENDUM_PROCESS_TREE",
    )
    identifiers = process_tree.get("observed_process_identifiers")
    markers = process_tree.get("observed_process_markers")
    require(
        isinstance(identifiers, list)
        and identifiers
        and all(
            isinstance(row, dict)
            and isinstance(row.get("pid"), int)
            and row["pid"] > 0
            and isinstance(row.get("role"), str)
            and row["role"]
            for row in identifiers
        ),
        "KLT_ADDENDUM_PROCESS_IDENTIFIERS",
    )
    require(
        isinstance(markers, list) and markers
        and all(isinstance(value, str) and value for value in markers),
        "KLT_ADDENDUM_PROCESS_MARKERS",
    )
    canonical_info = KLT_DIR.lstat()
    workspace_info = KLT_WORKSPACE.lstat()
    require(stat.S_ISDIR(canonical_info.st_mode), "KLT_ADDENDUM_CANONICAL_KIND")
    require(stat.S_ISLNK(workspace_info.st_mode), "KLT_ADDENDUM_WORKSPACE_KIND")
    require(os.readlink(KLT_WORKSPACE) == str(KLT_DIR), "KLT_ADDENDUM_WORKSPACE_TARGET")
    workspace_target_info = KLT_WORKSPACE.stat()
    require(
        (workspace_target_info.st_dev, workspace_target_info.st_ino)
        == (canonical_info.st_dev, canonical_info.st_ino),
        "KLT_ADDENDUM_WORKSPACE_INODE",
    )
    expected_path_state = {
        "canonical": {
            "path": str(KLT_DIR), "is_real_directory": True,
            "device": int(canonical_info.st_dev), "inode": int(canonical_info.st_ino),
        },
        "workspace": {
            "path": str(KLT_WORKSPACE), "is_symlink": True, "target": str(KLT_DIR),
            "resolves_canonical_inode": True,
        },
    }
    require(addendum.get("path_state") == expected_path_state, "KLT_ADDENDUM_PATH_STATE")
    bindings = addendum.get("bindings")
    expected_bindings = {
        "klt_features": dict(artifacts["features.bag"]),
        "klt_metrics": dict(artifacts["frontend_metrics.csv"]),
        "klt_camera": dict(artifacts["aqualoc_archaeo09_pinhole.yaml"]),
        "klt_claim": dict(claim_identity),
        "klt_receipt": dict(receipt_identity),
        "klt_log": dict(artifacts["supervisor_process.log"]),
    }
    require(bindings == expected_bindings, "KLT_ADDENDUM_BINDINGS")
    rehash = addendum.get("postcommit_external_rehash")
    require(
        isinstance(rehash, dict)
        and set(rehash) == {
            "all_six_rehashed_after_commit", "bindings_sha256",
            "canonical_is_real_directory", "receipt_output_binding_equal",
            "workspace_resolves_canonical_inode",
        }
        and rehash.get("all_six_rehashed_after_commit") is True
        and rehash.get("canonical_is_real_directory") is True
        and rehash.get("receipt_output_binding_equal") is True
        and rehash.get("workspace_resolves_canonical_inode") is True
        and rehash.get("bindings_sha256") == compact_sha256(expected_bindings),
        "KLT_ADDENDUM_EXTERNAL_REHASH",
    )
    return {
        "status": "PASS_KLT_EXECUTION_STRENGTH_NARROWED_AND_EXTERNALLY_VERIFIED",
        "source_status": addendum["status"],
        "addendum": addendum_identity,
        "receipt_and_four_science_outputs_bound": True,
        "old_process_group_waited_to_terminal_treated_as_strong_proof": False,
        "posthoc_snapshot_treated_as_continuous_ownership_proof": False,
        "limitations": KLT_ADDENDUM_LIMITATIONS,
        "bindings_sha256": compact_sha256(expected_bindings),
    }


def load_klt_authority() -> dict[str, Any]:
    stage = "klt"
    spec = FRONTEND_SPECS[stage]
    directory = KLT_DIR.absolute()
    canonical_directory(directory, stage)
    storage_binding = frontend_storage_binding(directory)
    receipt_path = directory / str(spec["receipt"])
    claim_path = directory / str(spec["claim"])
    receipt, receipt_identity = load_json_bound(receipt_path)
    control_modes = {
        "receipt": fuse_projected_file_mode(receipt_path, storage_binding),
        "claim": fuse_projected_file_mode(claim_path, storage_binding),
    }
    require(
        receipt.get("schema_version")
        == "aqua-fe-a09-samehistory-warmstart-frontend-receipt-v1",
        f"FRONTEND_RECEIPT_SCHEMA:{stage}",
    )
    require(receipt.get("status") == "PASS_FRONTEND_STAGE_ACCEPTED", f"FRONTEND_NOT_ACCEPTED:{stage}")
    require(receipt.get("stage") == stage, f"FRONTEND_STAGE_MISMATCH:{stage}")
    terminal = receipt.get("terminal_process")
    require(
        isinstance(terminal, dict)
        and terminal.get("return_code") == 0
        and terminal.get("single_popen") is True,
        f"FRONTEND_TERMINAL_INVALID:{stage}",
    )
    execution = receipt.get("execution_integrity")
    require(
        isinstance(execution, dict)
        and execution.get("no_automatic_retry") is True,
        f"FRONTEND_EXECUTION_INVALID:{stage}",
    )
    # Deliberately do not use process_group_waited_to_terminal as proof that
    # the old producer's full owned process tree was empty.
    before = receipt.get("inputs_before")
    after = receipt.get("inputs_after")
    require(isinstance(before, dict) and before == after and before, f"FRONTEND_INPUT_BINDING:{stage}")
    producer_inputs: dict[str, Any] = {}
    for recorded_key, recorded in sorted(before.items()):
        require(isinstance(recorded_key, str), f"FRONTEND_INPUT_KEY_TYPE:{stage}")
        resolved_path = resolve_frontend_input_key(stage, recorded_key)
        require(isinstance(recorded, dict), f"FRONTEND_INPUT_IDENTITY:{stage}:{recorded_key}")
        actual = identity(resolved_path)
        recorded_identity = dict(recorded)
        # The v1 receipt's one relative producer key records that same relative
        # string in its identity path.  Bind its size/hash to ROOT/key while
        # preserving the exact producer spelling rather than rewriting history.
        require(
            recorded_identity.get("path") == recorded_key,
            f"FRONTEND_INPUT_RECORDED_PATH:{stage}:{recorded_key}",
        )
        require(
            actual["size_bytes"] == recorded_identity.get("size_bytes")
            and actual["sha256"] == recorded_identity.get("sha256"),
            f"FRONTEND_INPUT_CHANGED:{stage}:{recorded_key}",
        )
        producer_inputs[recorded_key] = {
            "recorded_key": recorded_key,
            "resolved_path": str(resolved_path),
            "identity": actual,
        }

    outputs = receipt.get("outputs")
    required_outputs = tuple(spec["required_outputs"])
    require(isinstance(outputs, dict), f"FRONTEND_OUTPUT_MAP:{stage}")
    require(set(outputs) == set(required_outputs), f"FRONTEND_OUTPUT_SET:{stage}")
    artifacts: dict[str, Any] = {}
    artifact_modes: dict[str, str] = {}
    for name in required_outputs:
        recorded = outputs.get(name)
        require(isinstance(recorded, dict), f"FRONTEND_OUTPUT_IDENTITY:{stage}:{name}")
        actual = identity(directory / name)
        require_identity_matches(actual, recorded, f"FRONTEND_OUTPUT_CHANGED:{stage}:{name}")
        artifacts[name] = actual
        artifact_modes[name] = fuse_projected_file_mode(directory / name, storage_binding)
    audit = receipt.get("artifact_audit")
    require(
        isinstance(audit, dict) and audit.get("status") == "PASS_KLT_FRONTEND_AUDIT",
        "KLT_ARTIFACT_AUDIT",
    )
    claim, claim_identity = load_json_bound(claim_path)
    require(
        claim.get("schema_version") == "aqua-fe-a09-frontend-process-start-claim-v1"
        and claim.get("status") == "CLAIMED_BEFORE_SINGLE_POPEN"
        and claim.get("stage") == "klt"
        and claim.get("no_automatic_retry") is True,
        "KLT_CLAIM_CONTRACT",
    )
    require(claim.get("command") == receipt.get("command"), "KLT_CLAIM_COMMAND")
    require(claim.get("environment") == receipt.get("environment"), "KLT_CLAIM_ENVIRONMENT")
    require(claim.get("inputs") == before, "KLT_CLAIM_INPUTS")
    strength = verify_klt_strength_addendum(
        receipt_identity, artifacts, claim_identity,
    )
    return {
        "stage": stage,
        "authority_version": spec["authority_version"],
        "status": "PASS_KLT_V1_ARTIFACT_ACCEPTED_WITH_NARROWED_EXECUTION_AUTHORITY",
        "directory": str(directory),
        "claim": claim_identity,
        "receipt": receipt_identity,
        "artifacts": artifacts,
        "producer_inputs": producer_inputs,
        "artifact_audit_sha256": compact_sha256(audit),
        "command_sha256": compact_sha256(receipt.get("command")),
        "environment_sha256": compact_sha256(receipt.get("environment")),
        "storage_filesystem_binding": storage_binding,
        "artifact_observed_modes": artifact_modes,
        "control_observed_modes": control_modes,
        "execution_strength": strength,
        "causal_lineage": {
            "producer": "a09_samehistory_warmstart_frontend_v1:klt",
            "receipt": receipt_identity,
            "science_outputs": artifacts,
        },
    }


def load_aquafe_v2_authority() -> dict[str, Any]:
    stage = "aquafe"
    spec = FRONTEND_SPECS[stage]
    directory = AQUA_DIR.absolute()
    canonical_directory(directory, stage)
    storage_binding = frontend_storage_binding(directory)
    receipt_path = directory / str(spec["receipt"])
    claim_path = directory / str(spec["claim"])
    receipt, receipt_identity = load_json_bound(receipt_path)
    claim, claim_identity = load_json_bound(claim_path)
    control_modes = {
        "receipt": fuse_projected_file_mode(receipt_path, storage_binding),
        "claim": fuse_projected_file_mode(claim_path, storage_binding),
    }
    producer_lock, producer_lock_identity = load_json_bound(AQUA_V2_EXECUTION_LOCK)
    require(
        producer_lock.get("schema_version") == "aqua-fe-a09-samehistory-warmstart-aquafe-lock-v2"
        and producer_lock.get("status") == "FROZEN_BEFORE_AQUAFE_POPEN"
        and producer_lock.get("stage") == "aquafe",
        "AQUAFE_V2_EXECUTION_LOCK_CONTRACT",
    )
    lock_identities = producer_lock.get("identities")
    require(isinstance(lock_identities, dict) and lock_identities, "AQUAFE_V2_LOCK_IDENTITIES")
    producer_inputs: dict[str, Any] = {}
    for key, recorded in sorted(lock_identities.items()):
        require(isinstance(recorded, dict), f"AQUAFE_V2_LOCK_IDENTITY:{key}")
        raw_path = recorded.get("path")
        require(isinstance(raw_path, str) and Path(raw_path).is_absolute(), f"AQUAFE_V2_LOCK_PATH:{key}")
        actual = identity(Path(raw_path))
        require_identity_matches(actual, recorded, f"AQUAFE_V2_LOCK_INPUT_CHANGED:{key}")
        producer_inputs[key] = actual
    for key, expected_path in (
        ("runner", AQUA_V2_RUNNER),
        ("builder", AQUA_V2_BUILDER),
        ("protocol", AQUA_V2_PROTOCOL),
        ("klt_execution_strength_addendum", KLT_STRENGTH_ADDENDUM),
    ):
        recorded = producer_inputs.get(key)
        require(
            isinstance(recorded, dict) and recorded.get("path") == str(expected_path),
            f"AQUAFE_V2_PRODUCER_PATH:{key}",
        )
    require(
        claim.get("schema_version") == "aqua-fe-a09-samehistory-warmstart-aquafe-supervisor-v2"
        and claim.get("status") == "CLAIMED_BEFORE_SINGLE_POPEN"
        and claim.get("stage") == "aquafe"
        and claim.get("launch_allowance_consumed") is True
        and claim.get("popen_invocation_count_at_claim") == 0
        and claim.get("retry_count") == 0
        and claim.get("no_automatic_retry") is True,
        "AQUAFE_V2_CLAIM_CONTRACT",
    )
    validate_recorded_identity(
        producer_lock_identity, claim.get("execution_lock"), "AQUAFE_V2_CLAIM_LOCK_BINDING",
    )
    require(
        receipt.get("schema_version") == "aqua-fe-a09-samehistory-warmstart-aquafe-supervisor-v2"
        and receipt.get("status") == "PASS_AQUAFE_V2_ACCEPTED"
        and receipt.get("stage") == "aquafe"
        and receipt.get("launch_allowance_consumed") is True
        and receipt.get("no_automatic_retry") is True,
        "AQUAFE_V2_RECEIPT_CONTRACT",
    )
    validate_recorded_identity(
        producer_lock_identity, receipt.get("execution_lock"), "AQUAFE_V2_RECEIPT_LOCK_BINDING",
    )
    claim_commit_binding = validate_aquafe_v2_claim_commit(
        receipt, directory, claim_identity,
    )
    terminal = receipt.get("terminal_process")
    require(
        isinstance(terminal, dict)
        and terminal.get("popen_invocation_count") == 1
        and terminal.get("child_started") is True
        and terminal.get("raw_return_code") == 0
        and terminal.get("timed_out") is False,
        "AQUAFE_V2_TERMINAL",
    )
    process_group = terminal.get("process_group")
    require(
        isinstance(process_group, dict)
        and all(
            process_group.get(key) is True
            for key in ("leader_reaped", "process_group_empty", "owned_descendants_empty")
        ),
        "AQUAFE_V2_PROCESS_TREE",
    )
    execution = receipt.get("execution_integrity")
    require(
        isinstance(execution, dict)
        and execution.get("status") == "PASS"
        and execution.get("process_group_empty") is True
        and execution.get("owned_descendants_empty") is True
        and execution.get("authority_before_after_equal") is True,
        "AQUAFE_V2_EXECUTION_INTEGRITY",
    )
    audit = receipt.get("artifact_audit")
    require(
        isinstance(audit, dict) and audit.get("status") == "PASS_STRICT_AQUAFE_ARTIFACT_AUDIT",
        "AQUAFE_V2_ARTIFACT_AUDIT",
    )
    outputs = receipt.get("outputs_postcommit")
    expected_postcommit_names = {
        "full_merged.bag", "sidecar.bag", "stats.csv",
        "process_start_claim_v2.json", "supervisor_process.log",
    }
    require(isinstance(outputs, dict) and set(outputs) == expected_postcommit_names, "AQUAFE_V2_OUTPUT_SET")
    postcommit: dict[str, Any] = {}
    postcommit_modes: dict[str, str] = {}
    for name in sorted(expected_postcommit_names):
        actual = identity(directory / name)
        validate_recorded_identity(actual, outputs.get(name), f"AQUAFE_V2_OUTPUT_CHANGED:{name}")
        postcommit[name] = actual
        postcommit_modes[name] = fuse_projected_file_mode(directory / name, storage_binding)
    require(postcommit["process_start_claim_v2.json"] == claim_identity, "AQUAFE_V2_OUTPUT_CLAIM")
    expected_tree = expected_postcommit_names | {"formal_run_receipt_v2.json"}
    require(
        {path.name for path in directory.iterdir()} == expected_tree
        and all(path.is_file() and not path.is_symlink() for path in directory.iterdir()),
        "AQUAFE_V2_EXACT_TREE",
    )
    artifacts = {
        name: postcommit[name]
        for name in ("full_merged.bag", "sidecar.bag", "stats.csv", "supervisor_process.log")
    }
    return {
        "stage": stage,
        "authority_version": spec["authority_version"],
        "status": "PASS_AQUAFE_V2_ACCEPTED_AND_EXTERNALLY_REHASHED",
        "directory": str(directory),
        "execution_lock": producer_lock_identity,
        "claim": claim_identity,
        "claim_commit_binding": claim_commit_binding,
        "receipt": receipt_identity,
        "artifacts": artifacts,
        "outputs_postcommit": postcommit,
        "producer_inputs": producer_inputs,
        "execution_integrity_sha256": compact_sha256(execution),
        "artifact_audit_sha256": compact_sha256(audit),
        "storage_filesystem_binding": storage_binding,
        "outputs_postcommit_observed_modes": postcommit_modes,
        "control_observed_modes": control_modes,
        "causal_lineage": {
            "producer": "a09_samehistory_warmstart_aquafe_supervisor_v2",
            "execution_lock": producer_lock_identity,
            "claim": claim_identity,
            "receipt": receipt_identity,
            "science_outputs": artifacts,
        },
    }


def load_frontend_authority(stage: str) -> dict[str, Any]:
    require(stage in FRONTEND_SPECS, f"UNKNOWN_FRONTEND_STAGE:{stage}")
    if stage == "klt":
        return load_klt_authority()
    return load_aquafe_v2_authority()


def current_namespace(kind: str) -> str:
    require(kind in {"net", "user"}, f"NAMESPACE_KIND:{kind}")
    try:
        value = os.readlink(f"/proc/self/ns/{kind}")
    except OSError as error:
        raise LockBuildError(f"NAMESPACE_READ_FAILED:{kind}:{error}") from error
    require(re.fullmatch(rf"{kind}:\[[0-9]+\]", value) is not None, f"NAMESPACE_FORMAT:{kind}:{value}")
    return value


def expected_policy(host_net: str, host_user: str) -> dict[str, Any]:
    return {
        "item_order": list(ITEM_ORDER),
        "serial_execution": True,
        "one_process_launch_per_item": True,
        "result_informed_retry": False,
        "prior_item_must_have_independently_validated_accepted_receipt": True,
        "later_items_must_have_no_claim_or_receipt": True,
        "failed_or_unusable_item_permanently_blocks_later_items": True,
        "machine_exclusive_cpu_scheduling": False,
        "development_only": True,
        "formal_paper_accuracy_evidence_permitted": False,
        "global_backend_flock": str(BACKEND_FLOCK),
        "required_frontend_flock": str(FRONTEND_FLOCK),
        "large_artifact_root": str(EXP_ROOT),
        "runtime_artifact_root": str(EXP_ROOT / "runtime"),
        "cwd": str(ROOT),
        "base_environment": dict(BASE_ENVIRONMENT),
        "host_namespace_identity": {"network": host_net, "user": host_user},
        "network_isolation": {
            "policy": "loopback_only_network_namespace",
            "formal_port": 11981,
            "fresh_user_and_network_namespace_per_backend": True,
            "machine_exclusive_cpu_scheduling": False,
        },
        "host_ambient_process_policy": {
            "nonblocking_roles": ["ambient_standalone_rosout", "ambient_todesk"],
            "record_pid_start_ticks_role_and_argv_digest": True,
            "before_after_population_equality_required": False,
            "justification": "fresh_loopback_only_user_and_network_namespace",
            "runtime_or_throughput_claim_permitted": False,
        },
        "storage_permission_semantics": storage_permission_semantics(),
        "output_commit": {
            "mode": "sealed_in_place",
            "reason": "namespace_adapter_requires_canonical_real_output_directory",
            "workspace_symlink_target_and_inode_guarded": True,
            "requested_mode": "0444",
            "observed_mode": "0755",
            "posix_readonly_enforced": False,
            "permission_bits_are_integrity_basis": False,
            "file_and_directory_fsync_required": True,
            "science_snapshot_before_receipt": True,
            "atomic_receipt_then_exact_tree_and_full_rehash": True,
        },
        "python3_symlink": {"path": "/usr/bin/python3", "target": "python3.8"},
        "ros_profile_directory": str(ROS_PROFILE_DIR),
        "ros_profile_exact_names": list(ROS_HOOK_NAMES),
        "workspace_profile_directories_required_absent": [
            str(path) for path in ABSENT_WORKSPACE_PROFILE_DIRS
        ],
        "score_usability": {
            "score_start_ns": 1_542_888_946_038_630_384,
            "score_end_ns": 1_542_888_966_034_698_672,
            "crop_interval": "inclusive",
            "minimum_score_trajectory_rows": 2,
            "minimum_score_temporal_span_coverage": 0.70,
            "maximum_score_output_gap_s": 0.50,
            "require_initialization_before_or_within_score_end": True,
            "maximum_score_failure_mentions": 0,
            "maximum_score_restart_or_reset_events": 0,
            "unresolved_score_log_event_attribution_is_failure": True,
        },
        "formal_ape_gate": {
            "minimum_native_reference_poses": 30,
            "available_native_reference_poses": 21,
            "status": "CLOSED_BY_CONSTRUCTION",
        },
    }


def item_environment(item_id: str) -> dict[str, str]:
    spec = ARM_SPECS[item_id]
    result = dict(COMMON_ITEM_ENVIRONMENT)
    result.update(
        {
            "TAG": spec["tag"],
            "ROS_HOME": str(EXP_ROOT / "runtime" / item_id / "ros_home"),
            "ROS_LOG_DIR": str(EXP_ROOT / "runtime" / item_id / "ros_log"),
        }
    )
    if "feature_bag" in spec:
        result["FEATURE_BAG_OVERRIDE"] = spec["feature_bag"]
    return result


def build_items(host_net: str, host_user: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item_id in ITEM_ORDER:
        spec = ARM_SPECS[item_id]
        output_dir = EXP_ROOT / "backends" / item_id
        workspace_link = ROOT / "logs/aqualoc_archaeo_vins" / spec["run_leaf"]
        inner = [
            "/usr/bin/bash",
            str(BACKEND_SHELL),
            spec["mode"],
            "9",
            "0",
            "4400",
            spec["method"],
            spec["every_n"],
        ]
        argv = [
            "/usr/bin/unshare",
            "--user",
            "--map-root-user",
            "--net",
            "/usr/bin/python3.8",
            str(NETNS_ENTRY),
            "--output-dir",
            str(output_dir),
            "--formal-port",
            "11981",
            "--host-network-namespace",
            host_net,
            "--host-user-namespace",
            host_user,
            "--",
            *inner,
        ]
        environment = item_environment(item_id)
        outputs = [
            "vins_output/vio.csv",
            "vins.log",
            "ape.txt",
            "replay_manifest.txt",
            spec["config_name"],
            "aqualoc_archaeo09_pinhole.yaml",
            "vins_env_manifest.txt",
            "roscore.log",
            "network_namespace_manifest.json",
        ]
        if item_id == "klt_external_feature_context":
            outputs.append("frontend_metrics.csv")
        if item_id == "vanilla_origin_native_image_context":
            causal_lineage = {
                "upstream_authority": "raw_materialization_v1",
                "upstream_artifact": str(RAW_BAG),
                "ingestion_context": "native_image_plus_imu_plus_ground_truth",
            }
        else:
            frontend_stage = (
                "klt" if item_id == "klt_external_feature_context" else "aquafe"
            )
            causal_lineage = {
                "upstream_authority": f"frontend_authorities.{frontend_stage}",
                "upstream_artifact": spec["feature_bag"],
                "ingestion_context": "external_feature_plus_imu_plus_ground_truth",
            }
        result[item_id] = {
            "item_id": item_id,
            "kind": "backend_replay",
            "output_dir": str(output_dir),
            "workspace_link": str(workspace_link),
            "argv": argv,
            "inner_backend_argv_sha256": compact_sha256(inner),
            "env": environment,
            "command_contract": {
                "cwd": str(ROOT),
                "argv_sha256": compact_sha256(argv),
                "env_sha256": compact_sha256(environment),
            },
            "timeout_seconds": 900,
            "expected_outputs": outputs,
            "generated_config": {
                "path": spec["config_name"],
                "size_bytes": int(spec["config_size"]),
                "sha256": spec["config_sha256"],
            },
            "camera_config": {
                "path": "aqualoc_archaeo09_pinhole.yaml",
                **CAMERA_CONFIG_IDENTITY,
            },
            "replay_contract": {
                "run_dir": str(workspace_link),
                "raw_bag": str(RAW_BAG),
                "play_bag": (
                    str(RAW_BAG)
                    if item_id == "vanilla_origin_native_image_context"
                    else spec["feature_bag"]
                ),
                "vins_csv": str(workspace_link / "vins_output/vio.csv"),
            },
            "input_binding": (
                {"kind": "raw", "stage": "raw", "artifact": str(RAW_BAG)}
                if item_id == "vanilla_origin_native_image_context"
                else {
                    "kind": "external_feature",
                    "stage": (
                        "klt" if item_id == "klt_external_feature_context" else "aquafe"
                    ),
                    "artifact": spec["feature_bag"],
                }
            ),
            "causal_lineage": causal_lineage,
        }
    return result


def validate_dynamic_setup_inputs() -> None:
    canonical_directory(ROS_PROFILE_DIR, "ros-profile")
    names = sorted(entry.name for entry in ROS_PROFILE_DIR.iterdir())
    require(names == sorted(ROS_HOOK_NAMES), f"ROS_PROFILE_MEMBERSHIP:{names}")
    for path in ABSENT_WORKSPACE_PROFILE_DIRS:
        require(not path.exists() and not path.is_symlink(), f"WORKSPACE_PROFILE_PRESENT:{path}")
    python_link = Path("/usr/bin/python3")
    require(python_link.is_symlink(), "PYTHON3_NOT_SYMLINK")
    require(os.readlink(python_link) == "python3.8", "PYTHON3_SYMLINK_TARGET")


def collect_static_identities() -> dict[str, Any]:
    validate_dynamic_setup_inputs()
    values = {key: identity(path) for key, path in STATIC_IDENTITY_PATHS.items()}
    for key, expected in EXPECTED_FIXED.items():
        actual = values[key]
        require(
            (actual["size_bytes"], actual["sha256"]) == expected,
            f"EXPECTED_FIXED_IDENTITY_DRIFT:{key}",
        )
    for index, name in enumerate(ROS_HOOK_NAMES):
        values[f"ros_environment_hook_{index:02d}"] = identity(ROS_PROFILE_DIR / name)
    return values


def contract_sha256(
    policy: Mapping[str, Any], items: Mapping[str, Any],
    identities: Mapping[str, Any], frontends: Mapping[str, Any],
) -> str:
    return compact_sha256(
        {
            "policy": policy,
            "items": items,
            "identities": identities,
            "frontend_authorities": frontends,
        }
    )


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_publish(path: Path, value: Mapping[str, Any]) -> None:
    path = path.absolute()
    require(not path.exists() and not path.is_symlink(), f"FINAL_PATH_EXISTS:{path}")
    data = canonical_bytes(value)
    temp = path.parent / f".{path.name}.tmp.{os.getpid()}.{secrets.token_hex(8)}"
    descriptor = os.open(
        temp,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        offset = 0
        while offset < len(data):
            written = os.write(descriptor, data[offset:])
            require(written > 0, "ATOMIC_WRITE_NO_PROGRESS")
            offset += written
        os.fchmod(descriptor, 0o444)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.link(temp, path, follow_symlinks=False)
        fsync_directory(path.parent)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
        fsync_directory(path.parent)


@contextmanager
def frontend_lock() -> Iterator[None]:
    regular_file(FRONTEND_FLOCK, "frontend-flock")
    descriptor = os.open(FRONTEND_FLOCK, os.O_RDWR | os.O_CLOEXEC)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise LockBuildError("FRONTEND_STAGE_STILL_RUNNING") from error
        yield
    finally:
        os.close(descriptor)


def build_lock() -> dict[str, Any]:
    with frontend_lock():
        host_net = current_namespace("net")
        host_user = current_namespace("user")
        policy = expected_policy(host_net, host_user)
        items = build_items(host_net, host_user)
        frontends = {
            "klt": load_frontend_authority("klt"),
            "aquafe": load_frontend_authority("aquafe"),
        }
        identities = collect_static_identities()
        value: dict[str, Any] = {
            "schema_version": SCHEMA,
            "status": "FROZEN_BEFORE_BACKEND_LAUNCH",
            "created_at_local": datetime.now().astimezone().isoformat(),
            "evidence_scope": {
                "development_only": True,
                "machine_exclusive_cpu_scheduling": False,
                "formal_paper_accuracy_evidence_permitted": False,
                "formal_ape_gate": "CLOSED_BY_CONSTRUCTION",
            },
            "policy": policy,
            "items": items,
            "frontend_authorities": frontends,
            "identities": identities,
        }
        value["contract_sha256"] = contract_sha256(policy, items, identities, frontends)
        return value


def preflight() -> dict[str, Any]:
    with frontend_lock():
        host_net = current_namespace("net")
        host_user = current_namespace("user")
        frontends = {
            "klt": load_frontend_authority("klt"),
            "aquafe": load_frontend_authority("aquafe"),
        }
        identities = collect_static_identities()
        policy = expected_policy(host_net, host_user)
        items = build_items(host_net, host_user)
        return {
            "status": "READY_TO_BUILD_BACKEND_LOCK",
            "lock_path": str(LOCK_PATH),
            "host_namespaces": {"network": host_net, "user": host_user},
            "frontend_authorities": frontends,
            "static_identity_count": len(identities),
            "contract_sha256": contract_sha256(policy, items, identities, frontends),
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("preflight")
    build = commands.add_parser("build")
    build.add_argument("--authorization-token", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status":
        state = "PRESENT" if LOCK_PATH.exists() or LOCK_PATH.is_symlink() else "ABSENT"
        print(json.dumps({"lock_path": str(LOCK_PATH), "status": state}, indent=2))
        return 0
    if args.command == "preflight":
        print(json.dumps(preflight(), indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    require(args.authorization_token == AUTHORIZATION_TOKEN, "AUTHORIZATION_TOKEN_MISMATCH")
    require(not LOCK_PATH.exists() and not LOCK_PATH.is_symlink(), "LOCK_ALREADY_EXISTS")
    value = build_lock()
    atomic_publish(LOCK_PATH, value)
    print(
        json.dumps(
            {
                "status": value["status"],
                "lock": identity(LOCK_PATH),
                "contract_sha256": value["contract_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (LockBuildError, OSError, ValueError) as error:
        print(f"A09_BACKEND_LOCK_ERROR:{type(error).__name__}:{error}", file=os.sys.stderr)
        raise SystemExit(2)
