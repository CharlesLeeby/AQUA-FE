#!/usr/bin/env python3
"""Build, but never publish over, the A10 v4 backend-recovery lock.

V4 is deliberately backend-only. It launches three new VINS-Fusion attempts
inside fresh loopback-only user/network namespaces and consumes only the raw
input audited in v1 plus the two frontend artifacts accepted by the immutable
v3 receipts. It neither retries the failed v3 Vanilla attempt nor consumes the
two unlaunched v3 backend allowances.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
EXP = Path(
    "/mnt/data/AQUA-FE_WS/experiments/"
    "a10_samehistory_system_v4_backend_recovery"
)
V3_EXP = Path(
    "/mnt/data/AQUA-FE_WS/experiments/"
    "a10_samehistory_system_v3_recovery"
)
RAW = Path(
    "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v1/raw/"
    "archaeo10_0000_2800.bag"
)
RAW_AUDIT = ROOT / "papers/samehistory_system_comparison_a10_finalonline_v1_raw_audit.json"
V3_LOCK = ROOT / (
    "papers/samehistory_system_comparison_a10_finalonline_"
    "v3_recovery_execution_lock.json"
)
PROTOCOL = ROOT / (
    "papers/samehistory_system_comparison_a10_finalonline_"
    "v4_backend_recovery_protocol.md"
)
DEFAULT_OUTPUT = ROOT / (
    "papers/samehistory_system_comparison_a10_finalonline_"
    "v4_backend_recovery_execution_lock.candidate.json"
)

V3_KLT = V3_EXP / "frontends/klt_input_adoption"
V3_AQUA = V3_EXP / "frontends/aquafe_finalonline"
V3_FAILED_VANILLA = V3_EXP / "backends/vanilla_origin_native_image_context"
V3_KLT_RECEIPT = V3_KLT / "formal_run_receipt_v3.json"
V3_AQUA_RECEIPT = V3_AQUA / "formal_run_receipt_v3.json"
V3_FAILED_VANILLA_RECEIPT = V3_FAILED_VANILLA / "formal_run_receipt_v3.json"
V3_PENDING_BACKEND_GUARDS = {
    "external_klt_finalonline_backbone": {
        "output_dir": V3_EXP / "backends/external_klt_finalonline_backbone",
        "claim_path": V3_EXP / (
            "backends/external_klt_finalonline_backbone/process_start_claim.json"
        ),
        "receipt_path": V3_EXP / (
            "backends/external_klt_finalonline_backbone/formal_run_receipt_v3.json"
        ),
    },
    "aquafe_finalonline_xfeat_lineage": {
        "output_dir": V3_EXP / "backends/aquafe_finalonline_xfeat_lineage",
        "claim_path": V3_EXP / (
            "backends/aquafe_finalonline_xfeat_lineage/process_start_claim.json"
        ),
        "receipt_path": V3_EXP / (
            "backends/aquafe_finalonline_xfeat_lineage/formal_run_receipt_v3.json"
        ),
    },
}
V3_PENDING_REQUIRED_ABSENCE_PHASES = (
    "lock_build",
    "lock_verification",
    "before_claim",
    "after_claim_before_popen",
    "postflight",
)
CATKIN_MARKERS = {
    "ros_catkin_marker": Path("/opt/ros/noetic/.catkin"),
    "vins_catkin_marker": Path("/home/ma/SLAM/VINS-Fusion-origin/devel/.catkin"),
    "dave_catkin_marker": Path("/home/ma/dave_ws/devel/.catkin"),
    "uuv_catkin_marker": Path("/home/ma/uuv_ws/devel/.catkin"),
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
    Path("/home/ma/SLAM/VINS-Fusion-origin/devel/etc/catkin/profile.d"),
    Path("/home/ma/dave_ws/devel/etc/catkin/profile.d"),
    Path("/home/ma/uuv_ws/devel/etc/catkin/profile.d"),
)
PYTHON3_SYMLINK = Path("/usr/bin/python3")
PYTHON3_SYMLINK_TARGET = "python3.8"

RUNNER = ROOT / "scripts/run_aqualoc_archaeo_vins_eval_v4_backend_recovery.sh"
NETNS_ENTRY = ROOT / "scripts/enter_samehistory_backend_netns_v4.py"
FORMAL_PORT = 11981
SCORE_START_NS = 1542888916043622160
SCORE_END_NS = 1542888936039921424

APE_KEYS = [
    "matched", "duration_s", "max_timestamp_error_s", "se3_ape_rmse_m",
    "se3_ape_median_m", "se3_ape_max_m", "rpe_delta_s", "rpe_pairs",
    "rpe_trans_rmse_m", "rpe_trans_median_m", "rpe_trans_max_m",
    "output_poses", "output_duration_s", "expected_duration_s",
    "output_coverage_ratio", "first_output_delay_s", "last_output_drop_s",
    "median_output_dt_s", "max_output_gap_s", "large_output_gap_count",
    "init_success", "tracking_lost_count_proxy", "log_linear_solver_failures",
    "log_failure_mentions", "log_restart_mentions", "log_waiting_mentions",
]
APE_INTEGER_KEYS = [
    "matched", "rpe_pairs", "output_poses", "large_output_gap_count",
    "init_success", "tracking_lost_count_proxy", "log_linear_solver_failures",
    "log_failure_mentions", "log_restart_mentions", "log_waiting_mentions",
]

ITEM_ORDER = (
    "vanilla_origin_native_image_context",
    "klt_external_feature_context",
    "aquafe_external_feature_context",
)
WORKSPACE_LINKS = {
    "vanilla_origin_native_image_context": ROOT / (
        "logs/aqualoc_archaeo_vins/"
        "origin_klt_every1_systemfair_a10_finalonline_v4_backend_recovery_"
        "feed0000_2800_score2400_2800_vanilla_origin"
    ),
    "klt_external_feature_context": ROOT / (
        "logs/aqualoc_archaeo_vins/"
        "external_klt_every2_systemfair_a10_finalonline_v4_backend_recovery_"
        "feed0000_2800_score2400_2800_external_klt"
    ),
    "aquafe_external_feature_context": ROOT / (
        "logs/aqualoc_archaeo_vins/"
        "external_hybrid_xfeat_every2_systemfair_a10_finalonline_"
        "v4_backend_recovery_feed0000_2800_score2400_2800_"
        "aquafe_finalonline_xfeat_lineage"
    ),
}


def compact_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def command_contract(argv: list[str], env: Mapping[str, str]) -> dict[str, str]:
    return {
        "cwd": str(ROOT),
        "argv_sha256": compact_json_sha256(argv),
        "env_sha256": compact_json_sha256(dict(env)),
    }


def write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("short write while publishing execution-lock candidate")
        offset += written


def identity(path: Path) -> dict[str, Any]:
    canonical = path.absolute().resolve(strict=True)
    observed = canonical.lstat()
    if not stat.S_ISREG(observed.st_mode):
        raise RuntimeError(f"identity is not a regular file: {canonical}")
    digest = hashlib.sha256()
    with canonical.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "path": str(canonical),
        "size_bytes": observed.st_size,
        "sha256": digest.hexdigest(),
    }


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON root is not an object: {path}")
    return value


def identity_claim_equal(actual: Mapping[str, Any], claim: Any) -> bool:
    return isinstance(claim, dict) and all(
        claim.get(key) == actual.get(key) for key in ("path", "size_bytes", "sha256")
    )


def validate_accepted_v3_receipt(
    receipt_path: Path, *, item_id: str, artifacts: list[Path]
) -> None:
    receipt = read_json(receipt_path)
    terminal = receipt.get("terminal_process")
    artifact_contract = receipt.get("artifact_contract")
    integrity = receipt.get("execution_integrity")
    if not (
        receipt.get("schema_version")
        == "aqua-fe-a10-samehistory-finalonline-supervisor-v3"
        and receipt.get("item_id") == item_id
        and receipt.get("launch_allowance_consumed") is True
        and receipt.get("status") == "TERMINAL_PROCESS_RC0"
        and receipt.get("overall_disposition") == "ACCEPTED"
        and isinstance(terminal, dict)
        and terminal.get("raw_return_code") == 0
        and terminal.get("status") == "TERMINAL_PROCESS_RC0"
        and terminal.get("timed_out") is False
        and terminal.get("popen_invocation_count") == 1
        and isinstance(artifact_contract, dict)
        and artifact_contract.get("status") == "PASS"
        and isinstance(integrity, dict)
        and integrity.get("status") == "PASS"
        and isinstance(integrity.get("postflight"), dict)
        and integrity["postflight"].get("status") == "PASS"
    ):
        raise RuntimeError(f"v3 source receipt is not accepted: {receipt_path}")
    if not identity_claim_equal(identity(V3_LOCK), receipt.get("execution_lock")):
        raise RuntimeError(f"v3 receipt lock binding mismatch: {receipt_path}")
    for key, actual_path in (
        ("claim", receipt_path.parent / "process_start_claim.json"),
        ("process_log", receipt_path.parent / "supervisor_process.log"),
    ):
        if not identity_claim_equal(identity(actual_path), receipt.get(key)):
            raise RuntimeError(f"v3 receipt {key} binding mismatch: {receipt_path}")
    outputs = artifact_contract.get("outputs")
    if not isinstance(outputs, dict):
        raise RuntimeError(f"v3 receipt lacks artifact output identities: {receipt_path}")
    for artifact in artifacts:
        actual = identity(artifact)
        if not identity_claim_equal(actual, outputs.get(str(artifact))):
            raise RuntimeError(
                f"v3 accepted receipt does not bind source artifact: {artifact}"
            )


def validate_failed_v3_vanilla_receipt() -> None:
    receipt = read_json(V3_FAILED_VANILLA_RECEIPT)
    terminal = receipt.get("terminal_process")
    artifact_contract = receipt.get("artifact_contract")
    integrity = receipt.get("execution_integrity")
    if not (
        receipt.get("schema_version")
        == "aqua-fe-a10-samehistory-finalonline-supervisor-v3"
        and receipt.get("item_id") == "vanilla_origin_native_image_context"
        and receipt.get("launch_allowance_consumed") is True
        and receipt.get("status") == "TERMINAL_PROCESS_FAILED"
        and receipt.get("overall_disposition") == "PROCESS_FAILED"
        and isinstance(terminal, dict)
        and terminal.get("raw_return_code") == -9
        and terminal.get("status") == "TERMINAL_PROCESS_FAILED"
        and terminal.get("timed_out") is True
        and terminal.get("popen_invocation_count") == 1
        and isinstance(artifact_contract, dict)
        and artifact_contract.get("status") == "FAIL"
        and isinstance(integrity, dict)
        and integrity.get("status") == "FAIL"
    ):
        raise RuntimeError("the immutable v3 Vanilla failure provenance drifted")
    if not identity_claim_equal(identity(V3_LOCK), receipt.get("execution_lock")):
        raise RuntimeError("the failed v3 Vanilla receipt lock binding drifted")
    for key, actual_path in (
        ("claim", V3_FAILED_VANILLA / "process_start_claim.json"),
        ("process_log", V3_FAILED_VANILLA / "supervisor_process.log"),
    ):
        if not identity_claim_equal(identity(actual_path), receipt.get(key)):
            raise RuntimeError(f"the failed v3 Vanilla {key} binding drifted")


def v3_pending_allowance_guard_contract() -> dict[str, Any]:
    return {
        "required_state": "CLAIM_AND_RECEIPT_ABSENT",
        "required_absence_phases": list(V3_PENDING_REQUIRED_ABSENCE_PHASES),
        "items": {
            item_id: {
                role: str(path)
                for role, path in paths.items()
            }
            for item_id, paths in V3_PENDING_BACKEND_GUARDS.items()
        },
    }


def open_real_directory(path: Path) -> int:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            observed = os.lstat(current)
        except FileNotFoundError as error:
            raise RuntimeError(f"directory component is missing: {current}") from error
        if stat.S_ISLNK(observed.st_mode):
            raise RuntimeError(f"directory component is a symlink: {current}")
    try:
        descriptor = os.open(
            absolute,
            os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as error:
        raise RuntimeError(f"cannot open real directory: {absolute}:{error}") from error
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise RuntimeError(f"path is not a directory: {absolute}")
    return descriptor


def catkin_setup_dynamic_input_contract() -> dict[str, Any]:
    return {
        "catkin_marker_identity_keys": list(CATKIN_MARKERS),
        "ros_profile_directory": str(ROS_PROFILE_DIR),
        "ros_profile_exact_entries": [
            {
                "name": name,
                "identity_key": f"ros_environment_hook_{index:02d}",
            }
            for index, name in enumerate(ROS_HOOK_NAMES)
        ],
        "workspace_profile_directories_required_absent": [
            str(path) for path in ABSENT_WORKSPACE_PROFILE_DIRS
        ],
        "python3_symlink": {
            "path": str(PYTHON3_SYMLINK),
            "required_target": PYTHON3_SYMLINK_TARGET,
            "canonical_identity_key": "python3_8",
        },
    }


def validate_catkin_setup_dynamic_inputs() -> None:
    for key, path in CATKIN_MARKERS.items():
        try:
            identity(path)
        except (OSError, RuntimeError) as error:
            raise RuntimeError(f"catkin marker invalid: {key}:{path}:{error}") from error
    descriptor = open_real_directory(ROS_PROFILE_DIR)
    try:
        observed_names = tuple(sorted(os.listdir(descriptor)))
        if observed_names != ROS_HOOK_NAMES:
            raise RuntimeError(
                f"ROS profile.d membership drifted: {observed_names!r}"
            )
        for name in observed_names:
            observed = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if not stat.S_ISREG(observed.st_mode):
                raise RuntimeError(f"ROS environment hook is not regular: {name}")
    finally:
        os.close(descriptor)
    for path in ABSENT_WORKSPACE_PROFILE_DIRS:
        try:
            os.lstat(path)
        except FileNotFoundError:
            continue
        raise RuntimeError(f"workspace profile.d must remain absent: {path}")
    observed_link = os.lstat(PYTHON3_SYMLINK)
    if not stat.S_ISLNK(observed_link.st_mode):
        raise RuntimeError(f"python3 path is not a symlink: {PYTHON3_SYMLINK}")
    if os.readlink(PYTHON3_SYMLINK) != PYTHON3_SYMLINK_TARGET:
        raise RuntimeError(f"python3 symlink target drifted: {PYTHON3_SYMLINK}")
    if PYTHON3_SYMLINK.resolve(strict=True) != Path("/usr/bin/python3.8"):
        raise RuntimeError("python3 canonical interpreter drifted")


def validate_v3_pending_backend_allowances_unconsumed() -> None:
    v3_lock = read_json(V3_LOCK)
    v3_items = v3_lock.get("items")
    if not isinstance(v3_items, dict):
        raise RuntimeError("v3 execution lock item map is invalid")
    for item_id, paths in V3_PENDING_BACKEND_GUARDS.items():
        output_dir = paths["output_dir"]
        item = v3_items.get(item_id)
        if not isinstance(item, dict) or item.get("output_dir") != str(output_dir):
            raise RuntimeError(
                f"v3 pending backend output-dir binding drifted: "
                f"{item_id}:{output_dir}"
            )
        descriptor = open_real_directory(output_dir)
        try:
            for role in ("claim_path", "receipt_path"):
                path = paths[role]
                if path.parent != output_dir:
                    raise RuntimeError(
                        f"v3 pending guard leaf parent drifted: {item_id}:{role}:{path}"
                    )
                try:
                    os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                raise RuntimeError(
                    f"v3 pending backend launch allowance was consumed: "
                    f"{item_id}:{role}:{path}"
                )
        finally:
            os.close(descriptor)


def validate_raw_audit() -> None:
    audit = read_json(RAW_AUDIT)
    if not (
        audit.get("schema_version") == "aqua-fe-a10-samehistory-raw-audit-v1"
        and audit.get("status") == "PASS"
        and identity_claim_equal(identity(RAW), audit.get("raw_bag"))
    ):
        raise RuntimeError("the v1 raw audit or its raw-bag binding drifted")


def expected_vins_config(link: Path, mode: str) -> bytes:
    image_topic = "/camera/image_raw" if mode == "origin" else "/unused/image"
    return f'''%YAML:1.0

imu: 1
num_of_cam: 1
multiple_thread: 1

imu_topic: "/rtimulib_node/imu"
image0_topic: "{image_topic}"
image1_topic: ""
output_path: "{link / "vins_output"}"

image_width: 968
image_height: 608
cam0_calib: "aqualoc_archaeo10_pinhole.yaml"

estimate_extrinsic: 0
body_T_cam0: !!opencv-matrix
   rows: 4
   cols: 4
   dt: d
   data: [ -0.99937221, -0.03437489, -0.00857581, -0.01928963,
            0.00901561, -0.01265975, -0.99987922, -0.17514254,
            0.03426217, -0.99932882, 0.01296171, -0.02679520,
            0.0, 0.0, 0.0, 1.0 ]

max_cnt: 150
min_dist: 20
freq: 10
F_threshold: 1.0
show_track: 0
flow_back: 1
equalize: 1

max_solver_time: 0.04
max_num_iterations: 8
keyframe_parallax: 10.0

acc_n: 0.05
gyr_n: 0.003
acc_w: 0.0015
gyr_w: 0.0001
g_norm: 9.8100

loop_closure: 0
td: -0.053694112369382575
estimate_td: 0
rolling_shutter: 0
'''.encode("utf-8")


def backend_exec_argv(mode: str, method: str, every_n: str) -> list[str]:
    return [
        "/usr/bin/bash", str(RUNNER), mode, "10", "0", "2800", method, every_n
    ]


def network_namespace_check(
    *, host_net: str, host_user: str, backend: list[str]
) -> dict[str, Any]:
    return {
        "type": "network_namespace_manifest",
        "path": "network_namespace_manifest.json",
        "expected_host_network_namespace": host_net,
        "expected_host_user_namespace": host_user,
        "formal_port": FORMAL_PORT,
        "backend_argv_sha256": compact_json_sha256(backend),
    }


def backend_checks(
    *, link: Path, mode: str, play_bag: Path, host_net: str, host_user: str,
    backend: list[str],
) -> list[dict[str, Any]]:
    config_name = f"vins_aqualoc_archaeo_{mode}.yaml"
    return [
        {"type": "vins_trajectory", "path": "vins_output/vio.csv", "min_rows": 2},
        {
            "type": "file_sha256", "path": config_name,
            "sha256": hashlib.sha256(expected_vins_config(link, mode)).hexdigest(),
        },
        {
            "type": "file_sha256", "path": "aqualoc_archaeo10_pinhole.yaml",
            "sha256": "045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5",
        },
        {
            "type": "replay_manifest", "path": "replay_manifest.txt",
            "values": {
                "run_dir": str(link), "raw_bag": str(RAW),
                "play_bag": str(play_bag),
                "vins_csv": str(link / "vins_output/vio.csv"),
            },
        },
        {
            "type": "ape_kv", "path": "ape.txt", "required_keys": APE_KEYS,
            "integer_keys": APE_INTEGER_KEYS, "exact_keys": True,
        },
        network_namespace_check(
            host_net=host_net, host_user=host_user, backend=backend
        ),
    ]


def launch_argv(
    *, output_dir: Path, host_net: str, host_user: str, backend: list[str]
) -> list[str]:
    return [
        "/usr/bin/unshare", "--user", "--map-root-user", "--net",
        "/usr/bin/python3.8", str(NETNS_ENTRY), "--output-dir", str(output_dir),
        "--formal-port", str(FORMAL_PORT), "--host-network-namespace", host_net,
        "--host-user-namespace", host_user, "--", *backend,
    ]


def common_backend_environment() -> dict[str, str]:
    aqualoc_root = (
        "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
        "Archaeological_site_sequences"
    )
    return {
        "ROOT": str(ROOT), "VINS_WS": "/home/ma/SLAM/VINS-Fusion-origin",
        "AQUALOC_ROOT": aqualoc_root,
        "RAW_TAR": f"{aqualoc_root}/archaeo_sequence_10_raw_data.tar.gz",
        "GT_TXT": f"{aqualoc_root}/archaeo_groundtruth_files/"
        "new_archaeo_colmap_traj_sequence_10.txt",
        "RAW_BAG": str(RAW), "RUN_VINS": "1", "FORCE_RAW": "0",
        "FORCE_EXPORT": "0",
        "VINS_NODE_BIN": "/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node",
        "WAIT_FOR_VINS_SUBSCRIBERS": "1",
        "WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT": "20", "VINS_MULTIPLE_THREAD": "1",
        "AQUALOC_BODY_T_CAM0_MODE": "imu_cam",
        "VINS_TD": "-0.053694112369382575", "VINS_ESTIMATE_TD": "0",
        "VINS_MAX_SOLVER_TIME": "0.04", "VINS_MAX_NUM_ITERATIONS": "8",
        "PLAY_RATE": "1.0", "ROSBAG_PLAY_DELAY": "3",
        "ROSBAG_WAIT_FOR_SUBSCRIBERS": "0", "POST_PLAY_SLEEP": "8",
        "BACKEND_REPLAY_ONLY": "0",
    }


def item_contracts(host_net: str, host_user: str) -> dict[str, dict[str, Any]]:
    common = common_backend_environment()
    authority_common = [
        "unshare", "python3_8", "network_namespace_entry", "ip", "bash",
        "dedicated_archaeology_runner", "setsid", "sleep", "readlink",
        "record_vins_env", "wait_for_subscribers", "legacy_ape_evaluator",
        "vins_node", "vins_library", "vins_camera_models_library",
        "vins_setup_bash", "vins_setup_sh", "vins_setup_utility",
        "ros_setup_bash", "ros_setup_sh", "ros_setup_utility", "rosbag_cli",
        "roscore_cli", "rosmaster_cli", "rosparam_cli", "rosrun_cli",
        "rosout_node", "raw_bag", "raw_audit", "raw_tar", "ground_truth",
        "coreutils_cp", "coreutils_realpath", "coreutils_rm", "coreutils_mkdir",
        "coreutils_cat", "coreutils_basename", "coreutils_dirname", "coreutils_tee",
        "coreutils_date", "hostname", "rospack_cli", "coreutils_stat",
        "coreutils_md5sum", "sed", "coreutils_uname", "coreutils_mktemp",
        "grep", "awk", "rosbash_source",
        "ros_catkin_marker", "vins_catkin_marker",
        "dave_catkin_marker", "uuv_catkin_marker",
    ]
    authority_common.extend(
        f"ros_environment_hook_{index:02d}"
        for index, _name in enumerate(ROS_HOOK_NAMES)
    )
    metadata: dict[str, dict[str, Any]] = {
        "vanilla_origin_native_image_context": {
            "mode": "origin", "method": "klt", "every_n": "1",
            "play_bag": RAW,
            "tag": (
                "systemfair_a10_finalonline_v4_backend_recovery_feed0000_2800_"
                "score2400_2800_vanilla_origin"
            ),
            "feature_override": None,
            "external_input_bindings": {
                "raw_bag": {
                    "identity_key": "raw_bag",
                    "source_receipt_identity_key": "raw_audit",
                    "source_item_id": "v1_raw_audit",
                },
            },
            "source_authorities": [],
        },
        "klt_external_feature_context": {
            "mode": "external", "method": "klt", "every_n": "2",
            "play_bag": V3_KLT / "features.bag",
            "tag": (
                "systemfair_a10_finalonline_v4_backend_recovery_feed0000_2800_"
                "score2400_2800_external_klt"
            ),
            "feature_override": V3_KLT / "features.bag",
            "external_input_bindings": {
                "feature_bag": {
                    "identity_key": "v3_klt_features_bag",
                    "source_receipt_identity_key": "v3_klt_receipt",
                    "source_item_id": "klt_input_adoption",
                },
                "frontend_metrics": {
                    "identity_key": "v3_klt_frontend_metrics",
                    "source_receipt_identity_key": "v3_klt_receipt",
                    "source_item_id": "klt_input_adoption",
                },
            },
            "source_authorities": [
                "v3_execution_lock", "v3_klt_receipt", "v3_klt_claim",
                "v3_klt_log", "v3_klt_features_bag", "v3_klt_frontend_metrics",
                "v3_klt_camera_yaml", "v3_klt_adoption_manifest",
            ],
        },
        "aquafe_external_feature_context": {
            "mode": "external", "method": "hybrid_xfeat", "every_n": "2",
            "play_bag": V3_AQUA / "full_merged.bag",
            "tag": (
                "systemfair_a10_finalonline_v4_backend_recovery_feed0000_2800_"
                "score2400_2800_aquafe_finalonline_xfeat_lineage"
            ),
            "feature_override": V3_AQUA / "full_merged.bag",
            "external_input_bindings": {
                "feature_bag": {
                    "identity_key": "v3_aquafe_full_merged_bag",
                    "source_receipt_identity_key": "v3_aquafe_receipt",
                    "source_item_id": "aquafe_build",
                },
            },
            "source_authorities": [
                "v3_execution_lock", "v3_aquafe_receipt", "v3_aquafe_claim",
                "v3_aquafe_log", "v3_aquafe_full_merged_bag",
                "v3_aquafe_sidecar_bag", "v3_aquafe_stats_csv",
            ],
        },
    }
    contracts: dict[str, dict[str, Any]] = {}
    for item_id in ITEM_ORDER:
        specification = metadata[item_id]
        output_dir = EXP / "backends" / item_id
        link = WORKSPACE_LINKS[item_id]
        mode = str(specification["mode"])
        method = str(specification["method"])
        every_n = str(specification["every_n"])
        play_bag = Path(specification["play_bag"])
        backend = backend_exec_argv(mode, method, every_n)
        runtime_root = EXP / "runtime" / item_id
        env = {
            **common,
            "TAG": str(specification["tag"]),
            "PORT": str(FORMAL_PORT),
            "ROS_HOME": str(runtime_root / "ros_home"),
            "ROS_LOG_DIR": str(runtime_root / "ros_log"),
        }
        feature_override = specification["feature_override"]
        if isinstance(feature_override, Path):
            env["FEATURE_BAG_OVERRIDE"] = str(feature_override)
        argv = launch_argv(
            output_dir=output_dir, host_net=host_net, host_user=host_user,
            backend=backend,
        )
        config_name = f"vins_aqualoc_archaeo_{mode}.yaml"
        expected_outputs = [
            "vins_output/vio.csv", "vins.log", "ape.txt", "replay_manifest.txt",
            config_name, "aqualoc_archaeo10_pinhole.yaml", "vins_env_manifest.txt",
            "roscore.log", "network_namespace_manifest.json",
        ]
        checks = backend_checks(
            link=link, mode=mode, play_bag=play_bag, host_net=host_net,
            host_user=host_user, backend=backend,
        )
        archival_outputs = {
            "vins.log": (
                "Raw VINS diagnostic log retained for independent score-usability "
                "event attribution."
            ),
            "vins_env_manifest.txt": (
                "Runtime-environment provenance; not a numerical result artifact."
            ),
            "roscore.log": (
                "Nonempty namespace-local ROS-master and bounded-cleanup provenance."
            ),
        }
        if item_id == "klt_external_feature_context":
            expected_outputs.append("frontend_metrics.csv")
            checks.append(
                {
                    "type": "file_sha256", "path": "frontend_metrics.csv",
                    "sha256": identity(V3_KLT / "frontend_metrics.csv")["sha256"],
                }
            )
        contracts[item_id] = {
            "kind": "backend_replay", "dependencies": [],
            "isolation_policy": "loopback_only_network_namespace",
            "machine_exclusive_cpu_scheduling": False, "timeout_seconds": 600,
            "argv": argv, "env": env,
            "command_contract": command_contract(argv, env),
            "output_dir": str(output_dir), "workspace_link": str(link),
            "output_tree_policy": "REQUIRE_EMPTY_BEFORE_CLAIM",
            "archival_outputs": archival_outputs,
            "expected_outputs": expected_outputs, "semantic_checks": checks,
            "authority_identity_keys": authority_common
            + list(specification["source_authorities"]),
            "dependency_artifacts": {},
            "external_input_bindings": specification["external_input_bindings"],
        }
    return contracts


def identities() -> dict[str, dict[str, Any]]:
    fixed = {
        "lock_builder": Path(__file__),
        "supervisor": ROOT / "scripts/run_samehistory_system_a10_finalonline_v4_backend_recovery.py",
        "analysis_only_analyzer": ROOT / "scripts/analyze_samehistory_system_a10_finalonline_v4_backend_recovery.py",
        "protocol": PROTOCOL,
        "dedicated_archaeology_runner": RUNNER,
        "network_namespace_entry": NETNS_ENTRY,
        "v3_execution_lock": V3_LOCK,
        "v3_klt_receipt": V3_KLT_RECEIPT,
        "v3_klt_claim": V3_KLT / "process_start_claim.json",
        "v3_klt_log": V3_KLT / "supervisor_process.log",
        "v3_klt_features_bag": V3_KLT / "features.bag",
        "v3_klt_frontend_metrics": V3_KLT / "frontend_metrics.csv",
        "v3_klt_camera_yaml": V3_KLT / "aqualoc_archaeo10_pinhole.yaml",
        "v3_klt_adoption_manifest": V3_KLT / "adoption_manifest.json",
        "v3_aquafe_receipt": V3_AQUA_RECEIPT,
        "v3_aquafe_claim": V3_AQUA / "process_start_claim.json",
        "v3_aquafe_log": V3_AQUA / "supervisor_process.log",
        "v3_aquafe_full_merged_bag": V3_AQUA / "full_merged.bag",
        "v3_aquafe_sidecar_bag": V3_AQUA / "sidecar.bag",
        "v3_aquafe_stats_csv": V3_AQUA / "stats.csv",
        "v3_vanilla_failed_receipt": V3_FAILED_VANILLA_RECEIPT,
        "v3_vanilla_failed_claim": V3_FAILED_VANILLA / "process_start_claim.json",
        "v3_vanilla_failed_log": V3_FAILED_VANILLA / "supervisor_process.log",
        "raw_audit": RAW_AUDIT, "raw_bag": RAW,
        "raw_tar": Path(
            "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
            "Archaeological_site_sequences/archaeo_sequence_10_raw_data.tar.gz"
        ),
        "ground_truth": Path(
            "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
            "Archaeological_site_sequences/archaeo_groundtruth_files/"
            "new_archaeo_colmap_traj_sequence_10.txt"
        ),
        "record_vins_env": ROOT / "scripts/record_vins_env.sh",
        "wait_for_subscribers": ROOT / "scripts/wait_for_ros_subscribers.py",
        "legacy_ape_evaluator": ROOT / "scripts/evaluate_vins_sim_ape.py",
        "common_support_evaluator": ROOT / "scripts/evaluate_vins_common_support.py",
        "common_support_evaluator_core": ROOT / "scripts/trajectory_eval_core.py",
        "vins_node": Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node"),
        "vins_library": Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libvins_lib.so"),
        "vins_camera_models_library": Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libcamera_models.so"),
        "vins_setup_bash": Path("/home/ma/SLAM/VINS-Fusion-origin/devel/setup.bash"),
        "vins_setup_sh": Path("/home/ma/SLAM/VINS-Fusion-origin/devel/setup.sh"),
        "vins_setup_utility": Path("/home/ma/SLAM/VINS-Fusion-origin/devel/_setup_util.py"),
        "ros_setup_bash": Path("/opt/ros/noetic/setup.bash"),
        "ros_setup_sh": Path("/opt/ros/noetic/setup.sh"),
        "ros_setup_utility": Path("/opt/ros/noetic/_setup_util.py"),
        "ros_catkin_marker": CATKIN_MARKERS["ros_catkin_marker"],
        "vins_catkin_marker": CATKIN_MARKERS["vins_catkin_marker"],
        "dave_catkin_marker": CATKIN_MARKERS["dave_catkin_marker"],
        "uuv_catkin_marker": CATKIN_MARKERS["uuv_catkin_marker"],
        "rosbag_cli": Path("/opt/ros/noetic/bin/rosbag"),
        "roscore_cli": Path("/opt/ros/noetic/bin/roscore"),
        "rosmaster_cli": Path("/opt/ros/noetic/bin/rosmaster"),
        "rosparam_cli": Path("/opt/ros/noetic/bin/rosparam"),
        "rosrun_cli": Path("/opt/ros/noetic/bin/rosrun"),
        "rosout_node": Path("/opt/ros/noetic/lib/rosout/rosout"),
        "unshare": Path("/usr/bin/unshare"), "ip": Path("/usr/bin/ip"),
        "setsid": Path("/usr/bin/setsid"), "sleep": Path("/usr/bin/sleep"),
        "readlink": Path("/usr/bin/readlink"), "bash": Path("/usr/bin/bash"),
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
        "awk": Path("/usr/bin/awk"),
        "rosbash_source": Path("/opt/ros/noetic/share/rosbash/rosbash"),
    }
    result = {name: identity(path) for name, path in fixed.items()}
    for index, name in enumerate(ROS_HOOK_NAMES):
        result[f"ros_environment_hook_{index:02d}"] = identity(
            ROS_PROFILE_DIR / name
        )
    return result


def validate_external_bindings(
    items: Mapping[str, Mapping[str, Any]],
    identity_claims: Mapping[str, Mapping[str, Any]],
) -> None:
    expected = {
        "vanilla_origin_native_image_context": {
            "raw_bag": ("raw_bag", "raw_audit", "v1_raw_audit"),
        },
        "klt_external_feature_context": {
            "feature_bag": (
                "v3_klt_features_bag", "v3_klt_receipt", "klt_input_adoption"
            ),
            "frontend_metrics": (
                "v3_klt_frontend_metrics", "v3_klt_receipt", "klt_input_adoption"
            ),
        },
        "aquafe_external_feature_context": {
            "feature_bag": (
                "v3_aquafe_full_merged_bag", "v3_aquafe_receipt", "aquafe_build"
            ),
        },
    }
    for item_id, bindings in expected.items():
        actual = items[item_id].get("external_input_bindings")
        if not isinstance(actual, dict) or set(actual) != set(bindings):
            raise RuntimeError(f"external input binding set drift in {item_id}")
        for name, values in bindings.items():
            wanted = dict(
                zip(
                    ("identity_key", "source_receipt_identity_key", "source_item_id"),
                    values,
                )
            )
            if actual[name] != wanted:
                raise RuntimeError(f"external input binding drift in {item_id}:{name}")
            if any(key not in identity_claims for key in values[:2]):
                raise RuntimeError(f"external input identity is not pinned: {item_id}:{name}")


def validate_declared_contracts(
    items: Mapping[str, Mapping[str, Any]],
    identity_claims: Mapping[str, Mapping[str, Any]],
    host_net: str,
    host_user: str,
) -> None:
    if tuple(items) != ITEM_ORDER:
        raise RuntimeError("v4 requires exactly the three backend items in frozen order")
    output_dirs: set[str] = set()
    links: set[str] = set()
    reference_env: dict[str, str] | None = None
    permitted_env_differences = {
        "TAG", "PORT", "FEATURE_BAG_OVERRIDE", "ROS_HOME", "ROS_LOG_DIR"
    }
    for item_id, item in items.items():
        if item.get("kind") != "backend_replay" or item.get("dependencies") != []:
            raise RuntimeError(f"v4 contains a non-backend or false dependency: {item_id}")
        if item.get("isolation_policy") != "loopback_only_network_namespace":
            raise RuntimeError(f"network isolation policy drift: {item_id}")
        if item.get("machine_exclusive_cpu_scheduling") is not False:
            raise RuntimeError(f"machine exclusivity was overclaimed: {item_id}")
        argv, env = item.get("argv"), item.get("env")
        if not isinstance(argv, list) or not all(isinstance(v, str) and v for v in argv):
            raise RuntimeError(f"invalid argv: {item_id}")
        if argv[:4] != ["/usr/bin/unshare", "--user", "--map-root-user", "--net"]:
            raise RuntimeError(f"unshare prefix drift: {item_id}")
        required = [
            "/usr/bin/python3.8", str(NETNS_ENTRY), "--formal-port",
            str(FORMAL_PORT), "--host-network-namespace", host_net,
            "--host-user-namespace", host_user, "--", "/usr/bin/bash", str(RUNNER),
        ]
        if any(token not in argv for token in required):
            raise RuntimeError(f"network namespace argv drift: {item_id}")
        if not isinstance(env, dict) or env.get("PORT") != str(FORMAL_PORT):
            raise RuntimeError(f"backend environment or shared namespace port drift: {item_id}")
        if item.get("command_contract") != command_contract(argv, env):
            raise RuntimeError(f"command fingerprint drift: {item_id}")
        science_env = {k: v for k, v in env.items() if k not in permitted_env_differences}
        if reference_env is None:
            reference_env = science_env
        elif science_env != reference_env:
            raise RuntimeError(f"science environment differs between arms: {item_id}")
        output_dir = item.get("output_dir")
        workspace_link = item.get("workspace_link")
        if output_dir != str(EXP / "backends" / item_id):
            raise RuntimeError(f"output directory drift: {item_id}")
        if workspace_link != str(WORKSPACE_LINKS[item_id]):
            raise RuntimeError(f"workspace link drift: {item_id}")
        if output_dir in output_dirs or workspace_link in links:
            raise RuntimeError(f"duplicate output/link: {item_id}")
        output_dirs.add(str(output_dir))
        links.add(str(workspace_link))
        if item.get("output_tree_policy") != "REQUIRE_EMPTY_BEFORE_CLAIM":
            raise RuntimeError(f"output-tree policy drift: {item_id}")
        expected_outputs = item.get("expected_outputs")
        checks = item.get("semantic_checks")
        archives = item.get("archival_outputs")
        if not isinstance(expected_outputs, list) or not isinstance(checks, list):
            raise RuntimeError(f"output contract missing: {item_id}")
        if not isinstance(archives, dict):
            raise RuntimeError(f"archive contract missing: {item_id}")
        checked = {str(check.get("path")) for check in checks if isinstance(check, dict)}
        if set(expected_outputs) != checked | set(archives) or checked & set(archives):
            raise RuntimeError(f"output coverage mismatch: {item_id}")
        namespace_checks = [
            check for check in checks
            if isinstance(check, dict) and check.get("type") == "network_namespace_manifest"
        ]
        if len(namespace_checks) != 1:
            raise RuntimeError(f"network manifest check count drift: {item_id}")
        authority = item.get("authority_identity_keys")
        if not isinstance(authority, list) or any(key not in identity_claims for key in authority):
            raise RuntimeError(f"unbound authority identity: {item_id}")
        if item.get("dependency_artifacts") != {}:
            raise RuntimeError(f"v4 backend unexpectedly binds an internal dependency: {item_id}")
    if len(output_dirs) != 3 or len(links) != 3:
        raise RuntimeError("v4 requires three independent outputs and links")
    validate_external_bindings(items, identity_claims)


def namespace_target(path: str, expected_kind: str) -> str:
    value = os.readlink(path)
    if re.fullmatch(rf"{expected_kind}:\[[0-9]+\]", value) is None:
        raise RuntimeError(f"unexpected outer namespace identity: {path}:{value}")
    return value


def build() -> dict[str, Any]:
    validate_v3_pending_backend_allowances_unconsumed()
    validate_catkin_setup_dynamic_inputs()
    validate_raw_audit()
    validate_accepted_v3_receipt(
        V3_KLT_RECEIPT, item_id="klt_input_adoption",
        artifacts=[
            V3_KLT / "features.bag", V3_KLT / "frontend_metrics.csv",
            V3_KLT / "aqualoc_archaeo10_pinhole.yaml",
            V3_KLT / "adoption_manifest.json",
        ],
    )
    validate_accepted_v3_receipt(
        V3_AQUA_RECEIPT, item_id="aquafe_build",
        artifacts=[
            V3_AQUA / "full_merged.bag", V3_AQUA / "sidecar.bag",
            V3_AQUA / "stats.csv",
        ],
    )
    validate_failed_v3_vanilla_receipt()
    host_net = namespace_target("/proc/self/ns/net", "net")
    host_user = namespace_target("/proc/self/ns/user", "user")
    items = item_contracts(host_net, host_user)
    identity_claims = identities()
    validate_declared_contracts(items, identity_claims, host_net, host_user)
    validate_v3_pending_backend_allowances_unconsumed()
    validate_catkin_setup_dynamic_inputs()
    return {
        "schema_version": "aqua-fe-a10-samehistory-finalonline-v4-execution-lock-v1",
        "status": "FROZEN_BEFORE_SCORED_RUNS",
        "created_at_local": datetime.now().astimezone().isoformat(),
        "protocol": identity(PROTOCOL),
        "policy": {
            "item_order": list(items),
            "global_flock_path": str(EXP / ".supervisor.flock"),
            "one_process_launch_per_item": True, "result_informed_retry": False,
            "serial_execution": True,
            "require_prior_items_terminal_before_next_launch": False,
            "dependencies_are_only_declared_item_dependencies": True,
            "dependency_receipt_requires_terminal_process_rc0_and_artifact_contract_pass": True,
            "independent_backend_failure_is_retained_not_ranked_as_zero": True,
            "machine_exclusive_cpu_scheduling": False,
            "host_namespace_identity": {"network": host_net, "user": host_user},
            "recovery_evidence_scope": {
                "purpose": "PIPELINE_DEBUG_AND_SECONDARY_SENSITIVITY_ONLY",
                "paper_primary_evidence_permitted": False,
                "later_machine_exclusive_regeneration_required_for_primary_evidence": True,
                "v3_vanilla_attempt_reclassified": False,
                "v3_pending_backend_allowances_consumed": False,
                "result_informed_input_selection": False,
            },
            "process_isolation_policy": {
                "name": "loopback_only_network_namespace",
                "strict_before_claim_for_every_item": True,
                "strict_after_claim_before_popen_for_every_item": True,
                "postflight_by_item": {
                    item_id: "loopback_only_network_namespace" for item_id in items
                },
                "fresh_user_and_network_namespace_per_backend": True,
                "only_interface_inside_namespace": "lo",
                "host_network_namespace": host_net, "host_user_namespace": host_user,
                "formal_loopback_port_inside_each_namespace": FORMAL_PORT,
                "network_crosstalk_barrier": True,
                "machine_exclusive_cpu_scheduling": False,
            },
            "catkin_setup_dynamic_inputs": catkin_setup_dynamic_input_contract(),
            "large_artifact_root": str(EXP),
            "runtime_artifact_root": str(EXP / "runtime"),
            "cwd": str(ROOT),
            "forbidden_workspace": "/home/ma/SLAM/VINS-Fusion_3-15-WS",
            "command_contract": {
                "canonical_json": (
                    "json.dumps(sort_keys=True,separators=(',',':'),"
                    "ensure_ascii=False); UTF-8"
                ),
                "argv_and_item_env_must_match_per_item_sha256": True,
                "effective_environment_is_exact_base_plus_disjoint_item_env_plus_pwd": True,
                "reject_nul_in_argv_or_environment": True,
                "reject_equals_in_environment_keys": True,
                "reject_forbidden_workspace_in_argv_or_environment": True,
            },
            "workspace_link_policy": {
                "exact_count": 3, "root": str(ROOT / "logs/aqualoc_archaeo_vins"),
                "reject_dot_or_dotdot_components": True,
                "resolve_and_verify_real_parent": True,
                "exact_links": {
                    item_id: item["workspace_link"] for item_id, item in items.items()
                },
            },
            "output_tree_policy": {
                "preclaim": "REQUIRE_EMPTY_BEFORE_CLAIM",
                "reject_symlinks_and_nonregular_artifacts": True,
                "reject_unexpected_recursive_entries_after_run": True,
                "supervisor_control_files": [
                    "process_start_claim.json", "formal_run_receipt_v4.json",
                    "supervisor_process.log",
                ],
            },
            "base_environment": {
                "HOME": "/home/ma", "USER": "ma", "LOGNAME": "ma",
                "LANG": "zh_CN.UTF-8", "LANGUAGE": "zh_CN:zh",
                "PATH": (
                    "/opt/ros/noetic/bin:/usr/local/sbin:/usr/local/bin:"
                    "/usr/sbin:/usr/bin:/sbin:/bin"
                ),
                "CMAKE_PREFIX_PATH": (
                    "/home/ma/dave_ws/devel:/home/ma/uuv_ws/devel:/opt/ros/noetic"
                ),
                "LD_LIBRARY_PATH": (
                    "/home/ma/dave_ws/devel/lib:/home/ma/uuv_ws/devel/lib:"
                    "/opt/ros/noetic/lib:/opt/ros/noetic/lib/x86_64-linux-gnu"
                ),
                "PKG_CONFIG_PATH": (
                    "/home/ma/dave_ws/devel/lib/pkgconfig:"
                    "/home/ma/uuv_ws/devel/lib/pkgconfig:"
                    "/opt/ros/noetic/lib/pkgconfig:"
                    "/opt/ros/noetic/lib/x86_64-linux-gnu/pkgconfig"
                ),
                "PYTHONPATH": (
                    "/home/ma/dave_ws/devel/lib/python3/dist-packages:"
                    "/home/ma/uuv_ws/devel/lib/python3/dist-packages:"
                    "/opt/ros/noetic/lib/python3/dist-packages"
                ),
                "ROS_DISTRO": "noetic", "ROS_ETC_DIR": "/opt/ros/noetic/etc/ros",
                "ROS_PACKAGE_PATH": (
                    "/home/ma/dave_ws/src:/home/ma/uuv_ws/src:/opt/ros/noetic/share"
                ),
                "ROS_PYTHON_VERSION": "3", "ROS_ROOT": "/opt/ros/noetic/share/ros",
                "ROS_VERSION": "1", "ROS_MASTER_URI": "http://localhost:11311",
            },
        },
        "recovery_provenance": {
            "scope": "SECONDARY_DEBUG_ONLY",
            "v3_execution_lock_identity_key": "v3_execution_lock",
            "accepted_external_sources": {
                "klt_input_adoption": {
                    "receipt_identity_key": "v3_klt_receipt",
                    "required_disposition": "ACCEPTED",
                    "consumed_by": ["klt_external_feature_context"],
                },
                "aquafe_build": {
                    "receipt_identity_key": "v3_aquafe_receipt",
                    "required_disposition": "ACCEPTED",
                    "consumed_by": ["aquafe_external_feature_context"],
                },
            },
            "retained_failed_history": {
                "v3_vanilla_origin_native_image_context": {
                    "receipt_identity_key": "v3_vanilla_failed_receipt",
                    "required_disposition": "PROCESS_FAILED",
                    "used_as_runtime_input": False, "reclassified": False,
                    "retried_under_v3_allowance": False,
                },
            },
            "unconsumed_v3_backend_items": [
                "external_klt_finalonline_backbone",
                "aquafe_finalonline_xfeat_lineage",
            ],
            "v3_pending_backend_allowance_guard": (
                v3_pending_allowance_guard_contract()
            ),
        },
        "external_inputs": {
            "raw_v1": {
                "artifact_identity_keys": ["raw_bag"],
                "authority_identity_key": "raw_audit",
                "accepted_v3_receipt_required": False,
            },
            "klt_v3_accepted": {
                "artifact_identity_keys": [
                    "v3_klt_features_bag", "v3_klt_frontend_metrics",
                    "v3_klt_camera_yaml", "v3_klt_adoption_manifest",
                ],
                "authority_identity_key": "v3_klt_receipt",
                "accepted_v3_receipt_required": True,
            },
            "aquafe_v3_accepted": {
                "artifact_identity_keys": [
                    "v3_aquafe_full_merged_bag", "v3_aquafe_sidecar_bag",
                    "v3_aquafe_stats_csv",
                ],
                "authority_identity_key": "v3_aquafe_receipt",
                "accepted_v3_receipt_required": True,
            },
        },
        "score_usability": {
            "score_start_ns": SCORE_START_NS, "score_end_ns": SCORE_END_NS,
            "nominal_backend_output_rate_hz": 10, "crop_interval": "inclusive",
            "minimum_score_temporal_span_coverage": 0.70,
            "maximum_score_output_gap_s": 0.50,
            "require_initialization_before_or_within_score_window": True,
            "maximum_score_failure_mentions": 0,
            "maximum_score_restart_or_reset_events": 0,
            "unresolved_score_log_event_attribution_is_failure": True,
            "score_failure_is_usability_fail_not_terminal_process_failure": True,
        },
        "common_support": {
            "denominator_reference_rows": 21, "minimum_common_rows": 15,
            "minimum_common_coverage": 0.70,
            "minimum_descriptive_rpe_pairs": 10,
            "formal_ape_minimum_poses": 30, "formal_ape_gate_open": False,
        },
        "identities": identity_claims, "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    if output.exists() or output.is_symlink():
        print(f"REFUSE_OVERWRITE:{output}", file=sys.stderr)
        return 2
    payload = (json.dumps(build(), indent=2, sort_keys=False) + "\n").encode("utf-8")
    validate_v3_pending_backend_allowances_unconsumed()
    validate_catkin_setup_dynamic_inputs()
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        write_all(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    parent = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    print(json.dumps(identity(output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
