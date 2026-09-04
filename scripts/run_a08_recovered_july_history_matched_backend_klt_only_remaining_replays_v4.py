#!/usr/bin/python3.8
"""Additive A08 KLT R03--R05 supervisor after two consumed infra failures.

Importing this module is inert.  ``preflight`` and ``audit`` are read-only.
The v2 R01 and v3 R02 launches are immutable outcomes and have no v4 token.
No lock can be built before the independent analysis-v4 design freeze binds
this complete static implementation and both consumed terminal authorities.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
from types import ModuleType
from typing import Any, Mapping, Optional, Sequence


WORKSPACE = Path("/home/ma/AQUA-FE_WS")
EXPERIMENT = Path("/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1")
OVERLAY = EXPERIMENT / "recovered_july_core_overlay_v1"
OVERLAY_RUN_ROOT = OVERLAY / "logs/aqualoc_archaeo_vins"
BACKEND_ROOT = EXPERIMENT / "backend_klt_only_remaining_replays_v4"
RUNTIME_ROOT = EXPERIMENT / "runtime/backend_klt_only_remaining_replays_v4"

PROTOCOL = WORKSPACE / (
    "papers/a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v4_protocol.md"
)
DEFAULT_LOCK = WORKSPACE / (
    "papers/a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v4_execution_lock.json"
)
RUNNER = WORKSPACE / (
    "scripts/run_a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v4.py"
)
REPLAY_ONLY_GUARD = WORKSPACE / (
    "scripts/run_a08_recovered_july_history_matched_backend_klt_only_"
    "replay_guard_v4.sh"
)
LIFECYCLE_WRAPPER = WORKSPACE / "scripts/run_a08_vins_node_lifecycle_wrapper_v4.py"
SIGNAL_MASK_LAUNCHER = WORKSPACE / "scripts/run_a08_unblocked_overlay_exec_v4.py"
PROCESS_FREE_TESTS = WORKSPACE / (
    "scripts/tests/test_run_a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v4.py"
)
ANALYSIS_V4_DESIGN_FREEZE = WORKSPACE / (
    "papers/a08_hfnet_vs_klt_only_common_support_v4_design_freeze.json"
)
ANALYSIS_V4_DESIGN_FREEZE_SCHEMA = (
    "aqua-fe-a08-hfnet-vs-klt-only-common-support-design-freeze-v4"
)
ANALYSIS_V4_DESIGN_FREEZE_STATUS = (
    "FROZEN_AFTER_R01_R02_INFRASTRUCTURE_FAILURES_BEFORE_R03_R05_"
    "BACKEND_AND_ACCURACY"
)

V3_RUNNER = WORKSPACE / (
    "scripts/run_a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v3.py"
)
V3_PROTOCOL = WORKSPACE / (
    "papers/a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v3_protocol.md"
)
V3_GUARD = WORKSPACE / (
    "scripts/run_a08_recovered_july_history_matched_backend_klt_only_"
    "replay_guard_v3.sh"
)
V3_TESTS = WORKSPACE / (
    "scripts/tests/test_run_a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v3.py"
)
V3_LOCK = WORKSPACE / (
    "papers/a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v3_execution_lock.json"
)
ANALYSIS_V3_DESIGN_FREEZE = WORKSPACE / (
    "papers/a08_hfnet_vs_klt_only_common_support_v3_design_freeze.json"
)
REAL_VINS = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node")
PYTHON38 = Path("/usr/bin/python3.8")
DELEGATED_BASH = Path("/usr/bin/bash")

FROZEN_V3_EXPECTED = {
    "v3_runner": (44_728, "4a8739ae65b7c321bd425a6aa0c71e06d5b4c7dacaf9b4c0dd0eb19ee7dd6524"),
    "v3_protocol": (8_021, "de6db42cf857b7bea26985bad15e1d9cb08f4a113978af5d9d231e7b00bd4836"),
    "v3_guard": (12_477, "6c86a721192a14856ec34af89fd6ae781f8335d27096c04bf8f577d402269848"),
    "v3_process_free_tests": (18_946, "8e3fae8c1e0ec1acbb56d149dd43f2eda0ced0f14330f3cdb703a9b416b9b258"),
    "v3_execution_lock": (91_243, "63c485d15ea77b52df3ff0266332dc1e58446a6d8c0da3539bb2bee717ff3e64"),
    "analysis_v3_design_freeze": (15_827, "97b613c5d7bfc216e725f8a927b85f0a1c8fe14da568430a4daa1221b8db7d86"),
    "python38": (5_490_456, "298a9e830ed52f36c299427565485d717d1ce0179c0597cc16560513eb780b06"),
    "delegated_bash": (1_183_448, "025cf78cd9d276019e916b97b0decd10cacb14902db8eb9f28233019babfb331"),
    "real_vins_binary": (13_104_360, "4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278"),
}

R02_EXPECTED = {
    "receipt": (12_840, "022dd34eff25edf3e012ae6ea81d691c20351525d3fee964121366779d69bf2d"),
    "claim": (10_082, "55c02762b7b50bacdc88f20f2b3a07c47a2a333ca45b736943e659b17a5fd573"),
    "supervisor_log": (1_431, "c3eed8e1e188b942303296b0856f6f708416f7d1f62c088ef83c7cf9d677077e"),
    "guard_manifest": (4_738, "3d82a81cf54ea4eac50bb9d71ee2e18af596ff2bb2a001949e0a495036c2dda9"),
    "replay_manifest": (488, "f74425ac59752de069e222a38f8f070cbd81fce1a29a7be3a6f32dd5674114d0"),
    "vio": (280_238, "ee90649dcf92e2ff5cb200c5656b4d150bee6a1145ea05a8ab35e1c0e78e768f"),
    "ape": (671, "ac4d9c1bc62f8766a2622a3afd4ce09d6180fa081148516222703bd157c6e447"),
    "vins_log": (251_653, "896a0483094880e70b51f0569b7fff220f17fd74bb33ddcc75272d7482840ed2"),
    "namespace_manifest": (672, "a1079777a4a1f3fcb11f79f8b14a1a06743f3f5cc02f15caae1ffdef6c12ee4d"),
}

PRIOR_R01_DISPOSITION = (
    "NA_BACKEND_INFRASTRUCTURE_FD_INHERITANCE_FAILURE_NO_REPLAY_NO_REPLACEMENT"
)
R01_FAILURE_CODE = "ROSBAG_PYTHON_SUBPROCESS_CLOSE_FDS_DROPPED_SEALED_FD9"
PRIOR_R02_DISPOSITION = (
    "NA_BACKEND_INFRASTRUCTURE_VINS_SIGTERM_CLEANUP_TIMEOUT_AFTER_COMPLETE_"
    "REPLAY_NO_REPLACEMENT"
)
R02_FAILURE_CODE = "OVERLAY_CLEANUP_WAIT_BLOCKED_ON_SIGTERM_MASKED_VINS_PROCESS"
R02_STRICT_FAILURE = "PRIOR_STABLE_FD_OWNER_REPLAY_BINDING:KLT_R02"
R02_ARTIFACT_ISSUE = (
    "REPLAY_MANIFEST_GATE:missing=accepted_feature_bag,accepted_feature_bag_sha256,"
    "accepted_feature_bag_size_bytes,sealed_fd_owner_pid,sealed_play_bag,"
    "stable_owner_fd_guard,strict_replay_only_fd_guard;conflicting="
)
R02_MISSING_REPLAY_KEYS = [
    "accepted_feature_bag", "accepted_feature_bag_sha256",
    "accepted_feature_bag_size_bytes", "sealed_fd_owner_pid", "sealed_play_bag",
    "stable_owner_fd_guard", "strict_replay_only_fd_guard",
]


def _load_v3() -> ModuleType:
    raw = V3_RUNNER.read_bytes()
    require_bootstrap = (
        len(raw), hashlib.sha256(raw).hexdigest()
    ) == FROZEN_V3_EXPECTED["v3_runner"]
    if not require_bootstrap or V3_RUNNER.is_symlink() or V3_RUNNER.resolve() != V3_RUNNER:
        raise RuntimeError("V3_RUNNER_BOOTSTRAP_IDENTITY_DRIFT")
    specification = importlib.util.spec_from_file_location("a08_klt_v3_for_v4", V3_RUNNER)
    if specification is None or specification.loader is None:
        raise RuntimeError("V3_RUNNER_IMPORT_SPEC")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _fresh_v3_authority() -> ModuleType:
    """Return an isolated v3 authority whose shared v1 engine is unmodified.

    v2/v3 are frozen adapters around one mutable engine module.  Reusing that
    engine after v4 rebinding would make v2 lock reconstruction depend on v4
    callbacks.  A fresh import is read-only and preserves each frozen adapter's
    original bootstrap state for consumed-evidence audits.
    """
    return _load_v3()


V3 = _load_v3()
ENGINE = V3.ENGINE
BackendProtocolError = ENGINE.BackendProtocolError
require = ENGINE.require
identity = ENGINE.identity
stable_json = ENGINE.stable_json
compact_sha256 = ENGINE.compact_sha256
current_namespace = ENGINE.current_namespace
BASE_PRIOR_RECEIPT = V3.BASE_PRIOR_RECEIPT
BASE_ARTIFACT_AUDIT = ENGINE.artifact_audit

ITEM_ORDER = ("KLT_R03", "KLT_R04", "KLT_R05")
CLAIM_NAME = "process_start_claim_v1.json"
RECEIPT_NAME = "formal_run_receipt_v4.json"
LOCK_SCHEMA = "aqua-fe-a08-recovered-july-backend-klt-only-remaining-lock-v4"
RECEIPT_SCHEMA = "aqua-fe-a08-recovered-july-backend-klt-only-remaining-receipt-v4"
LOCK_STATUS = "FROZEN_REMAINING_R03_R05_AFTER_R01_R02_INFRA_FAILURES_BEFORE_LAUNCH"
BUILD_LOCK_TOKEN = (
    "A08_BUILD_KLT_ONLY_REMAINING_BACKEND_REPLAYS_V4_LOCK_AFTER_R01_R02_INFRA_FAILURES"
)
AUTHORIZATION_TOKENS = {
    item: f"A08_KLT_ONLY_REMAINING_BACKEND_REPLAYS_V4_RUN_{item}_EXACTLY_ONCE"
    for item in ITEM_ORDER
}
EXPECTED_OUTPUTS = tuple(ENGINE.EXPECTED_OUTPUTS) + (
    "vins_lifecycle_start_manifest_v4.json",
    "vins_lifecycle_terminal_manifest_v4.json",
    "overlay_signal_mask_manifest_v4.json",
)
CONTROL_SIGNAL_NUMBERS = {int(signal.SIGHUP), int(signal.SIGINT), int(signal.SIGTERM)}
SCIENTIFIC_ENV_KEYS = (
    "AQUALOC_BODY_T_CAM0_MODE", "VINS_MULTIPLE_THREAD", "VINS_TD",
    "VINS_ESTIMATE_TD", "VINS_MAX_SOLVER_TIME", "VINS_MAX_NUM_ITERATIONS",
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS", "ROS_MASTER_URI", "ROS_HOSTNAME",
)


def _identity_tuple(value: Mapping[str, Any]) -> tuple[int, str]:
    return int(value["size_bytes"]), str(value["sha256"])


def _identity_matches(value: Mapping[str, Any], expected: tuple[int, str]) -> bool:
    return _identity_tuple(value) == expected


def resolve_frontend_bindings() -> dict[str, Any]:
    return _fresh_v3_authority().resolve_frontend_bindings()


def arm_spec(item_id: str) -> dict[str, Any]:
    require(item_id in ITEM_ORDER, f"ITEM_ID:{item_id}")
    repeat = int(item_id[-2:])
    tag = f"a08_recoveredjuly_hist0000_4660_backend_klt_only_r{repeat:02d}_v4"
    return {
        "arm": "klt", "repeat_index": repeat, "method": "klt", "tag": tag,
        "run_leaf": f"external_klt_every2_{tag}",
    }


def item_environment(item_id: str, bindings: Mapping[str, Any]) -> dict[str, str]:
    spec = arm_spec(item_id)
    environment = V3.item_environment(item_id, bindings)
    environment.pop("A08_KLT_ONLY_REMAINING_REPLAYS_V3", None)
    wrapper = identity(LIFECYCLE_WRAPPER)
    launcher = identity(SIGNAL_MASK_LAUNCHER)
    real = identity(REAL_VINS)
    bash = identity(DELEGATED_BASH)
    python38 = identity(PYTHON38)
    overlay_shell = identity(ENGINE.BACKEND_SHELL)
    output = BACKEND_ROOT / item_id
    environment.update({
        "TAG": spec["tag"],
        "ROS_HOME": str(RUNTIME_ROOT / item_id / "ros_home"),
        "ROS_LOG_DIR": str(RUNTIME_ROOT / item_id / "ros_log"),
        "A08_ITEM_OUTPUT_DIR": str(output),
        "A08_ITEM_ID": item_id,
        "A08_WORKSPACE_LINK": str(OVERLAY_RUN_ROOT / spec["run_leaf"]),
        "A08_KLT_ONLY_REMAINING_REPLAYS_V4": "1",
        "A08_PRIOR_R01_DISPOSITION": PRIOR_R01_DISPOSITION,
        "A08_PRIOR_R02_DISPOSITION": PRIOR_R02_DISPOSITION,
        "VINS_NODE_BIN": str(LIFECYCLE_WRAPPER),
        "A08_VINS_LIFECYCLE_WRAPPER_V4": "1",
        "A08_VINS_LIFECYCLE_WRAPPER_PATH": str(LIFECYCLE_WRAPPER),
        "A08_VINS_LIFECYCLE_WRAPPER_SIZE_BYTES": str(wrapper["size_bytes"]),
        "A08_VINS_LIFECYCLE_WRAPPER_SHA256": str(wrapper["sha256"]),
        "A08_REAL_VINS_NODE_BIN": str(REAL_VINS),
        "A08_REAL_VINS_SIZE_BYTES": str(real["size_bytes"]),
        "A08_REAL_VINS_SHA256": str(real["sha256"]),
        "A08_VINS_LIFECYCLE_START_MANIFEST": str(output / "vins_lifecycle_start_manifest_v4.json"),
        "A08_VINS_LIFECYCLE_TERMINAL_MANIFEST": str(output / "vins_lifecycle_terminal_manifest_v4.json"),
        "A08_UNBLOCKED_OVERLAY_EXEC_V4": "1",
        "A08_SIGNAL_MASK_LAUNCHER_PATH": str(SIGNAL_MASK_LAUNCHER),
        "A08_SIGNAL_MASK_LAUNCHER_SIZE_BYTES": str(launcher["size_bytes"]),
        "A08_SIGNAL_MASK_LAUNCHER_SHA256": str(launcher["sha256"]),
        "A08_SIGNAL_MASK_MANIFEST": str(output / "overlay_signal_mask_manifest_v4.json"),
        "A08_DELEGATED_BASH_PATH": str(DELEGATED_BASH),
        "A08_DELEGATED_BASH_SIZE_BYTES": str(bash["size_bytes"]),
        "A08_DELEGATED_BASH_SHA256": str(bash["sha256"]),
        "A08_OVERLAY_BACKEND_SHELL_SIZE_BYTES": str(overlay_shell["size_bytes"]),
        "A08_OVERLAY_BACKEND_SHELL_SHA256": str(overlay_shell["sha256"]),
        "A08_PYTHON38_PATH": str(PYTHON38),
        "A08_PYTHON38_SIZE_BYTES": str(python38["size_bytes"]),
        "A08_PYTHON38_SHA256": str(python38["sha256"]),
    })
    return environment


def build_items(
    bindings: Mapping[str, Any], host_net: str, host_user: str,
) -> dict[str, Any]:
    require(re.fullmatch(r"net:\[[0-9]+\]", host_net) is not None, "HOST_NETNS")
    require(re.fullmatch(r"user:\[[0-9]+\]", host_user) is not None, "HOST_USERNS")
    result: dict[str, Any] = {}
    for item_id in ITEM_ORDER:
        spec = arm_spec(item_id)
        output = BACKEND_ROOT / item_id
        workspace = OVERLAY_RUN_ROOT / spec["run_leaf"]
        inner = [
            str(ENGINE.BASH), str(REPLAY_ONLY_GUARD), "aqualoc_archaeo", "8",
            "0", "4660", "klt", "2",
        ]
        argv = [
            str(ENGINE.UNSHARE), "--user", "--map-root-user", "--net",
            str(ENGINE.PYTHON38), str(ENGINE.NETNS_ENTRY),
            "--output-dir", str(output), "--formal-port", str(ENGINE.FORMAL_PORT),
            "--host-network-namespace", host_net, "--host-user-namespace", host_user,
            "--", *inner,
        ]
        environment = item_environment(item_id, bindings)
        result[item_id] = {
            "item_id": item_id, "arm": "klt", "repeat_index": spec["repeat_index"],
            "method": "klt", "output_dir": str(output),
            "workspace_link": str(workspace), "argv": argv,
            "inner_backend_argv_sha256": compact_sha256(inner),
            "host_network_namespace": host_net, "host_user_namespace": host_user,
            "env": environment, "cwd": str(OVERLAY),
            "timeout_seconds": ENGINE.TIMEOUT_SECONDS,
            "expected_outputs": list(EXPECTED_OUTPUTS),
            "input_binding": bindings["klt"],
            "excluded_xfeat_sha256": compact_sha256(bindings["excluded_xfeat"]),
            "prior_r01_disposition": PRIOR_R01_DISPOSITION,
            "prior_r02_disposition": PRIOR_R02_DISPOSITION,
            "scientific_boundary": {
                "repeat_r01": PRIOR_R01_DISPOSITION,
                "repeat_r02": PRIOR_R02_DISPOSITION,
                "maximum_valid_repeat_count": 3,
                "xfeat_accuracy": "NA",
                "learned_contribution_claim_permitted": False,
            },
            "command_sha256": compact_sha256({"argv": argv, "env": environment}),
        }
    return result


def static_identity_paths() -> dict[str, Path]:
    inherited = dict(V3.static_identity_paths())
    inherited["v3_runner"] = inherited.pop("runner")
    inherited["v3_protocol"] = inherited.pop("protocol")
    inherited["v3_guard"] = inherited.pop("stable_owner_replay_guard_v3")
    inherited["v3_process_free_tests"] = inherited.pop("process_free_tests")
    inherited.update({
        "v3_execution_lock": V3_LOCK,
        "analysis_v3_design_freeze": ANALYSIS_V3_DESIGN_FREEZE,
        "python38": PYTHON38,
        "delegated_bash": DELEGATED_BASH,
        "real_vins_binary": REAL_VINS,
        "runner": RUNNER,
        "protocol": PROTOCOL,
        "stable_owner_replay_guard_v4": REPLAY_ONLY_GUARD,
        "vins_lifecycle_wrapper_v4": LIFECYCLE_WRAPPER,
        "signal_mask_launcher_v4": SIGNAL_MASK_LAUNCHER,
        "process_free_tests": PROCESS_FREE_TESTS,
    })
    return inherited


def collect_static_identities() -> dict[str, Any]:
    _fresh_v3_authority().collect_static_identities()
    values = {name: identity(path) for name, path in static_identity_paths().items()}
    for label, expected in FROZEN_V3_EXPECTED.items():
        require(_identity_matches(values[label], expected), f"STATIC_IDENTITY:{label}")
    return values


def v3_lock_authority(bindings: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    frozen = _fresh_v3_authority()
    lock, lock_identity = frozen.verify_lock(V3_LOCK, bindings)
    require(_identity_matches(lock_identity, FROZEN_V3_EXPECTED["v3_execution_lock"]),
            "V3_LOCK_EXACT_IDENTITY")
    return lock, lock_identity


def prior_r01_authority(bindings: Mapping[str, Any]) -> dict[str, Any]:
    value = _fresh_v3_authority().prior_r01_authority(bindings)
    require(value.get("disposition") == PRIOR_R01_DISPOSITION, "PRIOR_R01_DISPOSITION")
    return value


def _v3_remaining_unstarted(lock: Mapping[str, Any]) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for item_id in ITEM_ORDER:
        item = lock["items"][item_id]
        paths = {
            "output": Path(item["output_dir"]),
            "workspace": Path(item["workspace_link"]),
            "runtime": V3.RUNTIME_ROOT / item_id,
        }
        for label, path in paths.items():
            require(not path.exists() and not path.is_symlink(),
                    f"V3_REMAINING_ITEM_TOUCHED:{item_id}:{label}")
        rows[item_id] = {label: str(path) for label, path in paths.items()}
    return {"status": "PASS_V3_R03_R05_ALL_UNSTARTED", "items": rows}


def prior_r02_authority(bindings: Mapping[str, Any]) -> dict[str, Any]:
    frozen = _fresh_v3_authority()
    lock, lock_identity = frozen.verify_lock(V3_LOCK, bindings)
    require(_identity_matches(lock_identity, FROZEN_V3_EXPECTED["v3_execution_lock"]),
            "V3_LOCK_EXACT_IDENTITY")
    item = lock["items"]["KLT_R02"]
    output = Path(item["output_dir"])
    receipt_path = output / V3.RECEIPT_NAME
    receipt_identity = identity(receipt_path)
    require(_identity_matches(receipt_identity, R02_EXPECTED["receipt"]),
            "V3_R02_RECEIPT_IDENTITY")
    frozen._configure_engine()
    receipt = frozen.BASE_PRIOR_RECEIPT(lock_identity, item)
    strict_error: Optional[str] = None
    try:
        frozen._configure_engine()
        frozen.prior_receipt(lock_identity, item)
    except RuntimeError as error:
        strict_error = str(error)
    finally:
        _configure_engine()
    require(strict_error == R02_STRICT_FAILURE, "V3_R02_STRICT_AUDIT_EXPECTED_FAILURE")

    require(receipt.get("status") == "FAILED_BACKEND_REPLAY_NO_REPLACEMENT",
            "V3_R02_TERMINAL_STATUS")
    integrity = receipt.get("execution_integrity")
    runtime = receipt.get("runtime")
    artifact = receipt.get("artifact_contract")
    require(
        isinstance(integrity, dict) and integrity.get("status") == "PASS"
        and integrity.get("irreversible_fault_latch_clear") is True
        and receipt.get("integrity_fault_latch") == [],
        "V3_R02_EXECUTION_INTEGRITY",
    )
    require(
        isinstance(runtime, dict) and runtime.get("timed_out") is True
        and runtime.get("raw_return_code") == -9
        and runtime.get("popen_invocation_count") == 1
        and runtime.get("child_started") is True,
        "V3_R02_TIMEOUT_RUNTIME",
    )
    require(
        receipt.get("retry_count") == 0
        and receipt.get("replacement_permitted") is False
        and receipt.get("launch_allowance_consumed") is True,
        "V3_R02_NO_RETRY_NO_REPLACEMENT",
    )
    require(
        isinstance(artifact, dict) and artifact.get("status") == "FAIL"
        and artifact.get("evidence_tree_integrity") is True
        and artifact.get("integrity_issues") == []
        and artifact.get("issues") == [R02_ARTIFACT_ISSUE],
        "V3_R02_ARTIFACT_CONTRACT_EXACT_FAIL",
    )
    outputs = artifact["outputs"]
    expected_output_keys = set(item["expected_outputs"])
    require(set(outputs) == expected_output_keys, "V3_R02_COMPLETE_OUTPUT_SET")
    critical = {
        "ape.txt": "ape", "replay_manifest.txt": "replay_manifest",
        "replay_only_guard_manifest.json": "guard_manifest",
        "network_namespace_manifest.json": "namespace_manifest",
        "vins_output/vio.csv": "vio", "vins.log": "vins_log",
    }
    for relative, label in critical.items():
        require(_identity_matches(outputs[relative], R02_EXPECTED[label]),
                f"V3_R02_OUTPUT_IDENTITY:{relative}")
    require(_identity_matches(receipt["claim"], R02_EXPECTED["claim"]),
            "V3_R02_CLAIM_IDENTITY")
    require(_identity_matches(receipt["process_log"], R02_EXPECTED["supervisor_log"]),
            "V3_R02_LOG_IDENTITY")

    semantic = artifact.get("semantic_checks", {})
    trajectory = semantic.get("trajectory")
    usability = semantic.get("backend_usability")
    replay = semantic.get("replay_manifest")
    guard = semantic.get("replay_only_guard")
    require(
        trajectory.get("rows") == 2319
        and abs(float(trajectory.get("duration_s")) - 231.761931776) < 1e-12,
        "V3_R02_COMPLETE_TRAJECTORY",
    )
    require(
        usability.get("status") == "PASS"
        and usability.get("values", {}).get("matched") == 2319.0
        and usability.get("values", {}).get("output_coverage_ratio") == 0.99485,
        "V3_R02_BACKEND_USABILITY",
    )
    require(
        replay.get("status") == "FAIL"
        and replay.get("missing_keys") == R02_MISSING_REPLAY_KEYS
        and replay.get("conflicting_keys") == []
        and replay.get("explicit_lineage_conflict") is False,
        "V3_R02_EXPECTED_REPLAY_MANIFEST_INCOMPLETE",
    )
    require(guard.get("status") == "PASS", "V3_R02_GUARD_PASS")
    owner = guard.get("sealed_fd_owner_pid")
    require(isinstance(owner, int) and owner == runtime.get("pid"),
            "V3_R02_STABLE_OWNER_PID")
    log_path = output / "supervisor_process.log"
    log_before = identity(log_path)
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    require(identity(log_path) == log_before, "V3_R02_LOG_CHANGED_DURING_READ")
    require(
        f"Opening /proc/{owner}/fd/9" in log_text and "Done." in log_text
        and "matched=2319" in log_text and "output_coverage_ratio=0.994850" in log_text,
        "V3_R02_COMPLETE_REPLAY_SIGNATURE",
    )
    later = _v3_remaining_unstarted(lock)
    return {
        "item_id": "KLT_R02", "disposition": PRIOR_R02_DISPOSITION,
        "failure_code": R02_FAILURE_CODE,
        "rerun_permitted": False, "replacement_permitted": False,
        "counts_as_valid_repeat": False,
        "v3_execution_lock": lock_identity,
        "v3_terminal_receipt": receipt_identity,
        "v3_claim": receipt["claim"], "v3_process_log": receipt["process_log"],
        "v3_guard_manifest": outputs["replay_only_guard_manifest.json"],
        "v3_replay_manifest": outputs["replay_manifest.txt"],
        "v3_vio": outputs["vins_output/vio.csv"], "v3_ape": outputs["ape.txt"],
        "base_deep_terminal_evidence_audit": "PASS",
        "v3_strict_deep_terminal_evidence_audit":
            "FAIL_EXPECTED_LEGACY_REPLAY_MANIFEST_SCHEMA",
        "v3_strict_deep_failure_code": strict_error,
        "receipt_status": receipt["status"], "execution_integrity": "PASS",
        "runtime_timed_out": True, "raw_return_code": -9,
        "artifact_contract_status": "FAIL", "artifact_issue": R02_ARTIFACT_ISSUE,
        "replay_manifest_semantic_status": "FAIL_EXPECTED_LEGACY_SCHEMA",
        "replay_manifest_missing_keys": list(R02_MISSING_REPLAY_KEYS),
        "evidence_tree_integrity": True, "complete_artifacts": True,
        "complete_artifact_identities": dict(outputs),
        "trajectory_complete": True, "trajectory_admitted": False,
        "replay_completed": True, "post_result_cleanup_failed": True,
        "artifact_accepted": False, "rerun_or_replacement_permitted": False,
        "v3_remaining_items": later,
    }


def collect_analysis_v4_design_freeze_binding() -> dict[str, Any]:
    value, freeze_identity = stable_json(ANALYSIS_V4_DESIGN_FREEZE)
    require(value.get("schema_version") == ANALYSIS_V4_DESIGN_FREEZE_SCHEMA,
            "ANALYSIS_V4_DESIGN_FREEZE_SCHEMA")
    require(value.get("status") == ANALYSIS_V4_DESIGN_FREEZE_STATUS,
            "ANALYSIS_V4_DESIGN_FREEZE_STATUS")
    digest = value.get("freeze_sha256")
    unsigned = dict(value)
    unsigned.pop("freeze_sha256", None)
    require(digest == compact_sha256(unsigned), "ANALYSIS_V4_DESIGN_FREEZE_DIGEST")
    frozen = value.get("static_identities")
    require(isinstance(frozen, dict), "ANALYSIS_V4_STATIC_IDENTITIES")
    required = {
        "backend_v4_protocol": identity(PROTOCOL),
        "backend_v4_runner": identity(RUNNER),
        "backend_v4_guard": identity(REPLAY_ONLY_GUARD),
        "backend_v4_lifecycle_wrapper": identity(LIFECYCLE_WRAPPER),
        "backend_v4_signal_mask_launcher": identity(SIGNAL_MASK_LAUNCHER),
        "backend_v4_process_free_tests": identity(PROCESS_FREE_TESTS),
        "backend_v4_python38": identity(PYTHON38),
        "backend_v4_vins_node": identity(REAL_VINS),
        "analysis_v3_design_freeze": identity(ANALYSIS_V3_DESIGN_FREEZE),
        "backend_v3_execution_lock": identity(V3_LOCK),
        "v3_r02_terminal_receipt": identity(
            V3.BACKEND_ROOT / "KLT_R02" / V3.RECEIPT_NAME
        ),
    }
    require(all(frozen.get(key) == row for key, row in required.items()),
            "ANALYSIS_V4_STATIC_BACKEND_BINDINGS")
    prior = value.get("prior_r02")
    require(
        isinstance(prior, dict)
        and prior.get("disposition") == PRIOR_R02_DISPOSITION
        and prior.get("failure_code") == R02_FAILURE_CODE
        and prior.get("receipt") == required["v3_r02_terminal_receipt"]
        and prior.get("v3_execution_lock") == required["backend_v3_execution_lock"]
        and prior.get("base_deep_terminal_evidence_audit") == "PASS"
        and prior.get("v3_strict_deep_terminal_evidence_audit")
            == "FAIL_EXPECTED_LEGACY_REPLAY_MANIFEST_SCHEMA"
        and prior.get("v3_strict_deep_failure_code") == R02_STRICT_FAILURE
        and prior.get("receipt_status") == "FAILED_BACKEND_REPLAY_NO_REPLACEMENT"
        and prior.get("execution_integrity") == "PASS"
        and prior.get("runtime_timed_out") is True
        and prior.get("raw_return_code") == -9
        and prior.get("artifact_contract_status") == "FAIL"
        and prior.get("artifact_issue") == R02_ARTIFACT_ISSUE
        and prior.get("replay_manifest_semantic_status") == "FAIL_EXPECTED_LEGACY_SCHEMA"
        and prior.get("replay_manifest_missing_keys") == R02_MISSING_REPLAY_KEYS
        and prior.get("evidence_tree_integrity") is True
        and prior.get("complete_artifacts") is True
        and prior.get("complete_artifact_identities")
            == prior_r02_authority(resolve_frontend_bindings())["complete_artifact_identities"]
        and prior.get("trajectory_complete") is True
        and prior.get("trajectory_admitted") is False
        and prior.get("replay_completed") is True
        and prior.get("post_result_cleanup_failed") is True
        and prior.get("rerun_or_replacement_permitted") is False,
        "ANALYSIS_V4_PRIOR_R02_BOUNDARY",
    )
    contract = value.get("design_contract")
    population = contract.get("population_and_failure_rules") if isinstance(contract, dict) else None
    require(
        isinstance(population, dict)
        and population.get("backend_item_order")
            == ["KLT_R01", "KLT_R02", "KLT_R03", "KLT_R04", "KLT_R05"]
        and population.get("v4_backend_item_order") == list(ITEM_ORDER)
        and population.get("klt_planned_count") == 5
        and population.get("maximum_valid_klt_count") == 3
        and population.get("r01_counts_as_valid") is False
        and population.get("r02_counts_as_valid") is False
        and population.get("r01_rerun_or_replacement_permitted") is False
        and population.get("r02_rerun_or_replacement_permitted") is False,
        "ANALYSIS_V4_PLANNED_POPULATION",
    )
    boundary = value.get("claim_boundary")
    require(
        isinstance(boundary, dict)
        and boundary.get("backend_v4_execution_lock_built") is False
        and boundary.get("v4_backend_items_started") == 0
        and boundary.get("ape_or_rpe_computed_for_v4") is False
        and boundary.get("ros_or_vins_started_for_v4") is False,
        "ANALYSIS_V4_PREBACKEND_BOUNDARY",
    )
    return {
        "identity": freeze_identity, "schema_version": value["schema_version"],
        "status": value["status"], "freeze_sha256": digest,
        "required_static_identities": required, "prior_r02": prior,
        "population_and_failure_rules": population, "claim_boundary": boundary,
    }


def require_campaign_unstarted() -> None:
    require(not BACKEND_ROOT.exists() and not BACKEND_ROOT.is_symlink(),
            "V4_OUTPUT_ROOT_ALREADY_TOUCHED")
    require(not RUNTIME_ROOT.exists() and not RUNTIME_ROOT.is_symlink(),
            "V4_RUNTIME_ROOT_ALREADY_TOUCHED")
    for item_id in ITEM_ORDER:
        workspace = OVERLAY_RUN_ROOT / arm_spec(item_id)["run_leaf"]
        require(not workspace.exists() and not workspace.is_symlink(),
                f"V4_WORKSPACE_ALREADY_TOUCHED:{item_id}")


def shutdown_stage_audit(
    stages: Any, final_code: Any,
) -> dict[str, Any]:
    """Validate the exact bounded SIGINT -> SIGTERM -> SIGKILL state machine."""
    failures: list[str] = []
    allowed_sequences = (
        ["SIGINT"], ["SIGINT", "SIGTERM"],
        ["SIGINT", "SIGTERM", "SIGKILL"],
    )
    if not isinstance(stages, list) or not stages:
        return {"status": "FAIL", "failure_codes": ["STAGES_NONEMPTY_LIST"]}
    if not isinstance(final_code, int) or isinstance(final_code, bool):
        failures.append("FINAL_RETURN_CODE_INTEGER")
    if any(not isinstance(row, dict) for row in stages):
        return {"status": "FAIL", "failure_codes": failures + ["STAGE_ROWS_DICT"]}
    observed = [row.get("signal") for row in stages]
    if observed not in allowed_sequences:
        failures.append("STAGE_SIGNAL_SEQUENCE")
    specifications = {
        "SIGINT": ("grace_seconds", 1.0, "child_return_code_after_grace"),
        "SIGTERM": ("grace_seconds", 0.5, "child_return_code_after_grace"),
        "SIGKILL": ("reap_timeout_seconds", 2.0, "child_return_code_after_wait"),
    }
    return_codes: list[Any] = []
    for index, row in enumerate(stages):
        name = row.get("signal")
        if name not in specifications:
            failures.append(f"STAGE_NAME:{index}")
            continue
        duration_key, duration_value, return_key = specifications[name]
        expected_keys = {"signal", "sent", duration_key, return_key}
        if set(row) != expected_keys:
            failures.append(f"STAGE_KEYS:{index}")
        if row.get("sent") is not True:
            failures.append(f"STAGE_SENT:{index}")
        if row.get(duration_key) != duration_value:
            failures.append(f"STAGE_BOUND:{index}")
        return_codes.append(row.get(return_key))
    if return_codes:
        if any(value is not None for value in return_codes[:-1]):
            failures.append("NONFINAL_STAGE_RETURN_CODE")
        if return_codes[-1] != final_code:
            failures.append("FINAL_STAGE_RETURN_CODE")
    if observed and observed[-1] == "SIGKILL" and final_code != -int(signal.SIGKILL):
        failures.append("SIGKILL_FINAL_RETURN_CODE")
    return {
        "status": "PASS" if not failures else "FAIL",
        "failure_codes": failures,
        "signals": observed,
        "final_return_code": final_code,
    }


def wrapper_signal_sequence_audit(signals: Any) -> dict[str, Any]:
    expected = [int(signal.SIGTERM)]
    passed = signals == expected
    return {
        "status": "PASS" if passed else "FAIL",
        "failure_codes": [] if passed else ["WRAPPER_SIGNAL_SEQUENCE"],
        "expected": expected,
        "observed": signals,
    }


def lifecycle_manifest_audit(output: Path, item: Mapping[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    integrity_failures: list[str] = []
    try:
        start, start_identity = stable_json(output / "vins_lifecycle_start_manifest_v4.json")
        terminal, terminal_identity = stable_json(
            output / "vins_lifecycle_terminal_manifest_v4.json"
        )
        start_unsigned = dict(start); start_digest = start_unsigned.pop("contract_sha256", None)
        terminal_unsigned = dict(terminal); terminal_digest = terminal_unsigned.pop("contract_sha256", None)
        wrapper_expected = {
            "path": item["env"]["A08_VINS_LIFECYCLE_WRAPPER_PATH"],
            "size_bytes": int(item["env"]["A08_VINS_LIFECYCLE_WRAPPER_SIZE_BYTES"]),
            "sha256": item["env"]["A08_VINS_LIFECYCLE_WRAPPER_SHA256"],
        }
        real_expected = {
            "path": item["env"]["A08_REAL_VINS_NODE_BIN"],
            "size_bytes": int(item["env"]["A08_REAL_VINS_SIZE_BYTES"]),
            "sha256": item["env"]["A08_REAL_VINS_SHA256"],
        }
        policy = {
            "overlay_signal_received_by_wrapper": "SIGTERM",
            "first_real_child_signal": "SIGINT", "sigint_grace_seconds": 1.0,
            "second_real_child_signal": "SIGTERM", "sigterm_grace_seconds": 0.5,
            "final_real_child_signal": "SIGKILL", "sigkill_reap_timeout_seconds": 2.0,
            "maximum_shutdown_seconds": 3.5,
            "real_child_must_be_reaped_before_wrapper_exit": True,
            "automatic_restart_count": 0,
        }
        config_expected = identity(output / "vins_aqualoc_archaeo_external.yaml")
        selected_env = {
            key: item["env"][key] for key in SCIENTIFIC_ENV_KEYS if key in item["env"]
        }
        start_checks = {
            "schema": start.get("schema_version") == "aqua-fe-a08-vins-lifecycle-wrapper-start-v4",
            "status": start.get("status") == "PASS_REAL_VINS_STARTED_ONCE_BEFORE_REPLAY",
            "digest": start_digest == compact_sha256(start_unsigned),
            "item": start.get("item_id") == item["item_id"],
            "wrapper": start.get("wrapper") == wrapper_expected,
            "real": start.get("real_vins_binary") == real_expected,
            "config": start.get("config") == config_expected,
            "argv": start.get("argv") == [real_expected["path"], item["workspace_link"] + "/vins_aqualoc_archaeo_external.yaml"],
            "cwd": start.get("working_directory") == item["cwd"],
            "environment": start.get("scientific_environment") == selected_env
                and start.get("scientific_environment_sha256") == compact_sha256(selected_env),
            "popen_once": start.get("real_child_popen_count") == 1,
            "no_restart": start.get("automatic_restart_count") == 0,
            "policy": start.get("lifecycle_policy") == policy,
            "pids": isinstance(start.get("wrapper_pid"), int)
                and isinstance(start.get("real_child_pid"), int)
                and start.get("wrapper_pid") != start.get("real_child_pid")
                and isinstance(start.get("real_child_start_ticks"), int),
            "group": start.get("real_child_process_group") == start.get("wrapper_process_group")
                and start.get("real_child_session") == start.get("wrapper_session"),
            "mask": not (CONTROL_SIGNAL_NUMBERS & set(start.get("wrapper_blocked_signals_after_unblock", []))),
        }
        terminal_checks = {
            "schema": terminal.get("schema_version") == "aqua-fe-a08-vins-lifecycle-wrapper-terminal-v4",
            "digest": terminal_digest == compact_sha256(terminal_unsigned),
            "item": terminal.get("item_id") == item["item_id"],
            "wrapper_pid": terminal.get("wrapper_pid") == start.get("wrapper_pid"),
            "child_pid": terminal.get("real_child_pid") == start.get("real_child_pid"),
            "start_identity": terminal.get("start_manifest") == start_identity,
            "real": terminal.get("real_vins_binary") == real_expected,
            "config": terminal.get("config") == config_expected,
            "policy": terminal.get("lifecycle_policy") == policy,
            "reaped": terminal.get("real_child_reaped") is True,
            "no_restart": policy["automatic_restart_count"] == 0,
        }
        stage_gate = shutdown_stage_audit(
            terminal.get("shutdown_stages"), terminal.get("real_child_return_code")
        )
        signal_gate = wrapper_signal_sequence_audit(
            terminal.get("received_wrapper_signals")
        )
        terminal_checks["shutdown_state_machine"] = stage_gate["status"] == "PASS"
        terminal_checks["wrapper_signal_sequence"] = signal_gate["status"] == "PASS"
        for name, passed in {**{f"start:{k}": v for k, v in start_checks.items()},
                             **{f"terminal:{k}": v for k, v in terminal_checks.items()}}.items():
            if not passed:
                integrity_failures.append(name)
        accepted = bool(
            not integrity_failures
            and terminal.get("status") == "PASS_OVERLAY_TERM_RECEIVED_REAL_VINS_REAPED"
            and terminal.get("expected_overlay_term_received") is True
            and terminal.get("wrapper_exit_code") == 0
        )
        if not accepted:
            failures.append("LIFECYCLE_NOT_ACCEPTED")
        return {
            "status": "PASS" if accepted else "FAIL",
            "contract_integrity": not integrity_failures,
            "failure_codes": failures + integrity_failures,
            "start_identity": start_identity, "terminal_identity": terminal_identity,
            "wrapper_pid": start.get("wrapper_pid"),
            "real_child_pid": start.get("real_child_pid"),
            "wrapper_parent_pid": start.get("wrapper_parent_pid"),
            "real_child_reaped": terminal.get("real_child_reaped"),
            "shutdown_stages": terminal.get("shutdown_stages"),
            "shutdown_stage_audit": stage_gate,
            "wrapper_signal_sequence_audit": signal_gate,
        }
    except (BackendProtocolError, OSError, ValueError, TypeError) as error:
        return {
            "status": "FAIL", "contract_integrity": False,
            "failure_codes": [f"{type(error).__name__}:{error}"],
        }


def signal_mask_manifest_audit(output: Path, item: Mapping[str, Any]) -> dict[str, Any]:
    try:
        value, manifest_identity = stable_json(output / "overlay_signal_mask_manifest_v4.json")
        unsigned = dict(value); digest = unsigned.pop("contract_sha256", None)
        before = set(value.get("blocked_signals_before", []))
        after = set(value.get("blocked_signals_after", []))
        expected_launcher = {
            "path": item["env"]["A08_SIGNAL_MASK_LAUNCHER_PATH"],
            "size_bytes": int(item["env"]["A08_SIGNAL_MASK_LAUNCHER_SIZE_BYTES"]),
            "sha256": item["env"]["A08_SIGNAL_MASK_LAUNCHER_SHA256"],
        }
        expected_bash = {
            "path": item["env"]["A08_DELEGATED_BASH_PATH"],
            "size_bytes": int(item["env"]["A08_DELEGATED_BASH_SIZE_BYTES"]),
            "sha256": item["env"]["A08_DELEGATED_BASH_SHA256"],
        }
        expected_overlay = {
            "path": item["env"]["A08_OVERLAY_BACKEND_SHELL"],
            "size_bytes": int(item["env"]["A08_OVERLAY_BACKEND_SHELL_SIZE_BYTES"]),
            "sha256": item["env"]["A08_OVERLAY_BACKEND_SHELL_SHA256"],
        }
        checks = {
            "schema": value.get("schema_version") == "aqua-fe-a08-unblocked-overlay-exec-v4",
            "status": value.get("status") == "PASS_CONTROL_SIGNALS_UNBLOCKED_BEFORE_OVERLAY_EXEC",
            "digest": digest == compact_sha256(unsigned),
            "item": value.get("item_id") == item["item_id"],
            "output": value.get("output_dir") == item["output_dir"],
            "workspace": value.get("workspace_link") == item["workspace_link"],
            "before": CONTROL_SIGNAL_NUMBERS <= before,
            "after": not (CONTROL_SIGNAL_NUMBERS & after),
            "numbers": value.get("control_signal_numbers") == sorted(CONTROL_SIGNAL_NUMBERS),
            "launcher": value.get("launcher") == expected_launcher,
            "bash": value.get("delegated_bash") == expected_bash,
            "overlay": value.get("frozen_overlay_shell") == expected_overlay,
            "argv": value.get("exec_argv") == [
                expected_bash["path"], expected_overlay["path"],
                "aqualoc_archaeo", "8", "0", "4660", "klt", "2",
            ],
            "exec": value.get("exec_replaces_launcher_process") is True,
            "pids": isinstance(value.get("launcher_overlay_pid"), int)
                and isinstance(value.get("stable_fd_owner_parent_pid"), int),
        }
        failures = [name for name, passed in checks.items() if not passed]
        return {
            "status": "PASS" if not failures else "FAIL",
            "contract_integrity": not failures, "checks": checks,
            "failure_codes": failures, "identity": manifest_identity,
            "launcher_overlay_pid": value.get("launcher_overlay_pid"),
            "stable_fd_owner_parent_pid": value.get("stable_fd_owner_parent_pid"),
            "blocked_signals_before": sorted(before), "blocked_signals_after": sorted(after),
        }
    except (BackendProtocolError, OSError, ValueError, TypeError) as error:
        return {"status": "FAIL", "contract_integrity": False,
                "failure_codes": [f"{type(error).__name__}:{error}"]}


def replay_guard_manifest_audit(path: Path, item: Mapping[str, Any]) -> dict[str, Any]:
    value, manifest_identity = stable_json(path)
    owner = value.get("sealed_fd_owner_pid")
    owner_valid = isinstance(owner, int) and not isinstance(owner, bool) and owner > 1
    expected_inputs = {
        "ground_truth": (item["env"]["GT_TXT"], int(item["env"]["A08_GT_SIZE_BYTES"]), item["env"]["A08_GT_SHA256"], 6),
        "raw_bag": (item["env"]["RAW_BAG"], int(item["env"]["A08_RAW_BAG_SIZE_BYTES"]), item["env"]["A08_RAW_BAG_SHA256"], 7),
        "raw_archive": (item["env"]["RAW_TAR"], int(item["env"]["A08_RAW_TAR_SIZE_BYTES"]), item["env"]["A08_RAW_TAR_SHA256"], 8),
        "feature_bag": (item["env"]["FEATURE_BAG_OVERRIDE"], int(item["env"]["A08_FEATURE_BAG_SIZE_BYTES"]), item["env"]["A08_FEATURE_BAG_SHA256"], 9),
        "frontend_metrics": (item["env"]["A08_FRONTEND_METRICS"], int(item["env"]["A08_FRONTEND_METRICS_SIZE_BYTES"]), item["env"]["A08_FRONTEND_METRICS_SHA256"], 10),
        "camera_config": (item["env"]["A08_FRONTEND_CAMERA_CONFIG"], int(item["env"]["A08_FRONTEND_CAMERA_SIZE_BYTES"]), item["env"]["A08_FRONTEND_CAMERA_SHA256"], 11),
    }
    observed = value.get("bound_inputs")
    input_checks: dict[str, bool] = {}
    for label, expected in expected_inputs.items():
        row = observed.get(label) if isinstance(observed, dict) else None
        input_checks[label] = bool(
            isinstance(row, dict) and row.get("accepted_path") == expected[0]
            and row.get("size_bytes") == expected[1] and row.get("sha256") == expected[2]
            and row.get("sealed_fd") == expected[3]
            and row.get("sealed_fd_owner_pid") == owner
            and row.get("sealed_path") == f"/proc/{owner}/fd/{expected[3]}"
            and row.get("stable_owner_path_verified_before_delegate") is True
        )
    lifecycle = value.get("vins_lifecycle", {})
    launcher = value.get("signal_mask_launcher", {})
    checks = {
        "schema": value.get("schema_version") == "aqua-fe-a08-replay-only-stable-owner-fd-guard-v4",
        "status": value.get("status") == "PASS_BEFORE_DELEGATED_BACKEND",
        "item": value.get("item_id") == item["item_id"],
        "output": value.get("output_dir") == item["output_dir"],
        "workspace": value.get("workspace_link") == item["workspace_link"],
        "delegated_shell": value.get("delegated_backend_shell")
            == item["env"]["A08_OVERLAY_BACKEND_SHELL"],
        "owner": owner_valid,
        "prior": value.get("prior_dispositions") == {
            "KLT_R01": PRIOR_R01_DISPOSITION, "KLT_R02": PRIOR_R02_DISPOSITION,
        },
        "history": value.get("history") == {
            "dataset": "aqualoc_archaeo", "sequence": 8, "start_source_index": 0,
            "end_source_index": 4660, "every_n": 2, "method": "klt",
        },
        "policy": value.get("policy") == {
            "frontend_export_permitted": False,
            "raw_reconstruction_permitted": False,
            "accepted_frontend_paths_passed_as_delegated_data_arguments": False,
            "delegated_data_environment_values_are_stable_owner_fd_paths": True,
            "all_delegated_data_paths_are_stable_owner_fd_paths": True,
            "child_self_fd_paths_forbidden": True,
            "owner_remains_alive_during_delegated_backend": True,
            "published_before_delegated_backend": True,
            "bounded_vins_lifecycle_wrapper_required": True,
        },
        "wrapper": lifecycle.get("wrapper") == {
            "path": item["env"]["A08_VINS_LIFECYCLE_WRAPPER_PATH"],
            "size_bytes": int(item["env"]["A08_VINS_LIFECYCLE_WRAPPER_SIZE_BYTES"]),
            "sha256": item["env"]["A08_VINS_LIFECYCLE_WRAPPER_SHA256"],
        },
        "real_vins": lifecycle.get("real_vins_binary") == {
            "path": item["env"]["A08_REAL_VINS_NODE_BIN"],
            "size_bytes": int(item["env"]["A08_REAL_VINS_SIZE_BYTES"]),
            "sha256": item["env"]["A08_REAL_VINS_SHA256"],
        },
        "lifecycle_paths": lifecycle.get("start_manifest") == item["env"]["A08_VINS_LIFECYCLE_START_MANIFEST"]
            and lifecycle.get("terminal_manifest") == item["env"]["A08_VINS_LIFECYCLE_TERMINAL_MANIFEST"],
        "lifecycle_policy": lifecycle.get("real_child_launch_count") == 1
            and lifecycle.get("automatic_restart_count") == 0
            and lifecycle.get("maximum_shutdown_seconds") == 3.5,
        "launcher": launcher.get("launcher") == {
            "path": item["env"]["A08_SIGNAL_MASK_LAUNCHER_PATH"],
            "size_bytes": int(item["env"]["A08_SIGNAL_MASK_LAUNCHER_SIZE_BYTES"]),
            "sha256": item["env"]["A08_SIGNAL_MASK_LAUNCHER_SHA256"],
        },
        "launcher_manifest": launcher.get("manifest") == item["env"]["A08_SIGNAL_MASK_MANIFEST"],
        "launcher_python": launcher.get("python38") == {
            "path": item["env"]["A08_PYTHON38_PATH"],
            "size_bytes": int(item["env"]["A08_PYTHON38_SIZE_BYTES"]),
            "sha256": item["env"]["A08_PYTHON38_SHA256"],
        },
        "launcher_bash": launcher.get("delegated_bash") == {
            "path": item["env"]["A08_DELEGATED_BASH_PATH"],
            "size_bytes": int(item["env"]["A08_DELEGATED_BASH_SIZE_BYTES"]),
            "sha256": item["env"]["A08_DELEGATED_BASH_SHA256"],
        },
        "launcher_overlay": launcher.get("frozen_overlay_shell") == {
            "path": item["env"]["A08_OVERLAY_BACKEND_SHELL"],
            "size_bytes": int(item["env"]["A08_OVERLAY_BACKEND_SHELL_SIZE_BYTES"]),
            "sha256": item["env"]["A08_OVERLAY_BACKEND_SHELL_SHA256"],
        },
        "launcher_policy": launcher.get("unblocked_before_overlay_exec") == [1, 2, 15]
            and launcher.get("exec_replaces_launcher_process") is True,
        **{f"bound_input:{label}": passed for label, passed in input_checks.items()},
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {"status": "PASS" if not failures else "FAIL", "checks": checks,
            "failure_codes": failures, "sealed_fd_owner_pid": owner,
            "identity": manifest_identity}


def replay_manifest_audit(path: Path, item: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        require(line.count("=") == 1, f"REPLAY_MANIFEST_LAYOUT:{line_number}")
        key, value = line.split("=", 1)
        require(key and key not in values, f"REPLAY_MANIFEST_KEY:{line_number}:{key}")
        values[key] = value
    guard, _ = stable_json(path.parent / "replay_only_guard_manifest.json")
    owner = guard.get("sealed_fd_owner_pid")
    expected = {
        "play_bag": f"/proc/{owner}/fd/9", "raw_bag": f"/proc/{owner}/fd/7",
        "accepted_feature_bag": item["env"]["FEATURE_BAG_OVERRIDE"],
        "accepted_feature_bag_size_bytes": item["env"]["A08_FEATURE_BAG_SIZE_BYTES"],
        "accepted_feature_bag_sha256": item["env"]["A08_FEATURE_BAG_SHA256"],
        "sealed_play_bag": f"/proc/{owner}/fd/9", "sealed_fd_owner_pid": str(owner),
        "stable_owner_fd_guard": "1", "strict_replay_only_fd_guard": "1",
        "bounded_vins_lifecycle_wrapper_v4": "1", "unblocked_overlay_exec_v4": "1",
        "vins_lifecycle_start_manifest": item["env"]["A08_VINS_LIFECYCLE_START_MANIFEST"],
        "vins_lifecycle_terminal_manifest": item["env"]["A08_VINS_LIFECYCLE_TERMINAL_MANIFEST"],
        "overlay_signal_mask_manifest": item["env"]["A08_SIGNAL_MASK_MANIFEST"],
        "delegated_backend_return_code": "0", "run_dir": item["workspace_link"],
    }
    missing = sorted(set(expected) - set(values))
    conflicts = sorted(k for k, v in expected.items() if k in values and values[k] != v)
    self_fd = sorted(k for k, v in values.items() if v.startswith("/proc/self/fd/"))
    return {
        "status": "PASS" if not missing and not conflicts and not self_fd else "FAIL",
        "missing_keys": missing, "conflicting_keys": conflicts,
        "child_self_fd_value_keys": self_fd,
        "explicit_lineage_conflict": bool(conflicts or self_fd),
        "sealed_fd_owner_pid": owner, "values": values,
    }


def artifact_audit(item: Mapping[str, Any]) -> dict[str, Any]:
    base = BASE_ARTIFACT_AUDIT(item)
    semantic = dict(base.get("semantic_checks", {}))
    issues = list(base.get("issues", []))
    integrity = list(base.get("integrity_issues", []))
    output = Path(item["output_dir"])
    lifecycle = lifecycle_manifest_audit(output, item)
    mask = signal_mask_manifest_audit(output, item)
    semantic["vins_lifecycle"] = lifecycle
    semantic["overlay_signal_mask"] = mask
    if lifecycle.get("status") != "PASS":
        issues.append("VINS_LIFECYCLE_GATE:" + ",".join(lifecycle.get("failure_codes", [])))
        if lifecycle.get("contract_integrity") is not True:
            integrity.append("VINS_LIFECYCLE_MANIFEST_CONTRACT")
    if mask.get("status") != "PASS":
        issues.append("OVERLAY_SIGNAL_MASK_GATE:" + ",".join(mask.get("failure_codes", [])))
        integrity.append("OVERLAY_SIGNAL_MASK_MANIFEST_CONTRACT")
    base.update({
        "status": "PASS" if not issues else "FAIL", "issues": issues,
        "integrity_issues": sorted(set(integrity)), "semantic_checks": semantic,
    })
    return base


def contract_core(
    bindings: Mapping[str, Any], static_identities: Mapping[str, Any],
    host_net: str, host_user: str,
) -> dict[str, Any]:
    prior_r01 = prior_r01_authority(bindings)
    prior_r02 = prior_r02_authority(bindings)
    freeze = collect_analysis_v4_design_freeze_binding()
    items = build_items(bindings, host_net, host_user)
    return {
        "schema_version": LOCK_SCHEMA, "status": LOCK_STATUS,
        "campaign": "A08_KLT_ONLY_REMAINING_R03_R05_SIGNAL_LIFECYCLE_V4",
        "item_order": list(ITEM_ORDER),
        "declared_repeat_outcomes": {
            "KLT_R01": {"disposition": PRIOR_R01_DISPOSITION, "failure_code": R01_FAILURE_CODE,
                        "source_campaign": "v2", "rerun_permitted": False},
            "KLT_R02": {"disposition": PRIOR_R02_DISPOSITION, "failure_code": R02_FAILURE_CODE,
                        "source_campaign": "v3", "rerun_permitted": False},
            **{item: {"disposition": "PREDECLARED_V4_ITEM", "source_campaign": "v4"}
               for item in ITEM_ORDER},
        },
        "policy": {
            "original_declared_repeat_count": 5, "v4_executable_repeat_count": 3,
            "maximum_valid_repeat_count": 3, "single_supervisor_popen_per_item": True,
            "automatic_retry_count": 0, "r01_rerun_or_replacement_permitted": False,
            "r02_rerun_or_replacement_permitted": False,
            "replacement_repeat_permitted": False,
            "terminal_result_failure_does_not_block_later_items": True,
            "execution_integrity_failure_blocks_later_items": True,
            "vins_multiple_thread": 0, "fresh_user_and_network_namespace_per_item": True,
            "strict_stable_owner_fd_replay_only": True,
            "control_signals_unblocked_before_overlay_exec": True,
            "bounded_vins_child_reap": True, "formal_internal_ros_port": ENGINE.FORMAL_PORT,
            "all_five_outcomes_and_valid_count_must_be_reported": True,
        },
        "scientific_boundary": {
            "campaign_result": "KLT_BACKEND_REPEAT_STABILITY_WITH_R01_R02_NA",
            "r01_accuracy": "NA", "r02_accuracy": "NA", "xfeat_accuracy": "NA",
            "learned_frontend_contribution_claim_permitted": False,
            "valid_repeat_summary_rule": "MEDIAN_OVER_VALID_R03_R05_WITH_VALID_COUNT",
        },
        "host_namespace": {"network": host_net, "user": host_user},
        "frontend_authority": bindings, "prior_r01_authority": prior_r01,
        "prior_r02_authority": prior_r02, "analysis_v4_design_freeze": freeze,
        "static_identities": dict(static_identities), "items": items,
    }


def build_lock_payload(
    bindings: Mapping[str, Any], static_identities: Mapping[str, Any],
    host_net: str, host_user: str, created_at_utc: str,
) -> dict[str, Any]:
    payload = {**contract_core(bindings, static_identities, host_net, host_user),
               "created_at_utc": created_at_utc}
    payload["contract_sha256"] = compact_sha256(payload)
    return payload


def expected_lock_from_current_authority(
    bindings: Mapping[str, Any], created: str,
) -> dict[str, Any]:
    return build_lock_payload(bindings, collect_static_identities(),
                              current_namespace("net"), current_namespace("user"), created)


def verify_lock(lock_path: Path, bindings: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    require(lock_path.absolute() == DEFAULT_LOCK.absolute(), "NONCANONICAL_V4_LOCK_PATH")
    lock, lock_identity = stable_json(lock_path)
    created = lock.get("created_at_utc")
    require(isinstance(created, str) and created, "LOCK_CREATED_AT")
    require(lock == expected_lock_from_current_authority(bindings, created),
            "V4_EXECUTION_LOCK_AUTHORITY_DRIFT")
    return lock, lock_identity


def _configure_engine() -> None:
    assignments = {
        "BACKEND_ROOT": BACKEND_ROOT, "RUNTIME_ROOT": RUNTIME_ROOT,
        "PROTOCOL": PROTOCOL, "DEFAULT_LOCK": DEFAULT_LOCK,
        "KLT_RECEIPT": V3.KLT_RECEIPT, "DEFAULT_RECEIPTS": {"klt": V3.KLT_RECEIPT},
        "REPLAY_ONLY_GUARD": REPLAY_ONLY_GUARD, "ITEM_ORDER": ITEM_ORDER,
        "CLAIM_NAME": CLAIM_NAME, "RECEIPT_NAME": RECEIPT_NAME,
        "LOCK_SCHEMA": LOCK_SCHEMA, "RECEIPT_SCHEMA": RECEIPT_SCHEMA,
        "LOCK_STATUS": LOCK_STATUS, "BUILD_LOCK_TOKEN": BUILD_LOCK_TOKEN,
        "AUTHORIZATION_TOKENS": AUTHORIZATION_TOKENS, "EXPECTED_OUTPUTS": EXPECTED_OUTPUTS,
        "arm_spec": arm_spec, "item_environment": item_environment,
        "build_items": build_items, "static_identity_paths": static_identity_paths,
        "collect_static_identities": collect_static_identities,
        "contract_core": contract_core, "build_lock_payload": build_lock_payload,
        "expected_lock_from_current_authority": expected_lock_from_current_authority,
        "verify_lock": verify_lock, "resolve_frontend_bindings": resolve_frontend_bindings,
        "require_campaign_unstarted": require_campaign_unstarted,
        "replay_guard_manifest_audit": replay_guard_manifest_audit,
        "replay_manifest_audit": replay_manifest_audit,
        "artifact_audit": artifact_audit, "prior_receipt": prior_receipt,
    }
    for name, value in assignments.items():
        setattr(ENGINE, name, value)


def prior_receipt(lock_identity: Mapping[str, Any], item: Mapping[str, Any]) -> dict[str, Any]:
    _configure_engine()
    receipt = BASE_PRIOR_RECEIPT(lock_identity, item)
    semantic = receipt["artifact_contract"]["semantic_checks"]
    lifecycle = semantic.get("vins_lifecycle")
    mask = semantic.get("overlay_signal_mask")
    require(isinstance(lifecycle, dict) and lifecycle.get("contract_integrity") is True,
            f"PRIOR_VINS_LIFECYCLE_CONTRACT:{item['item_id']}")
    require(isinstance(mask, dict) and mask.get("status") == "PASS",
            f"PRIOR_OVERLAY_SIGNAL_MASK:{item['item_id']}")
    guard, _ = stable_json(Path(item["output_dir"]) / "replay_only_guard_manifest.json")
    runtime = receipt.get("runtime", {})
    require(guard.get("sealed_fd_owner_pid") == runtime.get("pid"),
            f"PRIOR_STABLE_OWNER_PID:{item['item_id']}")
    require(lifecycle.get("wrapper_parent_pid") == mask.get("launcher_overlay_pid"),
            f"PRIOR_WRAPPER_DIRECT_OVERLAY_CHILD:{item['item_id']}")
    require(mask.get("stable_fd_owner_parent_pid") == runtime.get("pid"),
            f"PRIOR_LAUNCHER_DIRECT_GUARD_CHILD:{item['item_id']}")
    return receipt


def inspect_item_readonly(item_id: str) -> dict[str, Any]:
    _configure_engine()
    return ENGINE.inspect_item_readonly(item_id)


def preflight_readonly(lock_path: Path = DEFAULT_LOCK) -> dict[str, Any]:
    try:
        require(lock_path.absolute() == DEFAULT_LOCK.absolute(),
                "NONCANONICAL_V4_LOCK_PATH")
        bindings = resolve_frontend_bindings()
        r01 = prior_r01_authority(bindings)
        r02 = prior_r02_authority(bindings)
        if not lock_path.exists() and not lock_path.is_symlink():
            if not ANALYSIS_V4_DESIGN_FREEZE.exists() and not ANALYSIS_V4_DESIGN_FREEZE.is_symlink():
                return {
                    "status": "WAITING_ANALYSIS_V4_STATIC_DESIGN_FREEZE", "read_only": True,
                    "prior_r01_authority": r01, "prior_r02_authority": r02,
                    "analysis_v4_design_freeze": str(ANALYSIS_V4_DESIGN_FREEZE),
                    "backend_lock_build_permitted": False,
                    "backend_item_launch_permitted": False,
                    "lock_path": str(lock_path.absolute()), "lock_present": False,
                    "item_order": list(ITEM_ORDER),
                }
            freeze = collect_analysis_v4_design_freeze_binding()
            require_campaign_unstarted()
            core = contract_core(bindings, collect_static_identities(),
                                 current_namespace("net"), current_namespace("user"))
            return {
                "status": "READY_TO_BUILD_KLT_ONLY_REMAINING_V4_EXECUTION_LOCK",
                "read_only": True, "prior_r01_authority": r01,
                "prior_r02_authority": r02, "analysis_v4_design_freeze": freeze,
                "candidate_core_sha256": compact_sha256(core),
                "lock_path": str(lock_path.absolute()), "lock_present": False,
                "item_order": list(ITEM_ORDER),
            }
        lock, lock_identity = verify_lock(lock_path, bindings)
        return {
            "status": "PASS_LOCKED_READY_FOR_AUTHORIZED_REMAINING_KLT_ITEM",
            "read_only": True, "prior_r01_authority": r01,
            "prior_r02_authority": r02, "lock": lock_identity,
            "contract_sha256": lock["contract_sha256"], "item_order": list(ITEM_ORDER),
        }
    except (BackendProtocolError, OSError, ValueError, RuntimeError) as error:
        return {"status": "BLOCKED_PREFLIGHT", "read_only": True,
                "error": f"{type(error).__name__}:{error}",
                "lock_path": str(lock_path.absolute()), "item_order": list(ITEM_ORDER)}


def audit_readonly(lock_path: Path = DEFAULT_LOCK) -> dict[str, Any]:
    preflight = preflight_readonly(lock_path)
    lock_present = lock_path.exists() or lock_path.is_symlink()
    verified_lock: Optional[dict[str, Any]] = None
    verified_identity: Optional[dict[str, Any]] = None
    lock_audit: dict[str, Any] = {"path": str(lock_path.absolute()),
                                  "state": "PRESENT" if lock_present else "ABSENT"}
    if lock_present:
        try:
            verified_lock, verified_identity = verify_lock(lock_path, resolve_frontend_bindings())
            lock_audit.update({"authority": "PASS", "identity": verified_identity})
        except (BackendProtocolError, OSError, ValueError, RuntimeError) as error:
            lock_audit.update({"authority": "FAIL", "error": f"{type(error).__name__}:{error}"})
    else:
        lock_audit["authority"] = "NOT_CHECKED_LOCK_ABSENT"
    rows = [inspect_item_readonly(item) for item in ITEM_ORDER]
    if verified_lock is not None and verified_identity is not None:
        for row in rows:
            if row["state"] != "TERMINAL_RECEIPT":
                continue
            try:
                prior_receipt(verified_identity, verified_lock["items"][row["item_id"]])
                row["deep_terminal_evidence_audit"] = "PASS"
            except (BackendProtocolError, OSError, ValueError) as error:
                row.update({"state": "INVALID_TERMINAL_EVIDENCE",
                            "deep_terminal_evidence_audit": "FAIL",
                            "error": f"{type(error).__name__}:{error}"})
    next_item: Optional[str] = None
    blocked_by: Optional[str] = None
    for row in rows:
        if row["state"] == "TERMINAL_RECEIPT" and row.get("integrity") == "PASS":
            continue
        if row["state"] == "NOT_STARTED":
            next_item = row["item_id"]
        else:
            blocked_by = row["item_id"]
        break
    if lock_audit.get("authority") != "PASS" or blocked_by:
        next_item = None
    return {"status": "READ_ONLY_AUDIT", "read_only": True,
            "preflight": preflight, "lock": lock_audit, "item_order": list(ITEM_ORDER),
            "items": rows, "next_item_if_lock_and_authorization_pass": next_item,
            "blocked_by_integrity_or_incomplete_item": blocked_by,
            "r01_rerun_permitted": False, "r02_rerun_permitted": False,
            "maximum_valid_repeat_count": 3}


def execute_item(lock_path: Path, item_id: str, authorization_token: str) -> tuple[int, dict[str, Any]]:
    require(lock_path.absolute() == DEFAULT_LOCK.absolute(), "NONCANONICAL_V4_LOCK_PATH")
    require(item_id in ITEM_ORDER, f"ITEM_ID:{item_id}")
    require(authorization_token == AUTHORIZATION_TOKENS[item_id], "AUTHORIZATION_TOKEN")
    _configure_engine()
    return ENGINE.execute_item(lock_path, item_id, authorization_token)


def build_lock(lock_path: Path, authorization_token: str) -> dict[str, Any]:
    require(lock_path.absolute() == DEFAULT_LOCK.absolute(), "NONCANONICAL_V4_LOCK_PATH")
    require(authorization_token == BUILD_LOCK_TOKEN, "BUILD_LOCK_AUTHORIZATION_TOKEN")
    require(not lock_path.exists() and not lock_path.is_symlink(), "LOCK_ALREADY_EXISTS")
    bindings = resolve_frontend_bindings()
    prior_r01_authority(bindings); prior_r02_authority(bindings)
    collect_analysis_v4_design_freeze_binding(); require_campaign_unstarted()
    payload = expected_lock_from_current_authority(
        bindings, datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    ENGINE.safety_module().atomic_publish(
        lock_path, payload, propagate_interruption_after_commit=True
    )
    return {"status": "KLT_ONLY_REMAINING_V4_EXECUTION_LOCK_PUBLISHED",
            "lock": identity(lock_path)}


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight"); commands.add_parser("audit")
    build = commands.add_parser("build-lock")
    build.add_argument("--authorization-token", required=True)
    run = commands.add_parser("run-item")
    run.add_argument("item_id", choices=ITEM_ORDER)
    run.add_argument("--authorization-token", required=True)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv); lock_path = args.lock.absolute()
    if args.command == "preflight":
        result = preflight_readonly(lock_path)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0 if result["status"].startswith(("PASS_", "READY_", "WAITING_")) else 2
    if args.command == "audit":
        print(json.dumps(audit_readonly(lock_path), indent=2, sort_keys=True,
                         ensure_ascii=False)); return 0
    try:
        if args.command == "build-lock":
            result = build_lock(lock_path, args.authorization_token); code = 0
        else:
            code, result = execute_item(lock_path, args.item_id, args.authorization_token)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False)); return code
    except (OSError, ValueError, RuntimeError) as error:
        print(f"A08_KLT_ONLY_REMAINING_V4_ERROR:{type(error).__name__}:{error}",
              file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
