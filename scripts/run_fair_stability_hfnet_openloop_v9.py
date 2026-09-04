#!/usr/bin/python3
"""Prepare and run the open-loop HFNet arms of runtime-exclusive v9.

The formal one-shot HFNet namespaces are read-only.  This controller creates a
new development namespace, verifies the exact VINS camera phase against both
historical feature bags, generates loop-off configs, gives every replicate an
independent timing-cache seed, and retains every terminal outcome.
"""

from __future__ import annotations

import argparse
import bisect
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable, Mapping, Sequence
import uuid

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from fair_stability_ordinal_common_v9 import (
    EXPERIMENT_ID,
    MAX_ATTEMPTS_PER_CELL,
    MAX_REPLACEMENT_ATTEMPTS_PER_CELL,
    SCHEDULE_SHA256,
    authorize as authorize_ordinal,
    next_state as ordinal_next_state,
    strict_json_equal,
    verify_dispatch_claim,
)
from fair_stability_runtime_resource_monitor_v9 import (
    RuntimeResourceMonitor,
    resource_gate,
    watchdog_terminal_transition_candidate,
)


ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path(__file__).resolve()
PROTOCOL = ROOT / "papers/fair_stability_positive_roster_protocol_v1.md"
ROSTER = ROOT / "papers/fair_stability_positive_roster_v1.csv"
HISTORICAL_RESULTS = (
    ROOT
    / "papers/frozen_frontend_eval_20260714/positive_regression_results_20260717.csv"
)
HISTORICAL_MANIFEST = ROOT / "papers/frozen_frontend_eval_20260714/manifest.csv"
RUNTIME_EXCLUSIVITY_ADDENDUM = (
    ROOT / "papers/fair_stability_runtime_exclusivity_addendum_v9.md"
)
V1_RUNTIME_CONTAMINATION_REPORT = (
    ROOT / "papers/fair_stability_v1_runtime_contamination_report_20260829.md"
)
V2_LIFECYCLE_CONTAMINATION_REPORT = (
    ROOT
    / "papers/fair_stability_v2_lifecycle_false_positive_contamination_report_20260829_v3.md"
)
CONTROL_SUPERSESSION = ROOT / "papers/fair_stability_control_supersession_v9.md"
V3_ABANDONMENT_REPORT = (
    ROOT
    / "papers/fair_stability_v3_outer_batch_timeout_abandonment_report_20260829_v4.md"
)
V4_ABANDONMENT_REPORT = (
    ROOT
    / "papers/fair_stability_v4_ros_python_environment_abandonment_report_20260829_v5.md"
)
V5_ABANDONMENT_REPORT = (
    ROOT
    / "papers/fair_stability_v5_watchdog_exit_race_abandonment_report_20260829_v6.md"
)
V6_ABANDONMENT_REPORT = (
    ROOT
    / "papers/fair_stability_v6_final_gate_timing_abandonment_report_20260829_v7.md"
)
V8_ABANDONMENT_REPORT = (
    ROOT
    / "papers/fair_stability_v8_historical_no_start_revalidation_abandonment_report_20260830_v9.md"
)
SHUTDOWN_ADDENDUM = (
    ROOT / "papers/fair_stability_vins_supervised_shutdown_addendum_v1.md"
)
EXPERIMENT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v9"
)
VINS_ROOT = EXPERIMENT_ROOT / "vins_dev_nativeq_schedfix_runtimeexcl_v9"
BACKEND_FREEZE = VINS_ROOT / "backend_freeze.json"
ORDINAL_COMMON = ROOT / "scripts/fair_stability_ordinal_common_v9.py"
RUNTIME_RESOURCE_MONITOR = (
    ROOT / "scripts/fair_stability_runtime_resource_monitor_v9.py"
)
SYSTEMD_SUPERVISOR = ROOT / "scripts/run_fair_stability_systemd_supervisor_v9.py"

EXPECTED_PROTOCOL_SHA256 = (
    "ab057022d47e4e90e81c639c84a5444000c67cca3aab10316a554b3e3beecd09"
)
EXPECTED_ROSTER_SHA256 = (
    "63715003fde3374a96fd045917e1e718a8b3473723ba1afc50e2d48693d87e3c"
)
EXPECTED_HISTORICAL_RESULTS_SHA256 = (
    "0f48af044f061d0e4013bd23ad54b427c95eca00332e014279d7555f78036341"
)
EXPECTED_HISTORICAL_MANIFEST_SHA256 = (
    "fc3f53fc6a83587522ae87d3d0d84191f73863a22a920ef70a4418aaacf7a760"
)
EXPECTED_CONTROL_DOCUMENTS = {
    "runtime_exclusivity_addendum": (
        RUNTIME_EXCLUSIVITY_ADDENDUM,
        35_991,
        "30ea679e49099956520f312d12958cb1847e1c23472d00731df6cb235997ac05",
    ),
    "v1_runtime_contamination_report": (
        V1_RUNTIME_CONTAMINATION_REPORT,
        3_436,
        "575c18cf6f5f84b6c5ceaedacff0c071986d6113c984000740688586a03d7264",
    ),
    "v2_lifecycle_false_positive_contamination_report": (
        V2_LIFECYCLE_CONTAMINATION_REPORT,
        4_077,
        "ecb46671e3ec2ad827bb80c0edb3a3ecbc2e3db12984234dc22ca45c12365256",
    ),
    "control_supersession": (
        CONTROL_SUPERSESSION,
        25_894,
        "d8630f643b0af36381b4c0a8be7d3c4e6f12ef5f8449cc093e13ef7f3ef43f4f",
    ),
    "v3_outer_batch_timeout_abandonment_report": (
        V3_ABANDONMENT_REPORT,
        4_491,
        "7ef9db8a1fad82edfac69b462fe3b395d543fde63a5c29eff7e5e588f840cb0e",
    ),
    "v4_ros_python_environment_abandonment_report": (
        V4_ABANDONMENT_REPORT,
        2_731,
        "ca484cf9e95e3200b58924f6d30e8feae50f1b9ab44f77b9f1674c7ba2b2de1a",
    ),
    "v5_watchdog_exit_race_abandonment_report": (
        V5_ABANDONMENT_REPORT,
        4_473,
        "603f2a76bb2b4e88a1654a64a43911569a8081411f6e33db78f69e5cad447e0f",
    ),
    "v6_final_gate_timing_abandonment_report": (
        V6_ABANDONMENT_REPORT,
        12_481,
        "8e3af5739d9b58d69d912ca3d26694f4fd159e1e4e9fb7320f09436a1f9bada1",
    ),
    "v8_historical_no_start_revalidation_abandonment_report": (
        V8_ABANDONMENT_REPORT,
        4_343,
        "e8f827a970d36e9f17b15b1c4096c88a5f9ded4f186292652d9ef9a28c8f309e",
    ),
    "shutdown_addendum": (
        SHUTDOWN_ADDENDUM,
        1_645,
        "34f9ac4b0ed5ecc7dab9f6dd8219fd2527a19ef7a4ef74b9b8aa50bc72e0117a",
    ),
}

BINARY = (
    ROOT
    / "build/published_baselines/hfnet_slam_headless_entry_v3"
    / "mono_inertial_euroc_headless_v3"
)
OFFICIAL_LIBRARY = Path(
    "/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1/lib/libHFNet_SLAM.so"
)
SHARED_ONNX = Path(
    "/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT/HF-Net.onnx"
)
SHARED_CACHE = Path(
    "/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT/HF-Net.cache"
)

EXPECTED_STACK = {
    "binary": (118_280, "4d17eecc74ec8f4bcbe4381d579d2bb48160cf63f6dc948f7857d92e681affeb"),
    "official_library": (4_807_712, "a56dfd1b48dee4af5be4e55b076d32eac2cf8fb463da8ab943b690377f193717"),
    "onnx": (132_238_602, "354a23f9c28b75ea9056a8eb5586e3b13191426521fd3f5556e5bfd670fc39b5"),
    "cache": (853_319, "6798ef896e4f503d4d81827a81fc9dad99d40c5e10352abbe974ed309bd0c0e7"),
}
EXPECTED_CONFIGS = {
    "aqualoc_archaeology": "d0cbe8e575c2b8234d1d617baabc27560118625398fd588ec83c3e93b4ce6177",
    "ntnu": "5b8b8d7ed6c010f25d4cf8d80ca24692b06de4cd17f4d19ae2a0cb9cc91a54dd",
    "cirs": "b6e93daf3ca06e3e29433fffa7eb037119b97261888395fe1d51fa2d7a218204",
}
CANONICAL_TD_SECONDS = {
    "aqualoc_archaeology": "-0.053694112369382575",
    "ntnu": "0.0017656238182069367",
    "cirs": "0.0",
}

CASE_ORDER = [
    "a05_3300_3700",
    "a07_10800_11200",
    "a08_4500_4660",
    "a09_6000_6200",
    "fjord1_s83_d10",
    "mclab1_s60_d15",
    "cirs_s575_d30",
    "cirs_s900_d30",
    "a02_7600_8000",
    "mclab2_s110_d10",
]
BUDGETS = (675, 350)
REPEATS = (1, 2, 3)
ASSOCIATION_TOLERANCE_NS = 256
MIN_SUCCESS_COVERAGE = 0.70
MIN_PARTIAL_COVERAGE = 0.50
MAX_INIT_LATENCY_S = 10.0
TIMEOUT_SECONDS = 1800
ZERO_KF_WATCHDOG_GRACE_SECONDS = 30.0
ZERO_KF_WATCHDOG_TARGET_POLL_SECONDS = 0.20
ZERO_KF_WATCHDOG_POLL_SECONDS = 0.25
ZERO_KF_WATCHDOG_FINAL_GATE_SECONDS = 0.25
ZERO_KF_WATCHDOG_SCHEMA = (
    "aqua-fe-fair-stability-hfnet-zero-kf-post-shutdown-watchdog-v9"
)
ZERO_KF_WATCHDOG_ALGORITHM_CODE = "CONFIRMED_ZERO_KF_POST_SHUTDOWN_SAVE_HANG"
ZERO_KF_WATCHDOG_PIPELINE_CODE = "ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN"
MIN_MNT_FREE_BYTES = 5 * 1024**3
MIN_ROOT_FREE_BYTES = 512 * 1024**2


class ContractError(RuntimeError):
    """A frozen input or execution boundary was violated."""


class SupervisorInterrupted(RuntimeError):
    pass


def raise_supervisor_interrupt(signum: int, _frame: object) -> None:
    raise SupervisorInterrupted(f"received signal {signum}")


def supervised_shutdown_failure_codes(
    process_group_clean: bool, residuals: Sequence[object] = ()
) -> list[str]:
    return (
        []
        if process_group_clean and not residuals
        else ["SUPERVISED_SHUTDOWN_CONTRACT_UNPROVEN"]
    )


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def systemd_start_authority(ordinal_state: Mapping[str, Any]) -> dict[str, object]:
    """Verify this runner is inside the exact frozen transient-service cgroup."""

    raw = os.environ.get("FAIR_STABILITY_SYSTEMD_START_RECEIPT", "")
    invocation_id = os.environ.get("INVOCATION_ID", "")
    if not raw or not re.fullmatch(r"[0-9a-f]{32}", invocation_id):
        raise ContractError("SYSTEMD_START_AUTHORITY_REQUIRED")
    path = Path(raw)
    supervision_root = EXPERIMENT_ROOT / "systemd_supervision"
    try:
        path.relative_to(supervision_root)
    except ValueError as error:
        raise ContractError("SYSTEMD_START_RECEIPT_OUTSIDE_SUPERVISION_ROOT") from error
    candidate = supervision_root
    if candidate.is_symlink():
        raise ContractError("SYSTEMD_SUPERVISION_ROOT_SYMLINK")
    for part in path.relative_to(supervision_root).parts:
        candidate /= part
        if candidate.is_symlink():
            raise ContractError(f"SYSTEMD_START_RECEIPT_SYMLINK:{candidate}")
    receipt_identity = identity(path)
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if (
        receipt.get("schema_version")
        != "aqua-fe-fair-stability-systemd-start-receipt-v9"
        or receipt.get("experiment_id") != EXPERIMENT_ID
        or receipt.get("invocation_id") != invocation_id
    ):
        raise ContractError("SYSTEMD_START_RECEIPT_HEADER_INVALID")
    claim_identity = receipt.get("submission_claim")
    if not isinstance(claim_identity, Mapping):
        raise ContractError("SYSTEMD_SUBMISSION_CLAIM_IDENTITY_MISSING")
    claim_path = Path(str(claim_identity.get("path", "")))
    if claim_path.parent != path.parent or not strict_json_equal(
        claim_identity, identity(claim_path)
    ):
        raise ContractError("SYSTEMD_SUBMISSION_CLAIM_IDENTITY_DRIFT")
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    if (
        claim.get("schema_version")
        != "aqua-fe-fair-stability-systemd-submission-v9"
        or claim.get("experiment_id") != EXPERIMENT_ID
        or not strict_json_equal(claim.get("ordinal_state_before_submit"), ordinal_state)
    ):
        raise ContractError("SYSTEMD_SUBMISSION_ORDINAL_OR_ATTEMPT_DRIFT")
    verified = receipt.get("verified_unit")
    if not isinstance(verified, Mapping):
        raise ContractError("SYSTEMD_VERIFIED_UNIT_MISSING")
    control_group = str(verified.get("control_group", ""))
    cgroups = [
        line.split(":", 2)[2]
        for line in Path("/proc/self/cgroup").read_text(encoding="ascii").splitlines()
        if line.count(":") >= 2
    ]
    if not control_group or control_group not in cgroups:
        raise ContractError("RUNNER_OUTSIDE_FROZEN_SYSTEMD_CONTROL_GROUP")
    return receipt_identity


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"MISSING_OR_SYMLINK_FILE:{path}")
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def require_identity(path: Path, size: int, digest: str, label: str) -> dict[str, object]:
    actual = identity(path)
    if actual["size_bytes"] != size or actual["sha256"] != digest:
        raise ContractError(f"IDENTITY_MISMATCH:{label}:{path}")
    return actual


def control_document_identities() -> dict[str, dict[str, object]]:
    return {
        label: require_identity(path, size, digest, label)
        for label, (path, size, digest) in EXPECTED_CONTROL_DOCUMENTS.items()
    }


def require_recorded_identity(
    recorded: object, path: Path, label: str
) -> dict[str, object]:
    observed = identity(path)
    if not isinstance(recorded, Mapping) or recorded != observed:
        raise ContractError(f"RECORDED_IDENTITY_DRIFT:{label}:{path}")
    return observed


def write_exclusive(path: Path, payload: bytes, mode: int = 0o444) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def open_regular_lock(path: Path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ContractError(f"LOCK_PATH_INVALID:{path}")
    descriptor = os.open(
        path,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    return os.fdopen(descriptor, "r+b")


def atomic_copy(source: Path, target: Path, mode: int) -> dict[str, object]:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.copy-", dir=str(target.parent)
    )
    temporary = Path(temporary_name)
    try:
        with source.open("rb") as src, os.fdopen(descriptor, "wb") as dst:
            descriptor = -1
            shutil.copyfileobj(src, dst, 1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        os.chmod(temporary, mode)
        os.link(temporary, target, follow_symlinks=False)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return identity(target)


def load_roster() -> dict[str, dict[str, str]]:
    require_identity(PROTOCOL, PROTOCOL.stat().st_size, EXPECTED_PROTOCOL_SHA256, "protocol")
    require_identity(ROSTER, ROSTER.stat().st_size, EXPECTED_ROSTER_SHA256, "roster")
    with ROSTER.open(newline="", encoding="utf-8") as stream:
        rows = {row["case_id"]: row for row in csv.DictReader(stream)}
    if list(rows) != CASE_ORDER or len(rows) != 10:
        raise ContractError("ROSTER_ORDER_OR_SIZE_MISMATCH")
    return rows


def load_historical_rows() -> dict[str, dict[str, str]]:
    require_identity(
        HISTORICAL_RESULTS,
        HISTORICAL_RESULTS.stat().st_size,
        EXPECTED_HISTORICAL_RESULTS_SHA256,
        "historical_results",
    )
    require_identity(
        HISTORICAL_MANIFEST,
        HISTORICAL_MANIFEST.stat().st_size,
        EXPECTED_HISTORICAL_MANIFEST_SHA256,
        "historical_manifest",
    )
    with HISTORICAL_RESULTS.open(newline="", encoding="utf-8") as stream:
        rows = {row["case_id"]: row for row in csv.DictReader(stream)}
    if any(case_id not in rows for case_id in CASE_ORDER):
        raise ContractError("HISTORICAL_CASE_SET_MISMATCH")
    return rows


def source_vins_config(historical_row: Mapping[str, str]) -> Path:
    source_run = Path(historical_row["full_run"])
    if source_run.is_symlink() or not source_run.is_dir():
        raise ContractError(f"SOURCE_RUN_INVALID:{source_run}")
    configs = list(source_run.glob("vins_*_external.yaml"))
    if len(configs) != 1:
        raise ContractError(f"SOURCE_CONFIG_DISCOVERY_FAILED:{source_run}")
    return configs[0]


def parse_vins_imu_clock(config: Path) -> dict[str, str]:
    text = config.read_text(encoding="utf-8")
    topic_matches = re.findall(r'^imu_topic:\s*"([^"]+)"\s*$', text, re.MULTILINE)
    td_matches = re.findall(r"^td:\s*([^\s#]+)\s*$", text, re.MULTILINE)
    estimate_matches = re.findall(r"^estimate_td:\s*([^\s#]+)\s*$", text, re.MULTILINE)
    if len(topic_matches) != 1 or len(td_matches) != 1 or estimate_matches != ["0"]:
        raise ContractError(f"VINS_IMU_CLOCK_PARSE_FAILED:{config}")
    try:
        td = Decimal(td_matches[0])
    except InvalidOperation as error:
        raise ContractError(f"VINS_TD_DECIMAL_INVALID:{config}") from error
    if not td.is_finite():
        raise ContractError(f"VINS_TD_NONFINITE:{config}")
    return {"imu_topic": topic_matches[0], "source_td_seconds": str(td)}


def read_ns_lines(path: Path) -> list[int]:
    values = [int(line.strip()) for line in path.read_text(encoding="ascii").splitlines() if line.strip()]
    if not values or any(right <= left for left, right in zip(values, values[1:])):
        raise ContractError(f"TIMESTAMP_LIST_INVALID:{path}")
    return values


def selected_source_stamps(row: Mapping[str, str]) -> tuple[list[int], list[int]]:
    source = read_ns_lines(Path(row["input_root"]) / "cam0_times.txt")
    if len(source) != int(row["source_camera_count"]):
        raise ContractError(f"SOURCE_CAMERA_COUNT_MISMATCH:{row['case_id']}")
    indices = list(range(len(source))) if row["selection"] == "every1" else list(range(1, len(source), 2))
    selected = [source[index] for index in indices]
    if len(selected) != int(row["selected_camera_count"]):
        raise ContractError(f"SELECTED_CAMERA_COUNT_MISMATCH:{row['case_id']}")
    return indices, selected


def pinned_rosbag() -> Any:
    """Load ROS bag support only from the frozen Noetic interpreter boundary."""
    try:
        import rosbag  # type: ignore
    except ImportError as error:
        raise ContractError("ROSBAG_IMPORT_FAILED_FIXED_ROS_PYTHON_PATH") from error
    interpreter = Path(sys.executable).resolve()
    module = Path(str(rosbag.__file__)).resolve()
    if interpreter != Path("/usr/bin/python3.8"):
        raise ContractError(f"ROSBAG_INTERPRETER_CONTRACT_DRIFT:{interpreter}")
    expected_module = Path(
        "/opt/ros/noetic/lib/python3/dist-packages/rosbag/__init__.py"
    )
    if module != expected_module:
        raise ContractError(f"ROSBAG_ORIGIN_CONTRACT_DRIFT:{module}")
    return rosbag


def bag_feature_stamps(path: Path) -> list[int]:
    rosbag = pinned_rosbag()
    stamps: list[int] = []
    with rosbag.Bag(str(path), "r") as bag:
        for _, message, _ in bag.read_messages(topics=["/feature_tracker/feature"]):
            stamps.append(int(message.header.stamp.to_nsec()))
    if not stamps or any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise ContractError(f"FEATURE_TIMESTAMPS_INVALID:{path}")
    return stamps


def bag_replay_schedule(
    path: Path, imu_topic: str
) -> tuple[list[tuple[str, int, int]], dict[str, object]]:
    """Return the exact feature/IMU record-time interleaving replayed by rosbag."""
    rosbag = pinned_rosbag()
    feature_topic = "/feature_tracker/feature"
    rows: list[tuple[str, int, int]] = []
    counts = {"feature": 0, "imu": 0}
    digest = hashlib.sha256()
    with rosbag.Bag(str(path), "r") as bag:
        for topic, message, record_time in bag.read_messages(
            topics=[feature_topic, imu_topic]
        ):
            kind = "feature" if topic == feature_topic else "imu"
            header_ns = int(message.header.stamp.to_nsec())
            record_ns = int(record_time.to_nsec())
            item = (kind, header_ns, record_ns)
            rows.append(item)
            counts[kind] += 1
            digest.update(f"{kind}\0{header_ns}\0{record_ns}\n".encode("ascii"))
    if not rows or counts["feature"] == 0 or counts["imu"] == 0:
        raise ContractError(f"REPLAY_SCHEDULE_EMPTY_OR_INCOMPLETE:{path}")
    return rows, {
        "message_count": len(rows),
        "feature_message_count": counts["feature"],
        "imu_message_count": counts["imu"],
        "ordered_topic_header_record_sha256": digest.hexdigest(),
    }


def imu_semantic_digest(
    rows: Sequence[tuple[int, int, tuple[float, float, float, float, float, float]]]
) -> str:
    digest = hashlib.sha256()
    for header_ns, record_ns, values in rows:
        digest.update(struct.pack(">qq6d", header_ns, record_ns, *values))
    return digest.hexdigest()


def bag_imu_rows(
    path: Path, topic: str
) -> tuple[
    list[tuple[int, int, tuple[float, float, float, float, float, float]]],
    dict[str, object],
]:
    rosbag = pinned_rosbag()
    rows: list[tuple[int, int, tuple[float, float, float, float, float, float]]] = []
    message_types: set[str] = set()
    with rosbag.Bag(str(path), "r") as bag:
        for _, message, record_time in bag.read_messages(topics=[topic]):
            message_types.add(str(getattr(message, "_type", "")))
            values = (
                float(message.angular_velocity.x),
                float(message.angular_velocity.y),
                float(message.angular_velocity.z),
                float(message.linear_acceleration.x),
                float(message.linear_acceleration.y),
                float(message.linear_acceleration.z),
            )
            if not all(math.isfinite(value) for value in values):
                raise ContractError(f"IMU_NONFINITE:{path}:{topic}")
            rows.append(
                (
                    int(message.header.stamp.to_nsec()),
                    int(record_time.to_nsec()),
                    values,
                )
            )
    if (
        not rows
        or message_types != {"sensor_msgs/Imu"}
        or any(right[0] <= left[0] for left, right in zip(rows, rows[1:]))
        or any(right[1] <= left[1] for left, right in zip(rows, rows[1:]))
    ):
        raise ContractError(f"IMU_BAG_SERIES_INVALID:{path}:{topic}")
    return rows, {
        "topic": topic,
        "message_type": "sensor_msgs/Imu",
        "message_count": len(rows),
        "first_header_ns": rows[0][0],
        "last_header_ns": rows[-1][0],
        "first_record_ns": rows[0][1],
        "last_record_ns": rows[-1][1],
        "ordered_header_record_six_axis_sha256": imu_semantic_digest(rows),
    }


def matched_imu_csv(
    rows: Sequence[tuple[int, int, tuple[float, float, float, float, float, float]]],
    td_seconds: str,
    selected: Sequence[int],
    label: str,
) -> tuple[bytes, list[int], dict[str, object]]:
    td = Decimal(td_seconds)
    one_billion = Decimal(1_000_000_000)
    shifted: list[int] = []
    residuals: list[Decimal] = []
    lines = [
        "#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],"
        "w_RS_S_z [rad s^-1],a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],"
        "a_RS_S_z [m s^-2]"
    ]
    max_float32_error = 0.0
    for header_ns, _, values in rows:
        exact = Decimal(header_ns) - td * one_billion
        stamp = int(exact.to_integral_value(rounding=ROUND_HALF_EVEN))
        shifted.append(stamp)
        residuals.append(abs(Decimal(stamp) - exact))
        for value in values:
            float32 = struct.unpack(">f", struct.pack(">f", value))[0]
            max_float32_error = max(max_float32_error, abs(float32 - value))
        value_tokens = [format(value, ".17g") for value in values]
        if any(float(token) != value for token, value in zip(value_tokens, values)):
            raise ContractError(f"IMU_CSV_FLOAT_ROUNDTRIP_FAILED:{label}")
        lines.append(",".join([str(stamp), *value_tokens]))
    if any(right <= left for left, right in zip(shifted, shifted[1:])):
        raise ContractError(f"MATCHED_IMU_TIMESTAMPS_NOT_STRICT:{label}")
    bag_headers = [row[0] for row in rows]
    integer_vins_predecessors = [
        bisect.bisect_right(
            bag_headers, Decimal(camera_ns) + td * one_billion
        ) - 1
        for camera_ns in selected
    ]
    integer_hfnet_predecessors = [
        bisect.bisect_right(shifted, camera_ns) - 1 for camera_ns in selected
    ]

    # Reproduce both native programs' binary64 conversions and different
    # boundary operators.  This catches equality/rounding cases hidden by an
    # ideal integer-nanosecond comparison.
    def ros_seconds(ns: int) -> float:
        seconds, nanoseconds = divmod(ns, 1_000_000_000)
        return float(seconds) + float(nanoseconds) * 1e-9

    def euroc_seconds(ns: int) -> float:
        return float(ns) / 1e9

    td_binary64 = float(td_seconds)
    vins_imu_seconds = [ros_seconds(value) for value in bag_headers]
    vins_cutoffs = [ros_seconds(value) + td_binary64 for value in selected]
    hfnet_imu_seconds = [euroc_seconds(value) for value in shifted]
    hfnet_camera_seconds = [euroc_seconds(value) for value in selected]
    if (
        any(
            right <= left
            for left, right in zip(vins_imu_seconds, vins_imu_seconds[1:])
        )
        or any(
            right <= left
            for left, right in zip(hfnet_imu_seconds, hfnet_imu_seconds[1:])
        )
    ):
        raise ContractError(f"NATIVE_BINARY64_IMU_TIMESTAMPS_NOT_STRICT:{label}")
    vins_predecessors = [
        bisect.bisect_left(vins_imu_seconds, cutoff) - 1
        for cutoff in vins_cutoffs
    ]
    hfnet_predecessors = [
        bisect.bisect_right(hfnet_imu_seconds, cutoff) - 1
        for cutoff in hfnet_camera_seconds
    ]

    def nearest_margin(values: Sequence[float], cutoff: float) -> float:
        position = bisect.bisect_left(values, cutoff)
        candidates = []
        if position < len(values):
            candidates.append(abs(values[position] - cutoff))
        if position:
            candidates.append(abs(values[position - 1] - cutoff))
        return min(candidates)

    native_margins = [
        nearest_margin(vins_imu_seconds, cutoff) for cutoff in vins_cutoffs
    ] + [
        nearest_margin(hfnet_imu_seconds, cutoff)
        for cutoff in hfnet_camera_seconds
    ]
    if (
        vins_predecessors != hfnet_predecessors
        or any(index < 0 or index + 1 >= len(rows) for index in vins_predecessors)
    ):
        raise ContractError(f"CROSS_BACKEND_IMU_CUTOFF_MISMATCH:{label}")
    bracket = imu_bracket(shifted, selected, label)
    payload = "\n".join(lines).encode("ascii")
    return payload, shifted, {
        "canonical_td_seconds": td_seconds,
        "timestamp_formula": "round_half_even(bag_header_ns-td_seconds*1e9)",
        "message_count": len(rows),
        "integer_timestamp_shift_ns": shifted[0] - rows[0][0],
        "maximum_rounding_residual_ns": float(max(residuals, default=Decimal(0))),
        "six_axis_csv_roundtrip": True,
        "native_hfnet_float32_max_absolute_quantization": max_float32_error,
        "matched_imu_bracket": bracket,
        "all_camera_predecessor_indices_equal": True,
        "native_predecessor_comparison": {
            "vins_timestamp_conversion": "ros_sec_plus_nsec_times_1e-9_binary64",
            "vins_cutoff": "imu_timestamp_strictly_less_than_camera_plus_td",
            "hfnet_timestamp_conversion": "stod_integer_ns_divided_by_1e9_binary64",
            "hfnet_cutoff": "shifted_imu_timestamp_less_than_or_equal_to_camera",
            "minimum_boundary_margin_seconds": min(native_margins),
            "minimum_boundary_margin_nanoseconds": min(native_margins) * 1e9,
            "boundary_equality_count": sum(value == 0.0 for value in native_margins),
        },
        "integer_clock_predecessor_indices_equal": (
            integer_vins_predecessors == integer_hfnet_predecessors
        ),
        "camera_predecessor_index_sha256": list_digest(vins_predecessors),
        "camera_cutoff_count": len(vins_predecessors),
    }


def list_digest(values: Iterable[int]) -> str:
    payload = "".join(f"{value}\n" for value in values).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def validate_mapping(selected: Sequence[int], feature: Sequence[int], label: str) -> dict[str, object]:
    if len(selected) != len(feature):
        raise ContractError(f"FEATURE_COUNT_MISMATCH:{label}")
    deltas = [abs(left - right) for left, right in zip(selected, feature)]
    if max(deltas, default=0) > ASSOCIATION_TOLERANCE_NS:
        raise ContractError(f"FEATURE_TIMESTAMP_PHASE_MISMATCH:{label}")
    return {
        "feature_count": len(feature),
        "feature_timestamp_sha256": list_digest(feature),
        "max_absolute_header_delta_ns": max(deltas, default=0),
        "bijection_within_256ns": True,
    }


def parse_imu_stamps(path: Path) -> list[int]:
    stamps: list[int] = []
    with path.open(newline="", encoding="ascii") as stream:
        for row in csv.reader(stream):
            if not row or row[0].startswith("#"):
                continue
            stamps.append(int(row[0]))
    if not stamps or any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise ContractError(f"IMU_TIMESTAMPS_INVALID:{path}")
    return stamps


def imu_bracket(stamps: Sequence[int], selected: Sequence[int], label: str) -> dict[str, int]:
    first_right = bisect.bisect_right(stamps, selected[0])
    last_right = bisect.bisect_right(stamps, selected[-1])
    if first_right == 0 or first_right >= len(stamps) or last_right == 0 or last_right >= len(stamps):
        raise ContractError(f"IMU_BRACKET_INVALID:{label}")
    return {
        "first_camera_ns": selected[0],
        "first_predecessor_imu_ns": stamps[first_right - 1],
        "first_successor_imu_ns": stamps[first_right],
        "last_camera_ns": selected[-1],
        "last_predecessor_imu_ns": stamps[last_right - 1],
        "last_successor_imu_ns": stamps[last_right],
    }


def image_inventory(input_root: Path, selected: Sequence[int]) -> dict[str, object]:
    digest = hashlib.sha256()
    total = 0
    for stamp in selected:
        image_path = input_root / "mav0/cam0/data" / f"{stamp}.png"
        item = identity(image_path)
        total += int(item["size_bytes"])
        digest.update(f"{stamp}\0{item['size_bytes']}\0{item['sha256']}\n".encode("ascii"))
    return {
        "image_count": len(selected),
        "total_bytes": total,
        "ordered_image_inventory_sha256": digest.hexdigest(),
    }


def frozen_schedule() -> list[dict[str, object]]:
    arms = ["learned_klt_vins", "pure_klt_vins", "hfnet_openloop_675", "hfnet_openloop_350"]
    schedule: list[dict[str, object]] = []
    ordinal = 0
    for repeat in REPEATS:
        case_rotation = (repeat - 1) * 3
        cases = CASE_ORDER[case_rotation:] + CASE_ORDER[:case_rotation]
        for case_position, case_id in enumerate(cases):
            arm_rotation = (case_position + repeat - 1) % len(arms)
            ordered_arms = arms[arm_rotation:] + arms[:arm_rotation]
            for arm in ordered_arms:
                ordinal += 1
                schedule.append(
                    {"ordinal": ordinal, "case_id": case_id, "arm": arm, "repeat": repeat}
                )
    return schedule


def freeze_inputs() -> dict[str, object]:
    if EXPERIMENT_ROOT.exists() or EXPERIMENT_ROOT.is_symlink():
        raise ContractError(f"EXPERIMENT_NAMESPACE_EXISTS:{EXPERIMENT_ROOT}")
    rows = load_roster()
    historical = load_historical_rows()
    control_documents = control_document_identities()
    stack = {
        "binary": require_identity(BINARY, *EXPECTED_STACK["binary"], "binary"),
        "official_library": require_identity(
            OFFICIAL_LIBRARY, *EXPECTED_STACK["official_library"], "official_library"
        ),
        "shared_onnx": require_identity(SHARED_ONNX, *EXPECTED_STACK["onnx"], "onnx"),
        "shared_cache_seed": require_identity(SHARED_CACHE, *EXPECTED_STACK["cache"], "cache"),
    }
    cases: dict[str, dict[str, object]] = {}
    selected_by_case: dict[str, list[int]] = {}
    matched_imu_by_case: dict[str, tuple[bytes, list[int]]] = {}
    for case_id in CASE_ORDER:
        row = rows[case_id]
        input_root = Path(row["input_root"])
        if input_root.is_symlink() or not input_root.is_dir():
            raise ContractError(f"INPUT_ROOT_INVALID:{case_id}")
        config_path = Path(row["base_config"])
        config = identity(config_path)
        if config["sha256"] != EXPECTED_CONFIGS[row["dataset"]]:
            raise ContractError(f"BASE_CONFIG_IDENTITY_MISMATCH:{case_id}")
        indices, selected = selected_source_stamps(row)
        selected_by_case[case_id] = selected
        learned_path = Path(row["learned_klt_bag"])
        klt_path = Path(row["klt_bag"])
        learned_identity = identity(learned_path)
        klt_identity = identity(klt_path)
        if learned_identity["sha256"] != row["learned_klt_sha256"]:
            raise ContractError(f"LEARNED_BAG_IDENTITY_MISMATCH:{case_id}")
        if klt_identity["sha256"] != row["klt_sha256"]:
            raise ContractError(f"KLT_BAG_IDENTITY_MISMATCH:{case_id}")
        learned_mapping = validate_mapping(selected, bag_feature_stamps(learned_path), f"{case_id}:learned")
        klt_mapping = validate_mapping(selected, bag_feature_stamps(klt_path), f"{case_id}:klt")
        source_config = source_vins_config(historical[case_id])
        clock = parse_vins_imu_clock(source_config)
        canonical_td = CANONICAL_TD_SECONDS[row["dataset"]]
        learned_imu, learned_imu_meta = bag_imu_rows(
            learned_path, clock["imu_topic"]
        )
        klt_imu, klt_imu_meta = bag_imu_rows(klt_path, clock["imu_topic"])
        if learned_imu != klt_imu or learned_imu_meta != klt_imu_meta:
            raise ContractError(f"CROSS_VINS_ARM_IMU_MISMATCH:{case_id}")
        learned_replay, learned_replay_meta = bag_replay_schedule(
            learned_path, clock["imu_topic"]
        )
        klt_replay, klt_replay_meta = bag_replay_schedule(
            klt_path, clock["imu_topic"]
        )
        if learned_replay != klt_replay or learned_replay_meta != klt_replay_meta:
            raise ContractError(f"CROSS_VINS_ARM_REPLAY_SCHEDULE_MISMATCH:{case_id}")
        imu_payload, matched_stamps, matched_generation = matched_imu_csv(
            learned_imu, canonical_td, selected, case_id
        )
        matched_imu_by_case[case_id] = (imu_payload, matched_stamps)
        source_imu_path = input_root / "mav0/imu0/data.csv"
        materialization = input_root / "materialization_manifest.json"
        cases[case_id] = {
            "case_id": case_id,
            "dataset": row["dataset"],
            "source_input_root": str(input_root),
            "input_root": str(EXPERIMENT_ROOT / "runtime_input" / case_id),
            "source_camera_count": int(row["source_camera_count"]),
            "selected_camera_count": len(selected),
            "selected_source_indices": indices,
            "selected_header_ns_inclusive": [selected[0], selected[-1]],
            "selected_timestamp_sha256": list_digest(selected),
            "selection": row["selection"],
            "nominal_fps": int(row["nominal_fps"]),
            "base_config": config,
            "source_vins_config": identity(source_config),
            "source_vins_td_seconds": clock["source_td_seconds"],
            "canonical_dataset_td_seconds": canonical_td,
            "source_td_replaced_by_dataset_canonical": (
                Decimal(clock["source_td_seconds"]) != Decimal(canonical_td)
            ),
            "imu_topic": clock["imu_topic"],
            "source_times": identity(input_root / "cam0_times.txt"),
            "source_materialization_manifest": identity(materialization),
            "source_imu": identity(source_imu_path),
            "source_imu_bracket": imu_bracket(
                parse_imu_stamps(source_imu_path), selected, case_id
            ),
            "source_images": image_inventory(input_root, selected),
            "learned_klt_bag": learned_identity,
            "pure_klt_bag": klt_identity,
            "learned_mapping": learned_mapping,
            "klt_mapping": klt_mapping,
            "cross_vins_arm_imu": {
                "exact_semantic_equality": True,
                "learned": learned_imu_meta,
                "pure_klt": klt_imu_meta,
            },
            "cross_vins_arm_replay_schedule": {
                "exact_feature_imu_header_record_interleaving": True,
                "learned": learned_replay_meta,
                "pure_klt": klt_replay_meta,
            },
            "matched_imu_generation": matched_generation,
            "native_backend_input_semantics": {
                "available_physical_imu_samples_and_clock_matched": True,
                "identical_estimator_ingress_or_preroll_consumption_claimed": False,
                "hfnet_internal_imu_storage": "float32",
                "vins_internal_imu_storage": "float64",
            },
        }

    staging = EXPERIMENT_ROOT.parent / f".{EXPERIMENT_ROOT.name}.staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    try:
        seed_root = staging / "runtime_seed/HFNet-RT"
        seed_root.mkdir(parents=True)
        seed_onnx = atomic_copy(SHARED_ONNX, seed_root / "HF-Net.onnx", 0o444)
        seed_cache = atomic_copy(SHARED_CACHE, seed_root / "HF-Net.cache", 0o444)
        seed_onnx["path"] = str(EXPERIMENT_ROOT / "runtime_seed/HFNet-RT/HF-Net.onnx")
        seed_cache["path"] = str(EXPERIMENT_ROOT / "runtime_seed/HFNet-RT/HF-Net.cache")
        for case_id, selected in selected_by_case.items():
            case_root = staging / "input_freeze" / case_id
            runtime_root = staging / "runtime_input" / case_id
            runtime_image_root = runtime_root / "mav0/cam0/data"
            runtime_image_root.mkdir(parents=True)
            source_root = Path(str(cases[case_id]["source_input_root"]))
            for stamp in selected:
                source_image = source_root / "mav0/cam0/data" / f"{stamp}.png"
                identity(source_image)
                os.link(
                    source_image,
                    runtime_image_root / source_image.name,
                    follow_symlinks=False,
                )
            os.link(
                source_root / "cam0_times.txt",
                runtime_root / "cam0_times.txt",
                follow_symlinks=False,
            )
            imu_payload, matched_stamps = matched_imu_by_case[case_id]
            runtime_imu = runtime_root / "mav0/imu0/data.csv"
            write_exclusive(runtime_imu, imu_payload)
            runtime_imu_identity = identity(runtime_imu)
            runtime_imu_identity["path"] = str(
                EXPERIMENT_ROOT / "runtime_input" / case_id / "mav0/imu0/data.csv"
            )
            runtime_times_identity = identity(runtime_root / "cam0_times.txt")
            runtime_times_identity["path"] = str(
                EXPERIMENT_ROOT / "runtime_input" / case_id / "cam0_times.txt"
            )
            cases[case_id]["imu"] = runtime_imu_identity
            cases[case_id]["imu_bracket"] = imu_bracket(
                matched_stamps, selected, case_id
            )
            cases[case_id]["runtime_input_cam0_times"] = runtime_times_identity
            cases[case_id]["images"] = image_inventory(runtime_root, selected)
            if cases[case_id]["images"] != cases[case_id]["source_images"]:
                raise ContractError(f"RUNTIME_IMAGE_INVENTORY_MISMATCH:{case_id}")
            times_payload = "".join(f"{stamp}\n" for stamp in selected).encode("ascii")
            write_exclusive(case_root / "cam0_times_vins_matched.txt", times_payload)
            cases[case_id]["selected_times_file"] = identity(
                case_root / "cam0_times_vins_matched.txt"
            )
            cases[case_id]["selected_times_file"]["path"] = str(
                EXPERIMENT_ROOT / "input_freeze" / case_id / "cam0_times_vins_matched.txt"
            )
            write_exclusive(case_root / "case_manifest.json", canonical_json(cases[case_id]))
        schedule = frozen_schedule()
        write_exclusive(staging / "planned_schedule.json", canonical_json(schedule))
        schedule_identity = identity(staging / "planned_schedule.json")
        schedule_identity["path"] = str(EXPERIMENT_ROOT / "planned_schedule.json")
        manifest = {
            "schema_version": "aqua-fe-fair-stability-hfnet-input-freeze-v9",
            "experiment_id": EXPERIMENT_ID,
            "status": "FROZEN_INPUTS_NO_ESTIMATOR_STARTED",
            "created_at_utc": now_utc(),
            "protocol": identity(PROTOCOL),
            "roster": identity(ROSTER),
            "historical_results": identity(HISTORICAL_RESULTS),
            "historical_manifest": identity(HISTORICAL_MANIFEST),
            "control_documents": control_documents,
            "execution_controls": {
                "ordinal_common": identity(ORDINAL_COMMON),
                "runtime_resource_monitor": identity(RUNTIME_RESOURCE_MONITOR),
                "systemd_supervisor": identity(SYSTEMD_SUPERVISOR),
            },
            "runner": identity(RUNNER),
            "stack": stack,
            "runtime_seed": {"onnx": seed_onnx, "cache": seed_cache},
            "cases": cases,
            "planned_schedule": schedule_identity,
            "claims": {
                "same_camera_timestamps_verified": True,
                "cross_arm_imu_semantics_exact_before_clock_normalization": True,
                "cross_vins_arm_replay_schedule_exact": True,
                "dataset_canonical_td_shared_across_windows": True,
                "available_imu_samples_and_camera_cutoff_matched": True,
                "identical_native_backend_imu_consumption_claimed": False,
                "loop_closing_disabled_at_runtime_config_generation": True,
                "outcome_selected_roster": True,
                "system_ranking_supported": False,
                "estimator_started": False,
                "runtime_exclusivity_monitor_required": True,
                "v1_results_imported": False,
                "v2_results_imported": False,
                "v3_results_imported": False,
                "v4_results_imported": False,
                "v5_results_imported": False,
                "v6_results_imported": False,
                "v7_results_imported": False,
                "v8_results_imported": False,
                "todesk_exemption": False,
            },
        }
        write_exclusive(staging / "experiment_manifest.json", canonical_json(manifest))
        os.rename(staging, EXPERIMENT_ROOT)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return manifest


def load_experiment() -> dict[str, Any]:
    load_roster()
    load_historical_rows()
    manifest_path = EXPERIMENT_ROOT / "experiment_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "aqua-fe-fair-stability-hfnet-input-freeze-v9":
        raise ContractError("EXPERIMENT_MANIFEST_SCHEMA_MISMATCH")
    if manifest.get("experiment_id") != EXPERIMENT_ID:
        raise ContractError("EXPERIMENT_ID_MISMATCH")
    if manifest.get("status") != "FROZEN_INPUTS_NO_ESTIMATOR_STARTED":
        raise ContractError("EXPERIMENT_MANIFEST_STATUS_MISMATCH")
    require_recorded_identity(manifest.get("protocol"), PROTOCOL, "protocol")
    require_recorded_identity(manifest.get("roster"), ROSTER, "roster")
    require_recorded_identity(
        manifest.get("historical_results"), HISTORICAL_RESULTS, "historical_results"
    )
    require_recorded_identity(
        manifest.get("historical_manifest"), HISTORICAL_MANIFEST, "historical_manifest"
    )
    if manifest["protocol"]["sha256"] != EXPECTED_PROTOCOL_SHA256:
        raise ContractError("EXPERIMENT_PROTOCOL_PIN_MISMATCH")
    if manifest["roster"]["sha256"] != EXPECTED_ROSTER_SHA256:
        raise ContractError("EXPERIMENT_ROSTER_PIN_MISMATCH")
    if (
        manifest.get("claims", {}).get("v1_results_imported") is not False
        or manifest.get("claims", {}).get("v2_results_imported") is not False
        or manifest.get("claims", {}).get("v3_results_imported") is not False
        or manifest.get("claims", {}).get("v4_results_imported") is not False
        or manifest.get("claims", {}).get("v5_results_imported") is not False
        or manifest.get("claims", {}).get("v6_results_imported") is not False
        or manifest.get("claims", {}).get("v7_results_imported") is not False
        or manifest.get("claims", {}).get("v8_results_imported") is not False
        or manifest.get("claims", {}).get(
            "cross_arm_imu_semantics_exact_before_clock_normalization"
        ) is not True
        or manifest.get("claims", {}).get(
            "cross_vins_arm_replay_schedule_exact"
        ) is not True
        or manifest.get("claims", {}).get(
            "dataset_canonical_td_shared_across_windows"
        ) is not True
        or manifest.get("claims", {}).get(
            "available_imu_samples_and_camera_cutoff_matched"
        ) is not True
        or manifest.get("claims", {}).get(
            "identical_native_backend_imu_consumption_claimed"
        ) is not False
    ):
        raise ContractError("PRIOR_RESULTS_IMPORT_BOUNDARY_INVALID")
    for label, (path, _, _) in EXPECTED_CONTROL_DOCUMENTS.items():
        require_recorded_identity(
            manifest.get("control_documents", {}).get(label), path, label
        )
    for label, path in (
        ("ordinal_common", ORDINAL_COMMON),
        ("runtime_resource_monitor", RUNTIME_RESOURCE_MONITOR),
        ("systemd_supervisor", SYSTEMD_SUPERVISOR),
    ):
        require_recorded_identity(
            manifest.get("execution_controls", {}).get(label), path, label
        )
    require_recorded_identity(manifest.get("runner"), RUNNER, "runner")
    for label, path in (
        ("binary", BINARY),
        ("official_library", OFFICIAL_LIBRARY),
        ("shared_onnx", SHARED_ONNX),
        ("shared_cache_seed", SHARED_CACHE),
    ):
        require_recorded_identity(
            manifest.get("stack", {}).get(label), path, f"stack:{label}"
        )
    for label, path in (
        ("onnx", EXPERIMENT_ROOT / "runtime_seed/HFNet-RT/HF-Net.onnx"),
        ("cache", EXPERIMENT_ROOT / "runtime_seed/HFNet-RT/HF-Net.cache"),
    ):
        require_recorded_identity(
            manifest.get("runtime_seed", {}).get(label), path, f"runtime_seed:{label}"
        )
    schedule_path = EXPERIMENT_ROOT / "planned_schedule.json"
    schedule_identity = require_recorded_identity(
        manifest.get("planned_schedule"), schedule_path, "planned_schedule"
    )
    if schedule_identity["sha256"] != SCHEDULE_SHA256:
        raise ContractError("PLANNED_SCHEDULE_PIN_MISMATCH")
    cases = manifest.get("cases")
    if (
        not isinstance(cases, Mapping)
        or len(cases) != len(CASE_ORDER)
        or set(cases) != set(CASE_ORDER)
    ):
        raise ContractError("FROZEN_CASE_SET_MISMATCH")
    for case_id in CASE_ORDER:
        case = cases[case_id]
        if not isinstance(case, Mapping):
            raise ContractError(f"FROZEN_CASE_INVALID:{case_id}")
        case_path = EXPERIMENT_ROOT / "input_freeze" / case_id / "case_manifest.json"
        recorded_case = json.loads(case_path.read_text(encoding="utf-8"))
        if recorded_case != case:
            raise ContractError(f"FROZEN_CASE_MANIFEST_DRIFT:{case_id}")
        require_recorded_identity(
            case.get("selected_times_file"),
            EXPERIMENT_ROOT / "input_freeze" / case_id / "cam0_times_vins_matched.txt",
            f"selected_times:{case_id}",
        )
        selected = read_ns_lines(
            EXPERIMENT_ROOT / "input_freeze" / case_id / "cam0_times_vins_matched.txt"
        )
        runtime_root = EXPERIMENT_ROOT / "runtime_input" / case_id
        if case.get("input_root") != str(runtime_root):
            raise ContractError(f"RUNTIME_INPUT_ROOT_DRIFT:{case_id}")
        for key, path in (
            ("source_vins_config", Path(str(case["source_vins_config"]["path"]))),
            ("source_times", Path(str(case["source_times"]["path"]))),
            (
                "source_materialization_manifest",
                Path(str(case["source_materialization_manifest"]["path"])),
            ),
            ("source_imu", Path(str(case["source_imu"]["path"]))),
            ("runtime_input_cam0_times", runtime_root / "cam0_times.txt"),
            ("imu", runtime_root / "mav0/imu0/data.csv"),
            ("learned_klt_bag", Path(str(case["learned_klt_bag"]["path"]))),
            ("pure_klt_bag", Path(str(case["pure_klt_bag"]["path"]))),
        ):
            require_recorded_identity(case.get(key), path, f"case:{case_id}:{key}")
        clock = parse_vins_imu_clock(Path(str(case["source_vins_config"]["path"])))
        canonical_td = CANONICAL_TD_SECONDS[str(case["dataset"])]
        if (
            case.get("imu_topic") != clock["imu_topic"]
            or case.get("source_vins_td_seconds") != clock["source_td_seconds"]
            or case.get("canonical_dataset_td_seconds") != canonical_td
            or case.get("source_td_replaced_by_dataset_canonical")
            is not (Decimal(clock["source_td_seconds"]) != Decimal(canonical_td))
        ):
            raise ContractError(f"CASE_IMU_CLOCK_RECEIPT_DRIFT:{case_id}")
        learned_imu, learned_meta = bag_imu_rows(
            Path(str(case["learned_klt_bag"]["path"])), clock["imu_topic"]
        )
        klt_imu, klt_meta = bag_imu_rows(
            Path(str(case["pure_klt_bag"]["path"])), clock["imu_topic"]
        )
        if learned_imu != klt_imu or learned_meta != klt_meta:
            raise ContractError(f"FROZEN_CROSS_ARM_IMU_DRIFT:{case_id}")
        if case.get("cross_vins_arm_imu") != {
            "exact_semantic_equality": True,
            "learned": learned_meta,
            "pure_klt": klt_meta,
        }:
            raise ContractError(f"FROZEN_CROSS_ARM_IMU_RECEIPT_DRIFT:{case_id}")
        learned_replay, learned_replay_meta = bag_replay_schedule(
            Path(str(case["learned_klt_bag"]["path"])), clock["imu_topic"]
        )
        klt_replay, klt_replay_meta = bag_replay_schedule(
            Path(str(case["pure_klt_bag"]["path"])), clock["imu_topic"]
        )
        if learned_replay != klt_replay or learned_replay_meta != klt_replay_meta:
            raise ContractError(f"FROZEN_CROSS_ARM_REPLAY_SCHEDULE_DRIFT:{case_id}")
        if case.get("cross_vins_arm_replay_schedule") != {
            "exact_feature_imu_header_record_interleaving": True,
            "learned": learned_replay_meta,
            "pure_klt": klt_replay_meta,
        }:
            raise ContractError(
                f"FROZEN_CROSS_ARM_REPLAY_SCHEDULE_RECEIPT_DRIFT:{case_id}"
            )
        payload, shifted, generation = matched_imu_csv(
            learned_imu, canonical_td, selected, case_id
        )
        runtime_imu = runtime_root / "mav0/imu0/data.csv"
        if hashlib.sha256(payload).hexdigest() != identity(runtime_imu)["sha256"]:
            raise ContractError(f"MATCHED_IMU_PAYLOAD_DRIFT:{case_id}")
        if case.get("matched_imu_generation") != generation:
            raise ContractError(f"MATCHED_IMU_GENERATION_RECEIPT_DRIFT:{case_id}")
        if case.get("imu_bracket") != imu_bracket(shifted, selected, case_id):
            raise ContractError(f"MATCHED_IMU_BRACKET_DRIFT:{case_id}")
        if image_inventory(runtime_root, selected) != case.get("images"):
            raise ContractError(f"MATCHED_IMAGE_INVENTORY_DRIFT:{case_id}")
    for label, path, expected in (
        ("binary", BINARY, EXPECTED_STACK["binary"]),
        ("official_library", OFFICIAL_LIBRARY, EXPECTED_STACK["official_library"]),
        ("shared_onnx", SHARED_ONNX, EXPECTED_STACK["onnx"]),
        ("shared_cache", SHARED_CACHE, EXPECTED_STACK["cache"]),
    ):
        require_identity(path, *expected, label)
    return manifest


def attempt_root(case_id: str, budget: int, repeat: int, attempt_index: int = 1) -> Path:
    base = EXPERIMENT_ROOT / f"hfnet_openloop_{budget}" / case_id / f"repeat_{repeat:03d}"
    if attempt_index != 1:
        raise ContractError("ATTEMPT_INDEX_INVALID")
    return base


def patch_config(base: Path, local_model_dir: Path, fps: int, budget: int) -> tuple[bytes, list[dict[str, object]]]:
    source = base.read_text(encoding="utf-8")
    substitutions = [
        (
            r'^Extractor\.modelPath: "/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT/"$',
            f'Extractor.modelPath: "{local_model_dir}/"',
            "model_path",
        ),
        (r"^Camera\.fps: (?:20|5\.0)$", f"Camera.fps: {fps}", "camera_fps"),
        (r"^Extractor\.nFeatures: 675$", f"Extractor.nFeatures: {budget}", "feature_budget"),
        (r"^loopClosing: 1$", "loopClosing: 0", "loop_closing"),
    ]
    receipts: list[dict[str, object]] = []
    for pattern, replacement, label in substitutions:
        source, count = re.subn(pattern, replacement, source, flags=re.MULTILINE)
        if count != 1:
            raise ContractError(f"CONFIG_SUBSTITUTION_COUNT:{label}:{count}")
        receipts.append({"label": label, "pattern": pattern, "replacement": replacement, "count": count})
    return source.encode("utf-8"), receipts


def validate_generated_config(path: Path, fps: int, budget: int, model_dir: Path) -> dict[str, object]:
    try:
        import cv2  # type: ignore
    except ImportError as error:
        raise ContractError("OPENCV_IMPORT_FAILED") from error
    storage = cv2.FileStorage(str(path), cv2.FILE_STORAGE_READ)
    if not storage.isOpened():
        raise ContractError(f"OPENCV_CONFIG_OPEN_FAILED:{path}")
    try:
        observed = {
            "Camera.fps": int(storage.getNode("Camera.fps").real()),
            "Extractor.nFeatures": int(storage.getNode("Extractor.nFeatures").real()),
            "loopClosing": int(storage.getNode("loopClosing").real()),
            "Extractor.modelPath": storage.getNode("Extractor.modelPath").string(),
        }
    finally:
        storage.release()
    expected = {
        "Camera.fps": fps,
        "Extractor.nFeatures": budget,
        "loopClosing": 0,
        "Extractor.modelPath": f"{model_dir}/",
    }
    if observed != expected:
        raise ContractError(f"GENERATED_CONFIG_VALUE_MISMATCH:{observed}:{expected}")
    return observed


def backend_freeze_identity() -> dict[str, object]:
    observed = identity(BACKEND_FREEZE)
    freeze = json.loads(BACKEND_FREEZE.read_text(encoding="utf-8"))
    if freeze.get("status") != "FROZEN_BEFORE_NEW_VINS_REPLAY":
        raise ContractError("BACKEND_FREEZE_STATUS_INVALID")
    if freeze.get("experiment_id") != EXPERIMENT_ID:
        raise ContractError("BACKEND_FREEZE_EXPERIMENT_ID_MISMATCH")
    claims = freeze.get("claims")
    if not isinstance(claims, Mapping) or any(
        claims.get(f"v{version}_results_imported") is not False
        for version in range(1, 9)
    ):
        raise ContractError("BACKEND_FREEZE_PRIOR_RESULTS_IMPORT_CLAIM_INVALID")
    require_recorded_identity(
        freeze.get("parent_experiment_manifest"),
        EXPERIMENT_ROOT / "experiment_manifest.json",
        "backend_freeze_parent_experiment_manifest",
    )
    return observed


def prepare_attempt(
    case_id: str,
    budget: int,
    repeat: int,
    attempt_index: int = 1,
    *,
    _verified_manifest: Mapping[str, Any] | None = None,
    _verified_backend: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if (_verified_manifest is None) != (_verified_backend is None):
        raise ContractError("PARTIAL_PREVERIFIED_PREPARATION_CONTEXT")
    manifest = load_experiment() if _verified_manifest is None else _verified_manifest
    frozen_backend = (
        backend_freeze_identity()
        if _verified_backend is None
        else _verified_backend
    )
    if case_id not in manifest["cases"] or budget not in BUDGETS or repeat not in REPEATS:
        raise ContractError("ATTEMPT_COORDINATE_INVALID")
    case = manifest["cases"][case_id]
    if attempt_index < 1 or attempt_index > MAX_ATTEMPTS_PER_CELL:
        raise ContractError("ATTEMPT_INDEX_INVALID")
    arm = f"hfnet_openloop_{budget}"
    root = attempt_root(case_id, budget, repeat, attempt_index)
    if attempt_index > 1:
        state = ordinal_next_state(EXPERIMENT_ROOT)
        state_cell = state.get("cell")
        if (
            state.get("state") != "NEEDS_PREPARATION"
            or not isinstance(state_cell, Mapping)
            or not strict_json_equal(
                [
                    state_cell.get("case_id"),
                    state_cell.get("arm"),
                    state_cell.get("repeat"),
                    state.get("attempt_index"),
                    state.get("attempt_root"),
                ],
                [case_id, arm, repeat, attempt_index, str(root)],
            )
        ):
            raise ContractError("REPLENISHMENT_NOT_AUTHORIZED_BY_ORDINAL_STATE")
    root.mkdir(parents=True, exist_ok=False)
    try:
        result_dir = root / "result"
        model_dir = root / "run_local_model/HFNet-RT"
        result_dir.mkdir(parents=True)
        model_dir.mkdir(parents=True)
        seed_onnx = EXPERIMENT_ROOT / "runtime_seed/HFNet-RT/HF-Net.onnx"
        seed_cache = EXPERIMENT_ROOT / "runtime_seed/HFNet-RT/HF-Net.cache"
        local_onnx = model_dir / "HF-Net.onnx"
        local_cache = model_dir / "HF-Net.cache"
        os.link(seed_onnx, local_onnx, follow_symlinks=False)
        os.chmod(local_onnx, 0o444)
        cache_pre = atomic_copy(seed_cache, local_cache, 0o644)
        selected_source = (
            EXPERIMENT_ROOT / "input_freeze" / case_id / "cam0_times_vins_matched.txt"
        )
        selected_local = root / "cam0_times_vins_matched.txt"
        os.link(selected_source, selected_local, follow_symlinks=False)
        config_payload, patch_receipt = patch_config(
            Path(case["base_config"]["path"]),
            model_dir,
            int(case["nominal_fps"]),
            budget,
        )
        config_path = root / "runtime_config_openloop.yaml"
        write_exclusive(config_path, config_payload)
        config_values = validate_generated_config(
            config_path, int(case["nominal_fps"]), budget, model_dir
        )
        attempt = {
            "schema_version": "aqua-fe-fair-stability-hfnet-attempt-v9",
            "experiment_id": EXPERIMENT_ID,
            "status": "PREPARED_NOT_STARTED",
            "prepared_at_utc": now_utc(),
            "case_id": case_id,
            "budget": budget,
            "arm": f"hfnet_openloop_{budget}",
            "repeat": repeat,
            "planned_repeat": repeat,
            "attempt_index": attempt_index,
            "replenishes_invalid_attempt": None,
            "maximum_replacement_attempts": MAX_REPLACEMENT_ATTEMPTS_PER_CELL,
            "maximum_total_attempts": MAX_ATTEMPTS_PER_CELL,
            "attempt_root": str(root),
            "backend_freeze": frozen_backend,
            "case_manifest": identity(
                EXPERIMENT_ROOT / "input_freeze" / case_id / "case_manifest.json"
            ),
            "selected_times": identity(selected_local),
            "base_config": case["base_config"],
            "runtime_config": identity(config_path),
            "config_patch_receipt": patch_receipt,
            "config_values": config_values,
            "local_onnx_pre": identity(local_onnx),
            "local_cache_seed_pre": cache_pre,
            "runtime_resource_monitor_control": identity(RUNTIME_RESOURCE_MONITOR),
            "zero_kf_post_shutdown_watchdog": {
                "enabled": True,
                "fixed_grace_seconds": ZERO_KF_WATCHDOG_GRACE_SECONDS,
                "target_poll_interval_seconds": ZERO_KF_WATCHDOG_TARGET_POLL_SECONDS,
                "maximum_poll_interval_seconds": ZERO_KF_WATCHDOG_POLL_SECONDS,
                "maximum_final_gate_duration_seconds": (
                    ZERO_KF_WATCHDOG_FINAL_GATE_SECONDS
                ),
                "signal": "SIGTERM",
                "signal_scope": "EXACT_REVALIDATED_PROCESS_GROUP",
                "signal_attempt_limit": 1,
                "sigkill_authorized_by_watchdog": False,
                "estimator_total_timeout_seconds": TIMEOUT_SECONDS,
                "applies_to_all_hfnet_budgets_windows_and_repeats": True,
            },
            "launch": {
                "argv": [
                    str(BINARY),
                    str(config_path),
                    f"{result_dir}/",
                    str(case["input_root"]),
                    str(selected_local),
                ],
                "cwd": str(root),
                "timeout_seconds": TIMEOUT_SECONDS,
            },
            "claims": {
                "cold_start": True,
                "loop_closing": False,
                "same_camera_timestamp_phase": True,
                "independent_cache_seed": True,
                "repeat_is_not_retry": True,
                "pipeline_invalid_replenishment_is_not_a_replicate": False,
                "continuous_runtime_resource_monitor_required": True,
                "todesk_exemption": False,
            },
        }
        write_exclusive(root / "attempt_manifest.json", canonical_json(attempt))
        return attempt
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise


def prepare_all() -> list[dict[str, object]]:
    manifest = load_experiment()
    frozen_backend = backend_freeze_identity()
    prepared: list[dict[str, object]] = []
    schedule = json.loads(
        (EXPERIMENT_ROOT / "planned_schedule.json").read_text(encoding="utf-8")
    )
    for cell in schedule:
        arm = str(cell["arm"])
        if not arm.startswith("hfnet_openloop_"):
            continue
        budget = int(arm.rsplit("_", 1)[1])
        root = attempt_root(str(cell["case_id"]), budget, int(cell["repeat"]))
        if root.exists():
            continue
        prepared.append(
            prepare_attempt(
                str(cell["case_id"]),
                budget,
                int(cell["repeat"]),
                _verified_manifest=manifest,
                _verified_backend=frozen_backend,
            )
        )
    return prepared


def process_record(pid: int) -> dict[str, object]:
    root = Path("/proc") / str(pid)
    try:
        executable = os.readlink(root / "exe")
    except OSError:
        executable = ""
    try:
        comm = (root / "comm").read_text(errors="replace").strip()
    except OSError:
        comm = ""
    try:
        tokens = [
            part.decode(errors="replace")
            for part in (root / "cmdline").read_bytes().split(b"\0")
            if part
        ]
    except OSError:
        tokens = []
    return {
        "pid": pid,
        "executable": executable,
        "comm": comm,
        "tokens": tokens,
        "command": " ".join(tokens),
    }


def verify_attempt(
    case_id: str,
    budget: int,
    repeat: int,
    require_unstarted: bool,
    attempt_index: int = 1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    experiment = load_experiment()
    root = attempt_root(case_id, budget, repeat, attempt_index)
    attempt = json.loads((root / "attempt_manifest.json").read_text(encoding="utf-8"))
    if attempt.get("schema_version") != "aqua-fe-fair-stability-hfnet-attempt-v9":
        raise ContractError("ATTEMPT_SCHEMA_MISMATCH")
    if attempt.get("experiment_id") != EXPERIMENT_ID:
        raise ContractError("ATTEMPT_EXPERIMENT_ID_MISMATCH")
    if (
        attempt.get("case_id") != case_id
        or attempt.get("budget") != budget
        or attempt.get("repeat") != repeat
        or int(attempt.get("attempt_index", 1)) != attempt_index
    ):
        raise ContractError("ATTEMPT_COORDINATE_MISMATCH")
    require_recorded_identity(
        attempt.get("backend_freeze"), BACKEND_FREEZE, "attempt_backend_freeze"
    )
    expected_watchdog = {
        "enabled": True,
        "fixed_grace_seconds": ZERO_KF_WATCHDOG_GRACE_SECONDS,
        "target_poll_interval_seconds": ZERO_KF_WATCHDOG_TARGET_POLL_SECONDS,
        "maximum_poll_interval_seconds": ZERO_KF_WATCHDOG_POLL_SECONDS,
        "maximum_final_gate_duration_seconds": (
            ZERO_KF_WATCHDOG_FINAL_GATE_SECONDS
        ),
        "signal": "SIGTERM",
        "signal_scope": "EXACT_REVALIDATED_PROCESS_GROUP",
        "signal_attempt_limit": 1,
        "sigkill_authorized_by_watchdog": False,
        "estimator_total_timeout_seconds": TIMEOUT_SECONDS,
        "applies_to_all_hfnet_budgets_windows_and_repeats": True,
    }
    if not strict_json_equal(
        attempt.get("zero_kf_post_shutdown_watchdog"), expected_watchdog
    ):
        raise ContractError("ZERO_KF_POST_SHUTDOWN_WATCHDOG_CONTRACT_DRIFT")
    require_recorded_identity(
        attempt.get("runtime_resource_monitor_control"),
        RUNTIME_RESOURCE_MONITOR,
        "attempt_runtime_resource_monitor_control",
    )
    case = experiment["cases"][case_id]
    checks = [
        (root / "runtime_config_openloop.yaml", attempt["runtime_config"]),
        (root / "cam0_times_vins_matched.txt", attempt["selected_times"]),
        (root / "run_local_model/HFNet-RT/HF-Net.onnx", attempt["local_onnx_pre"]),
    ]
    for path, expected in checks:
        actual = identity(path)
        if (
            actual["size_bytes"] != expected["size_bytes"]
            or actual["sha256"] != expected["sha256"]
        ):
            raise ContractError(f"ATTEMPT_INPUT_DRIFT:{path}")
    case_manifest_path = EXPERIMENT_ROOT / "input_freeze" / case_id / "case_manifest.json"
    case_manifest_identity = identity(case_manifest_path)
    expected_case_manifest = attempt["case_manifest"]
    if (
        case_manifest_identity["size_bytes"],
        case_manifest_identity["sha256"],
    ) != (
        expected_case_manifest["size_bytes"],
        expected_case_manifest["sha256"],
    ):
        raise ContractError("CASE_MANIFEST_DRIFT")
    case_manifest = json.loads(case_manifest_path.read_text(encoding="utf-8"))
    selected = read_ns_lines(root / "cam0_times_vins_matched.txt")
    for key in (
        "source_vins_config",
        "source_times",
        "source_materialization_manifest",
        "source_imu",
        "runtime_input_cam0_times",
        "imu",
        "learned_klt_bag",
        "pure_klt_bag",
    ):
        expected = case_manifest[key]
        observed = identity(Path(expected["path"]))
        if (observed["size_bytes"], observed["sha256"]) != (
            expected["size_bytes"],
            expected["sha256"],
        ):
            raise ContractError(f"FROZEN_SOURCE_INPUT_DRIFT:{key}")
    observed_images = image_inventory(Path(case_manifest["input_root"]), selected)
    if observed_images != case_manifest["images"]:
        raise ContractError("FROZEN_IMAGE_INVENTORY_DRIFT")
    observed_bracket = imu_bracket(
        parse_imu_stamps(Path(case_manifest["imu"]["path"])), selected, case_id
    )
    if observed_bracket != case_manifest["imu_bracket"]:
        raise ContractError("FROZEN_IMU_BRACKET_DRIFT")
    cache = identity(root / "run_local_model/HFNet-RT/HF-Net.cache")
    if require_unstarted and cache != attempt["local_cache_seed_pre"]:
        raise ContractError("CACHE_SEED_PRESTART_DRIFT")
    validate_generated_config(
        root / "runtime_config_openloop.yaml",
        int(case["nominal_fps"]),
        budget,
        root / "run_local_model/HFNet-RT",
    )
    if require_unstarted and any(
        (root / name).exists() for name in ("start_claim.json", "run_result.json")
    ):
        raise ContractError("ATTEMPT_ALREADY_STARTED_OR_TERMINAL")
    return experiment, attempt


def integral_epoch_ns(token: str, row: int) -> int:
    try:
        value = Decimal(token)
    except InvalidOperation as error:
        raise ValueError(f"ROW_{row}_TIMESTAMP_DECIMAL") from error
    if not value.is_finite() or value != value.to_integral_value():
        raise ValueError(f"ROW_{row}_TIMESTAMP_NOT_INTEGRAL")
    return int(value)


def parse_trajectory(path: Path, stamps: Sequence[int]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "exists": path.is_file(),
        "valid": False,
        "pose_count": 0,
        "errors": [],
    }
    if not path.is_file():
        result["errors"] = ["MISSING"]
        return result
    associated: list[int] = []
    used: set[int] = set()
    previous_serialized: int | None = None
    previous_index: int | None = None
    raw_lines = (
        line
        for line in path.read_text(encoding="ascii").splitlines()
        if line.strip()
    )
    for line_number, raw in enumerate(raw_lines, 1):
        fields = raw.split()
        if len(fields) != 8:
            result["errors"].append(f"ROW_{line_number}_FIELD_COUNT")
            continue
        try:
            stamp = integral_epoch_ns(fields[0], line_number)
            pose = [float(value) for value in fields[1:]]
        except ValueError:
            result["errors"].append(f"ROW_{line_number}_PARSE")
            continue
        if not all(math.isfinite(value) for value in pose):
            result["errors"].append(f"ROW_{line_number}_NONFINITE")
            continue
        if abs(math.sqrt(sum(value * value for value in pose[3:7])) - 1.0) > 1e-3:
            result["errors"].append(f"ROW_{line_number}_QUATERNION_NORM")
            continue
        if previous_serialized is not None and stamp <= previous_serialized:
            result["errors"].append(f"ROW_{line_number}_TIMESTAMP_NOT_STRICT")
            continue
        previous_serialized = stamp
        lower = bisect.bisect_left(stamps, stamp - ASSOCIATION_TOLERANCE_NS)
        upper = bisect.bisect_right(stamps, stamp + ASSOCIATION_TOLERANCE_NS)
        if (
            upper - lower != 1
            or lower in used
            or (previous_index is not None and lower <= previous_index)
        ):
            result["errors"].append(
                f"ROW_{line_number}_ASSOCIATION_NOT_UNIQUE_OR_STRICT"
            )
            continue
        used.add(lower)
        associated.append(lower)
        previous_index = lower
    longest = current = 0
    longest_start = longest_end = current_start = previous = None
    for index in associated:
        if previous is not None and index == previous + 1:
            current += 1
        else:
            current = 1
            current_start = index
        if current > longest:
            longest, longest_start, longest_end = current, current_start, index
        previous = index
    result.update(
        {
            "valid": bool(associated) and not result["errors"],
            "pose_count": len(associated),
            "first_relative_index": associated[0] if associated else None,
            "last_relative_index": associated[-1] if associated else None,
            "coverage_fraction": len(associated) / len(stamps),
            "longest_contiguous_count": longest,
            "longest_contiguous_fraction": longest / len(stamps),
            "longest_contiguous_relative_indices_inclusive": (
                [longest_start, longest_end] if longest_start is not None else None
            ),
            "identity": identity(path),
        }
    )
    return result


def parse_log(
    stdout_path: Path, stderr_path: Path, admitted_count: int
) -> dict[str, Any]:
    if not stdout_path.is_file() or not stderr_path.is_file():
        return {
            "valid": False,
            "errors": ["STDOUT_OR_STDERR_MISSING"],
            "init_frame_ids": [],
            "reset_events": [],
            "solver_risk_events": [],
        }
    lines = stdout_path.read_text(encoding="utf-8", errors="replace").splitlines()
    stderr_lines = stderr_path.read_text(
        encoding="utf-8", errors="replace"
    ).splitlines()
    errors: list[str] = []
    init_ids: list[int] = []
    reset_events: list[dict[str, object]] = []
    risk_events: list[dict[str, object]] = []
    last_init: int | None = None
    pending: list[dict[str, object]] = []
    risk_pattern = re.compile(
        r"Cholesky failure|FAIL LOCAL-INERTIAL BA|Fail to track local map|"
        r"Sophus.*ensure|(?<![A-Za-z])(?:[-+]?nan|[-+]?inf(?:inity)?)(?![A-Za-z])",
        re.IGNORECASE,
    )
    reset_pattern = re.compile(
        r"SYSTEM-> Reseting active map|LM: Reseting Atlas|Timestamp jump detected",
        re.IGNORECASE,
    )
    for line_number, line in enumerate(lines, 1):
        match = re.search(r"Init frame id:\s*(\d+)", line)
        if match:
            frame_id = int(match.group(1))
            for event in pending:
                event["next_init_frame_id"] = frame_id
            pending.clear()
            last_init = frame_id
            init_ids.append(frame_id)
        if reset_pattern.search(line):
            event = {
                "stream": "stdout",
                "line_number": line_number,
                "preceding_init_frame_id": last_init,
                "next_init_frame_id": None,
                "line_sha256": hashlib.sha256(
                    line.encode("utf-8", errors="replace")
                ).hexdigest(),
            }
            reset_events.append(event)
            pending.append(event)
        if risk_pattern.search(line):
            event = {
                "stream": "stdout",
                "line_number": line_number,
                "preceding_init_frame_id": last_init,
                "next_init_frame_id": None,
                "line_sha256": hashlib.sha256(
                    line.encode("utf-8", errors="replace")
                ).hexdigest(),
            }
            risk_events.append(event)
            pending.append(event)
    for line_number, line in enumerate(stderr_lines, 1):
        if risk_pattern.search(line):
            risk_events.append(
                {
                    "stream": "stderr",
                    "line_number": line_number,
                    "preceding_init_frame_id": None,
                    "next_init_frame_id": None,
                    "line_sha256": hashlib.sha256(
                        line.encode("utf-8", errors="replace")
                    ).hexdigest(),
                }
            )
    if any(frame_id < 0 or frame_id >= admitted_count for frame_id in init_ids):
        errors.append("INITIALIZATION_FRAME_ID_OUT_OF_RANGE")
    if any(right <= left for left, right in zip(init_ids, init_ids[1:])):
        errors.append("INITIALIZATION_FRAME_IDS_NOT_STRICT")
    saving = max(
        (
            index
            for index, line in enumerate(lines)
            if line.startswith("Saving trajectory to ")
        ),
        default=-1,
    )
    tail = lines[saving + 1 :] if saving >= 0 else []
    atlas_count = None
    atlas_position = -1
    for index, line in enumerate(tail):
        match = re.search(r"There are (\d+) maps in (?:the )?atlas", line)
        if match:
            atlas_count, atlas_position = int(match.group(1)), index
    end_position = (
        next(
            (
                index
                for index, line in enumerate(
                    tail[atlas_position + 1 :], start=atlas_position + 1
                )
                if line.startswith("End of saving trajectory to ")
            ),
            -1,
        )
        if atlas_position >= 0
        else -1
    )
    map_rows: list[tuple[int, int]] = []
    if atlas_position >= 0 and end_position >= 0:
        for line in tail[atlas_position + 1 : end_position]:
            match = re.fullmatch(r"\s*Map (\d+) has (\d+) KFs\s*", line)
            if match:
                map_rows.append((int(match.group(1)), int(match.group(2))))
    exact = bool(
        atlas_count is not None
        and end_position >= 0
        and len(map_rows) == atlas_count
        and {row[0] for row in map_rows} == set(range(atlas_count))
    )
    environment_failure_pattern = re.compile(
        r"CUDA driver version is insufficient|no CUDA-capable device|"
        r"cannot open shared object file|cudaErrorInsufficientDriver|"
        r"failed to (?:load|deserialize).*(?:model|engine|cache|onnx)",
        re.IGNORECASE,
    )
    environment_failures = [
        {"stream": stream, "line_number": index + 1}
        for stream, stream_lines in (("stdout", lines), ("stderr", stderr_lines))
        for index, line in enumerate(stream_lines)
        if environment_failure_pattern.search(line)
    ]
    return {
        "valid": exact and not errors,
        "errors": errors,
        "init_frame_ids": init_ids,
        "initialization_count": len(init_ids),
        "reinitialization_count": max(0, len(init_ids) - 1),
        "reset_events": reset_events,
        "active_map_reset_count": len(reset_events),
        "solver_risk_events": risk_events,
        "solver_risk_count": len(risk_events),
        "atlas_map_count": atlas_count,
        "map_keyframes": [row[1] for row in map_rows],
        "final_atlas_nonempty": bool(exact and any(row[1] > 0 for row in map_rows)),
        "trajectory_save_completed": end_position >= 0,
        "loop_event_text_count": sum(
            bool(
                re.search(
                    r"loop detected|loop fusion|global bundle adjustment",
                    line,
                    re.IGNORECASE,
                )
            )
            for line in lines
        ),
        "environment_failure_events": environment_failures,
        "stdout_identity": identity(stdout_path),
        "stderr_identity": identity(stderr_path),
    }


def accepted_events(
    log: Mapping[str, Any], trajectory: Mapping[str, Any]
) -> dict[str, object]:
    accepted = trajectory.get("longest_contiguous_relative_indices_inclusive")
    if (
        not isinstance(accepted, list)
        or len(accepted) != 2
        or not all(isinstance(value, int) for value in accepted)
    ):
        return {
            "proven_early_resets": [],
            "unresolved_resets": list(log.get("reset_events", [])),
            "proven_early_solver_risks": [],
            "unresolved_solver_risks": list(log.get("solver_risk_events", [])),
            "support_reinitializations": list(log.get("init_frame_ids", []))[1:],
        }
    start, end = accepted
    resets = list(log.get("reset_events", []))
    early = [
        event
        for event in resets
        if event.get("next_init_frame_id") is not None
        and int(event["next_init_frame_id"]) < start
    ]
    unresolved = [event for event in resets if event not in early]
    risks = list(log.get("solver_risk_events", []))
    early_risks = [
        event
        for event in risks
        if event.get("next_init_frame_id") is not None
        and int(event["next_init_frame_id"]) < start
    ]
    unresolved_risks = [event for event in risks if event not in early_risks]
    reinits = [
        int(value)
        for value in list(log.get("init_frame_ids", []))[1:]
        if start <= int(value) <= end
    ]
    return {
        "proven_early_resets": early,
        "unresolved_resets": unresolved,
        "proven_early_solver_risks": early_risks,
        "unresolved_solver_risks": unresolved_risks,
        "support_reinitializations": reinits,
    }


def parse_zero_kf_post_shutdown_signature(
    stdout_path: Path,
    trajectory_path: Path,
    keyframe_path: Path,
) -> dict[str, object]:
    """Recognize one exact, complete, ordered zero-KF save-hang signature."""
    evidence: dict[str, object] = {
        "parser_proven": False,
        "confirmed": False,
        "errors": [],
        "stdout_regular_non_symlink": (
            stdout_path.is_file() and not stdout_path.is_symlink()
        ),
        "trajectory_absent_non_symlink": not (
            trajectory_path.exists() or trajectory_path.is_symlink()
        ),
        "keyframe_trajectory_absent_non_symlink": not (
            keyframe_path.exists() or keyframe_path.is_symlink()
        ),
    }
    if stdout_path.is_symlink() or not stdout_path.is_file():
        evidence["errors"] = ["STDOUT_NOT_REGULAR_OR_IS_SYMLINK"]
        return evidence
    try:
        raw = stdout_path.read_bytes()
        decoded = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        evidence["errors"] = [
            f"STDOUT_READ_OR_DECODE_FAILED:{type(error).__name__}:{error}"
        ]
        return evidence
    raw_lines = decoded.splitlines(keepends=True)
    complete_lines = [
        line[:-1] for line in raw_lines if line.endswith("\n")
    ]
    incomplete_tail = (
        raw_lines[-1] if raw_lines and not raw_lines[-1].endswith("\n") else None
    )
    target_saving = f"Saving trajectory to {trajectory_path} ..."
    target_end = f"End of saving trajectory to {trajectory_path} ..."
    shutdown_indices = [
        index for index, line in enumerate(complete_lines) if line == "Shutdown"
    ]
    all_saving_indices = [
        index
        for index, line in enumerate(complete_lines)
        if line.startswith("Saving trajectory to ")
    ]
    target_saving_indices = [
        index for index, line in enumerate(complete_lines) if line == target_saving
    ]
    saving_index = target_saving_indices[0] if len(target_saving_indices) == 1 else -1
    ordered_shutdown = bool(
        len(shutdown_indices) == 1
        and saving_index >= 0
        and shutdown_indices[0] < saving_index
    )
    atlas_matches: list[tuple[int, int]] = []
    if saving_index >= 0:
        for index, line in enumerate(complete_lines[saving_index + 1 :], saving_index + 1):
            match = re.fullmatch(r"There are ([0-9]+) maps in the atlas", line)
            if match:
                atlas_matches.append((index, int(match.group(1))))
    atlas_index, atlas_count = (
        atlas_matches[0] if len(atlas_matches) == 1 else (-1, 0)
    )
    map_rows: list[tuple[int, int, int]] = []
    if atlas_index >= 0:
        for index, line in enumerate(complete_lines[atlas_index + 1 :], atlas_index + 1):
            match = re.fullmatch(r"  Map ([0-9]+) has ([0-9]+) KFs", line)
            if match:
                map_rows.append((index, int(match.group(1)), int(match.group(2))))
    map_ids = [map_id for _index, map_id, _keyframes in map_rows]
    complete_map_set = bool(
        atlas_count >= 1
        and len(map_rows) == atlas_count
        and len(map_ids) == len(set(map_ids))
        and set(map_ids) == set(range(atlas_count))
    )
    all_zero = bool(
        complete_map_set and all(keyframes == 0 for _index, _map_id, keyframes in map_rows)
    )
    end_observed = target_end in complete_lines or (
        isinstance(incomplete_tail, str) and incomplete_tail == target_end
    )
    only_target_saving = bool(
        len(all_saving_indices) == 1
        and all_saving_indices == target_saving_indices
    )
    evidence.update(
        {
            "parser_proven": True,
            "stdout_size_bytes": len(raw),
            "stdout_sha256_at_sample": hashlib.sha256(raw).hexdigest(),
            "incomplete_tail_present": incomplete_tail is not None,
            "shutdown_line_indices_zero_based": shutdown_indices,
            "target_saving_line_indices_zero_based": target_saving_indices,
            "all_saving_line_indices_zero_based": all_saving_indices,
            "ordered_single_shutdown_before_single_target_saving": ordered_shutdown,
            "only_target_saving_observed": only_target_saving,
            "atlas_headers_after_target_saving": [
                {"line_index_zero_based": index, "map_count": count}
                for index, count in atlas_matches
            ],
            "atlas_map_count": atlas_count if atlas_index >= 0 else None,
            "map_rows": [
                {
                    "line_index_zero_based": index,
                    "map_id": map_id,
                    "keyframes": keyframes,
                }
                for index, map_id, keyframes in map_rows
            ],
            "complete_unique_map_id_set": complete_map_set,
            "every_map_zero_keyframes": all_zero,
            "target_end_of_saving_observed": end_observed,
        }
    )
    evidence["confirmed"] = bool(
        ordered_shutdown
        and only_target_saving
        and len(atlas_matches) == 1
        and complete_map_set
        and all_zero
        and not end_observed
        and incomplete_tail is None
        and evidence["trajectory_absent_non_symlink"] is True
        and evidence["keyframe_trajectory_absent_non_symlink"] is True
    )
    return evidence


def wait_with_zero_kf_watchdog(
    process: subprocess.Popen[bytes],
    runtime_monitor: RuntimeResourceMonitor,
    stdout_path: Path,
    trajectory_path: Path,
    keyframe_path: Path,
    expected_executable: str,
    expected_argv: Sequence[str],
    *,
    timeout: float,
    monotonic: Any = time.monotonic,
) -> tuple[int | None, bool, bool, dict[str, object]]:
    """Wait within the unchanged budget while applying the narrow HF zero-KF gate."""
    started = float(monotonic())
    deadline = started + float(timeout)
    next_sample = started
    last_sample: float | None = None
    maximum_gap = 0.0
    maximum_pre_candidate_gap = 0.0
    maximum_confirmation_gap = 0.0
    pre_candidate_gap_count = 0
    confirmation_gap_reset_count = 0
    confirmation_candidate_count = 0
    phase_gap_events: list[dict[str, object]] = []
    sample_count = 0
    signature_since: float | None = None
    signature_first_utc: str | None = None
    last_signature: dict[str, object] | None = None
    last_group: dict[str, object] | None = None
    final_gate_signature: dict[str, object] | None = None
    final_gate_signature_completed: float | None = None
    final_gate_adjudication: dict[str, object] | None = None
    action: dict[str, object] | None = None
    monitoring_errors: list[str] = []
    permanently_disabled = False
    pending_terminal_transition: dict[str, object] | None = None
    passive_exit_adjudication: dict[str, object] | None = None

    def build_same_popen_reap(
        *,
        source: str,
        poll_observed_monotonic_ns: int,
        poll_returncode: int | None,
        wait_started_monotonic_ns: int,
        wait_completed_monotonic_ns: int,
        wait_timeout_seconds: float,
        wait_returncode: int,
    ) -> dict[str, object] | None:
        leader_identity = getattr(runtime_monitor, "leader_identity", None)
        leader_pid = getattr(runtime_monitor, "pid", None)
        leader_pgid = getattr(runtime_monitor, "pgid", None)
        if (
            not isinstance(leader_identity, tuple)
            or len(leader_identity) != 2
            or type(leader_identity[0]) is not int
            or type(leader_identity[1]) is not int
            or type(leader_pid) is not int
            or type(leader_pgid) is not int
            or leader_identity[0] != leader_pid
            or leader_pgid != leader_pid
            or type(poll_observed_monotonic_ns) is not int
            or type(wait_started_monotonic_ns) is not int
            or type(wait_completed_monotonic_ns) is not int
            or not (
                0
                < poll_observed_monotonic_ns
                <= wait_started_monotonic_ns
                <= wait_completed_monotonic_ns
            )
            or type(wait_timeout_seconds) is not float
            or not math.isfinite(wait_timeout_seconds)
            or not 0.0 <= wait_timeout_seconds <= ZERO_KF_WATCHDOG_POLL_SECONDS
            or (poll_returncode is not None and type(poll_returncode) is not int)
            or type(wait_returncode) is not int
            or (
                poll_returncode is not None
                and poll_returncode != wait_returncode
            )
        ):
            return None
        return {
            "schema_version": "aqua-fe-fair-stability-same-popen-reap-v9",
            "source": str(source),
            "same_popen": True,
            "frozen_process_identity": {
                "pid": leader_pid,
                "start_ticks": leader_identity[1],
                "pgid": leader_pgid,
                "session": leader_pid,
            },
            "poll_observed_monotonic_ns": poll_observed_monotonic_ns,
            "poll_returncode": poll_returncode,
            "wait_started_monotonic_ns": wait_started_monotonic_ns,
            "wait_completed_monotonic_ns": wait_completed_monotonic_ns,
            "wait_timeout_seconds": wait_timeout_seconds,
            "wait_returncode": wait_returncode,
        }

    def reap_after_same_popen_poll(
        source: str,
        poll_returncode: int,
        poll_observed_monotonic_ns: int,
    ) -> tuple[int | None, dict[str, object] | None, str | None]:
        wait_started = time.monotonic_ns()
        try:
            wait_returncode = process.wait(timeout=0)
        except (OSError, subprocess.SubprocessError) as error:
            return None, None, f"{type(error).__name__}:{error}"
        wait_completed = time.monotonic_ns()
        reap = build_same_popen_reap(
            source=source,
            poll_observed_monotonic_ns=poll_observed_monotonic_ns,
            poll_returncode=poll_returncode,
            wait_started_monotonic_ns=wait_started,
            wait_completed_monotonic_ns=wait_completed,
            wait_timeout_seconds=0.0,
            wait_returncode=wait_returncode,
        )
        if reap is None:
            return wait_returncode, None, "IDENTITY_RETURN_CODE_OR_TIMING_UNPROVEN"
        return wait_returncode, reap, None

    def record_passive_exit(
        phase: str,
        evidence: Mapping[str, object],
        returncode: int,
        reap: Mapping[str, object],
        *,
        observation_already_recorded: bool = False,
    ) -> None:
        nonlocal pending_terminal_transition, passive_exit_adjudication
        observation_phase = (
            "FINAL_GATE"
            if phase.startswith("FINAL_SIGNAL_GATE:")
            else "CONFIRMATION"
            if signature_since is not None
            else "PRE_CANDIDATE"
        )
        if not observation_already_recorded:
            record_observation_gap(
                float(monotonic()),
                phase=observation_phase,
                reason=f"PASSIVE_EXIT:{phase}",
                force=True,
            )
        if (
            monitoring_errors
            or reap.get("same_popen") is not True
            or reap.get("wait_returncode") != returncode
            or (
                phase.startswith("FINAL_SIGNAL_GATE:")
                and evidence.get("classification")
                == "LEADER_REAPED_BEFORE_SIGNAL"
                and not strict_json_equal(evidence.get("reap"), reap)
            )
        ):
            if not monitoring_errors:
                monitoring_errors.append("PASSIVE_EXIT_SAME_POPEN_REAP_PROOF_INVALID")
            pending_terminal_transition = None
            return
        passive_exit_adjudication = {
            "phase": phase,
            "evidence": json.loads(json.dumps(evidence, allow_nan=False)),
            "last_exact_group_snapshot": (
                json.loads(json.dumps(last_group, allow_nan=False))
                if isinstance(last_group, Mapping)
                else None
            ),
            "adjudicated_at_utc": now_utc(),
            "adjudicated_monotonic_ns": time.monotonic_ns(),
            "child_returncode": int(returncode),
            "reaped_before_next_sample": True,
            "reap": json.loads(json.dumps(reap, allow_nan=False)),
            "signal_attempted": False,
            "signal_sent": False,
        }
        pending_terminal_transition = None

    def ordinary_exit_evidence(
        phase: str,
        returncode: int,
    ) -> dict[str, object]:
        return {
            "classification": "ORDINARY_CHILD_REAPED",
            "phase": phase,
            "observed_at_utc": now_utc(),
            "observed_monotonic_ns": time.monotonic_ns(),
            "leader_returncode": int(returncode),
            "reaped_before_next_sample": True,
            "signal_attempted": False,
            "signal_sent": False,
            "errors": [],
        }

    def clear_confirmation_candidate() -> None:
        nonlocal signature_since, signature_first_utc, last_signature
        signature_since = None
        signature_first_utc = None
        last_signature = None

    def record_observation_gap(
        observed: float,
        *,
        phase: str,
        reason: str,
        force: bool = False,
    ) -> bool:
        nonlocal maximum_gap
        nonlocal maximum_pre_candidate_gap, maximum_confirmation_gap
        nonlocal pre_candidate_gap_count, confirmation_gap_reset_count
        nonlocal permanently_disabled
        if (action is not None and not force) or last_sample is None:
            return True
        current = float(observed)
        previous = float(last_sample)
        gap = current - previous
        if not all(math.isfinite(value) for value in (current, previous, gap)):
            monitoring_errors.append(
                f"WATCHDOG_MONOTONIC_TIMING_INVALID:{phase}:{reason}"
            )
            permanently_disabled = True
            return False
        if gap < 0.0:
            monitoring_errors.append(
                f"WATCHDOG_MONOTONIC_CLOCK_REGRESSION:{phase}:{reason}"
            )
            permanently_disabled = True
            return False
        maximum_gap = max(maximum_gap, gap)
        if phase == "PRE_CANDIDATE":
            maximum_pre_candidate_gap = max(maximum_pre_candidate_gap, gap)
        elif phase == "CONFIRMATION":
            maximum_confirmation_gap = max(maximum_confirmation_gap, gap)
        elif phase != "FINAL_GATE":
            monitoring_errors.append(f"WATCHDOG_GAP_PHASE_INVALID:{phase}")
            permanently_disabled = True
            return False
        if gap <= ZERO_KF_WATCHDOG_POLL_SECONDS:
            return True
        if phase == "FINAL_GATE":
            monitoring_errors.append(
                "FINAL_SIGNAL_GATE:WATCHDOG_FINAL_GATE_DURATION_EXCEEDED"
            )
            permanently_disabled = True
            return False
        candidate_reset = phase == "CONFIRMATION"
        phase_gap_events.append(
            {
                "event_index": len(phase_gap_events) + 1,
                "phase": phase,
                "reason": str(reason),
                "previous_observation_monotonic": previous,
                "observed_monotonic": current,
                "gap_seconds": gap,
                "maximum_allowed_seconds": ZERO_KF_WATCHDOG_POLL_SECONDS,
                "candidate_reset": candidate_reset,
            }
        )
        if candidate_reset:
            confirmation_gap_reset_count += 1
            clear_confirmation_candidate()
        else:
            pre_candidate_gap_count += 1
        return False

    def final_gate_receipt_errors(
        gate: Mapping[str, object],
        expected_started: float,
    ) -> list[str]:
        errors: list[str] = []

        def finite_number(name: str) -> float | None:
            value = gate.get(name)
            if type(value) not in (int, float) or not math.isfinite(float(value)):
                errors.append(f"WATCHDOG_FINAL_GATE_RECEIPT_INVALID:{name}")
                return None
            return float(value)

        recorded_deadline = finite_number("deadline_monotonic")
        recorded_started = finite_number("final_gate_started_monotonic")
        recorded_maximum = finite_number("maximum_final_gate_duration_seconds")
        recorded_pre_signal = finite_number("pre_signal_monotonic")
        recorded_elapsed = finite_number("final_gate_elapsed_seconds")
        if recorded_deadline is not None and recorded_deadline != deadline:
            errors.append("WATCHDOG_FINAL_GATE_RECEIPT_DEADLINE_MISMATCH")
        if recorded_started is not None and recorded_started != expected_started:
            errors.append("WATCHDOG_FINAL_GATE_RECEIPT_START_MISMATCH")
        if (
            recorded_maximum is not None
            and recorded_maximum != ZERO_KF_WATCHDOG_FINAL_GATE_SECONDS
        ):
            errors.append("WATCHDOG_FINAL_GATE_RECEIPT_MAXIMUM_MISMATCH")
        if (
            recorded_started is not None
            and recorded_pre_signal is not None
            and recorded_elapsed is not None
            and recorded_elapsed != recorded_pre_signal - recorded_started
        ):
            errors.append("WATCHDOG_FINAL_GATE_RECEIPT_ELAPSED_MISMATCH")
        if (
            recorded_deadline is not None
            and recorded_pre_signal is not None
            and recorded_pre_signal >= recorded_deadline
        ):
            errors.append("WATCHDOG_DEADLINE_REACHED_BEFORE_SIGNAL")
        if recorded_elapsed is not None:
            if recorded_elapsed < 0.0:
                errors.append("WATCHDOG_FINAL_GATE_CLOCK_REGRESSION")
            elif recorded_elapsed > ZERO_KF_WATCHDOG_FINAL_GATE_SECONDS:
                errors.append("WATCHDOG_FINAL_GATE_DURATION_EXCEEDED")
        if gate.get("signal_sent") is True and gate.get("signal_attempted") is not True:
            errors.append("WATCHDOG_FINAL_GATE_SIGNAL_WITHOUT_ATTEMPT")
        return list(dict.fromkeys(errors))

    def outcome() -> dict[str, object]:
        return {
            "schema_version": "aqua-fe-fair-stability-hfnet-zero-kf-watchdog-outcome-v9",
            "monitor_proven": not monitoring_errors,
            "monitoring_errors": list(dict.fromkeys(monitoring_errors)),
            "sample_count": sample_count,
            "target_poll_interval_seconds": ZERO_KF_WATCHDOG_TARGET_POLL_SECONDS,
            "maximum_allowed_poll_interval_seconds": ZERO_KF_WATCHDOG_POLL_SECONDS,
            "maximum_observed_poll_interval_seconds": maximum_gap,
            "pre_candidate_gap_count": pre_candidate_gap_count,
            "maximum_pre_candidate_gap_seconds": maximum_pre_candidate_gap,
            "confirmation_gap_reset_count": confirmation_gap_reset_count,
            "maximum_confirmation_gap_seconds": maximum_confirmation_gap,
            "confirmation_candidate_count": confirmation_candidate_count,
            "phase_gap_events": json.loads(
                json.dumps(phase_gap_events, allow_nan=False)
            ),
            "fixed_signature_grace_seconds": ZERO_KF_WATCHDOG_GRACE_SECONDS,
            "signature_first_observed_at_utc": signature_first_utc,
            "signature_continuous_seconds_at_end": (
                max(0.0, float(monotonic()) - signature_since)
                if signature_since is not None
                else 0.0
            ),
            "last_confirmed_signature": last_signature,
            "last_exact_group_snapshot": last_group,
            "final_signal_gate_signature": final_gate_signature,
            "final_signal_gate_signature_completed_monotonic": (
                final_gate_signature_completed
            ),
            "final_signal_gate_adjudication": final_gate_adjudication,
            "watchdog_action": action,
            "passive_exit_adjudication": passive_exit_adjudication,
            "signal_attempted": bool(action and action.get("signal_attempted")),
            "sigterm_sent": bool(action and action.get("signal_sent")),
            "permanently_disabled_after_unproven_evidence": permanently_disabled,
            "total_timeout_seconds": timeout,
        }

    while True:
        returncode = process.poll()
        loop_poll_observed_monotonic_ns = time.monotonic_ns()
        if returncode is not None:
            source = (
                "PENDING_TEARDOWN_LOOP_POLL_THEN_WAIT_ZERO"
                if pending_terminal_transition is not None
                else "LOOP_POLL_THEN_WAIT_ZERO"
            )
            returncode, reap, reap_error = reap_after_same_popen_poll(
                source,
                returncode,
                loop_poll_observed_monotonic_ns,
            )
            if reap_error is not None or reap is None or returncode is None:
                monitoring_errors.append(
                    f"LEADER_REAP_FAILED:{reap_error or 'UNPROVEN'}"
                )
                return returncode, False, False, outcome()
            if pending_terminal_transition is not None:
                record_passive_exit(
                    str(pending_terminal_transition["phase"]),
                    pending_terminal_transition["evidence"],
                    returncode,
                    reap,
                )
            elif action is None and not monitoring_errors:
                phase = "LOOP_POLL"
                record_passive_exit(
                    f"ORDINARY_PROCESS_EXIT:{phase}",
                    ordinary_exit_evidence(phase, returncode),
                    returncode,
                    reap,
                )
            return returncode, True, False, outcome()
        if pending_terminal_transition is not None:
            monitoring_errors.extend(
                str(value)
                for value in pending_terminal_transition.get("errors", [])
            )
            if not pending_terminal_transition.get("errors"):
                monitoring_errors.append(
                    "TERMINAL_TRANSITION_PENDING_REAP_STILL_LIVE"
                )
            pending_terminal_transition = None
            permanently_disabled = True
        now = float(monotonic())
        sample_phase = (
            "CONFIRMATION" if signature_since is not None else "PRE_CANDIDATE"
        )
        record_observation_gap(
            now,
            phase=sample_phase,
            reason="LOOP_POLL_START",
        )
        if now >= deadline:
            return process.poll(), False, True, outcome()
        if action is None:
            last_sample = now
            sample_count += 1
            signature = parse_zero_kf_post_shutdown_signature(
                stdout_path, trajectory_path, keyframe_path
            )
            if signature.get("parser_proven") is not True:
                parser_errors = [
                    str(value) for value in signature.get("errors", [])
                ]
                monitoring_errors.extend(
                    parser_errors or ["SIGNATURE_PARSER_UNPROVEN_WITHOUT_REASON"]
                )
                permanently_disabled = True
                clear_confirmation_candidate()
            elif signature.get("confirmed") is True and not permanently_disabled:
                group = runtime_monitor.watchdog_exact_group_snapshot(
                    expected_executable, expected_argv
                )
                last_group = group
                group_completed = float(monotonic())
                group_phase = (
                    "CONFIRMATION"
                    if signature_since is not None
                    else "PRE_CANDIDATE"
                )
                group_gap_within_bound = record_observation_gap(
                    group_completed,
                    phase=group_phase,
                    reason="PERIODIC_SIGNATURE_AND_GROUP_PROOF",
                )
                if group.get("proven") is not True:
                    group_returncode = process.poll()
                    group_poll_observed_monotonic_ns = time.monotonic_ns()
                    if group_returncode is not None:
                        group_returncode, reap, reap_error = (
                            reap_after_same_popen_poll(
                                "PERIODIC_PROOF_POLL_THEN_WAIT_ZERO",
                                group_returncode,
                                group_poll_observed_monotonic_ns,
                            )
                        )
                        if (
                            reap_error is not None
                            or reap is None
                            or group_returncode is None
                        ):
                            monitoring_errors.append(
                                f"LEADER_REAP_FAILED:{reap_error or 'UNPROVEN'}"
                            )
                            return group_returncode, False, False, outcome()
                        if watchdog_terminal_transition_candidate(group):
                            record_passive_exit(
                                "PERIODIC_EXACT_GROUP_PROOF",
                                group,
                                group_returncode,
                                reap,
                                observation_already_recorded=True,
                            )
                        else:
                            monitoring_errors.extend(
                                [
                                    f"EXACT_GROUP_UNPROVEN:{value}"
                                    for value in group.get("errors", [])
                                ]
                                or ["EXACT_GROUP_UNPROVEN_WITHOUT_REASON"]
                            )
                        return group_returncode, True, False, outcome()
                    elif watchdog_terminal_transition_candidate(group):
                        pending_terminal_transition = {
                            "phase": "PERIODIC_EXACT_GROUP_PROOF",
                            "evidence": group,
                            "poll_observed_monotonic_ns": (
                                group_poll_observed_monotonic_ns
                            ),
                            "errors": [
                                f"EXACT_GROUP_UNPROVEN:{value}"
                                for value in group.get("errors", [])
                            ],
                        }
                        last_sample = group_completed
                    else:
                        group_errors = [
                            f"EXACT_GROUP_UNPROVEN:{value}"
                            for value in group.get("errors", [])
                        ]
                        monitoring_errors.extend(
                            group_errors
                            or ["EXACT_GROUP_UNPROVEN_WITHOUT_REASON"]
                        )
                        permanently_disabled = True
                    clear_confirmation_candidate()
                else:
                    confirmation_completed = group_completed
                    if confirmation_completed >= deadline:
                        return process.poll(), False, True, outcome()
                    if permanently_disabled:
                        clear_confirmation_candidate()
                    elif signature_since is None:
                        # A late pre-candidate interval is only diagnostic.  A
                        # late confirmation interval has already reset the old
                        # window.  In either case this newly completed exact
                        # signature/group observation may anchor a fresh one.
                        last_signature = signature
                        signature_since = confirmation_completed
                        signature_first_utc = now_utc()
                        confirmation_candidate_count += 1
                        if not group_gap_within_bound:
                            last_sample = confirmation_completed
                    elif (
                        confirmation_completed - signature_since
                        >= ZERO_KF_WATCHDOG_GRACE_SECONDS
                    ):
                        last_signature = signature
                        final_signature = parse_zero_kf_post_shutdown_signature(
                            stdout_path, trajectory_path, keyframe_path
                        )
                        final_signature_completed = float(monotonic())
                        final_signature_gap_within_bound = record_observation_gap(
                            final_signature_completed,
                            phase="CONFIRMATION",
                            reason="FINAL_SIGNATURE_REVALIDATION",
                        )
                        if final_signature_completed >= deadline:
                            return process.poll(), False, True, outcome()
                        if not final_signature_gap_within_bound:
                            # The interrupted window cannot enter the gate.  A
                            # fresh candidate requires a new parser+group proof
                            # on a later sample; the parser alone is not enough.
                            last_sample = final_signature_completed
                        elif permanently_disabled:
                            clear_confirmation_candidate()
                        elif final_signature.get("parser_proven") is not True:
                            final_parser_errors = [
                                str(value)
                                for value in final_signature.get("errors", [])
                            ]
                            monitoring_errors.extend(
                                [
                                    f"FINAL_SIGNATURE_PARSER:{value}"
                                    for value in final_parser_errors
                                ]
                                or [
                                    "FINAL_SIGNATURE_PARSER_UNPROVEN_WITHOUT_REASON"
                                ]
                            )
                            permanently_disabled = True
                            clear_confirmation_candidate()
                        elif final_signature.get("confirmed") is not True:
                            # The parser remains trustworthy, but the trigger
                            # ceased to be continuous before gate entry.  This
                            # is an ordinary candidate reset, not an unproven
                            # control chain; a later exact sample may begin a
                            # new 30 s window within the same fixed budget.
                            clear_confirmation_candidate()
                            last_sample = final_signature_completed
                        else:
                            # The ordinary observation phase has already been
                            # bounded above against its original sample start.
                            # Start a fresh, independently bounded phase at the
                            # completed final signature revalidation so the
                            # final double group proof is not cumulatively
                            # charged for earlier parser/proof work.
                            last_sample = final_signature_completed
                            final_gate_signature = json.loads(
                                json.dumps(final_signature, allow_nan=False)
                            )
                            final_gate_signature_completed = (
                                final_signature_completed
                            )
                            gate = runtime_monitor.watchdog_sigterm_exact_group(
                                expected_executable,
                                expected_argv,
                                deadline_monotonic=deadline,
                                final_gate_started_monotonic=(
                                    final_signature_completed
                                ),
                                maximum_final_gate_duration_seconds=(
                                    ZERO_KF_WATCHDOG_FINAL_GATE_SECONDS
                                ),
                                monotonic=monotonic,
                            )
                            final_gate_adjudication = json.loads(
                                json.dumps(gate, allow_nan=False)
                            )
                            gate_pre_signal = gate.get("pre_signal_monotonic")
                            if (
                                type(gate_pre_signal) in (int, float)
                                and math.isfinite(float(gate_pre_signal))
                            ):
                                record_observation_gap(
                                    float(gate_pre_signal),
                                    phase="FINAL_GATE",
                                    reason="FINAL_GATE_ADJUDICATION",
                                    force=True,
                                )
                            action = (
                                gate
                                if gate.get("signal_attempted") is True
                                else None
                            )
                            last_signature = final_signature
                            gate_timing_errors = final_gate_receipt_errors(
                                gate,
                                final_signature_completed,
                            )
                            if gate_timing_errors:
                                monitoring_errors.extend(
                                    f"FINAL_SIGNAL_GATE:{value}"
                                    for value in gate_timing_errors
                                )
                                monitoring_errors.extend(
                                    f"FINAL_SIGNAL_GATE:{value}"
                                    for value in gate.get("errors", [])
                                )
                                permanently_disabled = True
                                clear_confirmation_candidate()
                            elif gate.get("signal_sent") is True:
                                pass
                            elif (
                                gate.get("classification")
                                == "LEADER_REAPED_BEFORE_SIGNAL"
                                and type(gate.get("leader_returncode")) is int
                                and isinstance(gate.get("reap"), Mapping)
                            ):
                                final_returncode = int(gate["leader_returncode"])
                                record_passive_exit(
                                    f"FINAL_SIGNAL_GATE:{gate.get('phase')}",
                                    gate,
                                    final_returncode,
                                    gate["reap"],
                                )
                                return final_returncode, True, False, outcome()
                            elif (
                                gate.get("classification")
                                == "TERMINAL_TRANSITION_PENDING_REAP"
                            ):
                                pending_poll_returncode = process.poll()
                                pending_poll_observed_monotonic_ns = (
                                    time.monotonic_ns()
                                )
                                pending_terminal_transition = {
                                    "phase": (
                                        "FINAL_SIGNAL_GATE:"
                                        f"{gate.get('phase')}"
                                    ),
                                    "evidence": gate,
                                    "poll_observed_monotonic_ns": (
                                        pending_poll_observed_monotonic_ns
                                    ),
                                    "errors": [
                                        f"FINAL_SIGNAL_GATE:{value}"
                                        for value in gate.get("errors", [])
                                    ],
                                }
                                if pending_poll_returncode is not None:
                                    (
                                        pending_returncode,
                                        pending_reap,
                                        pending_reap_error,
                                    ) = reap_after_same_popen_poll(
                                        "FINAL_GATE_PENDING_POLL_THEN_WAIT_ZERO",
                                        pending_poll_returncode,
                                        pending_poll_observed_monotonic_ns,
                                    )
                                    if (
                                        pending_reap_error is not None
                                        or pending_reap is None
                                        or pending_returncode is None
                                    ):
                                        monitoring_errors.append(
                                            "LEADER_REAP_FAILED:"
                                            f"{pending_reap_error or 'UNPROVEN'}"
                                        )
                                        return (
                                            pending_returncode,
                                            False,
                                            False,
                                            outcome(),
                                        )
                                    clear_confirmation_candidate()
                                    record_passive_exit(
                                        str(pending_terminal_transition["phase"]),
                                        pending_terminal_transition["evidence"],
                                        pending_returncode,
                                        pending_reap,
                                    )
                                    return pending_returncode, True, False, outcome()
                                clear_confirmation_candidate()
                            else:
                                monitoring_errors.extend(
                                    f"FINAL_SIGNAL_GATE:{value}"
                                    for value in gate.get("errors", [])
                                )
                                if not gate.get("errors"):
                                    monitoring_errors.append(
                                        "FINAL_SIGNAL_GATE:UNPROVEN_WITHOUT_REASON"
                                    )
                                permanently_disabled = True
                                clear_confirmation_candidate()
            else:
                clear_confirmation_candidate()
        next_sample += ZERO_KF_WATCHDOG_TARGET_POLL_SECONDS
        delay = max(0.0, min(next_sample, deadline) - float(monotonic()))
        scheduled_wait_started_monotonic_ns = time.monotonic_ns()
        try:
            returncode = process.wait(timeout=delay)
            scheduled_wait_completed_monotonic_ns = time.monotonic_ns()
            scheduled_poll_observed_monotonic_ns = (
                int(pending_terminal_transition["poll_observed_monotonic_ns"])
                if pending_terminal_transition is not None
                else loop_poll_observed_monotonic_ns
            )
            reap = build_same_popen_reap(
                source=(
                    "PENDING_TEARDOWN_BOUNDED_WAIT"
                    if pending_terminal_transition is not None
                    else "SCHEDULED_BOUNDED_WAIT"
                ),
                poll_observed_monotonic_ns=(
                    scheduled_poll_observed_monotonic_ns
                ),
                poll_returncode=None,
                wait_started_monotonic_ns=scheduled_wait_started_monotonic_ns,
                wait_completed_monotonic_ns=(
                    scheduled_wait_completed_monotonic_ns
                ),
                wait_timeout_seconds=float(delay),
                wait_returncode=returncode,
            )
            if reap is None:
                monitoring_errors.append("LEADER_REAP_FAILED:UNPROVEN")
                return returncode, False, False, outcome()
            if pending_terminal_transition is not None:
                record_passive_exit(
                    str(pending_terminal_transition["phase"]),
                    pending_terminal_transition["evidence"],
                    returncode,
                    reap,
                )
            elif action is None and not monitoring_errors:
                phase = "SCHEDULED_WAIT"
                record_passive_exit(
                    f"ORDINARY_PROCESS_EXIT:{phase}",
                    ordinary_exit_evidence(phase, returncode),
                    returncode,
                    reap,
                )
            return returncode, True, False, outcome()
        except subprocess.TimeoutExpired:
            continue


def optional_identity(path: Path) -> dict[str, object] | None:
    return identity(path) if path.is_file() and not path.is_symlink() else None


def build_zero_kf_watchdog_receipt(
    root: Path,
    case_id: str,
    budget: int,
    repeat: int,
    attempt_index: int,
    attempt: Mapping[str, Any],
    outcome: Mapping[str, object] | None,
    final_child_returncode: int | None,
    extra_errors: Sequence[str],
) -> dict[str, object]:
    errors = [str(value) for value in extra_errors]
    if not isinstance(outcome, Mapping):
        errors.append("WATCHDOG_OUTCOME_MISSING")
        outcome = {}
    receipt_outcome = dict(outcome)
    receipt_outcome["final_child_returncode"] = final_child_returncode
    errors.extend(str(value) for value in outcome.get("monitoring_errors", []))
    required_paths = {
        "attempt_manifest": root / "attempt_manifest.json",
        "start_claim": root / "start_claim.json",
        "launch_receipt": root / "launch_receipt.json",
        "stdout": root / "headless.stdout.log",
        "runtime_resource_monitor": root / "runtime_resource_monitor.json",
    }
    pins: dict[str, object] = {}
    for label, path in required_paths.items():
        try:
            pins[label] = identity(path)
        except BaseException as error:
            pins[label] = None
            errors.append(f"WATCHDOG_PIN_UNREADABLE:{label}:{type(error).__name__}:{error}")
    gate = outcome.get("final_signal_gate_adjudication")
    action = outcome.get("watchdog_action")
    if isinstance(action, Mapping):
        if action.get("signal_attempted") is not True:
            errors.append("WATCHDOG_ACTION_WITHOUT_SIGNAL_ATTEMPT")
        if not isinstance(gate, Mapping) or not strict_json_equal(action, gate):
            errors.append("WATCHDOG_ACTION_FINAL_GATE_BINDING_MISMATCH")
    elif isinstance(gate, Mapping) and gate.get("signal_attempted") is True:
        errors.append("WATCHDOG_SIGNAL_ATTEMPT_MISSING_ACTION")
    sent = bool(isinstance(action, Mapping) and action.get("signal_sent") is True)
    if outcome.get("signal_attempted") is True and not sent:
        errors.append("WATCHDOG_SIGNAL_ATTEMPT_NOT_DELIVERED")
    errors = list(dict.fromkeys(errors))
    receipt_outcome["monitoring_errors"] = errors
    receipt_outcome["monitor_proven"] = bool(
        outcome.get("monitor_proven") is True and not errors
    )
    monitor_proven = bool(
        receipt_outcome.get("monitor_proven") is True
        and all(value is not None for value in pins.values())
    )
    return {
        "schema_version": ZERO_KF_WATCHDOG_SCHEMA,
        "experiment_id": EXPERIMENT_ID,
        "finalized_at_utc": now_utc(),
        "case_id": case_id,
        "budget": budget,
        "arm": f"hfnet_openloop_{budget}",
        "repeat": repeat,
        "attempt_index": attempt_index,
        "attempt_root": str(root),
        "status": (
            "SIGTERM_SENT_FOR_CONFIRMED_ZERO_KF_POST_SHUTDOWN_SAVE_HANG"
            if sent and monitor_proven
            else "PASSIVE_NO_WATCHDOG_SIGNAL"
            if monitor_proven
            else "WATCHDOG_SUPERVISION_UNPROVEN_FAIL_CLOSED"
        ),
        "monitor_proven": monitor_proven,
        "monitoring_errors": errors,
        "fixed_contract": attempt.get("zero_kf_post_shutdown_watchdog"),
        "outcome": receipt_outcome,
        "final_signal_gate_adjudication": (
            dict(gate) if isinstance(gate, Mapping) else None
        ),
        "watchdog_action": dict(action) if isinstance(action, Mapping) else None,
        "final_child_returncode": final_child_returncode,
        "passive_exit_adjudication": (
            dict(outcome["passive_exit_adjudication"])
            if isinstance(outcome.get("passive_exit_adjudication"), Mapping)
            else None
        ),
        "sigterm_sent": sent,
        "signal_attempt_count": 1 if outcome.get("signal_attempted") is True else 0,
        "signal_count": 1 if sent else 0,
        "signal": "SIGTERM" if sent else None,
        "signal_scope": "EXACT_REVALIDATED_PROCESS_GROUP" if sent else None,
        "sigkill_sent_by_watchdog": False,
        "retry_permitted": False,
        "pins": pins,
        "final_outputs": {
            "trajectory_path": str(root / "result/trajectory.txt"),
            "trajectory_absent_non_symlink": not (
                (root / "result/trajectory.txt").exists()
                or (root / "result/trajectory.txt").is_symlink()
            ),
            "keyframe_path": str(root / "result/trajectory_keyframe.txt"),
            "keyframe_absent_non_symlink": not (
                (root / "result/trajectory_keyframe.txt").exists()
                or (root / "result/trajectory_keyframe.txt").is_symlink()
            ),
        },
    }


def runtime_environment(tmp_root: Path) -> dict[str, str]:
    tmp_root.mkdir(parents=True, exist_ok=True)
    return {
        "CUDA_VISIBLE_DEVICES": "0",
        "HOME": "/home/ma",
        "USER": "ma",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "TMPDIR": str(tmp_root / "tmp"),
        "XDG_CACHE_HOME": str(tmp_root / "xdg_cache"),
        "CUDA_CACHE_PATH": str(tmp_root / "cuda_cache"),
        "LD_LIBRARY_PATH": ":".join(
            [
                "/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1/lib",
                "/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1/Thirdparty/g2o/lib",
                "/home/ma/SLAM/aqua_deps/install/lib",
                "/home/ma/opt/hfnet_cuda116_trt851_r1/usr/lib/x86_64-linux-gnu",
                "/home/ma/opt/hfnet_cuda116_trt851_r1/usr/local/cuda-11.6/targets/x86_64-linux/lib",
                "/home/ma/opt/hfnet_cuda116_trt851_r1/usr/local/cuda-11.8/targets/x86_64-linux/lib",
            ]
        ),
    }


def process_start_receipt(process: subprocess.Popen[bytes], attempt: Mapping[str, Any]) -> dict[str, object]:
    proc = Path("/proc") / str(process.pid)
    errors: list[str] = []
    pgid: int | None = None
    session: int | None = None
    try:
        raw_stat = (proc / "stat").read_text(encoding="ascii")
        close = raw_stat.rfind(")")
        tail = raw_stat[close + 2 :].split()
        if close < 0 or int(raw_stat[: raw_stat.find("(")].strip()) != process.pid:
            raise ValueError("pid or comm boundary mismatch")
        start_ticks = int(tail[19])
        pgid = int(tail[2])
        session = int(tail[3])
    except (OSError, ValueError, IndexError):
        start_ticks = None
        errors.append("PROC_STAT_IDENTITY_UNREADABLE")
    try:
        executable = os.readlink(proc / "exe")
    except OSError:
        executable = ""
        errors.append("EXECUTABLE_UNREADABLE")
    try:
        argv = [
            token.decode("utf-8", errors="replace")
            for token in (proc / "cmdline").read_bytes().split(b"\0") if token
        ]
    except OSError:
        argv = []
        errors.append("ARGV_UNREADABLE")
    expected_argv = [str(value) for value in attempt["launch"]["argv"]]
    if executable != str(BINARY):
        errors.append("EXECUTABLE_MISMATCH")
    if argv != expected_argv:
        errors.append("ARGV_MISMATCH")
    if pgid != process.pid:
        errors.append("PROCESS_GROUP_MISMATCH")
    if session != process.pid:
        errors.append("SESSION_LEADER_MISMATCH")
    return {
        "schema_version": "aqua-fe-fair-stability-hfnet-launch-receipt-v9",
        "experiment_id": EXPERIMENT_ID,
        "valid": not errors,
        "errors": errors,
        "pid": process.pid,
        "start_ticks": start_ticks,
        "pgid": pgid,
        "session": session,
        "executable": executable,
        "argv": argv,
        "expected_executable": str(BINARY),
        "expected_argv": expected_argv,
    }


def emergency_terminate_unmonitored_child(
    process: subprocess.Popen[bytes],
) -> tuple[int | None, bool]:
    """Fail-safe cleanup used only when monitor construction itself fails."""
    for signal_value in (signal.SIGTERM, signal.SIGKILL):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal_value)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            returncode = process.poll()
            if returncode is not None:
                return returncode, True
            time.sleep(0.05)
    return process.poll(), process.poll() is not None


def write_unproven_monitor_receipt(
    path: Path,
    process: subprocess.Popen[bytes] | None,
    errors: Sequence[str],
) -> dict[str, object]:
    if path.is_file() and not path.is_symlink():
        return json.loads(path.read_text(encoding="utf-8"))
    receipt = {
        "schema_version": "aqua-fe-fair-stability-runtime-resource-monitor-v9",
        "experiment_id": EXPERIMENT_ID,
        "finalized_at_utc": now_utc(),
        "supervised_pid": process.pid if process is not None else None,
        "intrusion_detected": False,
        "monitor_proven": False,
        "monitor_errors": list(errors) or ["RUNTIME_MONITOR_UNAVAILABLE"],
        "pipeline_failure_reasons": ["RUNTIME_RESOURCE_MONITOR_UNPROVEN"],
        "all_intrusions": [],
        "fallback_receipt": True,
    }
    write_exclusive(path, canonical_json(receipt))
    return receipt


def residual_attempt_processes(attempt: Mapping[str, Any], pgid: int | None) -> list[dict[str, object]]:
    needles = [str(attempt["attempt_root"])] + [str(value) for value in attempt["launch"]["argv"][1:]]
    residuals: list[dict[str, object]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        pid = int(entry.name)
        record = process_record(pid)
        try:
            observed_pgid = os.getpgid(pid)
        except OSError:
            observed_pgid = None
        command = str(record["command"])
        if (pgid is not None and observed_pgid == pgid) or any(
            needle in command for needle in needles
        ):
            record["pgid"] = observed_pgid
            residuals.append(record)
    return residuals


def run_attempt(case_id: str, budget: int, repeat: int, attempt_index: int = 1) -> dict[str, object]:
    experiment, attempt = verify_attempt(case_id, budget, repeat, True, attempt_index)
    root = attempt_root(case_id, budget, repeat, attempt_index)
    lock_path = EXPERIMENT_ROOT / ".gpu_serial.lock"
    with open_regular_lock(lock_path) as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        ordinal_state = authorize_ordinal(
            EXPERIMENT_ROOT,
            case_id,
            f"hfnet_openloop_{budget}",
            repeat,
            attempt_index,
        )
        dispatch = verify_dispatch_claim(
            EXPERIMENT_ROOT,
            root,
            case_id,
            f"hfnet_openloop_{budget}",
            repeat,
            attempt_index,
        )
        gate = resource_gate(
            port=None,
            experiment_root=EXPERIMENT_ROOT,
            workspace_root=ROOT,
        )
        if gate["ready"] is not True:
            raise ContractError(f"RESOURCE_GATE_BLOCKED:{gate['errors']}")
        verify_attempt(case_id, budget, repeat, True, attempt_index)
        systemd_authority = systemd_start_authority(ordinal_state)
        claim = {
            "schema_version": "aqua-fe-fair-stability-hfnet-start-claim-v9",
            "experiment_id": EXPERIMENT_ID,
            "claimed_at_utc": now_utc(),
            "case_id": case_id,
            "budget": budget,
            "repeat": repeat,
            "attempt_index": attempt_index,
            "planned_ordinal": int(ordinal_state["cell"]["ordinal"]),
            "ordinal_state_before_start": ordinal_state,
            "ordinal_dispatch": dispatch,
            "resource_gate": gate,
            "backend_freeze": identity(BACKEND_FREEZE),
            "runtime_resource_monitor_control": identity(RUNTIME_RESOURCE_MONITOR),
            "attempt_manifest": identity(root / "attempt_manifest.json"),
            "runner": identity(RUNNER),
            "systemd_start_receipt": systemd_authority,
        }
        write_exclusive(root / "start_claim.json", canonical_json(claim))
        stdout_path = root / "headless.stdout.log"
        stderr_path = root / "headless.stderr.log"
        started = now_utc()
        start_monotonic = time.monotonic()
        process: subprocess.Popen[bytes] | None = None
        returncode: int | None = None
        reaped = False
        timed_out = False
        supervisor_error: str | None = None
        launch_receipt: dict[str, object] | None = None
        runtime_monitor: RuntimeResourceMonitor | None = None
        runtime_monitor_receipt: dict[str, object] | None = None
        runtime_monitor_errors: list[str] = []
        zero_kf_watchdog_outcome: dict[str, object] | None = None
        zero_kf_watchdog_receipt: dict[str, object] | None = None
        zero_kf_watchdog_receipt_errors: list[str] = []
        process_group_clean = False
        # Schema-continuity field; always empty. SIGTERM/SIGINT continue to
        # raise through result publication, so interrupted postprocessing can
        # never be reported as a normal algorithm outcome.
        deferred_postprocess_signals: list[int] = []

        previous_handlers = {
            value: signal.getsignal(value) for value in (signal.SIGTERM, signal.SIGINT)
        }
        for value in previous_handlers:
            signal.signal(value, raise_supervisor_interrupt)
        try:
            environment = runtime_environment(root / "runtime_temp")
            for key in ("TMPDIR", "XDG_CACHE_HOME", "CUDA_CACHE_PATH"):
                Path(environment[key]).mkdir(parents=True, exist_ok=True)
            with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
                process = subprocess.Popen(
                    attempt["launch"]["argv"],
                    cwd=attempt["launch"]["cwd"],
                    env=environment,
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=True,
                )
                runtime_monitor = RuntimeResourceMonitor(
                    process,
                    root / "runtime_resource_monitor.json",
                )
                launch_receipt = process_start_receipt(process, attempt)
                write_exclusive(
                    root / "launch_receipt.json", canonical_json(launch_receipt)
                )
                (
                    returncode,
                    reaped,
                    timed_out,
                    zero_kf_watchdog_outcome,
                ) = wait_with_zero_kf_watchdog(
                    process,
                    runtime_monitor,
                    stdout_path,
                    root / "result/trajectory.txt",
                    root / "result/trajectory_keyframe.txt",
                    str(BINARY),
                    [str(value) for value in attempt["launch"]["argv"]],
                    timeout=TIMEOUT_SECONDS,
                )
                if timed_out:
                    returncode, reaped = runtime_monitor.terminate()
        except BaseException as error:
            supervisor_error = f"{type(error).__name__}:{error}"
            if process is not None and not reaped:
                try:
                    if runtime_monitor is not None:
                        returncode, reaped = runtime_monitor.terminate()
                    else:
                        returncode, reaped = emergency_terminate_unmonitored_child(
                            process
                        )
                except BaseException as cleanup_error:
                    runtime_monitor_errors.append(
                        f"TERMINATE_FAILED:{type(cleanup_error).__name__}:{cleanup_error}"
                    )
        finally:
            if runtime_monitor is not None:
                try:
                    process_group_clean = runtime_monitor.reap_process_group()
                except BaseException as cleanup_error:
                    runtime_monitor_errors.append(
                        "PROCESS_GROUP_REAP_FAILED:"
                        f"{type(cleanup_error).__name__}:{cleanup_error}"
                    )
                try:
                    runtime_monitor_receipt = runtime_monitor.finalize()
                except BaseException as finalize_error:
                    runtime_monitor_errors.append(
                        f"FINALIZE_FAILED:{type(finalize_error).__name__}:{finalize_error}"
                    )
            elif process is None:
                process_group_clean = True
            if runtime_monitor_receipt is None:
                try:
                    runtime_monitor_receipt = write_unproven_monitor_receipt(
                        root / "runtime_resource_monitor.json",
                        process,
                        runtime_monitor_errors
                        + ["RUNTIME_MONITOR_NOT_SUCCESSFULLY_FINALIZED"],
                    )
                except BaseException as receipt_error:
                    runtime_monitor_errors.append(
                        "FALLBACK_RECEIPT_FAILED:"
                        f"{type(receipt_error).__name__}:{receipt_error}"
                    )
            try:
                zero_kf_watchdog_receipt = build_zero_kf_watchdog_receipt(
                    root,
                    case_id,
                    budget,
                    repeat,
                    attempt_index,
                    attempt,
                    zero_kf_watchdog_outcome,
                    returncode,
                    zero_kf_watchdog_receipt_errors,
                )
                write_exclusive(
                    root / "zero_kf_post_shutdown_watchdog.json",
                    canonical_json(zero_kf_watchdog_receipt),
                )
            except BaseException as watchdog_receipt_error:
                zero_kf_watchdog_receipt_errors.append(
                    "WATCHDOG_RECEIPT_PUBLICATION_FAILED:"
                    f"{type(watchdog_receipt_error).__name__}:"
                    f"{watchdog_receipt_error}"
                )
        execution = {
            "started_at_utc": started,
            "ended_at_utc": now_utc(),
            "duration_seconds": time.monotonic() - start_monotonic,
            "raw_returncode": returncode,
            "timed_out": timed_out,
            "child_reaped": reaped,
            "supervisor_error": supervisor_error,
            "popen_invocations": 1 if process is not None else 0,
            "postprocess_signals_deferred": deferred_postprocess_signals,
            "runtime_resource_monitor_errors": runtime_monitor_errors,
        }
        residuals = residual_attempt_processes(attempt, process.pid if process is not None else None)
        execution["supervised_process_group_empty_after_wait"] = process_group_clean
        execution["residual_attempt_processes"] = residuals
        stamps = read_ns_lines(root / "cam0_times_vins_matched.txt")
        trajectory = parse_trajectory(root / "result/trajectory.txt", stamps)
        keyframes = parse_trajectory(root / "result/trajectory_keyframe.txt", stamps)
        log = parse_log(stdout_path, stderr_path, len(stamps))
        events = accepted_events(log, trajectory)
        init_ids = [
            int(value) for value in log.get("init_frame_ids", [])
            if 0 <= int(value) < len(stamps)
        ]
        init_latency = (
            (stamps[int(init_ids[0])] - stamps[0]) / 1e9 if init_ids else None
        )
        pipeline_failures: list[str] = []
        algorithm_failures: list[str] = []
        zero_kf_watchdog_path = root / "zero_kf_post_shutdown_watchdog.json"
        try:
            zero_kf_watchdog_artifact: dict[str, object] = identity(
                zero_kf_watchdog_path
            )
        except BaseException as watchdog_identity_error:
            zero_kf_watchdog_artifact = {
                "error": (
                    f"{type(watchdog_identity_error).__name__}:"
                    f"{watchdog_identity_error}"
                )
            }
            zero_kf_watchdog_receipt_errors.append(
                "WATCHDOG_IDENTITY_UNREADABLE:"
                f"{type(watchdog_identity_error).__name__}:{watchdog_identity_error}"
            )
        watchdog_sent = bool(
            isinstance(zero_kf_watchdog_receipt, Mapping)
            and zero_kf_watchdog_receipt.get("sigterm_sent") is True
        )
        if (
            not isinstance(zero_kf_watchdog_receipt, Mapping)
            or zero_kf_watchdog_receipt.get("schema_version")
            != ZERO_KF_WATCHDOG_SCHEMA
            or zero_kf_watchdog_receipt.get("experiment_id") != EXPERIMENT_ID
            or zero_kf_watchdog_receipt.get("case_id") != case_id
            or zero_kf_watchdog_receipt.get("budget") != budget
            or zero_kf_watchdog_receipt.get("repeat") != repeat
            or zero_kf_watchdog_receipt.get("attempt_index") != attempt_index
            or zero_kf_watchdog_receipt.get("monitor_proven") is not True
            or bool(zero_kf_watchdog_receipt_errors)
            or "error" in zero_kf_watchdog_artifact
        ):
            pipeline_failures.append(ZERO_KF_WATCHDOG_PIPELINE_CODE)
        if watchdog_sent:
            algorithm_failures.append(ZERO_KF_WATCHDOG_ALGORITHM_CODE)
        runtime_monitor_path = root / "runtime_resource_monitor.json"
        try:
            runtime_monitor_artifact: dict[str, object] = identity(
                runtime_monitor_path
            )
        except BaseException as monitor_identity_error:
            runtime_monitor_artifact = {
                "error": (
                    f"{type(monitor_identity_error).__name__}:"
                    f"{monitor_identity_error}"
                )
            }
            runtime_monitor_errors.append(
                "RUNTIME_MONITOR_IDENTITY_UNREADABLE:"
                f"{type(monitor_identity_error).__name__}:{monitor_identity_error}"
            )
        monitor_reason_codes = (
            [
                str(value)
                for value in runtime_monitor_receipt.get(
                    "pipeline_failure_reasons", []
                )
            ]
            if isinstance(runtime_monitor_receipt, Mapping)
            else []
        )
        if (
            isinstance(runtime_monitor_receipt, Mapping)
            and runtime_monitor_receipt.get("intrusion_detected") is True
        ) or "MIDRUN_EXTERNAL_RESOURCE_INTRUSION" in monitor_reason_codes:
            pipeline_failures.append("MIDRUN_EXTERNAL_RESOURCE_INTRUSION")
        if (
            not isinstance(runtime_monitor_receipt, Mapping)
            or runtime_monitor_receipt.get("schema_version")
            != "aqua-fe-fair-stability-runtime-resource-monitor-v9"
            or runtime_monitor_receipt.get("experiment_id") != EXPERIMENT_ID
            or runtime_monitor_receipt.get("monitor_proven") is not True
            or bool(runtime_monitor_errors)
            or "RUNTIME_RESOURCE_MONITOR_UNPROVEN" in monitor_reason_codes
            or "error" in runtime_monitor_artifact
        ):
            pipeline_failures.append("RUNTIME_RESOURCE_MONITOR_UNPROVEN")
        if process is None or supervisor_error is not None or not reaped:
            pipeline_failures.append("SUPERVISOR_LAUNCH_OR_REAP_FAILED")
        if launch_receipt is None or launch_receipt.get("valid") is not True:
            pipeline_failures.append("ESTIMATOR_START_IDENTITY_UNPROVEN")
        pipeline_failures.extend(
            supervised_shutdown_failure_codes(process_group_clean, residuals)
        )
        if timed_out:
            algorithm_failures.append("ESTIMATOR_TIMEOUT")
        if returncode not in (None, 0) and not timed_out and not watchdog_sent:
            if log.get("environment_failure_events"):
                pipeline_failures.append("GPU_DRIVER_OR_RUNTIME_LOAD_FAILURE")
            else:
                algorithm_failures.append("ESTIMATOR_NONZERO_EXIT")
        if trajectory.get("valid") is not True:
            algorithm_failures.append("TRAJECTORY_INVALID")
        coverage = float(trajectory.get("coverage_fraction", 0.0))
        contiguous = float(trajectory.get("longest_contiguous_fraction", 0.0))
        if coverage < MIN_PARTIAL_COVERAGE or contiguous < MIN_PARTIAL_COVERAGE:
            algorithm_failures.append("TRAJECTORY_COVERAGE_BELOW_50_PERCENT")
        elif coverage < MIN_SUCCESS_COVERAGE or contiguous < MIN_SUCCESS_COVERAGE:
            algorithm_failures.append("PARTIAL_TRAJECTORY_COVERAGE_BELOW_70_PERCENT")
        if keyframes.get("valid") is not True or int(keyframes.get("pose_count", 0)) < 1:
            algorithm_failures.append("NO_VALID_KEYFRAME_TRAJECTORY")
        if log.get("valid") is not True or log.get("final_atlas_nonempty") is not True:
            algorithm_failures.append("FINAL_ATLAS_EMPTY_OR_UNPARSEABLE")
        if init_latency is None:
            algorithm_failures.append("NO_SUCCESSFUL_INITIALIZATION")
        elif init_latency > MAX_INIT_LATENCY_S:
            algorithm_failures.append("INITIALIZATION_AFTER_10_SECONDS")
        if events["unresolved_resets"]:
            algorithm_failures.append("ACTIVE_MAP_RESET_BOUNDARY_UNRESOLVED")
        if events["unresolved_solver_risks"]:
            algorithm_failures.append("SOLVER_OR_TRACKING_RISK_BOUNDARY_UNRESOLVED")
        if events["support_reinitializations"]:
            algorithm_failures.append("REINITIALIZATION_WITHIN_ACCEPTED_SUPPORT")
        if int(log.get("loop_event_text_count", 0)):
            algorithm_failures.append("LOOP_EVENT_OBSERVED_DESPITE_OPEN_LOOP_CONFIG")

        integrity: dict[str, object] = {
            "runtime_resource_monitor": runtime_monitor_artifact,
            "zero_kf_post_shutdown_watchdog": zero_kf_watchdog_artifact,
        }
        for label, path in (
            ("local_onnx_post", root / "run_local_model/HFNet-RT/HF-Net.onnx"),
            ("local_cache_post", root / "run_local_model/HFNet-RT/HF-Net.cache"),
            ("runtime_config", root / "runtime_config_openloop.yaml"),
            ("selected_times", root / "cam0_times_vins_matched.txt"),
        ):
            try:
                integrity[label] = identity(path)
            except BaseException as error:
                integrity[label] = {"error": f"{type(error).__name__}:{error}"}
                pipeline_failures.append(f"POSTRUN_IDENTITY_UNREADABLE:{label}")
        local_onnx_post = integrity["local_onnx_post"]
        if isinstance(local_onnx_post, Mapping) and local_onnx_post.get("sha256") != EXPECTED_STACK["onnx"][1]:
            pipeline_failures.append("ONNX_MODEL_DRIFT")
        runtime_config_post = integrity["runtime_config"]
        if isinstance(runtime_config_post, Mapping) and runtime_config_post.get("sha256") != attempt["runtime_config"]["sha256"]:
            pipeline_failures.append("RUNTIME_CONFIG_DRIFT")
        selected_times_post = integrity["selected_times"]
        if isinstance(selected_times_post, Mapping) and selected_times_post.get("sha256") != attempt["selected_times"]["sha256"]:
            pipeline_failures.append("SELECTED_TIMESTAMPS_DRIFT")
        try:
            verify_attempt(case_id, budget, repeat, False, attempt_index)
            integrity["full_frozen_input_and_stack_reverification"] = "PASS"
        except BaseException as error:
            integrity["full_frozen_input_and_stack_reverification"] = (
                f"FAIL:{type(error).__name__}:{error}"
            )
            pipeline_failures.append("POSTRUN_FROZEN_INPUT_OR_STACK_REVERIFICATION_FAILED")
        integrity["local_cache_seed_pre"] = attempt["local_cache_seed_pre"]
        local_cache_post = integrity["local_cache_post"]
        integrity["cache_mutation_expected"] = True
        integrity["cache_changed"] = bool(
            isinstance(local_cache_post, Mapping)
            and local_cache_post.get("sha256") != attempt["local_cache_seed_pre"]["sha256"]
        )

        pipeline_failures = list(dict.fromkeys(pipeline_failures))
        algorithm_failures = list(dict.fromkeys(algorithm_failures))
        if pipeline_failures:
            status = "PIPELINE_INVALID"
        elif not algorithm_failures:
            status = "SUCCESS"
        elif algorithm_failures == ["PARTIAL_TRAJECTORY_COVERAGE_BELOW_70_PERCENT"]:
            status = "PARTIAL_NON_SUCCESS"
        else:
            status = "ALGORITHM_FAILURE"
        failures = pipeline_failures + algorithm_failures
        clean_success = (
            status == "SUCCESS"
            and int(log.get("active_map_reset_count", 0)) == 0
            and int(log.get("solver_risk_count", 0)) == 0
            and int(log.get("reinitialization_count", 0)) == 0
            and len(init_ids) == 1
        )
        result = {
            "schema_version": "aqua-fe-fair-stability-hfnet-result-v9",
            "experiment_id": EXPERIMENT_ID,
            "status": status,
            "clean_success": clean_success,
            "case_id": case_id,
            "arm": f"hfnet_openloop_{budget}",
            "repeat": repeat,
            "attempt_index": attempt_index,
            "failure_codes": failures,
            "pipeline_failure_codes": pipeline_failures,
            "algorithm_failure_codes": algorithm_failures,
            "execution": execution,
            "launch_receipt": launch_receipt,
            "runtime_resource_monitor": runtime_monitor_artifact,
            "zero_kf_post_shutdown_watchdog": zero_kf_watchdog_artifact,
            "zero_kf_post_shutdown_watchdog_decision": {
                "monitor_proven": (
                    zero_kf_watchdog_receipt.get("monitor_proven")
                    if isinstance(zero_kf_watchdog_receipt, Mapping)
                    else False
                ),
                "sigterm_sent": watchdog_sent,
                "retry_permitted": False,
                "pipeline_failure_code_if_unproven": ZERO_KF_WATCHDOG_PIPELINE_CODE,
                "algorithm_failure_code_if_sent": ZERO_KF_WATCHDOG_ALGORITHM_CODE,
            },
            "runtime_resource_monitor_decision": {
                "intrusion_detected": (
                    runtime_monitor_receipt.get("intrusion_detected")
                    if isinstance(runtime_monitor_receipt, Mapping)
                    else None
                ),
                "monitor_proven": (
                    runtime_monitor_receipt.get("monitor_proven")
                    if isinstance(runtime_monitor_receipt, Mapping)
                    else False
                ),
                "pipeline_failure_reasons": monitor_reason_codes,
            },
            "support": {"trajectory": trajectory, "keyframes": keyframes, "log": log, "events": events},
            "initialization_latency_seconds": init_latency,
            "integrity": integrity,
            "claim_boundary": {
                "outcome_selected_roster": True,
                "loop_closing_disabled": True,
                "system_ranking_supported": False,
                "runtime_claim_allowed": False,
                "failed_accuracy_is_na": True,
            },
        }
        write_exclusive(root / "run_result.json", canonical_json(result))
        for value, handler in previous_handlers.items():
            signal.signal(value, handler)
        return result


def summary() -> dict[str, object]:
    """Use the receipt-validated one-attempt-per-coordinate state machine."""
    from summarize_fair_stability_v9 import summarize as summarize_receipts

    return summarize_receipts()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("freeze-inputs")
    subparsers.add_parser("prepare-all")
    for name in ("prepare", "check", "run"):
        child = subparsers.add_parser(name)
        child.add_argument("--case", required=True, choices=CASE_ORDER)
        child.add_argument("--budget", required=True, type=int, choices=BUDGETS)
        child.add_argument("--repeat", required=True, type=int, choices=REPEATS)
        child.add_argument("--attempt-index", type=int, default=1)
    subparsers.add_parser("resource-check")
    subparsers.add_parser("summary")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "freeze-inputs":
            result = freeze_inputs()
        elif args.command == "prepare-all":
            result = {"prepared_count": len(prepare_all())}
        elif args.command == "prepare":
            result = prepare_attempt(args.case, args.budget, args.repeat, args.attempt_index)
        elif args.command == "check":
            _, attempt = verify_attempt(
                args.case, args.budget, args.repeat, True, args.attempt_index
            )
            gate = resource_gate(
                port=None,
                experiment_root=EXPERIMENT_ROOT,
                workspace_root=ROOT,
            )
            result = {"attempt": attempt, "resource_gate": gate, "ready": gate["ready"]}
        elif args.command == "run":
            result = run_attempt(args.case, args.budget, args.repeat, args.attempt_index)
        elif args.command == "resource-check":
            result = resource_gate(
                port=None,
                experiment_root=EXPERIMENT_ROOT,
                workspace_root=ROOT,
            )
        elif args.command == "summary":
            result = summary()
        else:  # pragma: no cover
            raise ContractError("UNKNOWN_COMMAND")
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        if args.command in ("check", "resource-check") and result.get("ready") is not True:
            return 2
        if args.command == "run" and result.get("status") != "SUCCESS":
            return 3
        return 0
    except BaseException as error:
        print(f"{type(error).__name__}:{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
