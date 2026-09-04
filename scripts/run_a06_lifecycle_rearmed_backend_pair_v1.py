#!/usr/bin/env python3
"""Exactly-once paired A06 VINS replay for KLT and lifecycle-rearmed AQUA-FE."""

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
import time
from typing import Any, Iterable


ROOT = Path("/home/ma/AQUA-FE_WS")
PROTOCOL = ROOT / "papers/a06_lifecycle_rearmed_backend_pair_v1_protocol.md"
RUNNER = Path(__file__).resolve()
OUTPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/a06_lifecycle_rearmed_backend_pair_v1"
)
LOCK_PATH = OUTPUT_ROOT / ".backend_pair_supervisor.flock"
TERMINAL_RECEIPT = OUTPUT_ROOT / "terminal_backend_pair_receipt_v1.json"

KLT_BAG = Path(
    "/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/"
    "external_klt/features.bag"
)
AQUA_BAG = Path(
    "/mnt/data/AQUA-FE_WS/experiments/a06_lifecycle_rearmed_natural_history_v1/"
    "lifecycle_rearmed/full_merged.bag"
)
FRONTEND_TERMINAL = Path(
    "/mnt/data/AQUA-FE_WS/experiments/a06_lifecycle_rearmed_natural_history_v1/"
    "terminal_probe_receipt_v1.json"
)
FRONTEND_STAGE_RECEIPT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/a06_lifecycle_rearmed_natural_history_v1/"
    "lifecycle_rearmed/formal_run_receipt_v1.json"
)
SOURCE_CONFIG = Path(
    "/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/"
    "external_klt/vins_aqualoc_archaeo_external.yaml"
)
CAMERA_CONFIG = Path(
    "/mnt/data/AQUA-FE_WS/experiments/samehistory_system_v1/runs/a06/"
    "external_klt/aqualoc_archaeo06_pinhole.yaml"
)
REPLAY_WRAPPER = ROOT / "scripts/run_existing_featurebag_vins_replay_only_v1.sh"
VINS_WS = Path("/home/ma/SLAM/VINS-Fusion-origin")
VINS_NODE = VINS_WS / "devel/lib/vins/vins_node"

EXPECTED_IDENTITIES = {
    KLT_BAG: (
        37_403_698,
        "0779bb8a71e4d81ddf02ba933b7428e548534ab580fd4483754f08e26e9bbeb6",
    ),
    AQUA_BAG: (
        37_457_074,
        "e3594e6da04ed3644fa1e075ee2bd30ca1add3d8d9d244d0debc8b07c64e1bf1",
    ),
    FRONTEND_TERMINAL: (
        2_644,
        "4dd554b066bb67112c792f2e1c5c83a9a57601c941cfc56f6e7094161e33b705",
    ),
    FRONTEND_STAGE_RECEIPT: (
        13_629,
        "4a9a77ccce52673cfc8843cb1de20cb297deaef099e65c6d02e61534ef6ef69a",
    ),
    SOURCE_CONFIG: (
        976,
        "e3b0ef0badfbe4392b3c29f59b1dd0a4d6c5260b528bf7380dc0b17ac4de19d0",
    ),
    CAMERA_CONFIG: (
        357,
        "045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5",
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

RAW_FIRST_NS = 1_542_883_311_780_022_336
RAW_END_NS = 1_542_883_434_765_650_624
EVALUATION_START_NS = 1_542_883_404_763_902_848

ARM_ORDER = (
    "klt_external_feature_context_fresh_pair_v1",
    "aquafe_lifecycle_rearmed_external_feature_context_fresh_pair_v1",
)
ARMS = {
    ARM_ORDER[0]: {
        "method_id": "KLT_EXTERNAL_FEATURE_CONTEXT_FRESH_PAIR_V1",
        "bag": KLT_BAG,
        "port": 11966,
        "tag": "a06_lifecycle_rearmed_pair_v1_klt",
    },
    ARM_ORDER[1]: {
        "method_id": "AQUAFE_LIFECYCLE_REARMED_EXTERNAL_FEATURE_CONTEXT_FRESH_PAIR_V1",
        "bag": AQUA_BAG,
        "port": 11967,
        "tag": "a06_lifecycle_rearmed_pair_v1_aquafe",
    },
}


class BackendError(RuntimeError):
    pass


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


def common_input_identities() -> dict[str, Any]:
    values = {
        str(path): require_identity(path, expected)
        for path, expected in EXPECTED_IDENTITIES.items()
    }
    for path in (PROTOCOL, RUNNER):
        require(path.is_file() and not path.is_symlink(), f"CONTROL_NOT_REGULAR:{path}")
        values[str(path)] = identity(path)
    return values


def refresh_identities(previous: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw_path in previous:
        path = Path(raw_path)
        require(path.is_file() and not path.is_symlink(), f"CLAIMED_INPUT_NOT_REGULAR:{path}")
        result[raw_path] = identity(path)
    return result


def write_json(path: Path, value: Any) -> None:
    require(not path.exists() and not path.is_symlink(), f"REFUSE_OVERWRITE:{path}")
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def frontend_authority() -> dict[str, Any]:
    terminal = read_json(FRONTEND_TERMINAL)
    stage = read_json(FRONTEND_STAGE_RECEIPT)
    require(terminal.get("status") == "PASS_SCORE_ACTION_GATE_FRONTEND_ONLY", "FRONTEND_STATUS")
    gate = terminal.get("learned_action_gate") or {}
    require(gate.get("passed") is True and gate.get("value") == 107, "FRONTEND_GATE")
    decision = terminal.get("decision") or {}
    require(decision.get("backend_may_be_prepared") is True, "FRONTEND_BACKEND_AUTHORITY")
    require(decision.get("backend_started_by_this_runner") is False, "FRONTEND_BACKEND_ALREADY_STARTED")
    require(stage.get("status") == "PASS_STAGE_ACCEPTED", "FRONTEND_STAGE_STATUS")
    audit = stage.get("artifact_audit") or {}
    require(audit.get("remove_learned_recovers_klt_exactly") is True, "FRONTEND_DROP_PARITY")
    require((audit.get("gate") or {}).get("value") == 107, "FRONTEND_STAGE_GATE")
    return {
        "terminal_status": terminal["status"],
        "gate": gate,
        "remove_learned_recovers_klt_exactly": True,
        "method_id": terminal.get("method_id"),
    }


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


def stage_paths(arm: str) -> tuple[Path, Path, Path]:
    return (
        OUTPUT_ROOT / f".{arm}.stage_v1",
        OUTPUT_ROOT / arm,
        OUTPUT_ROOT / f"{arm}_failed_v1",
    )


def command_for(arm: str, stage: Path) -> tuple[list[str], dict[str, str]]:
    item = ARMS[arm]
    source_stub = stage / "source_stub"
    command = [
        "/usr/bin/bash", str(REPLAY_WRAPPER),
        str(source_stub), str(item["bag"]), str(item["tag"]),
    ]
    environment = {
        "ROOT": str(ROOT),
        "VINS_WS": str(VINS_WS),
        "RUN_DIR": str(stage),
        "SOURCE_CONFIG": str(SOURCE_CONFIG),
        "SOURCE_CAMERA_CONFIG": str(CAMERA_CONFIG),
        "IMU_TOPIC": "/rtimulib_node/imu",
        "WAIT_FOR_VINS_SUBSCRIBERS": "1",
        "WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT": "20",
        "ROSBAG_WAIT_FOR_SUBSCRIBERS": "0",
        "PLAY_RATE": "1.0",
        "ROSBAG_PLAY_DELAY": "3",
        "POST_PLAY_SLEEP": "8",
        "PORT": str(item["port"]),
        "OMP_NUM_THREADS": "2",
        "MKL_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "ROS_HOME": str(stage / "ros_home"),
        "ROS_LOG_DIR": str(stage / "ros_home/log"),
    }
    return command, environment


def preflight() -> dict[str, Any]:
    require(not OUTPUT_ROOT.exists() and not OUTPUT_ROOT.is_symlink(), "OUTPUT_ROOT_EXISTS")
    require(shutil.disk_usage(OUTPUT_ROOT.parent).free >= 5_000_000_000, "INSUFFICIENT_SPACE")
    inputs = common_input_identities()
    authority = frontend_authority()
    for arm in ARM_ORDER:
        require(port_available(int(ARMS[arm]["port"])), f"PORT_BUSY:{ARMS[arm]['port']}")
    return {
        "status": "READY_PAIRED_VINS_REPLAY",
        "arm_order": list(ARM_ORDER),
        "inputs": inputs,
        "frontend_authority": authority,
        "commands": {
            arm: command_for(arm, stage_paths(arm)[1])[0] for arm in ARM_ORDER
        },
        "ports": {arm: ARMS[arm]["port"] for arm in ARM_ORDER},
        "ambient_workloads_allowed_no_runtime_claim": True,
        "no_automatic_retry": True,
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
    command: list[str], environment: dict[str, str], log_path: Path, timeout: int
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
    require(len(re.findall(r'^output_path:\s*".*"$', text, flags=re.MULTILINE)) == 1, "CONFIG_OUTPUT_PATH")
    return re.sub(
        r'^output_path:\s*".*"$',
        'output_path: "<NORMALIZED>"',
        text,
        flags=re.MULTILINE,
    ).encode("utf-8")


def parse_trajectory(path: Path) -> dict[str, Any]:
    timestamps: list[int] = []
    with path.open(newline="", encoding="utf-8") as stream:
        for row_index, row in enumerate(csv.reader(stream)):
            values = [value for value in row if value != ""]
            require(len(values) >= 8, f"TRAJECTORY_COLUMNS:{row_index}")
            try:
                stamp = int(values[0])
                numbers = [float(value) for value in values[1:]]
            except ValueError as error:
                raise BackendError(f"TRAJECTORY_PARSE:{row_index}") from error
            require(all(math.isfinite(value) for value in numbers), f"TRAJECTORY_NONFINITE:{row_index}")
            timestamps.append(stamp)
    require(len(timestamps) >= 1000, f"TRAJECTORY_POSES:{len(timestamps)}")
    require(all(b > a for a, b in zip(timestamps, timestamps[1:])), "TRAJECTORY_ORDER")
    deltas_s = [(b - a) / 1e9 for a, b in zip(timestamps, timestamps[1:])]
    max_gap_s = max(deltas_s, default=0.0)
    require(max_gap_s <= 0.25, f"TRAJECTORY_GAP:{max_gap_s}")
    span_s = (timestamps[-1] - timestamps[0]) / 1e9
    require(span_s >= 100.0, f"TRAJECTORY_SPAN:{span_s}")
    require(timestamps[0] < EVALUATION_START_NS, "TRAJECTORY_LATE_START")
    require(timestamps[-1] >= RAW_END_NS - 250_000_000, "TRAJECTORY_EARLY_END")
    return {
        "poses": len(timestamps),
        "first_timestamp_ns": timestamps[0],
        "last_timestamp_ns": timestamps[-1],
        "span_seconds": span_s,
        "max_output_gap_seconds": max_gap_s,
        "gaps_over_0_25_seconds": sum(value > 0.25 for value in deltas_s),
        "last_output_drop_seconds": (RAW_END_NS - timestamps[-1]) / 1e9,
    }


def audit_arm(arm: str, directory: Path) -> dict[str, Any]:
    item = ARMS[arm]
    runtime_config = directory / SOURCE_CONFIG.name
    runtime_camera = directory / CAMERA_CONFIG.name
    trajectory = directory / "vins_output/vio.csv"
    log_path = directory / "vins.log"
    manifest_path = directory / "replay_manifest.txt"
    required = (
        runtime_config, runtime_camera, trajectory, log_path, manifest_path,
        directory / "roscore.log", directory / "vins_env_manifest.txt",
        directory / "supervisor_process.log",
    )
    for path in required:
        require(path.is_file() and not path.is_symlink(), f"OUTPUT_MISSING:{arm}:{path}")
    require(runtime_camera.read_bytes() == CAMERA_CONFIG.read_bytes(), f"CAMERA_CONFIG_DRIFT:{arm}")
    require(normalized_config(runtime_config) == normalized_config(SOURCE_CONFIG), f"VINS_CONFIG_DRIFT:{arm}")
    trajectory_audit = parse_trajectory(trajectory)
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    marker = "Initialization finish!"
    require(log_text.count(marker) == 1, f"INITIALIZATION_MARKER:{arm}")
    post_init = log_text.split(marker, 1)[1].lower()
    forbidden_counts = {
        "failure_detection": post_init.count("failure detection"),
        "tracking_lost": post_init.count("tracking lost"),
        "restart": post_init.count("restart"),
        "linear_solver_failure": post_init.count("linear solver failure"),
        "reset": post_init.count("reset"),
    }
    require(sum(forbidden_counts.values()) == 0, f"POST_INIT_FAILURE_MARKER:{arm}:{forbidden_counts}")
    manifest = manifest_path.read_text(encoding="utf-8")
    require(f"play_bag={item['bag']}" in manifest, f"MANIFEST_PLAY_BAG:{arm}")
    require(f"feature_bag={item['bag']}" in manifest, f"MANIFEST_FEATURE_BAG:{arm}")
    require(f"run_dir={directory}" in manifest, f"MANIFEST_RUN_DIR:{arm}")
    require("accuracy_evaluator_started=0" in manifest, f"MANIFEST_EVALUATOR_BOUNDARY:{arm}")
    require(port_available(int(item["port"])), f"PORT_NOT_RELEASED:{arm}")
    return {
        "status": "PASS_BACKEND_ARM_STRUCTURAL_AUDIT",
        "method_id": item["method_id"],
        "feature_bag": identity(Path(item["bag"])),
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


def stage_failure(
    stage: Path, accepted: Path, failure: Path, error: BaseException
) -> None:
    if accepted.is_symlink():
        accepted.unlink()
    if not stage.is_dir() or stage.is_symlink() or failure.exists() or failure.is_symlink():
        return
    try:
        write_json(stage / "failure_receipt_v1.json", {
            "status": "FAILED_NO_AUTOMATIC_RETRY",
            "error_type": type(error).__name__,
            "error": str(error),
            "recorded_at_utc": now(),
        })
        stage.rename(failure)
    except OSError:
        pass


def execute_arm(arm: str, inputs_before: dict[str, Any]) -> dict[str, Any]:
    stage, accepted, failure = stage_paths(arm)
    for path, code in ((stage, "STAGE"), (accepted, "ACCEPTED"), (failure, "FAILURE")):
        require(not path.exists() and not path.is_symlink(), f"{code}_PATH_EXISTS:{arm}")
    require(port_available(int(ARMS[arm]["port"])), f"PORT_BUSY_BEFORE_ARM:{arm}")
    stage.mkdir(mode=0o755)
    (stage / "source_stub").mkdir(mode=0o755)
    (stage / "ros_home/log").mkdir(parents=True, mode=0o755)
    accepted.symlink_to(stage, target_is_directory=True)
    command, environment = command_for(arm, accepted)
    claim = {
        "schema_version": "a06-lifecycle-rearmed-backend-start-claim-v1",
        "status": "CLAIMED_BEFORE_SINGLE_POPEN",
        "arm": arm,
        "method_id": ARMS[arm]["method_id"],
        "created_at_utc": now(),
        "command": command,
        "environment_updates": environment,
        "inputs": inputs_before,
        "no_automatic_retry": True,
    }
    write_json(stage / "process_start_claim_v1.json", claim)
    started = now()
    try:
        return_code, wall_time = run_child(
            command, environment, stage / "supervisor_process.log", timeout=900
        )
        require(return_code == 0, f"CHILD_RETURN_CODE:{arm}:{return_code}")
        audit = audit_arm(arm, accepted)
        inputs_after = refresh_identities(inputs_before)
        require(
            {
                key: (value["size_bytes"], value["sha256"])
                for key, value in inputs_before.items()
            }
            == {
                key: (value["size_bytes"], value["sha256"])
                for key, value in inputs_after.items()
            },
            f"INPUT_IDENTITY_CHANGED:{arm}",
        )
        outputs = output_identities(accepted, (
            "vins_output/vio.csv", "vins.log", "replay_manifest.txt",
            SOURCE_CONFIG.name, CAMERA_CONFIG.name, "roscore.log",
            "vins_env_manifest.txt", "supervisor_process.log", "process_start_claim_v1.json",
        ))
        receipt = {
            "schema_version": "a06-lifecycle-rearmed-backend-arm-receipt-v1",
            "status": "PASS_BACKEND_ARM_ACCEPTED",
            "arm": arm,
            "method_id": ARMS[arm]["method_id"],
            "started_at_utc": started,
            "ended_at_utc": now(),
            "terminal_process": {
                "return_code": return_code,
                "single_popen": True,
                "wall_time_seconds": wall_time,
            },
            "execution_integrity": {
                "no_automatic_retry": True,
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
        stage_failure(stage, accepted, failure, error)
        raise


def execute() -> dict[str, Any]:
    ready = preflight()
    OUTPUT_ROOT.mkdir(mode=0o755)
    LOCK_PATH.touch(exist_ok=False)
    with LOCK_PATH.open("r+") as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        inputs = common_input_identities()
        receipts: dict[str, Any] = {}
        for arm in ARM_ORDER:
            receipts[arm] = execute_arm(arm, inputs)
        normalized = {
            arm: receipts[arm]["artifact_audit"]["normalized_vins_config_sha256"]
            for arm in ARM_ORDER
        }
        require(len(set(normalized.values())) == 1, "PAIR_CONFIG_ASYMMETRY")
        terminal = {
            "schema_version": "a06-lifecycle-rearmed-backend-pair-terminal-v1",
            "status": "PASS_PAIRED_BACKENDS_ELIGIBLE_FOR_FIXED_EVALUATION",
            "recorded_at_utc": now(),
            "arm_order": list(ARM_ORDER),
            "frontend_authority": ready["frontend_authority"],
            "arm_receipts": {
                arm: identity(stage_paths(arm)[1] / "formal_run_receipt_v1.json")
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
                "fixed_common_support_evaluation_may_run": True,
                "backend_retry_permitted": False,
                "accuracy_evaluator_started": False,
            },
            "claim_boundary": {
                "backend_runability_and_trajectory_evidence_only": True,
                "accuracy_comparison_available": False,
                "runtime_comparison_permitted": False,
                "system_ranking_or_superiority_claim_permitted": False,
            },
        }
        write_json(TERMINAL_RECEIPT, terminal)
        return terminal


def audit_existing() -> dict[str, Any]:
    require(TERMINAL_RECEIPT.is_file() and not TERMINAL_RECEIPT.is_symlink(), "TERMINAL_MISSING")
    common_input_identities()
    audits = {arm: audit_arm(arm, stage_paths(arm)[1]) for arm in ARM_ORDER}
    terminal = read_json(TERMINAL_RECEIPT)
    require(
        terminal.get("status") == "PASS_PAIRED_BACKENDS_ELIGIBLE_FOR_FIXED_EVALUATION",
        "TERMINAL_STATUS",
    )
    return {
        "status": "PASS_EXISTING_BACKEND_PAIR_AUDIT",
        "terminal_status": terminal["status"],
        "arms": audits,
        "terminal_receipt": identity(TERMINAL_RECEIPT),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "run", "audit"))
    args = parser.parse_args()
    try:
        if args.command == "preflight":
            result = preflight()
        elif args.command == "run":
            result = execute()
        else:
            result = audit_existing()
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))
        return 0
    except (
        BackendError, OSError, ValueError, csv.Error, json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        print(f"A06_BACKEND_PAIR_ERROR:{type(error).__name__}:{error}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
