#!/usr/bin/env python3
"""Exactly-once fresh paired VINS replays for the A10/A09 KLT-positive roster."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from typing import Any, Iterable, Mapping


ROOT = Path("/home/ma/AQUA-FE_WS")
PROTOCOL = ROOT / "papers/positive_klt_windows_lifecycle_rearmed_backend_v1_protocol.md"
RUNNER = Path(__file__).resolve()
OUTPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/"
    "positive_klt_windows_lifecycle_rearmed_backend_v1"
)
FRONTEND_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/"
    "positive_klt_windows_lifecycle_rearmed_v1"
)
LOCK_PATH = OUTPUT_ROOT / ".multiwindow_backend_supervisor.flock"
TERMINAL_RECEIPT = OUTPUT_ROOT / "terminal_multiwindow_backend_receipt_v1.json"

REPLAY_WRAPPER = ROOT / "scripts/run_existing_featurebag_vins_replay_only_v1.sh"
VINS_WS = Path("/home/ma/SLAM/VINS-Fusion-origin")
VINS_NODE = VINS_WS / "devel/lib/vins/vins_node"

ARM_ORDER = (
    "klt_external_feature_context_fresh_pair_v1",
    "aquafe_lifecycle_rearmed_external_feature_context_fresh_pair_v1",
)
SEQUENCE_ORDER = ("a10", "a09")
METHOD_ID = "AQUAFE_XFEAT_LIFECYCLE_REARMED_DIAGNOSTIC_V1"

SEQUENCES: dict[str, dict[str, Any]] = {
    "a10": {
        "source_indices": [0, 2800],
        "score_indices": [2400, 2800],
        "primary_indices": [2199, 2800],
        "primary_start_ns": 1_542_888_905_994_706_672,
        "raw_end_ns": 1_542_888_936_039_921_424,
        "klt_bag": Path(
            "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v3_recovery/"
            "frontends/klt_input_adoption/features.bag"
        ),
        "camera_config": Path(
            "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v3_recovery/"
            "frontends/klt_input_adoption/aqualoc_archaeo10_pinhole.yaml"
        ),
        "source_config": Path(
            "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v4_backend_recovery/"
            "backends/klt_external_feature_context/vins_aqualoc_archaeo_external.yaml"
        ),
        "ports": {ARM_ORDER[0]: 12091, ARM_ORDER[1]: 12092},
    },
    "a09": {
        "source_indices": [0, 4400],
        "score_indices": [4000, 4400],
        "primary_indices": [3799, 4400],
        "primary_start_ns": 1_542_888_935_990_218_544,
        "raw_end_ns": 1_542_888_966_034_698_672,
        "klt_bag": Path(
            "/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1/"
            "frontends/klt_export/features.bag"
        ),
        "camera_config": Path(
            "/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1/"
            "frontends/klt_export/aqualoc_archaeo09_pinhole.yaml"
        ),
        "source_config": Path(
            "/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1/"
            "backends/klt_external_feature_context/vins_aqualoc_archaeo_external.yaml"
        ),
        "ports": {ARM_ORDER[0]: 12093, ARM_ORDER[1]: 12094},
    },
}

EXPECTED_IDENTITIES: dict[Path, tuple[int, str]] = {
    SEQUENCES["a10"]["klt_bag"]: (
        42_576_500,
        "34e7ea87dd5706c58e666341776107570cc3351794b92da541f7eb8ec0d04b1f",
    ),
    SEQUENCES["a10"]["camera_config"]: (
        357,
        "045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5",
    ),
    SEQUENCES["a10"]["source_config"]: (
        1_005,
        "46db57acf32b1a8f70cfbe67656b7f8544fd7c761e9f79e3c1832e1cce959370",
    ),
    SEQUENCES["a09"]["klt_bag"]: (
        66_859_585,
        "cce64be73ddd545ad469e42adddf9cf8f9592f8316adda69399ec27d0b71494f",
    ),
    SEQUENCES["a09"]["camera_config"]: (
        357,
        "045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5",
    ),
    SEQUENCES["a09"]["source_config"]: (
        986,
        "b928b31af629bddd9ff677953c185778a2172a0f946fce71bfa1e08b5d879178",
    ),
    REPLAY_WRAPPER: (
        3_960,
        "1579a330f1db02a964a87d57ade14dc7809306f69e60c83a0d59c969f718d1e3",
    ),
    VINS_NODE: (
        13_104_360,
        "4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278",
    ),
}


class BackendError(RuntimeError):
    """Fail-closed backend contract violation."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise BackendError(code)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def require_identity(path: Path, expected: tuple[int, str]) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"INPUT_NOT_REGULAR:{path}")
    actual = identity(path)
    require(
        (actual["size_bytes"], actual["sha256"]) == expected,
        f"INPUT_IDENTITY_DRIFT:{path}",
    )
    return actual


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path: Path, value: Any) -> None:
    require(not path.exists() and not path.is_symlink(), f"REFUSE_OVERWRITE:{path}")
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def static_input_identities(sequence: str | None = None) -> dict[str, Any]:
    paths: list[Path] = [REPLAY_WRAPPER, VINS_NODE]
    if sequence is None:
        for name in SEQUENCE_ORDER:
            paths.extend(
                [
                    SEQUENCES[name]["klt_bag"],
                    SEQUENCES[name]["camera_config"],
                    SEQUENCES[name]["source_config"],
                ]
            )
    else:
        item = SEQUENCES[sequence]
        paths.extend([item["klt_bag"], item["camera_config"], item["source_config"]])
    result = {str(path): require_identity(path, EXPECTED_IDENTITIES[path]) for path in paths}
    for path in (PROTOCOL, RUNNER):
        require(path.is_file() and not path.is_symlink(), f"CONTROL_NOT_REGULAR:{path}")
        result[str(path)] = identity(path)
    return result


def refresh_identities(previous: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw_path in previous:
        path = Path(raw_path)
        require(path.is_file() and not path.is_symlink(), f"CLAIMED_INPUT_NOT_REGULAR:{path}")
        result[raw_path] = identity(path)
    return result


def same_identity_maps(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    def compact(values: Mapping[str, Any]) -> dict[str, tuple[int, str]]:
        return {
            key: (int(value["size_bytes"]), str(value["sha256"]))
            for key, value in values.items()
        }

    return compact(left) == compact(right)


def _find_named_identity(value: Any, basename: str) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if {"size_bytes", "sha256"}.issubset(value):
            raw_path = value.get("path")
            if raw_path is not None and Path(str(raw_path)).name == basename:
                return value
        for key, child in value.items():
            if Path(str(key)).name == basename and isinstance(child, dict):
                if {"size_bytes", "sha256"}.issubset(child):
                    return child
            found = _find_named_identity(child, basename)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_named_identity(child, basename)
            if found is not None:
                return found
    return None


def _require_record_identity(record: Mapping[str, Any], actual: Mapping[str, Any], code: str) -> None:
    require(
        int(record.get("size_bytes", -1)) == int(actual["size_bytes"])
        and str(record.get("sha256")) == str(actual["sha256"]),
        code,
    )


def frontend_paths(sequence: str) -> tuple[Path, Path, Path]:
    root = FRONTEND_ROOT / sequence
    return (
        root / "terminal_probe_receipt_v1.json",
        root / "lifecycle_rearmed/formal_run_receipt_v1.json",
        root / "lifecycle_rearmed/full_merged.bag",
    )


def frontend_authority(sequence: str) -> dict[str, Any]:
    terminal_path, stage_path, aqua_bag = frontend_paths(sequence)
    require(
        terminal_path.is_file() and not terminal_path.is_symlink(),
        f"FRONTEND_TERMINAL_MISSING:{sequence}",
    )
    terminal = read_json(terminal_path)
    gate = terminal.get("learned_action_gate") or {}
    value = gate.get("value")
    require(type(value) is int and value >= 0, f"FRONTEND_GATE_VALUE:{sequence}")
    decision = terminal.get("decision") or {}
    require(
        decision.get("backend_started_by_this_runner") is False,
        f"FRONTEND_BACKEND_ALREADY_STARTED:{sequence}",
    )
    require(
        decision.get("automatic_retry_permitted") is False,
        f"FRONTEND_RETRY_POLICY:{sequence}",
    )
    require(terminal.get("method_id") == METHOD_ID, f"FRONTEND_METHOD_ID:{sequence}")
    require(
        terminal.get("score_gate_source_indices_inclusive")
        == SEQUENCES[sequence]["score_indices"],
        f"FRONTEND_SCORE_WINDOW:{sequence}",
    )
    require(
        gate.get("source_indices_inclusive")
        == SEQUENCES[sequence]["score_indices"],
        f"FRONTEND_GATE_SCORE_WINDOW:{sequence}",
    )
    terminal_identity = identity(terminal_path)
    if value == 0:
        require(gate.get("passed") is False, f"ZERO_GATE_PASS_FLAG:{sequence}")
        require(
            decision.get("backend_may_be_prepared") is False,
            f"ZERO_GATE_BACKEND_AUTHORITY:{sequence}",
        )
        status = str(terminal.get("status", ""))
        require(
            "ZERO" in status or "NO_ACTION" in status,
            f"ZERO_GATE_TERMINAL_STATUS:{sequence}:{status}",
        )
        return {
            "sequence": sequence,
            "action_gate": {"value": 0, "passed": False},
            "backend_authorized": False,
            "terminal_status": status,
            "terminal_receipt": terminal_identity,
        }

    require(
        terminal.get("status") == "PASS_SCORE_ACTION_GATE_FRONTEND_ONLY",
        f"FRONTEND_TERMINAL_STATUS:{sequence}",
    )
    require(gate.get("passed") is True, f"POSITIVE_GATE_PASS_FLAG:{sequence}")
    require(
        decision.get("backend_may_be_prepared") is True,
        f"FRONTEND_BACKEND_AUTHORITY:{sequence}",
    )
    require(stage_path.is_file() and not stage_path.is_symlink(), f"FRONTEND_STAGE_MISSING:{sequence}")
    require(aqua_bag.is_file() and not aqua_bag.is_symlink(), f"AQUA_BAG_MISSING:{sequence}")
    stage = read_json(stage_path)
    require(stage.get("status") == "PASS_STAGE_ACCEPTED", f"FRONTEND_STAGE_STATUS:{sequence}")
    audit = stage.get("artifact_audit") or {}
    require(
        audit.get("remove_learned_recovers_klt_exactly") is True,
        f"FRONTEND_DROP_PARITY:{sequence}",
    )
    require((audit.get("gate") or {}).get("value") == value, f"FRONTEND_STAGE_GATE:{sequence}")
    require((audit.get("gate") or {}).get("passed") is True, f"FRONTEND_STAGE_GATE_FLAG:{sequence}")
    stage_identity = identity(stage_path)
    lifecycle_record = terminal.get("lifecycle_receipt") or {}
    _require_record_identity(
        lifecycle_record,
        stage_identity,
        f"FRONTEND_TERMINAL_STAGE_BINDING:{sequence}",
    )
    aqua_identity = identity(aqua_bag)
    recorded_aqua = _find_named_identity(stage, "full_merged.bag")
    require(recorded_aqua is not None, f"FRONTEND_AQUA_OUTPUT_BINDING_MISSING:{sequence}")
    _require_record_identity(
        recorded_aqua,
        aqua_identity,
        f"FRONTEND_AQUA_OUTPUT_BINDING:{sequence}",
    )
    recorded_drop = _find_named_identity(stage, "drop_whole_lineage.bag")
    require(recorded_drop is not None, f"FRONTEND_DROP_OUTPUT_BINDING_MISSING:{sequence}")
    klt_expected = EXPECTED_IDENTITIES[SEQUENCES[sequence]["klt_bag"]]
    require(
        int(recorded_drop.get("size_bytes", -1)) == klt_expected[0]
        and str(recorded_drop.get("sha256")) == klt_expected[1],
        f"FRONTEND_DROP_FILE_NOT_EXACT_KLT:{sequence}",
    )
    return {
        "sequence": sequence,
        "action_gate": {"value": value, "passed": True},
        "backend_authorized": True,
        "terminal_status": terminal["status"],
        "method_id": METHOD_ID,
        "remove_learned_recovers_klt_exactly": True,
        "terminal_receipt": terminal_identity,
        "stage_receipt": stage_identity,
        "aquafe_feature_bag": aqua_identity,
    }


def window_input_identities(sequence: str, authority: Mapping[str, Any]) -> dict[str, Any]:
    result = static_input_identities(sequence)
    for key in ("terminal_receipt", "stage_receipt", "aquafe_feature_bag"):
        if key in authority:
            record = authority[key]
            result[str(record["path"])] = identity(Path(record["path"]))
    return result


def port_available(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def sequence_dir(sequence: str) -> Path:
    return OUTPUT_ROOT / sequence


def stage_paths(sequence: str, arm: str) -> tuple[Path, Path, Path]:
    base = sequence_dir(sequence)
    return (
        base / f".{arm}.stage_v1",
        base / arm,
        base / f"{arm}_failed_v1",
    )


def bag_for(sequence: str, arm: str) -> Path:
    if arm == ARM_ORDER[0]:
        return SEQUENCES[sequence]["klt_bag"]
    return frontend_paths(sequence)[2]


def command_for(sequence: str, arm: str, run_dir: Path) -> tuple[list[str], dict[str, str]]:
    item = SEQUENCES[sequence]
    feature_bag = bag_for(sequence, arm)
    tag = f"{sequence}_lifecycle_rearmed_backend_v1_{'klt' if arm == ARM_ORDER[0] else 'aquafe'}"
    command = [
        "/usr/bin/bash",
        str(REPLAY_WRAPPER),
        str(run_dir / "source_stub"),
        str(feature_bag),
        tag,
    ]
    environment = {
        "ROOT": str(ROOT),
        "VINS_WS": str(VINS_WS),
        "RUN_DIR": str(run_dir),
        "SOURCE_CONFIG": str(item["source_config"]),
        "SOURCE_CAMERA_CONFIG": str(item["camera_config"]),
        "IMU_TOPIC": "/rtimulib_node/imu",
        "WAIT_FOR_VINS_SUBSCRIBERS": "1",
        "WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT": "20",
        "ROSBAG_WAIT_FOR_SUBSCRIBERS": "0",
        "PLAY_RATE": "1.0",
        "ROSBAG_PLAY_DELAY": "3",
        "POST_PLAY_SLEEP": "8",
        "PORT": str(item["ports"][arm]),
        "OMP_NUM_THREADS": "2",
        "MKL_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "ROS_HOME": str(run_dir / "ros_home"),
        "ROS_LOG_DIR": str(run_dir / "ros_home/log"),
    }
    return command, environment


def static_preflight() -> dict[str, Any]:
    require(not OUTPUT_ROOT.exists() and not OUTPUT_ROOT.is_symlink(), "OUTPUT_ROOT_EXISTS")
    require(OUTPUT_ROOT.parent.is_dir(), "OUTPUT_PARENT_MISSING")
    require(shutil.disk_usage(OUTPUT_ROOT.parent).free >= 10_000_000_000, "INSUFFICIENT_SPACE")
    inputs = static_input_identities()
    ports: dict[str, dict[str, int]] = {}
    for sequence in SEQUENCE_ORDER:
        ports[sequence] = {}
        for arm in ARM_ORDER:
            port = int(SEQUENCES[sequence]["ports"][arm])
            require(port_available(port), f"PORT_BUSY:{sequence}:{arm}:{port}")
            ports[sequence][arm] = port
    return {
        "status": "READY_STATIC_WAITING_FOR_FRONTEND_AUTHORITY",
        "sequence_order": list(SEQUENCE_ORDER),
        "arm_order_within_window": list(ARM_ORDER),
        "ports": ports,
        "inputs": inputs,
        "no_automatic_retry": True,
        "accuracy_evaluator_started": False,
    }


def preflight() -> dict[str, Any]:
    static = static_preflight()
    authorities = {sequence: frontend_authority(sequence) for sequence in SEQUENCE_ORDER}
    commands: dict[str, dict[str, list[str]]] = {}
    for sequence in SEQUENCE_ORDER:
        commands[sequence] = {}
        if authorities[sequence]["backend_authorized"]:
            window_input_identities(sequence, authorities[sequence])
            for arm in ARM_ORDER:
                commands[sequence][arm] = command_for(
                    sequence, arm, stage_paths(sequence, arm)[1]
                )[0]
    return {
        **static,
        "status": "READY_ACTION_GATED_MULTIWINDOW_PAIRED_VINS_REPLAY",
        "frontend_authorities": authorities,
        "commands_for_action_positive_windows": commands,
        "zero_action_policy": "RECORD_SKIP_NO_BACKEND_NO_PARAMETER_CHANGE_NO_RETRY",
    }


def terminate_group(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    for sig, delay in ((signal.SIGINT, 15), (signal.SIGTERM, 10), (signal.SIGKILL, 2)):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=delay)
            return
        except subprocess.TimeoutExpired:
            continue


def run_child(
    command: list[str], environment: Mapping[str, str], log_path: Path, timeout: int
) -> tuple[int, float]:
    started = time.monotonic()
    with log_path.open("xb") as log:
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            env={**os.environ, **environment},
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            return_code = process.wait(timeout=timeout)
        except BaseException:
            terminate_group(process)
            raise
    return return_code, time.monotonic() - started


def normalized_config(path: Path) -> bytes:
    text = path.read_text(encoding="utf-8")
    require(
        len(re.findall(r'^output_path:\s*".*"$', text, flags=re.MULTILINE)) == 1,
        f"CONFIG_OUTPUT_PATH:{path}",
    )
    return re.sub(
        r'^output_path:\s*".*"$',
        'output_path: "<NORMALIZED>"',
        text,
        flags=re.MULTILINE,
    ).encode("utf-8")


def parse_trajectory(sequence: str, path: Path) -> dict[str, Any]:
    timestamps: list[int] = []
    with path.open(newline="", encoding="utf-8") as stream:
        for row_index, row in enumerate(csv.reader(stream)):
            values = [value for value in row if value != ""]
            require(len(values) >= 8, f"TRAJECTORY_COLUMNS:{sequence}:{row_index}")
            try:
                stamp = int(values[0])
                numbers = [float(value) for value in values[1:]]
            except ValueError as error:
                raise BackendError(f"TRAJECTORY_PARSE:{sequence}:{row_index}") from error
            require(
                all(math.isfinite(value) for value in numbers),
                f"TRAJECTORY_NONFINITE:{sequence}:{row_index}",
            )
            timestamps.append(stamp)
    require(len(timestamps) >= 1000, f"TRAJECTORY_POSES:{sequence}:{len(timestamps)}")
    require(
        all(right > left for left, right in zip(timestamps, timestamps[1:])),
        f"TRAJECTORY_ORDER:{sequence}",
    )
    deltas_s = [
        (right - left) / 1e9 for left, right in zip(timestamps, timestamps[1:])
    ]
    max_gap_s = max(deltas_s, default=0.0)
    require(max_gap_s <= 0.25, f"TRAJECTORY_GAP:{sequence}:{max_gap_s}")
    span_s = (timestamps[-1] - timestamps[0]) / 1e9
    require(span_s >= 100.0, f"TRAJECTORY_SPAN:{sequence}:{span_s}")
    item = SEQUENCES[sequence]
    require(timestamps[0] < item["primary_start_ns"], f"TRAJECTORY_LATE_START:{sequence}")
    require(
        timestamps[-1] >= item["raw_end_ns"] - 250_000_000,
        f"TRAJECTORY_EARLY_END:{sequence}",
    )
    return {
        "poses": len(timestamps),
        "first_timestamp_ns": timestamps[0],
        "last_timestamp_ns": timestamps[-1],
        "span_seconds": span_s,
        "max_output_gap_seconds": max_gap_s,
        "gaps_over_0_25_seconds": sum(value > 0.25 for value in deltas_s),
        "last_output_drop_seconds": (item["raw_end_ns"] - timestamps[-1]) / 1e9,
    }


def audit_arm(sequence: str, arm: str, directory: Path) -> dict[str, Any]:
    item = SEQUENCES[sequence]
    source_config: Path = item["source_config"]
    camera_config: Path = item["camera_config"]
    runtime_config = directory / source_config.name
    runtime_camera = directory / camera_config.name
    trajectory = directory / "vins_output/vio.csv"
    log_path = directory / "vins.log"
    manifest_path = directory / "replay_manifest.txt"
    required = (
        runtime_config,
        runtime_camera,
        trajectory,
        log_path,
        manifest_path,
        directory / "roscore.log",
        directory / "vins_env_manifest.txt",
        directory / "supervisor_process.log",
    )
    for path in required:
        require(path.is_file() and not path.is_symlink(), f"OUTPUT_MISSING:{sequence}:{arm}:{path}")
    require(runtime_camera.read_bytes() == camera_config.read_bytes(), f"CAMERA_CONFIG_DRIFT:{sequence}:{arm}")
    require(
        normalized_config(runtime_config) == normalized_config(source_config),
        f"VINS_CONFIG_DRIFT:{sequence}:{arm}",
    )
    trajectory_audit = parse_trajectory(sequence, trajectory)
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    marker = "Initialization finish!"
    require(log_text.count(marker) == 1, f"INITIALIZATION_MARKER:{sequence}:{arm}")
    post_init = log_text.split(marker, 1)[1].lower()
    forbidden_counts = {
        "failure_detection": post_init.count("failure detection"),
        "tracking_lost": post_init.count("tracking lost"),
        "restart": post_init.count("restart"),
        "linear_solver_failure": post_init.count("linear solver failure"),
        "reset": post_init.count("reset"),
    }
    require(
        sum(forbidden_counts.values()) == 0,
        f"POST_INIT_FAILURE_MARKER:{sequence}:{arm}:{forbidden_counts}",
    )
    feature_bag = bag_for(sequence, arm)
    manifest = manifest_path.read_text(encoding="utf-8")
    require(f"play_bag={feature_bag}" in manifest, f"MANIFEST_PLAY_BAG:{sequence}:{arm}")
    require(f"feature_bag={feature_bag}" in manifest, f"MANIFEST_FEATURE_BAG:{sequence}:{arm}")
    require(f"run_dir={directory}" in manifest, f"MANIFEST_RUN_DIR:{sequence}:{arm}")
    require("accuracy_evaluator_started=0" in manifest, f"MANIFEST_EVALUATOR:{sequence}:{arm}")
    port = int(item["ports"][arm])
    require(port_available(port), f"PORT_NOT_RELEASED:{sequence}:{arm}:{port}")
    return {
        "status": "PASS_BACKEND_ARM_STRUCTURAL_AUDIT",
        "sequence": sequence,
        "arm": arm,
        "method_id": (
            "KLT_EXTERNAL_FEATURE_CONTEXT_FRESH_PAIR_V1"
            if arm == ARM_ORDER[0]
            else "AQUAFE_LIFECYCLE_REARMED_EXTERNAL_FEATURE_CONTEXT_FRESH_PAIR_V1"
        ),
        "feature_bag": identity(feature_bag),
        "trajectory": trajectory_audit,
        "initialization_finish_count": 1,
        "post_initialization_forbidden_markers": forbidden_counts,
        "normalized_vins_config_sha256": hashlib.sha256(normalized_config(runtime_config)).hexdigest(),
        "camera_config_sha256": sha256(runtime_camera),
        "accuracy_evaluator_started": False,
    }


def output_identities(directory: Path, names: Iterable[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in names:
        path = directory / name
        require(path.is_file() and not path.is_symlink(), f"OUTPUT_NOT_REGULAR:{path}")
        result[name] = identity(path)
    return result


def stage_failure(sequence: str, arm: str, error: BaseException) -> None:
    stage, accepted, failure = stage_paths(sequence, arm)
    if accepted.is_symlink():
        accepted.unlink()
    if not stage.is_dir() or stage.is_symlink() or failure.exists() or failure.is_symlink():
        return
    try:
        write_json(
            stage / "failure_receipt_v1.json",
            {
                "status": "FAILED_NO_AUTOMATIC_RETRY",
                "sequence": sequence,
                "arm": arm,
                "error_type": type(error).__name__,
                "error": str(error),
                "recorded_at_utc": now(),
            },
        )
        stage.rename(failure)
    except OSError:
        pass


def execute_arm(
    sequence: str, arm: str, inputs_before: Mapping[str, Any]
) -> dict[str, Any]:
    stage, accepted, failure = stage_paths(sequence, arm)
    for path, code in ((stage, "STAGE"), (accepted, "ACCEPTED"), (failure, "FAILURE")):
        require(not path.exists() and not path.is_symlink(), f"{code}_PATH_EXISTS:{sequence}:{arm}")
    port = int(SEQUENCES[sequence]["ports"][arm])
    require(port_available(port), f"PORT_BUSY_BEFORE_ARM:{sequence}:{arm}:{port}")
    stage.mkdir(mode=0o755)
    (stage / "source_stub").mkdir(mode=0o755)
    (stage / "ros_home/log").mkdir(parents=True, mode=0o755)
    accepted.symlink_to(stage, target_is_directory=True)
    command, environment = command_for(sequence, arm, accepted)
    claim = {
        "schema_version": "positive-klt-lifecycle-rearmed-backend-start-claim-v1",
        "status": "CLAIMED_BEFORE_SINGLE_POPEN",
        "sequence": sequence,
        "arm": arm,
        "created_at_utc": now(),
        "command": command,
        "environment_updates": environment,
        "inputs": inputs_before,
        "no_automatic_retry": True,
        "accuracy_evaluator_started": False,
    }
    write_json(stage / "process_start_claim_v1.json", claim)
    started = now()
    try:
        return_code, wall_time = run_child(
            command, environment, stage / "supervisor_process.log", timeout=1_200
        )
        require(return_code == 0, f"CHILD_RETURN_CODE:{sequence}:{arm}:{return_code}")
        audit = audit_arm(sequence, arm, accepted)
        inputs_after = refresh_identities(inputs_before)
        require(
            same_identity_maps(inputs_before, inputs_after),
            f"INPUT_IDENTITY_CHANGED:{sequence}:{arm}",
        )
        source_config: Path = SEQUENCES[sequence]["source_config"]
        camera_config: Path = SEQUENCES[sequence]["camera_config"]
        outputs = output_identities(
            accepted,
            (
                "vins_output/vio.csv",
                "vins.log",
                "replay_manifest.txt",
                source_config.name,
                camera_config.name,
                "roscore.log",
                "vins_env_manifest.txt",
                "supervisor_process.log",
                "process_start_claim_v1.json",
            ),
        )
        receipt = {
            "schema_version": "positive-klt-lifecycle-rearmed-backend-arm-receipt-v1",
            "status": "PASS_BACKEND_ARM_ACCEPTED",
            "sequence": sequence,
            "arm": arm,
            "started_at_utc": started,
            "ended_at_utc": now(),
            "terminal_process": {
                "return_code": return_code,
                "single_popen": True,
                "wall_time_seconds": wall_time,
            },
            "execution_integrity": {
                "no_automatic_retry": True,
                "fixed_sequence_order": list(SEQUENCE_ORDER),
                "fixed_arm_order": list(ARM_ORDER),
                "ambient_desktop_and_unrelated_workloads_allowed": True,
                "runtime_comparison_permitted": False,
            },
            "command": command,
            "environment_updates": environment,
            "inputs_before": inputs_before,
            "inputs_after": inputs_after,
            "outputs": outputs,
            "artifact_audit": audit,
            "claim_boundary": {
                "trajectory_eligible_for_fixed_common_support_evaluator": True,
                "accuracy_evaluator_started": False,
                "accuracy_or_superiority_claim_available": False,
            },
        }
        write_json(stage / "formal_run_receipt_v1.json", receipt)
        accepted.unlink()
        stage.rename(accepted)
        return receipt
    except BaseException as error:
        stage_failure(sequence, arm, error)
        raise


def write_zero_action_skip(sequence: str, authority: Mapping[str, Any]) -> dict[str, Any]:
    directory = sequence_dir(sequence)
    directory.mkdir(mode=0o755)
    receipt = {
        "schema_version": "positive-klt-lifecycle-rearmed-zero-action-skip-v1",
        "status": "SKIPPED_ZERO_SCORE_ACTION_NO_BACKEND",
        "sequence": sequence,
        "recorded_at_utc": now(),
        "frontend_authority": authority,
        "backend_process_starts": 0,
        "parameter_changes": 0,
        "retry_count": 0,
        "evaluation_authorized": False,
    }
    path = directory / "window_skip_receipt_v1.json"
    write_json(path, receipt)
    return {**receipt, "receipt": identity(path)}


def execute_window(sequence: str, authority: Mapping[str, Any]) -> dict[str, Any]:
    require(not sequence_dir(sequence).exists(), f"WINDOW_OUTPUT_EXISTS:{sequence}")
    if not authority["backend_authorized"]:
        return write_zero_action_skip(sequence, authority)
    sequence_dir(sequence).mkdir(mode=0o755)
    inputs = window_input_identities(sequence, authority)
    receipts: dict[str, Any] = {}
    try:
        for arm in ARM_ORDER:
            receipts[arm] = execute_arm(sequence, arm, inputs)
        normalized = {
            arm: receipts[arm]["artifact_audit"]["normalized_vins_config_sha256"]
            for arm in ARM_ORDER
        }
        require(len(set(normalized.values())) == 1, f"PAIR_CONFIG_ASYMMETRY:{sequence}")
        terminal = {
            "schema_version": "positive-klt-lifecycle-rearmed-window-backend-terminal-v1",
            "status": "PASS_PAIRED_BACKENDS_ELIGIBLE_FOR_FIXED_EVALUATION",
            "sequence": sequence,
            "recorded_at_utc": now(),
            "arm_order": list(ARM_ORDER),
            "frontend_authority": authority,
            "arm_receipts": {
                arm: identity(stage_paths(sequence, arm)[1] / "formal_run_receipt_v1.json")
                for arm in ARM_ORDER
            },
            "trajectories": {
                arm: receipts[arm]["artifact_audit"]["trajectory"] for arm in ARM_ORDER
            },
            "pair_symmetry": {
                "normalized_vins_config_sha256": next(iter(normalized.values())),
                "same_camera_config": True,
                "same_vins_binary": True,
                "same_replay_wrapper": True,
                "fixed_order": list(ARM_ORDER),
            },
            "decision": {
                "fixed_two_layer_evaluation_may_run": True,
                "backend_retry_permitted": False,
                "accuracy_evaluator_started": False,
            },
        }
        terminal_path = sequence_dir(sequence) / "terminal_backend_pair_receipt_v1.json"
        write_json(terminal_path, terminal)
        return {**terminal, "terminal_receipt": identity(terminal_path)}
    except Exception as error:
        failure = {
            "schema_version": "positive-klt-lifecycle-rearmed-window-backend-failure-v1",
            "status": "RETAINED_BACKEND_FAILURE_NO_RETRY",
            "sequence": sequence,
            "recorded_at_utc": now(),
            "error_type": type(error).__name__,
            "error": str(error),
            "accepted_arms_before_failure": list(receipts),
            "unstarted_arms": [arm for arm in ARM_ORDER if arm not in receipts],
            "retry_permitted": False,
            "evaluation_authorized": False,
        }
        failure_path = sequence_dir(sequence) / "terminal_backend_failure_receipt_v1.json"
        write_json(failure_path, failure)
        return {**failure, "terminal_receipt": identity(failure_path)}


def execute() -> dict[str, Any]:
    ready = preflight()
    OUTPUT_ROOT.mkdir(mode=0o755)
    LOCK_PATH.touch(exist_ok=False)
    with LOCK_PATH.open("r+") as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        outcomes: dict[str, Any] = {}
        for sequence in SEQUENCE_ORDER:
            authority = frontend_authority(sequence)
            outcomes[sequence] = execute_window(sequence, authority)
        failures = [
            sequence
            for sequence, outcome in outcomes.items()
            if outcome["status"] == "RETAINED_BACKEND_FAILURE_NO_RETRY"
        ]
        skips = [
            sequence
            for sequence, outcome in outcomes.items()
            if outcome["status"] == "SKIPPED_ZERO_SCORE_ACTION_NO_BACKEND"
        ]
        eligible = [
            sequence
            for sequence, outcome in outcomes.items()
            if outcome["status"] == "PASS_PAIRED_BACKENDS_ELIGIBLE_FOR_FIXED_EVALUATION"
        ]
        status = (
            "COMPLETE_WITH_RETAINED_BACKEND_FAILURES"
            if failures
            else "COMPLETE_WITH_ZERO_ACTION_SKIPS"
            if skips
            else "PASS_ALL_ACTION_POSITIVE_PAIRED_BACKENDS"
        )
        terminal = {
            "schema_version": "positive-klt-lifecycle-rearmed-multiwindow-backend-terminal-v1",
            "status": status,
            "recorded_at_utc": now(),
            "sequence_order": list(SEQUENCE_ORDER),
            "arm_order_within_window": list(ARM_ORDER),
            "preflight_frontend_authorities": ready["frontend_authorities"],
            "window_outcomes": {
                sequence: {
                    "status": outcomes[sequence]["status"],
                    "terminal_receipt": outcomes[sequence].get("terminal_receipt")
                    or outcomes[sequence].get("receipt"),
                }
                for sequence in SEQUENCE_ORDER
            },
            "decision": {
                "evaluation_eligible_windows": eligible,
                "zero_action_skips": skips,
                "retained_failures": failures,
                "backend_retry_permitted": False,
                "accuracy_evaluator_started": False,
            },
            "claim_boundary": {
                "runability_and_trajectory_evidence_only": True,
                "accuracy_comparison_available": False,
                "runtime_comparison_permitted": False,
                "system_ranking_or_superiority_claim_permitted": False,
            },
        }
        write_json(TERMINAL_RECEIPT, terminal)
        return terminal


def audit_existing() -> dict[str, Any]:
    require(TERMINAL_RECEIPT.is_file() and not TERMINAL_RECEIPT.is_symlink(), "TERMINAL_MISSING")
    static_input_identities()
    terminal = read_json(TERMINAL_RECEIPT)
    require(
        terminal.get("sequence_order") == list(SEQUENCE_ORDER),
        "TERMINAL_SEQUENCE_ORDER",
    )
    outcomes = terminal.get("window_outcomes") or {}
    require(set(outcomes) == set(SEQUENCE_ORDER), "TERMINAL_WINDOW_SET")
    audits: dict[str, Any] = {}
    for sequence in SEQUENCE_ORDER:
        status = outcomes[sequence].get("status")
        if status == "PASS_PAIRED_BACKENDS_ELIGIBLE_FOR_FIXED_EVALUATION":
            authority = frontend_authority(sequence)
            window_input_identities(sequence, authority)
            arm_audits = {
                arm: audit_arm(sequence, arm, stage_paths(sequence, arm)[1])
                for arm in ARM_ORDER
            }
            receipt = read_json(sequence_dir(sequence) / "terminal_backend_pair_receipt_v1.json")
            require(receipt.get("status") == status, f"WINDOW_TERMINAL_STATUS:{sequence}")
            audits[sequence] = {"status": status, "arms": arm_audits}
        elif status == "SKIPPED_ZERO_SCORE_ACTION_NO_BACKEND":
            receipt = read_json(sequence_dir(sequence) / "window_skip_receipt_v1.json")
            require(receipt.get("backend_process_starts") == 0, f"SKIP_PROCESS_COUNT:{sequence}")
            audits[sequence] = {"status": status, "backend_process_starts": 0}
        elif status == "RETAINED_BACKEND_FAILURE_NO_RETRY":
            receipt = read_json(sequence_dir(sequence) / "terminal_backend_failure_receipt_v1.json")
            require(receipt.get("retry_permitted") is False, f"FAILURE_RETRY_POLICY:{sequence}")
            audits[sequence] = {"status": status, "retained": True}
        else:
            raise BackendError(f"UNKNOWN_WINDOW_STATUS:{sequence}:{status}")
    return {
        "status": "PASS_EXISTING_MULTIWINDOW_BACKEND_AUDIT",
        "terminal_status": terminal.get("status"),
        "windows": audits,
        "terminal_receipt": identity(TERMINAL_RECEIPT),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("static-preflight", "preflight", "run", "audit"))
    args = parser.parse_args()
    try:
        if args.command == "static-preflight":
            result = static_preflight()
        elif args.command == "preflight":
            result = preflight()
        elif args.command == "run":
            result = execute()
        else:
            result = audit_existing()
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))
        return 0
    except (
        BackendError,
        OSError,
        ValueError,
        csv.Error,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        print(
            f"POSITIVE_KLT_BACKEND_V1_ERROR:{type(error).__name__}:{error}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
