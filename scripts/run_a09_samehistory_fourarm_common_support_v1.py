#!/usr/bin/env python3
"""Run the frozen A09 four-arm, analysis-only common-support comparison.

The program reads four already-published trajectories.  It never starts ROS,
VINS, a frontend, rosbag replay, or HFNet.  ``check`` is read-only.  ``run``
consumes one durable claim and invokes the frozen common-support evaluator
exactly once, without retry.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping


ROOT = Path("/home/ma/AQUA-FE_WS")
RUNNER = ROOT / "scripts/run_a09_samehistory_fourarm_common_support_v1.py"
PROTOCOL = ROOT / "papers/a09_samehistory_fourarm_common_support_v1_protocol.md"
EXECUTION_LOCK = ROOT / "papers/a09_samehistory_fourarm_common_support_v1_execution_lock.json"

SYSTEM_ROOT = Path("/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1")
OUTPUT = Path("/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_fourarm_common_support_v1")
CLAIM = OUTPUT.parent / "a09_samehistory_fourarm_common_support_v1.process_start_claim.json"
TERMINAL_RECEIPT = OUTPUT.parent / "a09_samehistory_fourarm_common_support_v1.terminal_receipt.json"

RAW_BAG = SYSTEM_ROOT / "raw/archaeo09_0000_4400.bag"
EVALUATOR = ROOT / "scripts/evaluate_vins_common_support_epoch_v2.py"
EVALUATOR_BASE = ROOT / "scripts/evaluate_vins_common_support.py"
EVALUATOR_CORE = ROOT / "scripts/trajectory_eval_core.py"
HFNET_CONFIG = ROOT / "configs/published_baselines/hfnet_aqualoc_a02_body_T_cam0_v1.yaml"
EVO_APE = Path("/home/ma/.local/bin/evo_ape")
EVO_RPE = Path("/home/ma/.local/bin/evo_rpe")

SCORE_START_NS = 1_542_888_946_038_630_384
SCORE_END_NS = 1_542_888_966_034_698_672
SCORE_START_S = "1542888946.038630384"
SCORE_END_S = "1542888966.034698672"
REFERENCE_TOPIC = "/aqualoc/colmap_gt"
EXPECTED_GRID_COUNT = 20
EXPECTED_NATIVE_REFERENCE_SCORE_ROWS = 21
MIN_COMMON_MATCHED = 15
MIN_RPE_PAIRS = 10
EVO_MAX_ABS_DIFF_M = 1e-5
CONTRAST_NAME = "A09_SAMEHISTORY_FOURARM_COMMON_SUPPORT_V1_SCORE_4000_4400"

ARM_ORDER = (
    "VANILLA_ORIGIN_NATIVE_IMAGE_CONTEXT",
    "EXTERNAL_KLT_FINALONLINE_BACKBONE",
    "AQUAFE_FINALONLINE_XFEAT_LINEAGE",
    "HFNET_SLAM_WARMSTART",
)

TRAJECTORIES = {
    ARM_ORDER[0]: SYSTEM_ROOT / "backends/vanilla_origin_native_image_context/vins_output/vio.csv",
    ARM_ORDER[1]: SYSTEM_ROOT / "backends/klt_external_feature_context/vins_output/vio.csv",
    ARM_ORDER[2]: SYSTEM_ROOT / "backends/aquafe_external_feature_context/vins_output/vio.csv",
    ARM_ORDER[3]: SYSTEM_ROOT / (
        "external_baselines/hfnet_warmstart_bridge_v1/"
        "hfnet_world_T_body_source_stamp_canonical_v1.csv"
    ),
}

CONFIGS = {
    ARM_ORDER[0]: SYSTEM_ROOT / (
        "backends/vanilla_origin_native_image_context/vins_aqualoc_archaeo_origin.yaml"
    ),
    ARM_ORDER[1]: SYSTEM_ROOT / (
        "backends/klt_external_feature_context/vins_aqualoc_archaeo_external.yaml"
    ),
    ARM_ORDER[2]: SYSTEM_ROOT / (
        "backends/aquafe_external_feature_context/vins_aqualoc_archaeo_external.yaml"
    ),
    ARM_ORDER[3]: HFNET_CONFIG,
}

BACKEND_RECEIPTS = {
    ARM_ORDER[0]: SYSTEM_ROOT / (
        "backends/vanilla_origin_native_image_context/formal_run_receipt_v1.json"
    ),
    ARM_ORDER[1]: SYSTEM_ROOT / "backends/klt_external_feature_context/formal_run_receipt_v1.json",
    ARM_ORDER[2]: SYSTEM_ROOT / "backends/aquafe_external_feature_context/formal_run_receipt_v1.json",
}

HFNET_STAGE1_RECEIPT = SYSTEM_ROOT / (
    "external_baselines/hfnet_warmstart_bridge_v1/"
    "hfnet_world_T_body_vins_csv_v1.receipt.json"
)
HFNET_CANONICAL_RECEIPT = SYSTEM_ROOT / (
    "external_baselines/hfnet_warmstart_bridge_v1/"
    "hfnet_world_T_body_source_stamp_canonical_v1.receipt.json"
)

# Every evaluator input and every receipt used to authorize one is pinned here.
# RUNNER and PROTOCOL are bound separately by EXECUTION_LOCK to avoid a cycle.
EXPECTED_IDENTITIES: Mapping[str, tuple[int, str]] = {
    str(RAW_BAG): (1_187_038_470, "a4a24bd0c2451f4996d39f635e55fd99730698bf704c4e7dc81729070d0dca97"),
    str(BACKEND_RECEIPTS[ARM_ORDER[0]]): (41_435, "18bd02c2a268306a9154e60dffbac326b9320fc55084e62be01bdc0fa500474d"),
    str(BACKEND_RECEIPTS[ARM_ORDER[1]]): (44_131, "8c12b5701309bd79652aa723951fa6f8c866135f744c813c3092ec658c1775fb"),
    str(BACKEND_RECEIPTS[ARM_ORDER[2]]): (44_279, "34833858bddf210de373a8b3fc9c36be78b02168fbeda2274070382d82a89302"),
    str(TRAJECTORIES[ARM_ORDER[0]]): (227_239, "e7f8e06536bd788edc60dd13add6c0d371a41d0351eaa29a7f5c3d1cde9afc2d"),
    str(TRAJECTORIES[ARM_ORDER[1]]): (228_066, "edb75ed45449761c0a79cc72ad2084eb8e45f0508be9aa90641e84361e549b43"),
    str(TRAJECTORIES[ARM_ORDER[2]]): (228_064, "92089ada8e065dbb86940f8a5cc96f1850e8a76c4ac42a10b8a45b9a7d8053dd"),
    str(TRAJECTORIES[ARM_ORDER[3]]): (42_105, "2b5bd98de228b13c33a79e40b0462d51db57e3280449230d3e1f33f369072d5d"),
    str(CONFIGS[ARM_ORDER[0]]): (990, "eafd7e6f22e573c4e0d7b5e36f2550938029456fc75ad55bd741c1d000016ff7"),
    str(CONFIGS[ARM_ORDER[1]]): (986, "b928b31af629bddd9ff677953c185778a2172a0f946fce71bfa1e08b5d879178"),
    str(CONFIGS[ARM_ORDER[2]]): (1_015, "4b58c2e422fcce4dfecfc6ffbb227fe979e641923a378bbaa227f0baa22894ed"),
    str(HFNET_CONFIG): (415, "a76c728b31d47c3a87f54c465fb581007ed2da2b7d7d84df81dbde93e9a886c1"),
    str(HFNET_STAGE1_RECEIPT): (5_037, "d03e5cd87ec8e936b2160f1bef43fe8ae3a79f4b53540e9baf24b0e809371483"),
    str(HFNET_CANONICAL_RECEIPT): (5_632, "dff07d76e1d363846e31a693017df58e580a4482a076507dd1036372c1ce22b4"),
    str(EVALUATOR): (5_447, "3c455299b23157cc749b474b9460ca4a408b3bee516e9d1bf2109f253cf89f91"),
    str(EVALUATOR_BASE): (27_933, "ab6f2b5c1a10a41463657edee2724c022fc0248dc885096acb336e602384c110"),
    str(EVALUATOR_CORE): (27_945, "aa9ac4da81df7298d1f1c369548ca98a57235916004337cad66f4cf331560635"),
    str(EVO_APE): (213, "6bee25dc5bfdab0ead8988ab4014a72511339e94697ec61699f66f68f5f24d15"),
    str(EVO_RPE): (213, "9e07d0bd4566aa680d5e39e58589176a286f4f8a22ba9107a5834ddb278e2bd1"),
}

LOCK_SCHEMA = "aqua-fe-a09-samehistory-fourarm-common-support-execution-lock-v1"
LOCK_PROTOCOL_CONSTANTS: Mapping[str, Any] = {
    "alignment": "INDEPENDENT_SE3_PER_ARM_FIXED_SCALE_1",
    "ape_gate_open": False,
    "arm_order": list(ARM_ORDER),
    "contrast_name": CONTRAST_NAME,
    "evo_max_absolute_disagreement_m": "0.00001",
    "grid_count": EXPECTED_GRID_COUNT,
    "joint_mask": True,
    "minimum_rpe_pairs": MIN_RPE_PAIRS,
    "score_end_ns": SCORE_END_NS,
    "score_start_ns": SCORE_START_NS,
    "subprocess_policy": "EXACTLY_ONE_EVALUATOR_CALL_NO_RETRY",
}


class AnalysisError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise AnalysisError(code)


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, Any]:
    return {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256(path)}


def read_json(path: Path, canonical: bool = False) -> Any:
    payload = path.read_bytes()
    value = json.loads(payload.decode("utf-8"))
    if canonical:
        require(payload == canonical_json(value), f"JSON_NOT_CANONICAL:{path}")
    return value


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def stat_is_directory(mode: int) -> bool:
    return (mode & 0o170000) == 0o040000


def reserve_output_directory(path: Path) -> dict[str, Any]:
    """Atomically reserve the final output namespace with one mkdir call."""

    require(path.is_absolute(), "OUTPUT_RESERVATION_PATH_NOT_ABSOLUTE")
    try:
        os.mkdir(path, 0o755)
    except FileExistsError as error:
        raise AnalysisError(f"OUTPUT_RESERVATION_ALREADY_EXISTS:{path}") from error
    info = os.lstat(path)
    require(stat_is_directory(info.st_mode), "OUTPUT_RESERVATION_NOT_DIRECTORY")
    return {
        "path": str(path),
        "device": info.st_dev,
        "inode": info.st_ino,
    }


def reservation_is_current(reservation: Mapping[str, Any]) -> bool:
    try:
        info = os.lstat(reservation["path"])
    except FileNotFoundError:
        return False
    return (
        stat_is_directory(info.st_mode)
        and info.st_dev == reservation.get("device")
        and info.st_ino == reservation.get("inode")
    )


def require_current_reservation(reservation: Mapping[str, Any], phase: str) -> None:
    require(reservation_is_current(reservation), f"OUTPUT_RESERVATION_DRIFT:{phase}")


def fsync_tree(root: Path) -> None:
    """Fsync every regular file and directory in one reserved output tree."""

    paths = sorted(root.rglob("*"))
    for path in paths:
        require(not path.is_symlink(), f"OUTPUT_TREE_SYMLINK:{path}")
        if path.is_file():
            descriptor = os.open(
                path,
                os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        else:
            require(path.is_dir(), f"OUTPUT_TREE_NONREGULAR:{path}")
    directories = [path for path in paths if path.is_dir()]
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        fsync_directory(directory)
    fsync_directory(root)


def write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        require(written > 0, "ZERO_LENGTH_WRITE")
        offset += written


def write_json(path: Path, value: Any) -> None:
    payload = canonical_json(value)
    with path.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def write_json_exclusive(path: Path, value: Any) -> dict[str, Any]:
    payload = canonical_json(value)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o444,
    )
    try:
        write_all(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    fsync_directory(path.parent)
    require(path.read_bytes() == payload, f"EXCLUSIVE_PUBLICATION_BYTES_CHANGED:{path}")
    return identity(path)


def verify_backend_receipt(
    arm: str, receipt_path: Path, claims: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    receipt = read_json(receipt_path)
    require(
        receipt.get("schema_version") == "aqua-fe-a09-samehistory-warmstart-backend-supervisor-v1",
        f"BACKEND_RECEIPT_SCHEMA:{arm}",
    )
    require(receipt.get("status") == "TERMINAL_PROCESS_RC0", f"BACKEND_STATUS:{arm}")
    require(receipt.get("overall_disposition") == "ACCEPTED", f"BACKEND_NOT_ACCEPTED:{arm}")
    require(receipt.get("launch_allowance_consumed") is True, f"BACKEND_CLAIM_NOT_CONSUMED:{arm}")
    process = receipt.get("terminal_process") or {}
    require(process.get("child_started") is True, f"BACKEND_CHILD_NOT_STARTED:{arm}")
    require(process.get("popen_invocation_count") == 1, f"BACKEND_POPEN_COUNT:{arm}")
    require(process.get("raw_return_code") == 0, f"BACKEND_RC:{arm}")
    require(process.get("timed_out") is False, f"BACKEND_TIMEOUT:{arm}")
    process_group = process.get("process_group") or {}
    require(process_group.get("leader_reaped") is True, f"BACKEND_LEADER_NOT_REAPED:{arm}")
    require(process_group.get("process_group_empty") is True, f"BACKEND_GROUP_NOT_EMPTY:{arm}")
    require(process_group.get("owned_descendants_empty") is True, f"BACKEND_DESCENDANT_NOT_EMPTY:{arm}")
    artifact = receipt.get("artifact_contract") or {}
    execution = receipt.get("execution_integrity") or {}
    score = receipt.get("score_usability") or {}
    require(artifact.get("status") == "PASS" and artifact.get("issues") == [], f"BACKEND_ARTIFACT:{arm}")
    require(execution.get("status") == "PASS" and execution.get("supervisor_error") is None, f"BACKEND_EXECUTION:{arm}")
    require(score.get("status") == "PASS", f"BACKEND_SCORE:{arm}")
    require(score.get("score_start_ns") == SCORE_START_NS, f"BACKEND_SCORE_START:{arm}")
    require(score.get("score_end_ns") == SCORE_END_NS, f"BACKEND_SCORE_END:{arm}")
    outputs = artifact.get("outputs") or {}
    for direct_path in (TRAJECTORIES[arm], CONFIGS[arm]):
        recorded = outputs.get(str(direct_path)) or {}
        actual = claims[str(direct_path)]
        require(
            {key: recorded.get(key) for key in ("path", "size_bytes", "sha256")} == actual,
            f"BACKEND_OUTPUT_BINDING:{arm}:{direct_path.name}",
        )
    sealed = receipt.get("sealed_in_place_invariant") or {}
    require(sealed.get("status") == "PASS", f"BACKEND_SEAL:{arm}")
    return {
        "receipt": claims[str(receipt_path)],
        "status": receipt["status"],
        "overall_disposition": receipt["overall_disposition"],
        "artifact_contract_status": artifact["status"],
        "execution_integrity_status": execution["status"],
        "score_usability_status": score["status"],
        "popen_invocation_count": process["popen_invocation_count"],
        "raw_return_code": process["raw_return_code"],
    }


def verify_hfnet_chain(claims: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    stage1 = read_json(HFNET_STAGE1_RECEIPT, canonical=True)
    stage2 = read_json(HFNET_CANONICAL_RECEIPT, canonical=True)
    canonical_identity = claims[str(TRAJECTORIES[ARM_ORDER[3]])]
    stage1_receipt_identity = claims[str(HFNET_STAGE1_RECEIPT)]
    require(
        stage1.get("schema_version")
        == "aqua-fe-hfnet-v6-a09-warmstart-lossless-bridge-receipt-v1",
        "HFNET_STAGE1_SCHEMA",
    )
    require(stage1.get("status") == "PASS_SEALED_A09_HFNET_LOSSLESS_COLUMN_BRIDGE", "HFNET_STAGE1_STATUS")
    require(stage1.get("row_count") == 401, "HFNET_STAGE1_ROWS")
    require(stage1.get("source_indices_inclusive") == [4000, 4400], "HFNET_STAGE1_INDICES")
    stage1_output = stage1.get("output") or {}
    require(
        (stage1_output.get("size_bytes"), stage1_output.get("sha256"))
        == (42_105, "f58685b726495f851b5e36b2d5b9d5cbdad9d58f3a251328a617ebda945d3a77"),
        "HFNET_STAGE1_OUTPUT_IDENTITY",
    )
    require((stage1.get("claim_boundary") or {}).get("accuracy_evaluated") is False, "HFNET_STAGE1_CLAIM")
    require(
        stage2.get("schema_version")
        == "aqua-fe-hfnet-v6-a09-warmstart-source-stamp-canonical-receipt-v1",
        "HFNET_STAGE2_SCHEMA",
    )
    require(
        stage2.get("status") == "PASS_SEALED_A09_HFNET_SOURCE_STAMP_CANONICALIZATION",
        "HFNET_STAGE2_STATUS",
    )
    require(stage2.get("row_count") == 401, "HFNET_STAGE2_ROWS")
    require(stage2.get("source_indices_inclusive") == [4000, 4400], "HFNET_STAGE2_INDICES")
    require(stage2.get("upstream_bridge") == stage1_output, "HFNET_UPSTREAM_BRIDGE_BINDING")
    require(
        stage2.get("upstream_bridge_receipt") == stage1_receipt_identity,
        "HFNET_UPSTREAM_RECEIPT_BINDING",
    )
    require(stage2.get("output") == canonical_identity, "HFNET_CANONICAL_OUTPUT_BINDING")
    require(stage2.get("tool") == stage1.get("tool"), "HFNET_TOOL_BINDING")
    require(stage2.get("authorities") == stage1.get("authorities"), "HFNET_AUTHORITY_BINDING")
    timestamp = stage2.get("timestamp_contract") or {}
    require(timestamp.get("canonical_first_stamp_ns") == SCORE_START_NS, "HFNET_CANONICAL_START")
    require(timestamp.get("canonical_last_stamp_ns") == SCORE_END_NS, "HFNET_CANONICAL_END")
    require(timestamp.get("source_mapping") == "cam0_times_0000_4400[source_index=4000+i]", "HFNET_SOURCE_MAPPING")
    require(timestamp.get("timestamp_values_changed") == 401, "HFNET_TIMESTAMP_CHANGE_COUNT")
    require(timestamp.get("maximum_absolute_delta_ns") == 112, "HFNET_TIMESTAMP_MAX_DELTA")
    pose1 = (stage1.get("pose_token_contract") or {}).get("output_pose_stream_sha256")
    pose2 = (stage2.get("pose_token_contract") or {}).get(
        "upstream_and_output_pose_stream_sha256"
    )
    require(
        pose1 == pose2 == "3f93d76ed106b8dc2b0edb5fee1cdecc79a0fbb15d7fc8219669a9f59dd7847d",
        "HFNET_POSE_STREAM_BINDING",
    )
    require((stage2.get("claim_boundary") or {}).get("accuracy_evaluated") is False, "HFNET_STAGE2_CLAIM")

    stamps: list[int] = []
    for line_number, raw in enumerate(TRAJECTORIES[ARM_ORDER[3]].read_text(encoding="ascii").splitlines(), 1):
        fields = raw.split(",")
        require(len(fields) == 8, f"HFNET_CANONICAL_COLUMNS:LINE_{line_number}")
        try:
            stamp = int(fields[0])
            values = [float(value) for value in fields[1:]]
        except ValueError as error:
            raise AnalysisError(f"HFNET_CANONICAL_NUMERIC:LINE_{line_number}") from error
        require(all(math.isfinite(value) for value in values), f"HFNET_CANONICAL_NONFINITE:LINE_{line_number}")
        stamps.append(stamp)
    require(len(stamps) == 401, f"HFNET_CANONICAL_ROW_COUNT:{len(stamps)}")
    require(stamps[0] == SCORE_START_NS and stamps[-1] == SCORE_END_NS, "HFNET_CANONICAL_RANGE")
    require(all(right > left for left, right in zip(stamps, stamps[1:])), "HFNET_CANONICAL_ORDER")
    return {
        "canonical": canonical_identity,
        "stage1_receipt": stage1_receipt_identity,
        "stage2_receipt": claims[str(HFNET_CANONICAL_RECEIPT)],
        "row_count": len(stamps),
        "first_stamp_ns": stamps[0],
        "last_stamp_ns": stamps[-1],
        "pose_stream_sha256": pose1,
    }


def verify_execution_lock(inputs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    require(EXECUTION_LOCK.is_file() and not EXECUTION_LOCK.is_symlink(), "EXECUTION_LOCK_MISSING")
    lock = read_json(EXECUTION_LOCK, canonical=True)
    require(isinstance(lock, Mapping), "EXECUTION_LOCK_NOT_OBJECT")
    require(lock.get("schema_version") == LOCK_SCHEMA, "EXECUTION_LOCK_SCHEMA")
    require(lock.get("status") == "LOCKED_BEFORE_ANALYSIS", "EXECUTION_LOCK_STATUS")
    require(lock.get("runner") == identity(RUNNER), "EXECUTION_LOCK_RUNNER_BINDING")
    require(lock.get("protocol") == identity(PROTOCOL), "EXECUTION_LOCK_PROTOCOL_BINDING")
    require(lock.get("inputs") == dict(inputs), "EXECUTION_LOCK_INPUT_BINDING")
    require(lock.get("protocol_constants") == dict(LOCK_PROTOCOL_CONSTANTS), "EXECUTION_LOCK_PROTOCOL_CONSTANTS")
    return {"identity": identity(EXECUTION_LOCK), "value": lock}


def verify_inputs() -> dict[str, Any]:
    claims: dict[str, Mapping[str, Any]] = {}
    for raw_path, expected in EXPECTED_IDENTITIES.items():
        path = Path(raw_path)
        require(path.is_file() and not path.is_symlink(), f"INPUT_NOT_REGULAR:{path}")
        actual = identity(path)
        require((actual["size_bytes"], actual["sha256"]) == expected, f"INPUT_IDENTITY_DRIFT:{path}")
        claims[raw_path] = actual
    backend = {
        arm: verify_backend_receipt(arm, BACKEND_RECEIPTS[arm], claims)
        for arm in ARM_ORDER[:3]
    }
    hfnet = verify_hfnet_chain(claims)
    lock = verify_execution_lock(claims)
    return {"files": claims, "backend_acceptance": backend, "hfnet_chain": hfnet, "lock": lock}


def destinations_absent() -> None:
    for path in (OUTPUT, CLAIM, TERMINAL_RECEIPT):
        require(not path.exists() and not path.is_symlink(), f"DESTINATION_ALREADY_EXISTS:{path}")


def evaluator_command(output_dir: Path) -> list[str]:
    command = [
        "/usr/bin/python3.8",
        str(EVALUATOR),
        "--reference-bag", str(RAW_BAG),
        "--reference-topic", REFERENCE_TOPIC,
    ]
    for name in ARM_ORDER:
        command.extend(["--arm", f"{name}={TRAJECTORIES[name]}"])
    for name in ARM_ORDER:
        command.extend(["--arm-config", f"{name}={CONFIGS[name]}"])
    command.extend([
        "--nominal-reference-rate-hz", "1.0",
        "--nominal-estimate-rate-hz", "10.0",
        "--evaluation-rate-hz", "1.0",
        "--max-reference-gap-s", "2.5",
        "--max-estimate-gap-s", "0.25",
        "--window-start-s", SCORE_START_S,
        "--window-end-s", SCORE_END_S,
        "--rpe-delta-s", "1.0",
        "--min-ape-poses", "30",
        "--min-ape-span-s", "10.0",
        "--min-common-coverage", "0.70",
        "--min-rpe-pairs", str(MIN_RPE_PAIRS),
        "--contrast-name", CONTRAST_NAME,
        "--output-dir", str(output_dir),
        "--run-evo",
    ])
    return command


def validate_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    require(set(summary) == {"protocol", "support", "reference", "arms"}, "SUMMARY_SCHEMA")
    protocol = summary["protocol"]
    support = summary["support"]
    reference = summary["reference"]
    arms = summary["arms"]
    require(
        all(isinstance(value, Mapping) for value in (protocol, support, reference, arms)),
        "SUMMARY_TYPES",
    )
    require(protocol.get("contrast_name") == CONTRAST_NAME, "CONTRAST_DRIFT")
    require(protocol.get("body_to_camera_applied") is True, "BODY_CAMERA_NOT_APPLIED")
    require(protocol.get("rpe_semantics") == "aligned_global_frame_positional_delta", "RPE_SEMANTICS_DRIFT")
    require(protocol.get("nominal_reference_rate_hz") == 1.0, "NOMINAL_REFERENCE_RATE_DRIFT")
    require(protocol.get("nominal_estimate_rate_hz") == 10.0, "NOMINAL_ESTIMATE_RATE_DRIFT")
    require(protocol.get("evaluation_rate_hz") == 1.0, "EVAL_RATE_DRIFT")
    require(protocol.get("max_reference_gap_s") == 2.5, "REFERENCE_GAP_DRIFT")
    require(protocol.get("max_estimate_gap_s") == 0.25, "ESTIMATE_GAP_DRIFT")
    require(protocol.get("rpe_delta_s") == 1.0, "RPE_DELTA_DRIFT")
    require(protocol.get("reference_time_offset_s") == 0.0, "REFERENCE_TIME_OFFSET_DRIFT")
    require(
        protocol.get("arm_time_offsets_s") == {name: 0.0 for name in ARM_ORDER},
        "ARM_TIME_OFFSETS_DRIFT",
    )
    require(protocol.get("window_start_s") == float(SCORE_START_S), "WINDOW_START_DRIFT")
    require(protocol.get("window_end_s") == float(SCORE_END_S), "WINDOW_END_DRIFT")
    require(set(arms) == set(ARM_ORDER), "ARM_SET_DRIFT")
    grid = support.get("grid_count")
    matched = support.get("matched_count")
    pairs = support.get("rpe_pairs")
    coverage = support.get("common_coverage")
    require(type(grid) is int and grid == EXPECTED_GRID_COUNT, f"GRID_COUNT:{grid}")
    require(type(matched) is int and 0 <= matched <= grid, f"MATCHED_COUNT:{matched}")
    require(type(pairs) is int and 0 <= pairs <= grid - 1, f"RPE_PAIRS:{pairs}")
    require(isinstance(coverage, (int, float)) and math.isfinite(coverage), "COVERAGE_INVALID")
    require(abs(float(coverage) - matched / grid) <= 1e-12, "COVERAGE_INCONSISTENT")
    require(support.get("ape_valid") is False, "FORMAL_APE_GATE_UNEXPECTEDLY_OPEN")
    require(support.get("rpe_valid") is True, "RPE_GATE_CLOSED")
    reference_valid = reference.get("valid_grid_count")
    require(
        type(reference_valid) is int and matched <= reference_valid <= grid,
        "REFERENCE_SUPPORT_CANNOT_CONTAIN_JOINT_MASK",
    )
    common_gate = (
        matched >= MIN_COMMON_MATCHED
        and matched / EXPECTED_GRID_COUNT >= 0.70
        and matched / EXPECTED_NATIVE_REFERENCE_SCORE_ROWS >= 0.70
    )
    rpe_gate = common_gate and pairs >= MIN_RPE_PAIRS
    metrics: dict[str, Any] = {}
    for name in ARM_ORDER:
        row = arms[name]
        require(row.get("matched_count") == matched, f"ARM_MATCHED_DRIFT:{name}")
        require(row.get("rpe_pairs") == pairs, f"ARM_RPE_PAIR_DRIFT:{name}")
        values = {}
        for key in (
            "ape_rmse_m", "ape_median_m", "ape_max_m",
            "rpe_rmse_m", "rpe_median_m", "rpe_max_m",
        ):
            value = row.get(key)
            require(
                isinstance(value, (int, float)) and math.isfinite(value) and value >= 0,
                f"METRIC_INVALID:{name}:{key}",
            )
            values[key] = float(value)
        metrics[name] = values
    return {
        "uniform_grid_count": grid,
        "joint_common_matched_count": matched,
        "joint_common_coverage": matched / EXPECTED_GRID_COUNT,
        "conservative_fixed_denominator_index": matched / EXPECTED_NATIVE_REFERENCE_SCORE_ROWS,
        "joint_exact_1s_rpe_pairs": pairs,
        "common_support_gate_pass": common_gate,
        "descriptive_rpe_gate_pass": rpe_gate,
        "formal_ape_gate_open": False,
        "scale": 1.0,
        "alignment": "INDEPENDENT_SE3_PER_ARM",
        "metrics_fixed_order": metrics,
    }


def validate_evo(evo: Mapping[str, Any], adjudication: Mapping[str, Any]) -> None:
    require(evo.get("evo_version") == "1.31.1", "EVO_VERSION_DRIFT")
    require(evo.get("rpe_semantics") == "aligned_global_frame_positional_delta", "EVO_RPE_SEMANTICS_DRIFT")
    require(set((evo.get("arms") or {})) == set(ARM_ORDER), "EVO_ARM_SET_DRIFT")
    for name in ARM_ORDER:
        row = evo["arms"][name]
        require(row.get("rpe_pair_count") == adjudication["joint_exact_1s_rpe_pairs"], f"EVO_RPE_PAIR_DRIFT:{name}")
        require(float(row.get("ape_abs_diff_m")) <= EVO_MAX_ABS_DIFF_M, f"EVO_APE_CROSSCHECK_DRIFT:{name}")
        require(float(row.get("rpe_abs_diff_m")) <= EVO_MAX_ABS_DIFF_M, f"EVO_RPE_CROSSCHECK_DRIFT:{name}")


def report_markdown(adjudication: Mapping[str, Any]) -> str:
    lines = [
        "# A09 same-history four-arm common-support analysis v1",
        "",
        "Status: `DEVELOPMENT_ONLY_DESCRIPTIVE_COMMON_SUPPORT`.",
        "",
        "All three VINS backend receipts are independently `ACCEPTED`; HFNet is the published source-stamp-canonical trajectory and receipt chain. No SLAM, VINS, frontend, replay, or HFNet process was rerun.",
        "",
        "| Fixed-order system | Gate-closed SE(3) APE RMSE / median / max (m) | Descriptive 1 s RPE RMSE / median / max (m) |",
        "|---|---:|---:|",
    ]
    metrics = adjudication["metrics_fixed_order"]
    for name in ARM_ORDER:
        row = metrics[name]
        lines.append(
            f"| `{name}` | {row['ape_rmse_m']:.6f} / {row['ape_median_m']:.6f} / {row['ape_max_m']:.6f} | "
            f"{row['rpe_rmse_m']:.6f} / {row['rpe_median_m']:.6f} / {row['rpe_max_m']:.6f} |"
        )
    lines.extend([
        "",
        "## Support and boundary",
        "",
        f"- Joint mask: {adjudication['joint_common_matched_count']}/20; exact 1 s pairs: {adjudication['joint_exact_1s_rpe_pairs']}.",
        "- Each arm uses an independent proper rigid SE(3) alignment with scale fixed to 1.",
        "- The formal APE gate is closed because the common grid has only 20 poses (<30).",
        "- One selected window and one trajectory per method provide no independent repeated-run inference.",
        "- Do not infer a ranking, winner, superiority, significance, or a direct score-frame learned-action effect.",
        "",
    ])
    return "\n".join(lines)


def stats_markdown(adjudication: Mapping[str, Any]) -> str:
    return "\n".join([
        "# Statistical appendix",
        "",
        "- Unit of analysis: one preselected A09 score window (`n=1` for inference).",
        "- The 20 joint time-grid samples are correlated trajectory samples, not independent replicates.",
        f"- Common support: `{adjudication['joint_common_matched_count']}/20`; exact 1 s RPE pairs: `{adjudication['joint_exact_1s_rpe_pairs']}`.",
        "- Alignment: independent fixed-scale SE(3), never Sim(3).",
        "- Confidence intervals, significance tests, effect-size inference, and ranking are not computed.",
        "- APE values are retained only as gate-closed diagnostics; descriptive RPE requires at least 10 pairs.",
        "",
    ])


def tree_manifest(root: Path, excluded: tuple[str, ...] = ("result_manifest.json",)) -> dict[str, Any]:
    files = {}
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), f"OUTPUT_TREE_SYMLINK:{path}")
        if path.is_file() and path.name not in excluded:
            files[str(path.relative_to(root))] = {
                "size_bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        elif not path.is_file():
            require(path.is_dir(), f"OUTPUT_TREE_NONREGULAR:{path}")
    return files


def normalize_timeout_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def run() -> dict[str, Any]:
    destinations_absent()
    preflight = verify_inputs()
    require(OUTPUT.parent.is_dir() and not OUTPUT.parent.is_symlink(), "OUTPUT_PARENT_INVALID")
    command = evaluator_command(OUTPUT / "common_support")
    claim_record = {
        "schema_version": "aqua-fe-a09-fourarm-analysis-process-start-claim-v1",
        "status": "DURABLE_CLAIM_CONSUMES_ONLY_EVALUATOR_ALLOWANCE",
        "claimed_at_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "pid": os.getpid(),
        "popen_invocation_count_at_claim": 0,
        "retry_permitted": False,
        "runner": identity(RUNNER),
        "protocol": identity(PROTOCOL),
        "execution_lock": preflight["lock"]["identity"],
        "command": command,
    }
    claim_identity = write_json_exclusive(CLAIM, claim_record)
    process_record: dict[str, Any] = {
        "command": command,
        "popen_invocation_count": 0,
        "child_started": False,
        "raw_return_code": None,
        "timed_out": False,
        "stdout": "",
    }
    disposition = "FAILED_AFTER_DURABLE_CLAIM"
    error_text: str | None = None
    output_reservation: dict[str, Any] | None = None
    try:
        output_reservation = reserve_output_directory(OUTPUT)
        fsync_directory(OUTPUT.parent)
        require_current_reservation(output_reservation, "BEFORE_POPEN")
        before_popen = verify_inputs()
        require(before_popen["lock"]["identity"] == preflight["lock"]["identity"], "LOCK_DRIFT_BEFORE_POPEN")
        process_record["popen_invocation_count"] = 1
        try:
            process = subprocess.run(
                command,
                cwd=str(ROOT),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=180,
                check=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            process_record.update({
                "child_started": True,
                "raw_return_code": process.returncode,
                "stdout": process.stdout,
            })
        except subprocess.TimeoutExpired as error:
            process_record.update({
                "child_started": True,
                "timed_out": True,
                "stdout": normalize_timeout_output(error.stdout),
            })
            raise AnalysisError("EVALUATOR_TIMEOUT") from error
        require_current_reservation(output_reservation, "AFTER_EVALUATOR")
        write_json(OUTPUT / "evaluator_process_receipt.json", {
            "schema_version": "aqua-fe-a09-fourarm-evaluator-process-receipt-v1",
            **process_record,
            "retry_permitted": False,
        })
        require(process_record["popen_invocation_count"] == 1, "EVALUATOR_CALL_COUNT")
        require(process_record["raw_return_code"] == 0, f"EVALUATOR_RC:{process_record['raw_return_code']}")
        evaluator_dir = OUTPUT / "common_support"
        summary_path = evaluator_dir / "common_support_summary.json"
        require(summary_path.is_file(), "COMMON_SUPPORT_SUMMARY_MISSING")
        summary = read_json(summary_path)
        adjudication = validate_summary(summary)
        require(adjudication["common_support_gate_pass"] is True, "COMMON_SUPPORT_GATE_FAILED")
        require(adjudication["descriptive_rpe_gate_pass"] is True, "RPE_SUPPORT_GATE_FAILED")
        evo_path = evaluator_dir / "evo_crosscheck.json"
        require(evo_path.is_file(), "EVO_CROSSCHECK_MISSING")
        evo = read_json(evo_path)
        validate_evo(evo, adjudication)
        postflight = verify_inputs()
        require(postflight["lock"]["identity"] == preflight["lock"]["identity"], "LOCK_DRIFT_POSTFLIGHT")
        require_current_reservation(output_reservation, "BEFORE_ANALYSIS_WRITES")
        write_json(OUTPUT / "input_manifest.json", {
            "schema_version": "aqua-fe-a09-fourarm-analysis-input-manifest-v1",
            "status": "PASS",
            "runner": identity(RUNNER),
            "protocol": identity(PROTOCOL),
            **postflight,
            "fixed_arm_order": list(ARM_ORDER),
            "score_window_ns_inclusive": [SCORE_START_NS, SCORE_END_NS],
        })
        bundle = {
            "schema_version": "aqua-fe-a09-samehistory-fourarm-common-support-v1",
            "status": "DEVELOPMENT_ONLY_DESCRIPTIVE_COMMON_SUPPORT",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "slams_frontends_or_hfnet_executed": False,
            "fixed_arm_order": list(ARM_ORDER),
            "support_adjudication": adjudication,
            "common_support_summary": summary,
            "evo_1_31_1_crosscheck": evo,
            "claim_boundary": {
                "development_only": True,
                "formal_ape_gate_open": False,
                "independent_run_count_for_inference": 1,
                "ranking_or_winner_computed": False,
                "significance_test_performed": False,
                "superiority_claimed": False,
                "direct_score_frame_learned_action_isolated": False,
            },
        }
        write_json(OUTPUT / "analysis_bundle.json", bundle)
        (OUTPUT / "analysis-report.md").write_text(report_markdown(adjudication), encoding="utf-8")
        (OUTPUT / "stats-appendix.md").write_text(stats_markdown(adjudication), encoding="utf-8")
        write_json(OUTPUT / "result_manifest.json", {
            "schema_version": "aqua-fe-a09-fourarm-analysis-result-manifest-v1",
            "status": "COMPLETE",
            "files": tree_manifest(OUTPUT),
        })
        require_current_reservation(output_reservation, "BEFORE_TREE_FSYNC")
        fsync_tree(OUTPUT)
        require_current_reservation(output_reservation, "AFTER_TREE_FSYNC")
        fsync_directory(OUTPUT.parent)
        committed_files = tree_manifest(OUTPUT, excluded=())
        terminal = {
            "schema_version": "aqua-fe-a09-fourarm-analysis-terminal-receipt-v1",
            "status": "COMPLETE",
            "ended_at_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            "claim": claim_identity,
            "execution_lock": preflight["lock"]["identity"],
            "output_reservation": output_reservation,
            "process": process_record,
            "retry_permitted": False,
            "output": {"path": str(OUTPUT), "files": committed_files},
            "error": None,
        }
        terminal_identity = write_json_exclusive(TERMINAL_RECEIPT, terminal)
        disposition = "COMPLETE"
        return {
            "status": disposition,
            "output": str(OUTPUT),
            "terminal_receipt": terminal_identity,
            "support": adjudication,
        }
    except BaseException as error:
        error_text = f"{type(error).__name__}:{error}"
        retained_output = None
        evidence_error = None
        if output_reservation is not None and reservation_is_current(output_reservation):
            try:
                failure_path = OUTPUT / "failure.json"
                if not failure_path.exists() and not failure_path.is_symlink():
                    write_json_exclusive(failure_path, {
                        "schema_version": "aqua-fe-a09-fourarm-analysis-failure-v1",
                        "status": disposition,
                        "error": error_text,
                        "process": process_record,
                        "output_reservation": output_reservation,
                    })
                fsync_tree(OUTPUT)
                require_current_reservation(output_reservation, "FAILURE_EVIDENCE")
                retained_output = {
                    "path": str(OUTPUT),
                    "reservation": output_reservation,
                    "files": tree_manifest(OUTPUT, excluded=()),
                }
            except BaseException as evidence_failure:
                evidence_error = f"{type(evidence_failure).__name__}:{evidence_failure}"
        if not TERMINAL_RECEIPT.exists() and not TERMINAL_RECEIPT.is_symlink():
            write_json_exclusive(TERMINAL_RECEIPT, {
                "schema_version": "aqua-fe-a09-fourarm-analysis-terminal-receipt-v1",
                "status": disposition,
                "ended_at_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                "claim": claim_identity,
                "execution_lock": preflight["lock"]["identity"],
                "output_reservation": output_reservation,
                "process": process_record,
                "retry_permitted": False,
                "output": retained_output,
                "failure_evidence_error": evidence_error,
                "error": error_text,
            })
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "run"))
    args = parser.parse_args()
    try:
        if args.command == "check":
            destinations_absent()
            result = {"status": "READY", "destinations_absent": True, **verify_inputs()}
        else:
            result = run()
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))
        return 0
    except (AnalysisError, OSError, ValueError) as error:
        print(f"ANALYSIS_ERROR:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
