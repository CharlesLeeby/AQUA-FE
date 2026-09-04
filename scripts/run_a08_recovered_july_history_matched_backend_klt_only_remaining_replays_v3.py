#!/usr/bin/env python3
"""Additive A08 KLT R02--R05 supervisor after the v2 R01 FD-scope failure.

Importing this module is inert.  ``preflight`` and ``audit`` are read-only.
No v3 lock can be built until the sole v2 R01 launch reaches a deeply audited
terminal infrastructure-failure receipt, and R01 is never rerun or replaced.
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
import stat
import sys
from types import ModuleType
from typing import Any, Mapping, Optional, Sequence


WORKSPACE = Path("/home/ma/AQUA-FE_WS")
EXPERIMENT = Path("/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1")
OVERLAY = EXPERIMENT / "recovered_july_core_overlay_v1"
OVERLAY_RUN_ROOT = OVERLAY / "logs/aqualoc_archaeo_vins"
FRONTEND_ROOT = EXPERIMENT / "frontends_v1"
BACKEND_ROOT = EXPERIMENT / "backend_klt_only_remaining_replays_v3"
RUNTIME_ROOT = EXPERIMENT / "runtime/backend_klt_only_remaining_replays_v3"

PROTOCOL = WORKSPACE / (
    "papers/a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v3_protocol.md"
)
DEFAULT_LOCK = WORKSPACE / (
    "papers/a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v3_execution_lock.json"
)
RUNNER = WORKSPACE / (
    "scripts/run_a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v3.py"
)
REPLAY_ONLY_GUARD = WORKSPACE / (
    "scripts/run_a08_recovered_july_history_matched_backend_klt_only_"
    "replay_guard_v3.sh"
)
PROCESS_FREE_TESTS = WORKSPACE / (
    "scripts/tests/test_run_a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v3.py"
)
ANALYSIS_V3_DESIGN_FREEZE = WORKSPACE / (
    "papers/a08_hfnet_vs_klt_only_common_support_v3_design_freeze.json"
)
ANALYSIS_V3_DESIGN_FREEZE_SCHEMA = (
    "aqua-fe-a08-hfnet-vs-klt-only-common-support-design-freeze-v3"
)
ANALYSIS_V3_DESIGN_FREEZE_STATUS = (
    "FROZEN_AFTER_R01_INFRASTRUCTURE_FAILURE_BEFORE_R02_R05_BACKEND_AND_ACCURACY"
)

V2_RUNNER = WORKSPACE / (
    "scripts/run_a08_recovered_july_history_matched_backend_klt_only_replays_v2.py"
)
V2_PROTOCOL = WORKSPACE / (
    "papers/a08_recovered_july_history_matched_backend_klt_only_replays_v2_protocol.md"
)
V2_GUARD = WORKSPACE / (
    "scripts/run_a08_recovered_july_history_matched_backend_klt_only_replay_guard_v2.sh"
)
V2_LOCK = WORKSPACE / (
    "papers/a08_recovered_july_history_matched_backend_klt_only_replays_v2_"
    "execution_lock.json"
)

ROS_ENTRY = Path("/opt/ros/noetic/bin/rosbag")
ROS_DISPATCH = Path("/opt/ros/noetic/lib/python3/dist-packages/rosbag/rosbag_main.py")
ROS_CPP_PLAYER = Path("/opt/ros/noetic/lib/rosbag/play")

FROZEN_V2_AND_ROS_EXPECTED = {
    "v2_runner": (
        39_763,
        "f0285508a405f912238640e29d2245709caec32f3c8dc5cd2073ea4ec0835d77",
    ),
    "v2_protocol": (
        6_637,
        "ff70e97da324a699c7ca6c09848dd67b8f7e1932b09a3a72942f155d70ac1d03",
    ),
    "v2_guard": (
        3_480,
        "44eabeeb78d18d3038f0e9b2353c5bed9c7c58dc77af37c02741eea0080581a4",
    ),
    "v2_execution_lock": (
        90_258,
        "46e77bf9c812f875e8184d1d9af251fff5097b6bbc9461fff187e408b6b96a3a",
    ),
    "rosbag_python_entry": (
        1_658,
        "aed85a376f4dafeebe8257846315cb838d605fa67788530e95f86ff36aac67f5",
    ),
    "rosbag_python_dispatch": (
        48_875,
        "d9934f6683c355de80457cc69faeff6222b22fbd62d79f4b7c9c3650a5964b60",
    ),
    "rosbag_cpp_player": (
        231_824,
        "81942d60da87577c26e0373dafd7875c261e00e275da7fa3a216bf77c4bb7e3b",
    ),
}

R01_TERMINAL_EXPECTED = {
    "receipt": (
        9_999,
        "92bbcaa486eb353a43db6d9aa772d7022a2e2440794188181909a1f65a55848b",
    ),
    "supervisor_log": (
        483,
        "9cbb4da084c563b1a4020cd65a5ac1950518d41a304d524d899d41a1103e2ef8",
    ),
    "empty_vio": (
        0,
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ),
    "empty_ape": (
        0,
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ),
}


def _load_v2() -> ModuleType:
    runner = V2_RUNNER.absolute()
    if (
        not runner.exists()
        or runner.is_symlink()
        or not stat.S_ISREG(runner.lstat().st_mode)
        or runner.resolve(strict=True) != runner
    ):
        raise RuntimeError("V2_RUNNER_NOT_FROZEN_REGULAR_FILE")
    raw = runner.read_bytes()
    observed = (len(raw), hashlib.sha256(raw).hexdigest())
    if observed != FROZEN_V2_AND_ROS_EXPECTED["v2_runner"]:
        raise RuntimeError("V2_RUNNER_BOOTSTRAP_IDENTITY_DRIFT")
    specification = importlib.util.spec_from_file_location(
        "a08_klt_only_v2_authority_for_remaining_v3", runner
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("V2_RUNNER_IMPORT_SPEC")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


V2 = _load_v2()
ENGINE = V2.ENGINE
BackendProtocolError = ENGINE.BackendProtocolError
require = ENGINE.require
identity = ENGINE.identity
stable_json = ENGINE.stable_json
compact_sha256 = ENGINE.compact_sha256
current_namespace = ENGINE.current_namespace
BASE_REPLAY_GUARD_MANIFEST_AUDIT = ENGINE.replay_guard_manifest_audit
BASE_REPLAY_MANIFEST_AUDIT = ENGINE.replay_manifest_audit
BASE_PRIOR_RECEIPT = ENGINE.prior_receipt

KLT_RECEIPT = V2.KLT_RECEIPT
ITEM_ORDER = ("KLT_R02", "KLT_R03", "KLT_R04", "KLT_R05")
CLAIM_NAME = "process_start_claim_v1.json"
RECEIPT_NAME = "formal_run_receipt_v3.json"
LOCK_SCHEMA = "aqua-fe-a08-recovered-july-backend-klt-only-remaining-lock-v3"
RECEIPT_SCHEMA = "aqua-fe-a08-recovered-july-backend-klt-only-remaining-receipt-v3"
LOCK_STATUS = "FROZEN_REMAINING_R02_R05_AFTER_R01_INFRA_FAILURE_BEFORE_LAUNCH"
BUILD_LOCK_TOKEN = (
    "A08_BUILD_KLT_ONLY_REMAINING_BACKEND_REPLAYS_V3_LOCK_AFTER_R01_INFRA_FAILURE"
)
AUTHORIZATION_TOKENS = {
    item: f"A08_KLT_ONLY_REMAINING_BACKEND_REPLAYS_V3_RUN_{item}_EXACTLY_ONCE"
    for item in ITEM_ORDER
}
PRIOR_R01_DISPOSITION = (
    "NA_BACKEND_INFRASTRUCTURE_FD_INHERITANCE_FAILURE_"
    "NO_REPLAY_NO_REPLACEMENT"
)
R01_INFRASTRUCTURE_FAILURE_CODE = (
    "ROSBAG_PYTHON_SUBPROCESS_CLOSE_FDS_DROPPED_SEALED_FD9"
)


def _identity_tuple(value: Mapping[str, Any]) -> tuple[int, str]:
    return int(value["size_bytes"]), str(value["sha256"])


def resolve_frontend_bindings() -> dict[str, Any]:
    """Reuse the exact frozen v2 KLT acceptance and XFeat exclusion audit."""
    return V2.resolve_frontend_bindings()


def arm_spec(item_id: str) -> dict[str, Any]:
    require(item_id in ITEM_ORDER, f"ITEM_ID:{item_id}")
    repeat = int(item_id[-2:])
    tag = f"a08_recoveredjuly_hist0000_4660_backend_klt_only_r{repeat:02d}_v3"
    return {
        "arm": "klt",
        "repeat_index": repeat,
        "method": "klt",
        "tag": tag,
        "run_leaf": f"external_klt_every2_{tag}",
    }


def item_environment(item_id: str, bindings: Mapping[str, Any]) -> dict[str, str]:
    spec = arm_spec(item_id)
    accepted = bindings["klt"]
    environment = dict(ENGINE.BASE_ENVIRONMENT)
    environment.update(ENGINE.COMMON_BACKEND_ENVIRONMENT)
    environment.update({
        "TAG": spec["tag"],
        "ROS_HOME": str(RUNTIME_ROOT / item_id / "ros_home"),
        "ROS_LOG_DIR": str(RUNTIME_ROOT / item_id / "ros_log"),
        "FEATURE_BAG_OVERRIDE": str(accepted["features_bag"]["path"]),
        "A08_FEATURE_BAG_SIZE_BYTES": str(accepted["features_bag"]["size_bytes"]),
        "A08_FEATURE_BAG_SHA256": str(accepted["features_bag"]["sha256"]),
        "A08_FRONTEND_METRICS": str(accepted["frontend_metrics"]["path"]),
        "A08_FRONTEND_METRICS_SIZE_BYTES": str(
            accepted["frontend_metrics"]["size_bytes"]
        ),
        "A08_FRONTEND_METRICS_SHA256": str(
            accepted["frontend_metrics"]["sha256"]
        ),
        "A08_FRONTEND_CAMERA_CONFIG": str(accepted["camera_config"]["path"]),
        "A08_FRONTEND_CAMERA_SIZE_BYTES": str(accepted["camera_config"]["size_bytes"]),
        "A08_FRONTEND_CAMERA_SHA256": str(accepted["camera_config"]["sha256"]),
        "A08_RAW_BAG_SIZE_BYTES": str(ENGINE.RAW_BAG_EXPECTED[0]),
        "A08_RAW_BAG_SHA256": ENGINE.RAW_BAG_EXPECTED[1],
        "A08_RAW_TAR_SIZE_BYTES": str(ENGINE.SOURCE_ARCHIVE_EXPECTED[0]),
        "A08_RAW_TAR_SHA256": ENGINE.SOURCE_ARCHIVE_EXPECTED[1],
        "A08_GT_SIZE_BYTES": str(ENGINE.GROUND_TRUTH_EXPECTED[0]),
        "A08_GT_SHA256": ENGINE.GROUND_TRUTH_EXPECTED[1],
        "A08_ITEM_OUTPUT_DIR": str(BACKEND_ROOT / item_id),
        "A08_ITEM_ID": item_id,
        "A08_WORKSPACE_LINK": str(OVERLAY_RUN_ROOT / spec["run_leaf"]),
        "A08_OVERLAY_BACKEND_SHELL": str(ENGINE.BACKEND_SHELL),
        "A08_KLT_ONLY_REMAINING_REPLAYS_V3": "1",
        "A08_ACCEPTED_FRONTEND_RECEIPT": str(accepted["accepted_receipt"]["path"]),
        "A08_PRIOR_R01_DISPOSITION": PRIOR_R01_DISPOSITION,
        "A08_XFEAT_TERMINAL_DISPOSITION": (
            "NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED"
        ),
        "A08_XFEAT_BACKEND_LAUNCHED_COUNT": "0",
        "A08_LEARNING_CONTRIBUTION_CLAIM_PERMITTED": "0",
    })
    return environment


def build_items(
    bindings: Mapping[str, Any], host_net: str, host_user: str,
) -> dict[str, Any]:
    require(re.fullmatch(r"net:\[[0-9]+\]", host_net) is not None, "HOST_NETNS")
    require(re.fullmatch(r"user:\[[0-9]+\]", host_user) is not None, "HOST_USERNS")
    require(set(bindings) == {"klt", "excluded_xfeat"}, "FRONTEND_BINDING_KEYS")
    excluded = bindings["excluded_xfeat"]
    require(
        excluded.get("disposition")
        == "NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED"
        and excluded.get("accepted_receipt_present") is False
        and excluded.get("backend_launched_count") == 0
        and excluded.get("learning_contribution_claim_permitted") is False,
        "EXCLUDED_XFEAT_BOUNDARY",
    )
    result: dict[str, Any] = {}
    for item_id in ITEM_ORDER:
        spec = arm_spec(item_id)
        output_dir = BACKEND_ROOT / item_id
        workspace_link = OVERLAY_RUN_ROOT / spec["run_leaf"]
        inner = [
            str(ENGINE.BASH), str(REPLAY_ONLY_GUARD), "aqualoc_archaeo", "8",
            "0", "4660", "klt", "2",
        ]
        argv = [
            str(ENGINE.UNSHARE), "--user", "--map-root-user", "--net",
            str(ENGINE.PYTHON38), str(ENGINE.NETNS_ENTRY),
            "--output-dir", str(output_dir),
            "--formal-port", str(ENGINE.FORMAL_PORT),
            "--host-network-namespace", host_net,
            "--host-user-namespace", host_user,
            "--", *inner,
        ]
        environment = item_environment(item_id, bindings)
        result[item_id] = {
            "item_id": item_id,
            "arm": "klt",
            "repeat_index": spec["repeat_index"],
            "method": "klt",
            "output_dir": str(output_dir),
            "workspace_link": str(workspace_link),
            "argv": argv,
            "inner_backend_argv_sha256": compact_sha256(inner),
            "host_network_namespace": host_net,
            "host_user_namespace": host_user,
            "env": environment,
            "cwd": str(OVERLAY),
            "timeout_seconds": ENGINE.TIMEOUT_SECONDS,
            "expected_outputs": list(ENGINE.EXPECTED_OUTPUTS),
            "input_binding": bindings["klt"],
            "excluded_xfeat_sha256": compact_sha256(excluded),
            "prior_r01_disposition": PRIOR_R01_DISPOSITION,
            "scientific_boundary": {
                "repeat_r01": PRIOR_R01_DISPOSITION,
                "maximum_valid_repeat_count": 4,
                "xfeat_accuracy": "NA",
                "learned_contribution_claim_permitted": False,
            },
            "command_sha256": compact_sha256({"argv": argv, "env": environment}),
        }
    return result


def static_identity_paths() -> dict[str, Path]:
    inherited = dict(V2.static_identity_paths())
    paths = dict(inherited)
    paths["v2_runner"] = paths.pop("runner")
    paths["v2_protocol"] = paths.pop("protocol")
    paths["v2_guard"] = paths.pop("klt_only_replay_guard_v2")
    paths.update({
        "v2_execution_lock": V2_LOCK,
        "rosbag_python_entry": ROS_ENTRY,
        "rosbag_python_dispatch": ROS_DISPATCH,
        "rosbag_cpp_player": ROS_CPP_PLAYER,
        "runner": RUNNER,
        "protocol": PROTOCOL,
        "stable_owner_replay_guard_v3": REPLAY_ONLY_GUARD,
        "process_free_tests": PROCESS_FREE_TESTS,
    })
    return paths


def collect_static_identities() -> dict[str, Any]:
    # First re-run every frozen v2 bootstrap check without changing it.
    V2.collect_static_identities()
    values = {name: identity(path) for name, path in static_identity_paths().items()}
    for label, expected in FROZEN_V2_AND_ROS_EXPECTED.items():
        require(_identity_tuple(values[label]) == expected, f"STATIC_IDENTITY:{label}")
    return values


def collect_analysis_v3_design_freeze_binding() -> dict[str, Any]:
    """Audit the additive analysis freeze without hard-coding its own digest."""
    value, freeze_identity = stable_json(ANALYSIS_V3_DESIGN_FREEZE)
    require(
        value.get("schema_version") == ANALYSIS_V3_DESIGN_FREEZE_SCHEMA,
        "ANALYSIS_V3_DESIGN_FREEZE_SCHEMA",
    )
    require(
        value.get("status") == ANALYSIS_V3_DESIGN_FREEZE_STATUS,
        "ANALYSIS_V3_DESIGN_FREEZE_STATUS",
    )
    digest = value.get("freeze_sha256")
    unsigned = dict(value)
    unsigned.pop("freeze_sha256", None)
    require(digest == compact_sha256(unsigned), "ANALYSIS_V3_DESIGN_FREEZE_DIGEST")

    frozen_static = value.get("static_identities")
    require(isinstance(frozen_static, dict), "ANALYSIS_V3_STATIC_IDENTITIES")
    required_current = {
        "backend_v3_protocol": identity(PROTOCOL),
        "backend_v3_runner": identity(RUNNER),
        "backend_v3_guard": identity(REPLAY_ONLY_GUARD),
        "backend_v3_process_free_tests": identity(PROCESS_FREE_TESTS),
        "v2_r01_terminal_receipt": identity(
            V2.BACKEND_ROOT / "KLT_R01" / V2.RECEIPT_NAME
        ),
        "v2_execution_lock": identity(V2_LOCK),
    }
    require(
        all(frozen_static.get(key) == expected for key, expected in required_current.items()),
        "ANALYSIS_V3_STATIC_BACKEND_BINDINGS",
    )

    prior = value.get("prior_r01")
    require(
        isinstance(prior, dict)
        and prior.get("disposition") == PRIOR_R01_DISPOSITION
        and prior.get("failure_code") == R01_INFRASTRUCTURE_FAILURE_CODE
        and prior.get("receipt") == required_current["v2_r01_terminal_receipt"]
        and prior.get("v2_execution_lock") == required_current["v2_execution_lock"]
        and prior.get("v2_deep_terminal_evidence_audit") == "PASS"
        and prior.get("vio_empty") is True
        and prior.get("ape_empty") is True
        and prior.get("artifact_accepted") is False
        and prior.get("rerun_or_replacement_permitted") is False,
        "ANALYSIS_V3_PRIOR_R01_BOUNDARY",
    )
    contract = value.get("design_contract")
    population = (
        contract.get("population_and_failure_rules")
        if isinstance(contract, dict) else None
    )
    require(
        isinstance(population, dict)
        and population.get("backend_item_order")
        == ["KLT_R01", "KLT_R02", "KLT_R03", "KLT_R04", "KLT_R05"]
        and population.get("v3_backend_item_order") == list(ITEM_ORDER)
        and population.get("klt_planned_count") == 5
        and population.get("maximum_valid_klt_count") == 4
        and population.get("r01_disposition") == PRIOR_R01_DISPOSITION
        and population.get("r01_counts_as_valid") is False
        and population.get("r01_rerun_or_replacement_permitted") is False,
        "ANALYSIS_V3_PLANNED_POPULATION",
    )
    boundary = value.get("claim_boundary")
    require(
        isinstance(boundary, dict)
        and boundary.get("backend_v3_execution_lock_built") is False
        and boundary.get("v3_backend_items_started") == 0
        and boundary.get("ape_or_rpe_computed") is False
        and boundary.get("ros_or_vins_started_for_v3") is False,
        "ANALYSIS_V3_PREBACKEND_BOUNDARY",
    )
    return {
        "identity": freeze_identity,
        "schema_version": value["schema_version"],
        "status": value["status"],
        "freeze_sha256": digest,
        "required_static_identities": required_current,
        "prior_r01": prior,
        "population_and_failure_rules": population,
        "claim_boundary": boundary,
    }


def v2_remaining_items_unstarted(v2_lock: Mapping[str, Any]) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for item_id in ITEM_ORDER:
        item = v2_lock["items"][item_id]
        paths = {
            "output": Path(item["output_dir"]),
            "workspace": Path(item["workspace_link"]),
            "runtime": V2.RUNTIME_ROOT / item_id,
        }
        for label, path in paths.items():
            require(
                not path.exists() and not path.is_symlink(),
                f"V2_REMAINING_ITEM_TOUCHED:{item_id}:{label}",
            )
        rows[item_id] = {label: str(path) for label, path in paths.items()}
    return {
        "status": "PASS_V2_R02_R05_ALL_UNSTARTED",
        "items": rows,
    }


def prior_r01_authority(bindings: Mapping[str, Any]) -> dict[str, Any]:
    """Bind the natural v2 R01 terminal receipt; always restore v3 globals."""
    v2_lock, v2_lock_identity = V2.verify_lock(V2_LOCK, bindings)
    require(v2_lock.get("item_order") == list(V2.ITEM_ORDER), "V2_ITEM_ORDER")
    item = v2_lock["items"]["KLT_R01"]
    receipt_path = Path(item["output_dir"]) / V2.RECEIPT_NAME
    require(receipt_path.exists() and not receipt_path.is_symlink(),
            "V2_R01_TERMINAL_RECEIPT_ABSENT")
    receipt_identity = identity(receipt_path)
    require(
        _identity_tuple(receipt_identity) == R01_TERMINAL_EXPECTED["receipt"],
        "V2_R01_TERMINAL_RECEIPT_IDENTITY",
    )
    try:
        # V2 predates the additive v3 audit overrides and therefore expects the
        # exact inherited v1 /proc/self manifest semantics for its consumed R01.
        ENGINE.replay_guard_manifest_audit = BASE_REPLAY_GUARD_MANIFEST_AUDIT
        ENGINE.replay_manifest_audit = BASE_REPLAY_MANIFEST_AUDIT
        ENGINE.prior_receipt = BASE_PRIOR_RECEIPT
        receipt = V2.prior_receipt(v2_lock_identity, item)
    finally:
        # V2's reviewed adapter temporarily rebinds the shared v1 engine.
        _configure_engine()
    require(
        receipt.get("status") == "FAILED_BACKEND_REPLAY_NO_REPLACEMENT",
        "V2_R01_NOT_TERMINAL_FAILURE",
    )
    integrity = receipt.get("execution_integrity")
    require(
        isinstance(integrity, dict)
        and integrity.get("status") == "PASS"
        and integrity.get("irreversible_fault_latch_clear") is True,
        "V2_R01_EXECUTION_INTEGRITY",
    )
    require(
        receipt.get("retry_count") == 0
        and receipt.get("replacement_permitted") is False
        and receipt.get("launch_allowance_consumed") is True,
        "V2_R01_NO_RETRY_NO_REPLACEMENT",
    )
    artifact = receipt.get("artifact_contract")
    require(
        isinstance(artifact, dict) and artifact.get("status") == "FAIL",
        "V2_R01_UNEXPECTED_ACCEPTED_ARTIFACT",
    )
    log_claim = receipt.get("process_log")
    require(isinstance(log_claim, dict), "V2_R01_PROCESS_LOG_CLAIM")
    log_path = Path(str(log_claim.get("path", "")))
    before = identity(log_path)
    require(before == log_claim, "V2_R01_PROCESS_LOG_IDENTITY")
    require(
        _identity_tuple(before) == R01_TERMINAL_EXPECTED["supervisor_log"],
        "V2_R01_PROCESS_LOG_EXPECTED_IDENTITY",
    )
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    require(identity(log_path) == before, "V2_R01_PROCESS_LOG_CHANGED_DURING_READ")
    require(
        "Opening /proc/self/fd/9" in log_text
        and "Error opening file: /proc/self/fd/9" in log_text,
        "V2_R01_FD_SCOPE_FAILURE_SIGNATURE",
    )
    outputs = artifact.get("outputs")
    vio_claim = outputs.get("vins_output/vio.csv") if isinstance(outputs, dict) else None
    require(isinstance(vio_claim, dict), "V2_R01_VIO_CLAIM")
    vio_path = Path(str(vio_claim.get("path", "")))
    vio_identity = identity(vio_path)
    require(
        vio_identity == vio_claim
        and _identity_tuple(vio_identity) == R01_TERMINAL_EXPECTED["empty_vio"],
        "V2_R01_VIO_NOT_EXACTLY_EMPTY",
    )
    ape_claim = outputs.get("ape.txt") if isinstance(outputs, dict) else None
    require(isinstance(ape_claim, dict), "V2_R01_APE_CLAIM")
    ape_path = Path(str(ape_claim.get("path", "")))
    ape_identity = identity(ape_path)
    require(
        ape_identity == ape_claim
        and _identity_tuple(ape_identity) == R01_TERMINAL_EXPECTED["empty_ape"],
        "V2_R01_APE_NOT_EXACTLY_EMPTY",
    )
    issues = artifact.get("issues")
    require(
        isinstance(issues, list)
        and any("trajectory:BackendProtocolError:VIO_EMPTY" == row for row in issues)
        and any(
            isinstance(row, str)
            and row.startswith("backend_usability:BackendProtocolError:APE_KV_MISSING")
            for row in issues
        ),
        "V2_R01_EMPTY_OUTPUTS_NOT_REJECTED",
    )
    later = v2_remaining_items_unstarted(v2_lock)
    return {
        "item_id": "KLT_R01",
        "disposition": PRIOR_R01_DISPOSITION,
        "failure_code": R01_INFRASTRUCTURE_FAILURE_CODE,
        "rerun_permitted": False,
        "replacement_permitted": False,
        "counts_as_valid_repeat": False,
        "v2_execution_lock": v2_lock_identity,
        "v2_terminal_receipt": receipt_identity,
        "v2_process_log": before,
        "v2_empty_vio": vio_identity,
        "v2_empty_ape": ape_identity,
        "v2_claim": receipt["claim"],
        "v2_runtime": receipt["runtime"],
        "failure_signature": {
            "opening_self_fd9_present": True,
            "error_opening_self_fd9_present": True,
            "empty_vio_identity_bound": True,
            "empty_ape_identity_bound": True,
            "artifact_accepted": False,
            "v2_deep_terminal_evidence_audit": "PASS",
            "rosbag_return_code_is_not_an_acceptance_gate": True,
        },
        "execution_integrity": integrity,
        "v2_remaining_items": later,
    }


def require_campaign_unstarted() -> None:
    require(not BACKEND_ROOT.exists() and not BACKEND_ROOT.is_symlink(),
            "V3_OUTPUT_ROOT_ALREADY_TOUCHED")
    require(not RUNTIME_ROOT.exists() and not RUNTIME_ROOT.is_symlink(),
            "V3_RUNTIME_ROOT_ALREADY_TOUCHED")
    for item_id in ITEM_ORDER:
        spec = arm_spec(item_id)
        paths = {
            "output": BACKEND_ROOT / item_id,
            "workspace": OVERLAY_RUN_ROOT / spec["run_leaf"],
            "runtime": RUNTIME_ROOT / item_id,
        }
        for label, path in paths.items():
            require(not path.exists() and not path.is_symlink(),
                    f"V3_ITEM_ALREADY_TOUCHED:{item_id}:{label}")


def contract_core(
    bindings: Mapping[str, Any], static_identities: Mapping[str, Any],
    host_net: str, host_user: str,
) -> dict[str, Any]:
    prior = prior_r01_authority(bindings)
    analysis_freeze = collect_analysis_v3_design_freeze_binding()
    items = build_items(bindings, host_net, host_user)
    return {
        "schema_version": LOCK_SCHEMA,
        "status": LOCK_STATUS,
        "campaign": "A08_KLT_ONLY_REMAINING_R02_R05_STABLE_OWNER_FD_V3",
        "item_order": list(ITEM_ORDER),
        "declared_repeat_outcomes": {
            "KLT_R01": {
                "disposition": PRIOR_R01_DISPOSITION,
                "failure_code": R01_INFRASTRUCTURE_FAILURE_CODE,
                "source_campaign": "v2",
                "rerun_permitted": False,
            },
            **{
                item: {"disposition": "PREDECLARED_V3_ITEM", "source_campaign": "v3"}
                for item in ITEM_ORDER
            },
        },
        "policy": {
            "original_declared_repeat_count": 5,
            "v3_executable_repeat_count": 4,
            "maximum_valid_repeat_count": 4,
            "single_supervisor_popen_per_item": True,
            "automatic_retry_count": 0,
            "r01_rerun_or_replacement_permitted": False,
            "replacement_repeat_permitted": False,
            "terminal_result_failure_does_not_block_later_items": True,
            "execution_integrity_failure_blocks_later_items": True,
            "vins_multiple_thread": 0,
            "fresh_user_and_network_namespace_per_item": True,
            "strict_stable_owner_fd_replay_only": True,
            "formal_internal_ros_port": ENGINE.FORMAL_PORT,
            "all_five_outcomes_and_valid_count_must_be_reported": True,
        },
        "scientific_boundary": {
            "campaign_result": "KLT_BACKEND_REPEAT_STABILITY_WITH_R01_NA",
            "r01_accuracy": "NA",
            "xfeat_accuracy": "NA",
            "learned_frontend_contribution_claim_permitted": False,
            "valid_repeat_summary_rule": "MEDIAN_OVER_VALID_R02_R05_WITH_VALID_COUNT",
        },
        "host_namespace": {"network": host_net, "user": host_user},
        "frontend_authority": bindings,
        "prior_r01_authority": prior,
        "analysis_v3_design_freeze": analysis_freeze,
        "original_5_plus_5_diversion_gate": V2.original_campaign_diversion_gate(),
        "static_identities": dict(static_identities),
        "items": items,
    }


def build_lock_payload(
    bindings: Mapping[str, Any], static_identities: Mapping[str, Any],
    host_net: str, host_user: str, created_at_utc: str,
) -> dict[str, Any]:
    core = contract_core(bindings, static_identities, host_net, host_user)
    payload = {**core, "created_at_utc": created_at_utc}
    payload["contract_sha256"] = compact_sha256(payload)
    return payload


def expected_lock_from_current_authority(
    bindings: Mapping[str, Any], created: str,
) -> dict[str, Any]:
    return build_lock_payload(
        bindings, collect_static_identities(), current_namespace("net"),
        current_namespace("user"), created,
    )


def verify_lock(
    lock_path: Path, bindings: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    lock, lock_identity = stable_json(lock_path)
    created = lock.get("created_at_utc")
    require(isinstance(created, str) and created, "LOCK_CREATED_AT")
    expected = expected_lock_from_current_authority(bindings, created)
    require(lock == expected, "V3_EXECUTION_LOCK_AUTHORITY_DRIFT")
    require(
        lock["prior_r01_authority"]["disposition"] == PRIOR_R01_DISPOSITION
        and lock["prior_r01_authority"]["rerun_permitted"] is False
        and lock["prior_r01_authority"]["counts_as_valid_repeat"] is False,
        "LOCK_PRIOR_R01_BOUNDARY",
    )
    return lock, lock_identity


def replay_guard_manifest_audit(path: Path, item: Mapping[str, Any]) -> dict[str, Any]:
    value, manifest_identity = stable_json(path)
    owner = value.get("sealed_fd_owner_pid")
    owner_valid = isinstance(owner, int) and not isinstance(owner, bool) and owner > 1
    expected_inputs = {
        "ground_truth": (
            item["env"]["GT_TXT"], int(item["env"]["A08_GT_SIZE_BYTES"]),
            item["env"]["A08_GT_SHA256"], 6,
        ),
        "raw_bag": (
            item["env"]["RAW_BAG"], int(item["env"]["A08_RAW_BAG_SIZE_BYTES"]),
            item["env"]["A08_RAW_BAG_SHA256"], 7,
        ),
        "raw_archive": (
            item["env"]["RAW_TAR"], int(item["env"]["A08_RAW_TAR_SIZE_BYTES"]),
            item["env"]["A08_RAW_TAR_SHA256"], 8,
        ),
        "feature_bag": (
            item["env"]["FEATURE_BAG_OVERRIDE"],
            int(item["env"]["A08_FEATURE_BAG_SIZE_BYTES"]),
            item["env"]["A08_FEATURE_BAG_SHA256"], 9,
        ),
        "frontend_metrics": (
            item["env"]["A08_FRONTEND_METRICS"],
            int(item["env"]["A08_FRONTEND_METRICS_SIZE_BYTES"]),
            item["env"]["A08_FRONTEND_METRICS_SHA256"], 10,
        ),
        "camera_config": (
            item["env"]["A08_FRONTEND_CAMERA_CONFIG"],
            int(item["env"]["A08_FRONTEND_CAMERA_SIZE_BYTES"]),
            item["env"]["A08_FRONTEND_CAMERA_SHA256"], 11,
        ),
    }
    observed_inputs = value.get("bound_inputs")
    input_checks: dict[str, bool] = {}
    for label, expected in expected_inputs.items():
        row = observed_inputs.get(label) if isinstance(observed_inputs, dict) else None
        expected_path = f"/proc/{owner}/fd/{expected[3]}" if owner_valid else None
        input_checks[label] = bool(
            isinstance(row, dict)
            and row.get("accepted_path") == expected[0]
            and row.get("size_bytes") == expected[1]
            and row.get("sha256") == expected[2]
            and row.get("sealed_fd") == expected[3]
            and row.get("sealed_fd_owner_pid") == owner
            and row.get("sealed_path") == expected_path
            and row.get("stable_owner_path_verified_before_delegate") is True
            and isinstance(row.get("device"), int)
            and isinstance(row.get("inode"), int)
        )
    checks = {
        "schema": value.get("schema_version")
        == "aqua-fe-a08-replay-only-stable-owner-fd-guard-v3",
        "status": value.get("status") == "PASS_BEFORE_DELEGATED_BACKEND",
        "item_id": value.get("item_id") == item["item_id"],
        "output_dir": value.get("output_dir") == item["output_dir"],
        "workspace_link": value.get("workspace_link") == item["workspace_link"],
        "delegated_shell": value.get("delegated_backend_shell") == str(ENGINE.BACKEND_SHELL),
        "owner_pid": owner_valid,
        "prior_r01": value.get("prior_r01_disposition") == PRIOR_R01_DISPOSITION,
        "history": value.get("history") == {
            "dataset": "aqualoc_archaeo", "sequence": 8,
            "start_source_index": 0, "end_source_index": 4660,
            "every_n": 2, "method": "klt",
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
        },
        **{f"bound_input:{label}": passed for label, passed in input_checks.items()},
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "status": "PASS" if not failures else "FAIL",
        "checks": checks,
        "failure_codes": failures,
        "sealed_fd_owner_pid": owner,
        "identity": manifest_identity,
    }


def replay_manifest_audit(path: Path, item: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, str] = {}
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line:
            continue
        require(line.count("=") == 1, f"REPLAY_MANIFEST_LAYOUT:{line_number}")
        key, value = line.split("=", 1)
        require(key and key not in values, f"REPLAY_MANIFEST_KEY:{line_number}:{key}")
        values[key] = value
    guard, _ = stable_json(path.parent / "replay_only_guard_manifest.json")
    owner = guard.get("sealed_fd_owner_pid")
    owner_text = str(owner) if isinstance(owner, int) and owner > 1 else "INVALID"
    expected = {
        "play_bag": f"/proc/{owner_text}/fd/9",
        "raw_bag": f"/proc/{owner_text}/fd/7",
        "accepted_feature_bag": item["env"]["FEATURE_BAG_OVERRIDE"],
        "accepted_feature_bag_size_bytes": item["env"]["A08_FEATURE_BAG_SIZE_BYTES"],
        "accepted_feature_bag_sha256": item["env"]["A08_FEATURE_BAG_SHA256"],
        "sealed_play_bag": f"/proc/{owner_text}/fd/9",
        "sealed_fd_owner_pid": owner_text,
        "stable_owner_fd_guard": "1",
        "strict_replay_only_fd_guard": "1",
        "run_dir": item["workspace_link"],
    }
    missing = sorted(set(expected) - set(values))
    conflicts = sorted(
        key for key, expected_value in expected.items()
        if key in values and values[key] != expected_value
    )
    self_fd_values = sorted(
        key for key, value in values.items() if value.startswith("/proc/self/fd/")
    )
    return {
        "status": "PASS" if not missing and not conflicts and not self_fd_values else "FAIL",
        "missing_keys": missing,
        "conflicting_keys": conflicts,
        "child_self_fd_value_keys": self_fd_values,
        "explicit_lineage_conflict": bool(conflicts or self_fd_values),
        "sealed_fd_owner_pid": owner,
        "values": values,
    }


def _configure_engine() -> None:
    assignments = {
        "BACKEND_ROOT": BACKEND_ROOT,
        "RUNTIME_ROOT": RUNTIME_ROOT,
        "PROTOCOL": PROTOCOL,
        "DEFAULT_LOCK": DEFAULT_LOCK,
        "KLT_RECEIPT": KLT_RECEIPT,
        "DEFAULT_RECEIPTS": {"klt": KLT_RECEIPT},
        "REPLAY_ONLY_GUARD": REPLAY_ONLY_GUARD,
        "ITEM_ORDER": ITEM_ORDER,
        "CLAIM_NAME": CLAIM_NAME,
        "RECEIPT_NAME": RECEIPT_NAME,
        "LOCK_SCHEMA": LOCK_SCHEMA,
        "RECEIPT_SCHEMA": RECEIPT_SCHEMA,
        "LOCK_STATUS": LOCK_STATUS,
        "BUILD_LOCK_TOKEN": BUILD_LOCK_TOKEN,
        "AUTHORIZATION_TOKENS": AUTHORIZATION_TOKENS,
        "arm_spec": arm_spec,
        "item_environment": item_environment,
        "build_items": build_items,
        "static_identity_paths": static_identity_paths,
        "collect_static_identities": collect_static_identities,
        "contract_core": contract_core,
        "build_lock_payload": build_lock_payload,
        "expected_lock_from_current_authority": expected_lock_from_current_authority,
        "verify_lock": verify_lock,
        "resolve_frontend_bindings": resolve_frontend_bindings,
        "require_campaign_unstarted": require_campaign_unstarted,
        "replay_guard_manifest_audit": replay_guard_manifest_audit,
        "replay_manifest_audit": replay_manifest_audit,
        "prior_receipt": prior_receipt,
    }
    for name, value in assignments.items():
        setattr(ENGINE, name, value)


def inspect_item_readonly(item_id: str) -> dict[str, Any]:
    _configure_engine()
    return ENGINE.inspect_item_readonly(item_id)


def prior_receipt(
    lock_identity: Mapping[str, Any], item: Mapping[str, Any],
) -> dict[str, Any]:
    _configure_engine()
    receipt = BASE_PRIOR_RECEIPT(lock_identity, item)
    guard, _ = stable_json(
        Path(item["output_dir"]) / "replay_only_guard_manifest.json"
    )
    owner = guard.get("sealed_fd_owner_pid")
    runtime = receipt.get("runtime")
    require(
        isinstance(runtime, dict)
        and isinstance(owner, int)
        and owner == runtime.get("pid"),
        f"PRIOR_STABLE_FD_OWNER_NOT_SOLE_POPEN_PID:{item['item_id']}",
    )
    replay = receipt["artifact_contract"]["semantic_checks"].get("replay_manifest")
    require(
        isinstance(replay, dict)
        and replay.get("sealed_fd_owner_pid") == owner
        and replay.get("status") == "PASS",
        f"PRIOR_STABLE_FD_OWNER_REPLAY_BINDING:{item['item_id']}",
    )
    return receipt


def preflight_readonly(lock_path: Path = DEFAULT_LOCK) -> dict[str, Any]:
    presence = V2.authority_presence()
    bad = {
        label: row for label, row in presence.items()
        if row["state"] not in {"PRESENT_REGULAR", "ABSENT_AS_REQUIRED"}
    }
    if bad:
        return {
            "status": "BLOCKED_TERMINAL_DIVERSION_AUTHORITY",
            "read_only": True,
            "authority_presence": presence,
            "invalid": bad,
            "lock_path": str(lock_path.absolute()),
            "item_order": list(ITEM_ORDER),
        }
    v2_r01_receipt = V2.BACKEND_ROOT / "KLT_R01" / V2.RECEIPT_NAME
    if not v2_r01_receipt.exists() and not v2_r01_receipt.is_symlink():
        return {
            "status": "WAITING_V2_R01_NATURAL_TERMINAL_RECEIPT",
            "read_only": True,
            "r01_rerun_or_interruption_permitted": False,
            "v2_r01_receipt": str(v2_r01_receipt),
            "lock_path": str(lock_path.absolute()),
            "lock_present": lock_path.exists() or lock_path.is_symlink(),
            "item_order": list(ITEM_ORDER),
        }
    try:
        bindings = resolve_frontend_bindings()
        prior = prior_r01_authority(bindings)
        if not lock_path.exists() and not lock_path.is_symlink():
            if (
                not ANALYSIS_V3_DESIGN_FREEZE.exists()
                and not ANALYSIS_V3_DESIGN_FREEZE.is_symlink()
            ):
                return {
                    "status": "WAITING_ANALYSIS_V3_STATIC_DESIGN_FREEZE",
                    "read_only": True,
                    "prior_r01_authority": prior,
                    "analysis_v3_design_freeze": str(ANALYSIS_V3_DESIGN_FREEZE),
                    "backend_lock_build_permitted": False,
                    "backend_item_launch_permitted": False,
                    "lock_path": str(lock_path.absolute()),
                    "lock_present": False,
                    "item_order": list(ITEM_ORDER),
                }
            analysis_freeze = collect_analysis_v3_design_freeze_binding()
            require_campaign_unstarted()
            static_identities = collect_static_identities()
            core = contract_core(
                bindings, static_identities,
                current_namespace("net"), current_namespace("user"),
            )
            return {
                "status": "READY_TO_BUILD_KLT_ONLY_REMAINING_V3_EXECUTION_LOCK",
                "read_only": True,
                "prior_r01_authority": prior,
                "analysis_v3_design_freeze": analysis_freeze,
                "candidate_core_sha256": compact_sha256(core),
                "lock_path": str(lock_path.absolute()),
                "lock_present": False,
                "item_order": list(ITEM_ORDER),
            }
        lock, lock_identity = verify_lock(lock_path, bindings)
        return {
            "status": "PASS_LOCKED_READY_FOR_AUTHORIZED_REMAINING_KLT_ITEM",
            "read_only": True,
            "prior_r01_authority": prior,
            "lock": lock_identity,
            "contract_sha256": lock["contract_sha256"],
            "item_order": list(ITEM_ORDER),
        }
    except (BackendProtocolError, OSError, ValueError) as error:
        return {
            "status": "BLOCKED_PREFLIGHT",
            "read_only": True,
            "error": f"{type(error).__name__}:{error}",
            "lock_path": str(lock_path.absolute()),
            "item_order": list(ITEM_ORDER),
        }


def audit_readonly(lock_path: Path = DEFAULT_LOCK) -> dict[str, Any]:
    lock_present = lock_path.exists() or lock_path.is_symlink()
    lock_audit: dict[str, Any] = {
        "path": str(lock_path.absolute()),
        "state": "PRESENT" if lock_present else "ABSENT",
        "authority": "NOT_CHECKED_LOCK_ABSENT" if not lock_present else "NOT_CHECKED",
    }
    prior: dict[str, Any] = {"status": "NOT_CHECKED"}
    verified_lock: Optional[dict[str, Any]] = None
    verified_identity: Optional[dict[str, Any]] = None
    try:
        bindings = resolve_frontend_bindings()
        prior = prior_r01_authority(bindings)
        prior["status"] = "PASS"
        if lock_present:
            verified_lock, verified_identity = verify_lock(lock_path, bindings)
            lock_audit.update({
                "authority": "PASS", "identity": verified_identity,
                "contract_sha256": verified_lock["contract_sha256"],
            })
    except (BackendProtocolError, OSError, ValueError) as error:
        prior = {"status": "FAIL", "error": f"{type(error).__name__}:{error}"}
        if lock_present:
            lock_audit.update({"authority": "FAIL", "error": prior["error"]})
    rows = [inspect_item_readonly(item) for item in ITEM_ORDER]
    if verified_lock is not None and verified_identity is not None:
        for row in rows:
            if row["state"] != "TERMINAL_RECEIPT":
                continue
            try:
                prior_receipt(verified_identity, verified_lock["items"][row["item_id"]])
                row["deep_terminal_evidence_audit"] = "PASS"
            except (BackendProtocolError, OSError, ValueError) as error:
                row.update({
                    "state": "INVALID_TERMINAL_EVIDENCE",
                    "deep_terminal_evidence_audit": "FAIL",
                    "error": f"{type(error).__name__}:{error}",
                })
    blocked_by: Optional[str] = None
    next_item: Optional[str] = None
    for row in rows:
        if row["state"] == "TERMINAL_RECEIPT" and row.get("integrity") == "PASS":
            continue
        if row["state"] == "NOT_STARTED":
            next_item = row["item_id"]
        else:
            blocked_by = row["item_id"]
        break
    if lock_audit.get("authority") != "PASS":
        next_item = None
    elif blocked_by is not None:
        next_item = None
    return {
        "status": "READ_ONLY_AUDIT",
        "read_only": True,
        "prior_r01_authority": prior,
        "lock": lock_audit,
        "item_order": list(ITEM_ORDER),
        "items": rows,
        "next_item_if_lock_and_authorization_pass": next_item,
        "blocked_by_integrity_or_incomplete_item": blocked_by,
        "r01_rerun_permitted": False,
        "maximum_valid_repeat_count": 4,
    }


def execute_item(
    lock_path: Path, item_id: str, authorization_token: str,
) -> tuple[int, dict[str, Any]]:
    require(item_id in ITEM_ORDER, f"ITEM_ID:{item_id}")
    require(authorization_token == AUTHORIZATION_TOKENS[item_id], "AUTHORIZATION_TOKEN")
    _configure_engine()
    return ENGINE.execute_item(lock_path, item_id, authorization_token)


def build_lock(lock_path: Path, authorization_token: str) -> dict[str, Any]:
    require(authorization_token == BUILD_LOCK_TOKEN, "BUILD_LOCK_AUTHORIZATION_TOKEN")
    require(not lock_path.exists() and not lock_path.is_symlink(), "LOCK_ALREADY_EXISTS")
    bindings = resolve_frontend_bindings()
    prior_r01_authority(bindings)
    collect_analysis_v3_design_freeze_binding()
    require_campaign_unstarted()
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = expected_lock_from_current_authority(bindings, created)
    safety = ENGINE.safety_module()
    safety.atomic_publish(lock_path, payload, propagate_interruption_after_commit=True)
    return {"status": "KLT_ONLY_REMAINING_V3_EXECUTION_LOCK_PUBLISHED", "lock": identity(lock_path)}


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight")
    commands.add_parser("audit")
    build = commands.add_parser("build-lock")
    build.add_argument("--authorization-token", required=True)
    run = commands.add_parser("run-item")
    run.add_argument("item_id", choices=ITEM_ORDER)
    run.add_argument("--authorization-token", required=True)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    lock_path = args.lock.absolute()
    if args.command == "preflight":
        result = preflight_readonly(lock_path)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0 if result["status"].startswith(("PASS_", "READY_", "WAITING_")) else 2
    if args.command == "audit":
        print(json.dumps(audit_readonly(lock_path), indent=2, sort_keys=True,
                         ensure_ascii=False))
        return 0
    try:
        if args.command == "build-lock":
            result = build_lock(lock_path, args.authorization_token)
            code = 0
        else:
            code, result = execute_item(lock_path, args.item_id, args.authorization_token)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return code
    except (OSError, ValueError, RuntimeError) as error:
        print(f"A08_KLT_ONLY_REMAINING_V3_ERROR:{type(error).__name__}:{error}",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
