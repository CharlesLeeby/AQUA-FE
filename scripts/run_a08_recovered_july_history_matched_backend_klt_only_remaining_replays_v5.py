#!/usr/bin/python3.8
"""Additive A08 KLT R04--R05 supervisor after consumed R01--R03 infra NAs.

Import is inert.  Read-only preflight binds the frozen v2/v3/v4 authorities.
The sole scientific-environment correction is an explicit locked
``ROS_HOSTNAME=localhost``, matching the already-frozen overlay transform.
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
BACKEND_ROOT = EXPERIMENT / "backend_klt_only_remaining_replays_v5"
RUNTIME_ROOT = EXPERIMENT / "runtime/backend_klt_only_remaining_replays_v5"

PROTOCOL = WORKSPACE / (
    "papers/a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v5_protocol.md"
)
DEFAULT_LOCK = WORKSPACE / (
    "papers/a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v5_execution_lock.json"
)
RUNNER = WORKSPACE / (
    "scripts/run_a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v5.py"
)
REPLAY_ONLY_GUARD = WORKSPACE / (
    "scripts/run_a08_recovered_july_history_matched_backend_klt_only_"
    "replay_guard_v5.sh"
)
PROCESS_FREE_TESTS = WORKSPACE / (
    "scripts/tests/test_run_a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v5.py"
)
ANALYSIS_V5_DESIGN_FREEZE = WORKSPACE / (
    "papers/a08_hfnet_vs_klt_only_common_support_v5_design_freeze.json"
)
ANALYSIS_V5_PROTOCOL = WORKSPACE / (
    "papers/a08_hfnet_vs_klt_only_common_support_v5_protocol.md"
)
ANALYSIS_V5_RUNNER = WORKSPACE / (
    "scripts/run_a08_hfnet_vs_klt_only_common_support_v5.py"
)
ANALYSIS_V5_TESTS = WORKSPACE / (
    "scripts/tests/test_run_a08_hfnet_vs_klt_only_common_support_v5.py"
)
ANALYSIS_V5_DESIGN_FREEZE_SCHEMA = (
    "aqua-fe-a08-hfnet-vs-klt-only-common-support-design-freeze-v5"
)
ANALYSIS_V5_DESIGN_FREEZE_STATUS = (
    "FROZEN_AFTER_R01_R02_R03_INFRASTRUCTURE_FAILURES_BEFORE_R04_R05_"
    "BACKEND_AND_ACCURACY"
)

V4_RUNNER = WORKSPACE / (
    "scripts/run_a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v4.py"
)
V4_PROTOCOL = WORKSPACE / (
    "papers/a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v4_protocol.md"
)
V4_GUARD = WORKSPACE / (
    "scripts/run_a08_recovered_july_history_matched_backend_klt_only_"
    "replay_guard_v4.sh"
)
V4_TESTS = WORKSPACE / (
    "scripts/tests/test_run_a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v4.py"
)
V4_LOCK = WORKSPACE / (
    "papers/a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v4_execution_lock.json"
)
ANALYSIS_V4_DESIGN_FREEZE = WORKSPACE / (
    "papers/a08_hfnet_vs_klt_only_common_support_v4_design_freeze.json"
)
LIFECYCLE_WRAPPER = WORKSPACE / "scripts/run_a08_vins_node_lifecycle_wrapper_v4.py"
SIGNAL_MASK_LAUNCHER = WORKSPACE / "scripts/run_a08_unblocked_overlay_exec_v4.py"
REAL_VINS = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node")
PYTHON38 = Path("/usr/bin/python3.8")
DELEGATED_BASH = Path("/usr/bin/bash")

FROZEN_V4_EXPECTED = {
    "v4_runner": (64_551, "b0c5d3e77233bff595f372882cec6c99208fe198d11e4482f7e10c4836e58786"),
    "v4_protocol": (9_441, "e4fc7ca38ed22e2b350a507dde0a0d9e354c7dd2f427a5fdbd01fb0cd00b1467"),
    "v4_guard": (18_863, "1be1fafeb59cd1b1e44458e5165214423e87de09434920df16d2a7c34f9bcd47"),
    "v4_lifecycle_wrapper": (15_881, "c2aa603efd85b1800757be6d002aced88a0d89d2043ff5ee43dfa3457a0b9244"),
    "v4_signal_mask_launcher": (6_340, "8d9b188734d6fcae268496f572c965f341249830405745dfe8d09e831e522722"),
    "v4_process_free_tests": (14_615, "96dac289a3a4d46410d6b7d9b216d172ffae76f7dca5fd459e7978a4e9b4f4f2"),
    "v4_execution_lock": (100_210, "e28d61cf17116bc0fade98bf84f0a88f48831bbff442096abf877ef7226e15da"),
    "analysis_v4_design_freeze": (25_864, "2320b6c904fd10c6d2afa435aa771b750d641c50e62ee6f2511fade077e6cd34"),
    "python38": (5_490_456, "298a9e830ed52f36c299427565485d717d1ce0179c0597cc16560513eb780b06"),
    "real_vins_binary": (13_104_360, "4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278"),
}

R03_EXPECTED = {
    "receipt": (16_673, "8c40956b037acf078a820c0f3fb870d9607818bcd5bdd4a649e6df969a2bdf10"),
    "claim": (12_192, "b4e4f14d2f0cd1f8608bf6b3dbb24b60f769d5c0ec4066dca6186e784836d72d"),
    "supervisor_log": (1_431, "0523b37033976b14b47bf4b2c175bb6bed7bfb44930ca3a7df49aac2e2c26ae8"),
    "guard_manifest": (7_022, "2391b93d4797951e00ce93e7813d6540e8f2003fe91337021beafbce0f3047e9"),
    "replay_manifest": (1_617, "23ea4b89abb5946c3171ac4da251d2f218fecb73d195fc1e0af57316364bce63"),
    "vio": (279_716, "992e1c232f3266987243ae3233aaa66b8eec273ca3e518372178e9940dffd4cd"),
    "ape": (671, "96d7942dfa5b816e50a52896299ac649da3f7a4f73c6c9808d5c3c9f086aec6c"),
    "lifecycle_start": (2_834, "2b45511506640657c2481d84f88464de630b86373e00db6ed858c1c50b8bb623"),
    "lifecycle_terminal": (1_917, "3c735db252c95ea74783bc4c864b09cddb6e94efe725a62b4c654b7e038f1108"),
    "signal_mask": (1_823, "9e1abea870f0d95a7930646b3b41f7675dd1d6c02c1f8244d2a4be44d20222cd"),
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
PRIOR_R03_DISPOSITION = (
    "NA_BACKEND_INFRASTRUCTURE_RUNTIME_ENV_AUDIT_CONTRACT_MISMATCH_AFTER_"
    "COMPLETE_REPLAY_NO_REPLACEMENT"
)
R03_FAILURE_CODE = (
    "LOCKED_ITEM_ENV_OMITTED_OVERLAY_ROS_HOSTNAME_LOCALHOST_"
    "LIFECYCLE_AUDIT_MISMATCH"
)
R03_PRIOR_FAILURE = "PRIOR_EXECUTION_INTEGRITY:KLT_R03"
R03_ARTIFACT_ISSUE = (
    "VINS_LIFECYCLE_GATE:LIFECYCLE_NOT_ACCEPTED,start:environment"
)
R03_INTEGRITY_ISSUE = "VINS_LIFECYCLE_MANIFEST_CONTRACT"
ROS_HOSTNAME_TRANSFORM = {"ROS_HOSTNAME": "localhost"}


def _load_v4() -> ModuleType:
    raw = V4_RUNNER.read_bytes()
    observed = (len(raw), hashlib.sha256(raw).hexdigest())
    if (
        observed != FROZEN_V4_EXPECTED["v4_runner"]
        or V4_RUNNER.is_symlink()
        or V4_RUNNER.resolve(strict=True) != V4_RUNNER
    ):
        raise RuntimeError("V4_RUNNER_BOOTSTRAP_IDENTITY_DRIFT")
    specification = importlib.util.spec_from_file_location(
        "a08_klt_v4_authority_for_v5", V4_RUNNER
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("V4_RUNNER_IMPORT_SPEC")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _fresh_v4_authority() -> ModuleType:
    return _load_v4()


V4 = _load_v4()
ENGINE = V4.ENGINE
BackendProtocolError = ENGINE.BackendProtocolError
require = ENGINE.require
identity = ENGINE.identity
stable_json = ENGINE.stable_json
compact_sha256 = ENGINE.compact_sha256
current_namespace = ENGINE.current_namespace
BASE_PRIOR_RECEIPT = V4.BASE_PRIOR_RECEIPT

ITEM_ORDER = ("KLT_R04", "KLT_R05")
CLAIM_NAME = "process_start_claim_v1.json"
RECEIPT_NAME = "formal_run_receipt_v5.json"
LOCK_SCHEMA = "aqua-fe-a08-recovered-july-backend-klt-only-remaining-lock-v5"
RECEIPT_SCHEMA = "aqua-fe-a08-recovered-july-backend-klt-only-remaining-receipt-v5"
LOCK_STATUS = (
    "FROZEN_REMAINING_R04_R05_AFTER_R01_R02_R03_INFRA_FAILURES_BEFORE_LAUNCH"
)
BUILD_LOCK_TOKEN = (
    "A08_BUILD_KLT_ONLY_REMAINING_BACKEND_REPLAYS_V5_LOCK_AFTER_"
    "R01_R02_R03_INFRA_FAILURES"
)
AUTHORIZATION_TOKENS = {
    item: f"A08_KLT_ONLY_REMAINING_BACKEND_REPLAYS_V5_RUN_{item}_EXACTLY_ONCE"
    for item in ITEM_ORDER
}
EXPECTED_OUTPUTS = tuple(V4.EXPECTED_OUTPUTS)
SCIENTIFIC_ENV_KEYS = tuple(V4.SCIENTIFIC_ENV_KEYS)


def _identity_tuple(value: Mapping[str, Any]) -> tuple[int, str]:
    return int(value["size_bytes"]), str(value["sha256"])


def _matches(value: Mapping[str, Any], expected: tuple[int, str]) -> bool:
    return _identity_tuple(value) == expected


def resolve_frontend_bindings() -> dict[str, Any]:
    return _fresh_v4_authority().resolve_frontend_bindings()


def arm_spec(item_id: str) -> dict[str, Any]:
    require(item_id in ITEM_ORDER, f"ITEM_ID:{item_id}")
    repeat = int(item_id[-2:])
    tag = f"a08_recoveredjuly_hist0000_4660_backend_klt_only_r{repeat:02d}_v5"
    return {
        "arm": "klt", "repeat_index": repeat, "method": "klt", "tag": tag,
        "run_leaf": f"external_klt_every2_{tag}",
    }


def item_environment(item_id: str, bindings: Mapping[str, Any]) -> dict[str, str]:
    spec = arm_spec(item_id)
    environment = V4.item_environment(item_id, bindings)
    environment.pop("A08_KLT_ONLY_REMAINING_REPLAYS_V4", None)
    output = BACKEND_ROOT / item_id
    environment.update({
        "TAG": spec["tag"],
        "ROS_HOME": str(RUNTIME_ROOT / item_id / "ros_home"),
        "ROS_LOG_DIR": str(RUNTIME_ROOT / item_id / "ros_log"),
        "A08_ITEM_OUTPUT_DIR": str(output),
        "A08_ITEM_ID": item_id,
        "A08_WORKSPACE_LINK": str(OVERLAY_RUN_ROOT / spec["run_leaf"]),
        "A08_KLT_ONLY_REMAINING_REPLAYS_V5": "1",
        "A08_PRIOR_R03_DISPOSITION": PRIOR_R03_DISPOSITION,
        "A08_VINS_LIFECYCLE_START_MANIFEST": str(
            output / "vins_lifecycle_start_manifest_v4.json"
        ),
        "A08_VINS_LIFECYCLE_TERMINAL_MANIFEST": str(
            output / "vins_lifecycle_terminal_manifest_v4.json"
        ),
        "A08_SIGNAL_MASK_MANIFEST": str(output / "overlay_signal_mask_manifest_v4.json"),
        "ROS_HOSTNAME": "localhost",
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
            "prior_r03_disposition": PRIOR_R03_DISPOSITION,
            "scientific_environment_amendment": {
                "only_addition_from_v4": dict(ROS_HOSTNAME_TRANSFORM),
                "all_other_scientific_signal_lifecycle_values_unchanged": True,
            },
            "scientific_boundary": {
                "maximum_valid_repeat_count": 2, "xfeat_accuracy": "NA",
                "learned_contribution_claim_permitted": False,
            },
            "command_sha256": compact_sha256({"argv": argv, "env": environment}),
        }
    return result


def static_identity_paths() -> dict[str, Path]:
    inherited = dict(V4.static_identity_paths())
    inherited["v4_runner"] = inherited.pop("runner")
    inherited["v4_protocol"] = inherited.pop("protocol")
    inherited["v4_guard"] = inherited.pop("stable_owner_replay_guard_v4")
    inherited["v4_lifecycle_wrapper"] = inherited.pop("vins_lifecycle_wrapper_v4")
    inherited["v4_signal_mask_launcher"] = inherited.pop("signal_mask_launcher_v4")
    inherited["v4_process_free_tests"] = inherited.pop("process_free_tests")
    inherited.update({
        "v4_execution_lock": V4_LOCK,
        "analysis_v4_design_freeze": ANALYSIS_V4_DESIGN_FREEZE,
        "runner": RUNNER, "protocol": PROTOCOL,
        "stable_owner_replay_guard_v5": REPLAY_ONLY_GUARD,
        "process_free_tests": PROCESS_FREE_TESTS,
    })
    return inherited


def collect_static_identities() -> dict[str, Any]:
    _fresh_v4_authority().collect_static_identities()
    values = {name: identity(path) for name, path in static_identity_paths().items()}
    for label, expected in FROZEN_V4_EXPECTED.items():
        require(_matches(values[label], expected), f"STATIC_IDENTITY:{label}")
    return values


def prior_r01_authority(bindings: Mapping[str, Any]) -> dict[str, Any]:
    value = _fresh_v4_authority().prior_r01_authority(bindings)
    require(value.get("disposition") == PRIOR_R01_DISPOSITION, "PRIOR_R01")
    return value


def prior_r02_authority(bindings: Mapping[str, Any]) -> dict[str, Any]:
    value = _fresh_v4_authority().prior_r02_authority(bindings)
    require(value.get("disposition") == PRIOR_R02_DISPOSITION, "PRIOR_R02")
    return value


def v4_lock_authority(
    bindings: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    frozen = _fresh_v4_authority()
    lock, lock_identity = frozen.verify_lock(V4_LOCK, bindings)
    require(_matches(lock_identity, FROZEN_V4_EXPECTED["v4_execution_lock"]),
            "V4_LOCK_EXACT_IDENTITY")
    return lock, lock_identity


def frozen_nested_shell_authority(
    lock: Mapping[str, Any], item: Mapping[str, Any],
) -> dict[str, Any]:
    outer = Path(item["env"]["A08_OVERLAY_BACKEND_SHELL"])
    inner = ENGINE.ARCHAEO_SHELL
    outer_identity = identity(outer)
    inner_identity = identity(inner)
    require(outer_identity == lock["static_identities"]["backend_shell"],
            "OUTER_SEEDCHAIN_IDENTITY")
    require(inner_identity == lock["static_identities"]["archaeo_shell"],
            "INNER_ARCHAEO_SHELL_IDENTITY")
    require(_identity_tuple(outer_identity) == (
        4_061, "8b2db28e5a5c1cc4dfd8ce365d44bdc618e6ec2c4a70db4ea2549b73a965b106"
    ), "OUTER_SEEDCHAIN_EXPECTED")
    require(_identity_tuple(inner_identity) == (
        53_928, "9da109074d559875434bc82e43febd7acf1e60c027f11bae31023e6d08198a9b"
    ), "INNER_ARCHAEO_EXPECTED")
    outer_lines = outer.read_text(encoding="utf-8").splitlines()
    inner_lines = inner.read_text(encoding="utf-8").splitlines()
    require(identity(outer) == outer_identity and identity(inner) == inner_identity,
            "NESTED_SHELL_CHANGED_DURING_READ")
    require(
        outer_lines[102].strip()
        == 'bash "$ROOT/scripts/run_aqualoc_archaeo_vins_eval.sh" external "$SEQ" "$START" "$END" "$METHOD" "$EVERY_N"',
        "OUTER_LINE_103_DELEGATION",
    )
    require(inner_lines[924].strip() == "export ROS_HOSTNAME=localhost",
            "INNER_LINE_925_ROS_HOSTNAME")
    require(
        inner_lines[947].strip()
        == '"$VINS_NODE_BIN" "$VINS_CONFIG" > "$VINS_LOG" 2>&1 &',
        "INNER_LINE_948_WRAPPER_LAUNCH",
    )
    return {
        "outer_seedchain": outer_identity, "inner_archaeo_shell": inner_identity,
        "outer_line_103": outer_lines[102].strip(),
        "inner_line_925": inner_lines[924].strip(),
        "inner_line_948": inner_lines[947].strip(),
        "direct_launcher_to_wrapper_claim_permitted": False,
        "nested_shell_process_chain_required": True,
    }


def _expected_prior_failure(function: Any, code: str) -> str:
    try:
        function()
    except RuntimeError as error:
        observed = str(error)
        require(observed == code, f"EXPECTED_PRIOR_FAILURE:{observed}")
        return observed
    raise BackendProtocolError("EXPECTED_PRIOR_FAILURE_DID_NOT_OCCUR")


def _v4_remaining_unstarted(lock: Mapping[str, Any]) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for item_id in ITEM_ORDER:
        item = lock["items"][item_id]
        paths = {
            "output": Path(item["output_dir"]),
            "workspace": Path(item["workspace_link"]),
            "runtime": V4.RUNTIME_ROOT / item_id,
        }
        for label, path in paths.items():
            require(not path.exists() and not path.is_symlink(),
                    f"V4_REMAINING_ITEM_TOUCHED:{item_id}:{label}")
        rows[item_id] = {label: str(path) for label, path in paths.items()}
    return {"status": "PASS_V4_R04_R05_ALL_UNSTARTED", "items": rows}


def prior_r03_authority(bindings: Mapping[str, Any]) -> dict[str, Any]:
    frozen = _fresh_v4_authority()
    lock, lock_identity = frozen.verify_lock(V4_LOCK, bindings)
    require(_matches(lock_identity, FROZEN_V4_EXPECTED["v4_execution_lock"]),
            "V4_LOCK_EXACT_IDENTITY")
    item = lock["items"]["KLT_R03"]
    output = Path(item["output_dir"])
    receipt_path = output / frozen.RECEIPT_NAME
    receipt, receipt_identity = frozen.stable_json(receipt_path)
    require(_matches(receipt_identity, R03_EXPECTED["receipt"]),
            "V4_R03_RECEIPT_IDENTITY")

    frozen._configure_engine()
    base_artifact = frozen.BASE_ARTIFACT_AUDIT(item)
    current_artifact = frozen.artifact_audit(item)
    require(
        base_artifact.get("status") == "PASS"
        and base_artifact.get("issues") == []
        and base_artifact.get("integrity_issues") == [],
        "V4_R03_BASE_ARTIFACT_RECONSTRUCTION",
    )
    require(current_artifact == receipt.get("artifact_contract"),
            "V4_R03_ARTIFACT_RECEIPT_RECONSTRUCTION")
    base_failure = _expected_prior_failure(
        lambda: (frozen._configure_engine(),
                 frozen.BASE_PRIOR_RECEIPT(lock_identity, item))[1],
        R03_PRIOR_FAILURE,
    )
    strict_failure = _expected_prior_failure(
        lambda: frozen.prior_receipt(lock_identity, item), R03_PRIOR_FAILURE
    )

    require(
        receipt.get("schema_version") == frozen.RECEIPT_SCHEMA
        and receipt.get("status") == "FAILED_BACKEND_REPLAY_NO_REPLACEMENT"
        and receipt.get("item_id") == "KLT_R03"
        and receipt.get("execution_lock") == lock_identity
        and receipt.get("retry_count") == 0
        and receipt.get("replacement_permitted") is False
        and receipt.get("launch_allowance_consumed") is True,
        "V4_R03_TERMINAL_CONTROL",
    )
    runtime = receipt.get("runtime")
    group = runtime.get("process_group") if isinstance(runtime, dict) else None
    require(
        isinstance(runtime, dict) and runtime.get("raw_return_code") == 0
        and runtime.get("timed_out") is False
        and runtime.get("popen_invocation_count") == 1
        and isinstance(group, dict) and group.get("normal_exit_path") is True
        and group.get("leader_reaped") is True
        and group.get("process_group_empty") is True
        and group.get("owned_descendants_empty") is True,
        "V4_R03_RUNTIME_COMPLETE",
    )
    integrity = receipt.get("execution_integrity")
    require(
        receipt.get("integrity_fault_latch")
            == [f"ARTIFACT_INTEGRITY:{R03_INTEGRITY_ISSUE}"]
        and isinstance(integrity, dict) and integrity.get("status") == "FAIL"
        and integrity.get("irreversible_fault_latch_clear") is False
        and integrity.get("artifact_integrity_issues") == [R03_INTEGRITY_ISSUE]
        and integrity.get("authority_post") == {"status": "PASS", "lock": lock_identity}
        and integrity.get("claim_stable") is True
        and integrity.get("workspace_binding_stable") is True
        and integrity.get("owned_processes_drained") is True,
        "V4_R03_EXACT_INFRASTRUCTURE_INTEGRITY_FAILURE",
    )
    artifact = receipt["artifact_contract"]
    require(
        artifact.get("status") == "FAIL"
        and artifact.get("issues") == [R03_ARTIFACT_ISSUE]
        and artifact.get("integrity_issues") == [R03_INTEGRITY_ISSUE]
        and artifact.get("evidence_tree_integrity") is True,
        "V4_R03_EXACT_ARTIFACT_FAILURE",
    )
    outputs = artifact["outputs"]
    require(set(outputs) == set(item["expected_outputs"]), "V4_R03_COMPLETE_OUTPUT_SET")
    for relative, claim in outputs.items():
        require(identity(output / relative) == claim, f"V4_R03_OUTPUT:{relative}")
    critical = {
        "ape.txt": "ape", "replay_manifest.txt": "replay_manifest",
        "replay_only_guard_manifest.json": "guard_manifest",
        "vins_output/vio.csv": "vio",
        "vins_lifecycle_start_manifest_v4.json": "lifecycle_start",
        "vins_lifecycle_terminal_manifest_v4.json": "lifecycle_terminal",
        "overlay_signal_mask_manifest_v4.json": "signal_mask",
    }
    for relative, label in critical.items():
        require(_matches(outputs[relative], R03_EXPECTED[label]),
                f"V4_R03_CRITICAL_IDENTITY:{relative}")
    require(_matches(receipt["claim"], R03_EXPECTED["claim"]), "V4_R03_CLAIM")
    require(_matches(receipt["process_log"], R03_EXPECTED["supervisor_log"]),
            "V4_R03_PROCESS_LOG")

    semantic = artifact["semantic_checks"]
    require(semantic["trajectory"].get("rows") == 2319, "V4_R03_TRAJECTORY")
    require(
        semantic["backend_usability"].get("status") == "PASS"
        and semantic["backend_usability"]["values"].get("output_coverage_ratio") == 0.99485
        and semantic["replay_manifest"].get("status") == "PASS"
        and semantic["replay_only_guard"].get("status") == "PASS"
        and semantic["overlay_signal_mask"].get("status") == "PASS",
        "V4_R03_COMPLETE_REPLAY_SEMANTICS",
    )
    lifecycle = semantic["vins_lifecycle"]
    require(
        lifecycle.get("status") == "FAIL"
        and lifecycle.get("contract_integrity") is False
        and lifecycle.get("failure_codes") == ["LIFECYCLE_NOT_ACCEPTED", "start:environment"]
        and lifecycle.get("real_child_reaped") is True
        and lifecycle.get("shutdown_stage_audit", {}).get("status") == "PASS"
        and lifecycle.get("wrapper_signal_sequence_audit", {}).get("status") == "PASS",
        "V4_R03_LIFECYCLE_ONLY_ENVIRONMENT_FAILURE",
    )
    start, _ = frozen.stable_json(output / "vins_lifecycle_start_manifest_v4.json")
    expected_selected = {
        key: item["env"][key] for key in frozen.SCIENTIFIC_ENV_KEYS if key in item["env"]
    }
    observed_selected = start.get("scientific_environment")
    require(
        isinstance(observed_selected, dict)
        and "ROS_HOSTNAME" not in expected_selected
        and observed_selected == {**expected_selected, "ROS_HOSTNAME": "localhost"},
        "V4_R03_EXACT_ROS_HOSTNAME_ONLY_DELTA",
    )
    shell = frozen_nested_shell_authority(lock, item)
    later = _v4_remaining_unstarted(lock)
    return {
        "item_id": "KLT_R03", "disposition": PRIOR_R03_DISPOSITION,
        "failure_code": R03_FAILURE_CODE,
        "rerun_permitted": False, "replacement_permitted": False,
        "counts_as_valid_repeat": False,
        "v4_execution_lock": lock_identity,
        "analysis_v4_design_freeze": identity(ANALYSIS_V4_DESIGN_FREEZE),
        "v4_terminal_receipt": receipt_identity,
        "v4_claim": receipt["claim"], "v4_process_log": receipt["process_log"],
        "v4_base_artifact_audit": "PASS",
        "v4_artifact_receipt_reconstruction": "PASS",
        "v4_base_prior_receipt_audit": "FAIL_EXPECTED_R03_INFRASTRUCTURE",
        "v4_base_prior_failure_code": base_failure,
        "v4_strict_prior_receipt_audit": "FAIL_EXPECTED_R03_INFRASTRUCTURE",
        "v4_strict_prior_failure_code": strict_failure,
        "receipt_status": receipt["status"],
        "execution_integrity": "FAIL_EXPECTED_INFRASTRUCTURE_AUDIT_CONTRACT",
        "integrity_fault_latch": receipt["integrity_fault_latch"],
        "runtime_timed_out": False, "raw_return_code": 0,
        "artifact_contract_status": "FAIL",
        "artifact_issue": R03_ARTIFACT_ISSUE,
        "artifact_integrity_issue": R03_INTEGRITY_ISSUE,
        "artifact_integrity_issues": [R03_INTEGRITY_ISSUE],
        "evidence_tree_integrity": True,
        "complete_artifacts_identity_bound": True,
        "artifact_accepted": False,
        "complete_artifacts": True, "complete_artifact_identities": dict(outputs),
        "process_log": receipt["process_log"],
        "trajectory_complete": True, "trajectory_rows": 2319,
        "trajectory_identity": outputs["vins_output/vio.csv"],
        "trajectory_admitted": False, "replay_completed": True,
        "diagnostic_ape_identity": outputs["ape.txt"],
        "diagnostic_ape_admitted_to_common_support": False,
        "backend_usability_status": "PASS",
        "replay_manifest_semantic_status": "PASS",
        "replay_guard_status": "PASS",
        "overlay_signal_mask_status": "PASS",
        "vins_lifecycle_status": "FAIL_EXPECTED_LOCKED_ENV_AUDIT_MISMATCH",
        "post_result_cleanup_completed": True,
        "locked_item_ros_hostname_present": False,
        "observed_overlay_ros_hostname": "localhost",
        "runtime_lifecycle_ros_hostname": "localhost",
        "all_other_selected_scientific_environment_equal": True,
        "only_permitted_v5_environment_addition": dict(ROS_HOSTNAME_TRANSFORM),
        "counts_as_valid_repeat": False,
        "nested_shell_authority": shell,
        "rerun_or_replacement_permitted": False,
        "v4_remaining_items": later,
    }


def load_analysis_v5_authority_module(
    expected_identity: Mapping[str, Any],
) -> ModuleType:
    path = ANALYSIS_V5_RUNNER.absolute()
    require(
        path.exists() and not path.is_symlink()
        and stat.S_ISREG(path.lstat().st_mode)
        and path.resolve(strict=True) == path,
        "ANALYSIS_V5_RUNNER_KIND",
    )
    require(identity(path) == expected_identity, "ANALYSIS_V5_RUNNER_IDENTITY")
    specification = importlib.util.spec_from_file_location(
        "a08_analysis_v5_authority_for_backend_v5", path
    )
    require(
        specification is not None and specification.loader is not None,
        "ANALYSIS_V5_RUNNER_IMPORT_SPEC",
    )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    require(
        identity(path) == expected_identity,
        "ANALYSIS_V5_RUNNER_CHANGED_DURING_IMPORT",
    )
    require(
        getattr(module, "DESIGN_FREEZE_SCHEMA", None)
            == ANALYSIS_V5_DESIGN_FREEZE_SCHEMA
        and getattr(module, "DESIGN_FREEZE_STATUS", None)
            == ANALYSIS_V5_DESIGN_FREEZE_STATUS,
        "ANALYSIS_V5_RUNNER_CONTRACT",
    )
    # Tests may bind a temporary candidate freeze. Formal execution keeps the
    # canonical value, and both paths are still identity-checked below.
    module.DESIGN_FREEZE = ANALYSIS_V5_DESIGN_FREEZE
    return module


def collect_analysis_v5_design_freeze_binding() -> dict[str, Any]:
    value, freeze_identity = stable_json(ANALYSIS_V5_DESIGN_FREEZE)
    require(set(value) == {
        "schema_version", "status", "created_at_utc", "static_identities",
        "sealed_support", "klt_frontend", "excluded_xfeat", "evo_authority",
        "prior_r01", "prior_r02", "prior_r03", "design_contract",
        "backend_v5_terminal_presence_at_freeze",
        "backend_v5_campaign_prelaunch_presence_at_freeze",
        "v4_remaining_r04_r05_presence_at_freeze", "claim_boundary",
        "freeze_sha256",
    }, "ANALYSIS_V5_TOP_LEVEL_SCHEMA")
    require(value.get("schema_version") == ANALYSIS_V5_DESIGN_FREEZE_SCHEMA,
            "ANALYSIS_V5_SCHEMA")
    require(value.get("status") == ANALYSIS_V5_DESIGN_FREEZE_STATUS,
            "ANALYSIS_V5_STATUS")
    digest = value.get("freeze_sha256")
    unsigned = dict(value); unsigned.pop("freeze_sha256", None)
    require(digest == compact_sha256(unsigned), "ANALYSIS_V5_DIGEST")
    frozen = value.get("static_identities")
    require(isinstance(frozen, dict), "ANALYSIS_V5_STATIC")
    required = {
        "protocol": identity(ANALYSIS_V5_PROTOCOL),
        "runner": identity(ANALYSIS_V5_RUNNER),
        "process_free_tests": identity(ANALYSIS_V5_TESTS),
        "backend_v5_protocol": identity(PROTOCOL),
        "backend_v5_runner": identity(RUNNER),
        "backend_v5_guard": identity(REPLAY_ONLY_GUARD),
        "backend_v5_process_free_tests": identity(PROCESS_FREE_TESTS),
        "backend_v5_lifecycle_wrapper": identity(LIFECYCLE_WRAPPER),
        "backend_v5_signal_mask_launcher": identity(SIGNAL_MASK_LAUNCHER),
        # The analysis-v5 freeze exposes inherited v4 authorities under the
        # explicit ``frozen_`` namespace.  Keep this validator aligned with
        # that public freeze schema; the direct backend-v5 wrapper/launcher
        # entries above intentionally point to the same frozen v4 files.
        "frozen_backend_v4_protocol": identity(V4_PROTOCOL),
        "frozen_backend_v4_runner": identity(V4_RUNNER),
        "frozen_backend_v4_guard": identity(V4_GUARD),
        "frozen_backend_v4_tests": identity(V4_TESTS),
        "backend_v5_python38": identity(PYTHON38),
        "backend_v5_vins_node": identity(REAL_VINS),
        "analysis_v4_design_freeze": identity(ANALYSIS_V4_DESIGN_FREEZE),
        "backend_v4_execution_lock": identity(V4_LOCK),
        "v4_r03_terminal_receipt": identity(
            V4.BACKEND_ROOT / "KLT_R03" / V4.RECEIPT_NAME
        ),
    }
    require(all(frozen.get(key) == row for key, row in required.items()),
            "ANALYSIS_V5_STATIC_BINDINGS")
    analysis_authority = load_analysis_v5_authority_module(required["runner"])
    authoritative_binding = analysis_authority.collect_design_freeze_binding()
    require(
        authoritative_binding.get("identity") == freeze_identity
        and authoritative_binding.get("freeze_sha256") == digest,
        "ANALYSIS_V5_AUTHORITATIVE_LIVE_BINDING",
    )
    require(
        isinstance(value.get("created_at_utc"), str)
        and bool(value.get("created_at_utc"))
        and all(isinstance(value.get(key), dict) for key in (
            "sealed_support", "klt_frontend", "excluded_xfeat", "evo_authority",
        )),
        "ANALYSIS_V5_STATIC_AUTHORITY_SECTIONS",
    )
    prior01 = value.get("prior_r01")
    prior02 = value.get("prior_r02")
    require(
        isinstance(prior01, dict)
        and prior01.get("disposition") == PRIOR_R01_DISPOSITION
        and prior01.get("failure_code") == R01_FAILURE_CODE
        and prior01.get("rerun_or_replacement_permitted") is False,
        "ANALYSIS_V5_PRIOR_R01",
    )
    require(
        isinstance(prior02, dict)
        and prior02.get("disposition") == PRIOR_R02_DISPOSITION
        and prior02.get("failure_code") == R02_FAILURE_CODE
        and prior02.get("rerun_or_replacement_permitted") is False,
        "ANALYSIS_V5_PRIOR_R02",
    )
    live = prior_r03_authority(resolve_frontend_bindings())
    prior = value.get("prior_r03")
    scalar_keys = (
        "item_id", "disposition", "failure_code", "v4_base_artifact_audit",
        "analysis_v4_design_freeze",
        "v4_artifact_receipt_reconstruction", "v4_base_prior_receipt_audit",
        "v4_base_prior_failure_code", "v4_strict_prior_receipt_audit",
        "v4_strict_prior_failure_code", "receipt_status", "execution_integrity",
        "integrity_fault_latch", "runtime_timed_out", "raw_return_code",
        "artifact_contract_status", "artifact_issue", "artifact_integrity_issue",
        "artifact_integrity_issues",
        "evidence_tree_integrity", "complete_artifacts_identity_bound",
        "artifact_accepted", "complete_artifacts", "complete_artifact_identities",
        "process_log", "trajectory_complete", "trajectory_rows",
        "trajectory_identity", "trajectory_admitted", "diagnostic_ape_identity",
        "diagnostic_ape_admitted_to_common_support", "backend_usability_status",
        "replay_manifest_semantic_status", "replay_guard_status",
        "overlay_signal_mask_status", "vins_lifecycle_status",
        "locked_item_ros_hostname_present", "observed_overlay_ros_hostname",
        "runtime_lifecycle_ros_hostname",
        "all_other_selected_scientific_environment_equal",
        "only_permitted_v5_environment_addition",
        "replay_completed", "post_result_cleanup_completed",
        "counts_as_valid_repeat", "rerun_or_replacement_permitted",
    )
    require(
        isinstance(prior, dict)
        and prior.get("receipt") == required["v4_r03_terminal_receipt"]
        and live.get("v4_terminal_receipt") == required["v4_r03_terminal_receipt"]
        and prior.get("v4_execution_lock") == required["backend_v4_execution_lock"]
        and live.get("v4_execution_lock") == required["backend_v4_execution_lock"]
        and all(prior.get(key) == live.get(key) for key in scalar_keys),
        "ANALYSIS_V5_PRIOR_R03",
    )
    contract = value.get("design_contract")
    population = contract.get("population_and_failure_rules") if isinstance(contract, dict) else None
    amendment = contract.get("v5_environment_amendment") if isinstance(contract, dict) else None
    require(
        isinstance(population, dict)
        and population.get("backend_item_order")
            == ["KLT_R01", "KLT_R02", "KLT_R03", "KLT_R04", "KLT_R05"]
        and population.get("v5_backend_item_order") == list(ITEM_ORDER)
        and population.get("klt_planned_count") == 5
        and population.get("maximum_valid_klt_count") == 2
        and all(population.get(f"r0{i}_counts_as_valid") is False for i in (1, 2, 3))
        and all(population.get(f"r0{i}_rerun_or_replacement_permitted") is False
                for i in (1, 2, 3)),
        "ANALYSIS_V5_POPULATION",
    )
    require(
        isinstance(amendment, dict)
        and amendment.get("only_permitted_scientific_environment_addition")
            == ROS_HOSTNAME_TRANSFORM
        and amendment.get("all_other_scientific_signal_lifecycle_values_unchanged") is True
        and amendment.get("reuse_frozen_v4_lifecycle_wrapper") is True
        and amendment.get("reuse_frozen_v4_signal_mask_launcher") is True,
        "ANALYSIS_V5_ENVIRONMENT_AMENDMENT",
    )
    boundary = value.get("claim_boundary")
    require(
        isinstance(boundary, dict)
        and set(boundary) == {
            "r01_r02_r03_terminal_failures_opened_only_for_exclusion",
            "r03_complete_artifacts_identity_bound_but_unaccepted",
            "r03_trajectory_opened_for_common_support",
            "backend_v5_execution_lock_built", "v5_backend_items_started",
            "ape_or_rpe_computed_for_v5", "final_dynamic_analysis_lock_built",
            "ros_or_vins_started_for_v5",
        }
        and boundary.get(
            "r01_r02_r03_terminal_failures_opened_only_for_exclusion"
        ) is True
        and boundary.get(
            "r03_complete_artifacts_identity_bound_but_unaccepted"
        ) is True
        and boundary.get("r03_trajectory_opened_for_common_support") is False
        and boundary.get("backend_v5_execution_lock_built") is False
        and boundary.get("v5_backend_items_started") == 0
        and boundary.get("ape_or_rpe_computed_for_v5") is False
        and boundary.get("final_dynamic_analysis_lock_built") is False
        and boundary.get("ros_or_vins_started_for_v5") is False,
        "ANALYSIS_V5_PREBACKEND_BOUNDARY",
    )
    terminal_presence = value.get("backend_v5_terminal_presence_at_freeze")
    prelaunch_presence = value.get(
        "backend_v5_campaign_prelaunch_presence_at_freeze"
    )
    old_v4_presence = value.get("v4_remaining_r04_r05_presence_at_freeze")
    require(
        terminal_presence == {
            "backend_v5_execution_lock": "MISSING",
            "KLT_R04": "MISSING", "KLT_R05": "MISSING",
        },
        "ANALYSIS_V5_TERMINAL_ABSENCE_AT_FREEZE",
    )
    require(
        prelaunch_presence == {
            "backend_v5_root": "ABSENT", "backend_v5_runtime_root": "ABSENT",
            "workspace:KLT_R04": "ABSENT", "workspace:KLT_R05": "ABSENT",
        },
        "ANALYSIS_V5_PRELAUNCH_ABSENCE_AT_FREEZE",
    )
    require(
        old_v4_presence == {
            "output:KLT_R04": "ABSENT", "runtime:KLT_R04": "ABSENT",
            "workspace:KLT_R04": "ABSENT", "output:KLT_R05": "ABSENT",
            "runtime:KLT_R05": "ABSENT", "workspace:KLT_R05": "ABSENT",
        },
        "ANALYSIS_V5_OLD_V4_REMAINDER_ABSENCE_AT_FREEZE",
    )
    return {
        "identity": freeze_identity, "schema_version": value["schema_version"],
        "status": value["status"], "freeze_sha256": digest,
        "required_static_identities": required, "prior_r03": prior,
        "population_and_failure_rules": population,
        "v5_environment_amendment": amendment, "claim_boundary": boundary,
    }


def require_campaign_unstarted() -> None:
    require(not BACKEND_ROOT.exists() and not BACKEND_ROOT.is_symlink(),
            "V5_OUTPUT_ROOT_ALREADY_TOUCHED")
    require(not RUNTIME_ROOT.exists() and not RUNTIME_ROOT.is_symlink(),
            "V5_RUNTIME_ROOT_ALREADY_TOUCHED")
    for item_id in ITEM_ORDER:
        workspace = OVERLAY_RUN_ROOT / arm_spec(item_id)["run_leaf"]
        require(not workspace.exists() and not workspace.is_symlink(),
                f"V5_WORKSPACE_ALREADY_TOUCHED:{item_id}")


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
        "schema": value.get("schema_version") == "aqua-fe-a08-replay-only-stable-owner-fd-guard-v5",
        "status": value.get("status") == "PASS_BEFORE_DELEGATED_BACKEND",
        "item": value.get("item_id") == item["item_id"],
        "output": value.get("output_dir") == item["output_dir"],
        "workspace": value.get("workspace_link") == item["workspace_link"],
        "delegated_shell": value.get("delegated_backend_shell")
            == item["env"]["A08_OVERLAY_BACKEND_SHELL"],
        "owner": owner_valid,
        "prior": value.get("prior_dispositions") == {
            "KLT_R01": PRIOR_R01_DISPOSITION, "KLT_R02": PRIOR_R02_DISPOSITION,
            "KLT_R03": PRIOR_R03_DISPOSITION,
        },
        "runtime_environment": value.get("runtime_environment_contract") == {
            "locked_ros_hostname": "localhost",
            "frozen_overlay_export_line": "export ROS_HOSTNAME=localhost",
            "only_scientific_environment_addition_from_v4": ROS_HOSTNAME_TRANSFORM,
        },
        "history": value.get("history") == {
            "dataset": "aqualoc_archaeo", "sequence": 8,
            "start_source_index": 0, "end_source_index": 4660,
            "every_n": 2, "method": "klt",
        },
        "policy": value.get("policy") == {
            "frontend_export_permitted": False, "raw_reconstruction_permitted": False,
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
        "launcher_policy": launcher.get("unblocked_before_overlay_exec")
            == [1, 2, 15]
            and launcher.get("exec_replaces_launcher_process") is True,
        **{f"bound_input:{label}": passed for label, passed in input_checks.items()},
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {"status": "PASS" if not failures else "FAIL", "checks": checks,
            "failure_codes": failures, "sealed_fd_owner_pid": owner,
            "identity": manifest_identity}


def replay_manifest_audit(path: Path, item: Mapping[str, Any]) -> dict[str, Any]:
    return V4.replay_manifest_audit(path, item)


def artifact_audit(item: Mapping[str, Any]) -> dict[str, Any]:
    return V4.artifact_audit(item)


def nested_runtime_lineage_audit(
    receipt: Mapping[str, Any], item: Mapping[str, Any], lock: Mapping[str, Any],
) -> dict[str, Any]:
    output = Path(item["output_dir"])
    start, start_identity = stable_json(output / "vins_lifecycle_start_manifest_v4.json")
    mask, mask_identity = stable_json(output / "overlay_signal_mask_manifest_v4.json")
    guard, guard_identity = stable_json(output / "replay_only_guard_manifest.json")
    runtime = receipt["runtime"]
    outputs = receipt.get("artifact_contract", {}).get("outputs", {})
    wrapper_parent = start.get("wrapper_parent_pid")
    launcher_pid = mask.get("launcher_overlay_pid")
    guard_owner = guard.get("sealed_fd_owner_pid")
    mask_owner = mask.get("stable_fd_owner_parent_pid")
    runtime_pid = runtime.get("pid")
    checks = {
        "guard_owner_runtime": guard_owner == runtime_pid,
        "mask_owner_runtime": mask_owner == runtime_pid,
        "guard_mask_owner": guard_owner == mask_owner,
        "guard_identity_bound": outputs.get("replay_only_guard_manifest.json")
            == guard_identity,
        "mask_identity_bound": outputs.get("overlay_signal_mask_manifest_v4.json")
            == mask_identity,
        "start_identity_bound": outputs.get("vins_lifecycle_start_manifest_v4.json")
            == start_identity,
        "launcher_pid": isinstance(launcher_pid, int) and launcher_pid > 1,
        "wrapper_parent": isinstance(wrapper_parent, int) and wrapper_parent > 1,
        "nested_not_direct": wrapper_parent != launcher_pid,
        "wrapper_group": start.get("wrapper_process_group") == runtime_pid,
        "wrapper_session": start.get("wrapper_session") == runtime_pid,
        "child_group": start.get("real_child_process_group") == start.get("wrapper_process_group"),
        "child_session": start.get("real_child_session") == start.get("wrapper_session"),
        "owned_drained": runtime.get("process_group", {}).get("owned_descendants_empty") is True,
    }
    shell = frozen_nested_shell_authority(lock, item)
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "status": "PASS" if not failures else "FAIL", "checks": checks,
        "failure_codes": failures, "start_identity": start_identity,
        "mask_identity": mask_identity, "guard_identity": guard_identity,
        "sealed_fd_owner_pid": guard_owner,
        "stable_fd_owner_parent_pid": mask_owner,
        "runtime_pid": runtime_pid, "launcher_overlay_pid": launcher_pid,
        "wrapper_parent_pid": wrapper_parent, "shell_authority": shell,
        "direct_child_claim": False,
    }


def contract_core(
    bindings: Mapping[str, Any], static_identities: Mapping[str, Any],
    host_net: str, host_user: str,
) -> dict[str, Any]:
    r01 = prior_r01_authority(bindings)
    r02 = prior_r02_authority(bindings)
    r03 = prior_r03_authority(bindings)
    freeze = collect_analysis_v5_design_freeze_binding()
    items = build_items(bindings, host_net, host_user)
    return {
        "schema_version": LOCK_SCHEMA, "status": LOCK_STATUS,
        "campaign": "A08_KLT_ONLY_REMAINING_R04_R05_ROS_HOSTNAME_V5",
        "item_order": list(ITEM_ORDER),
        "declared_repeat_outcomes": {
            "KLT_R01": {"disposition": PRIOR_R01_DISPOSITION, "failure_code": R01_FAILURE_CODE,
                        "source_campaign": "v2", "rerun_permitted": False},
            "KLT_R02": {"disposition": PRIOR_R02_DISPOSITION, "failure_code": R02_FAILURE_CODE,
                        "source_campaign": "v3", "rerun_permitted": False},
            "KLT_R03": {"disposition": PRIOR_R03_DISPOSITION, "failure_code": R03_FAILURE_CODE,
                        "source_campaign": "v4", "rerun_permitted": False},
            **{item: {"disposition": "PREDECLARED_V5_ITEM", "source_campaign": "v5"}
               for item in ITEM_ORDER},
        },
        "policy": {
            "original_declared_repeat_count": 5, "v5_executable_repeat_count": 2,
            "maximum_valid_repeat_count": 2, "single_supervisor_popen_per_item": True,
            "automatic_retry_count": 0, "replacement_repeat_permitted": False,
            "r01_r02_r03_rerun_or_replacement_permitted": False,
            "execution_integrity_failure_blocks_later_items": True,
            "terminal_result_failure_does_not_block_later_items": True,
            "strict_stable_owner_fd_replay_only": True,
            "reuse_frozen_v4_lifecycle_wrapper": True,
            "reuse_frozen_v4_signal_mask_launcher": True,
            "formal_internal_ros_port": ENGINE.FORMAL_PORT,
        },
        "scientific_environment_amendment": {
            "only_permitted_addition": dict(ROS_HOSTNAME_TRANSFORM),
            "all_other_scientific_signal_lifecycle_values_unchanged": True,
        },
        "scientific_boundary": {
            "r01_accuracy": "NA", "r02_accuracy": "NA", "r03_accuracy": "NA",
            "xfeat_accuracy": "NA", "learned_frontend_contribution_claim_permitted": False,
            "valid_repeat_summary_rule": "MEDIAN_OVER_VALID_R04_R05_WITH_VALID_COUNT",
        },
        "host_namespace": {"network": host_net, "user": host_user},
        "frontend_authority": bindings, "prior_r01_authority": r01,
        "prior_r02_authority": r02, "prior_r03_authority": r03,
        "analysis_v5_design_freeze": freeze,
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


def verify_lock(
    lock_path: Path, bindings: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    require(lock_path.absolute() == DEFAULT_LOCK.absolute(), "NONCANONICAL_V5_LOCK_PATH")
    lock, lock_identity = stable_json(lock_path)
    created = lock.get("created_at_utc")
    require(isinstance(created, str) and created, "LOCK_CREATED_AT")
    require(lock == expected_lock_from_current_authority(bindings, created),
            "V5_EXECUTION_LOCK_AUTHORITY_DRIFT")
    return lock, lock_identity


def _configure_engine() -> None:
    assignments = {
        "BACKEND_ROOT": BACKEND_ROOT, "RUNTIME_ROOT": RUNTIME_ROOT,
        "PROTOCOL": PROTOCOL, "DEFAULT_LOCK": DEFAULT_LOCK,
        # Frozen v4 obtains the accepted KLT frontend receipt through its v3
        # authority module; v4 itself intentionally does not re-export a
        # ``KLT_RECEIPT`` attribute.
        "KLT_RECEIPT": V4.V3.KLT_RECEIPT,
        "DEFAULT_RECEIPTS": {"klt": V4.V3.KLT_RECEIPT},
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


def prior_receipt(
    lock_identity: Mapping[str, Any], item: Mapping[str, Any],
) -> dict[str, Any]:
    _configure_engine()
    receipt = BASE_PRIOR_RECEIPT(lock_identity, item)
    semantic = receipt["artifact_contract"]["semantic_checks"]
    require(semantic.get("overlay_signal_mask", {}).get("status") == "PASS",
            f"PRIOR_SIGNAL_MASK:{item['item_id']}")
    require(semantic.get("vins_lifecycle", {}).get("contract_integrity") is True,
            f"PRIOR_LIFECYCLE_CONTRACT:{item['item_id']}")
    lock, _ = stable_json(DEFAULT_LOCK)
    lineage = nested_runtime_lineage_audit(receipt, item, lock)
    require(lineage["status"] == "PASS", f"PRIOR_NESTED_LINEAGE:{item['item_id']}")
    start, _ = stable_json(
        Path(item["output_dir"]) / "vins_lifecycle_start_manifest_v4.json"
    )
    expected_selected = {
        key: item["env"][key] for key in SCIENTIFIC_ENV_KEYS if key in item["env"]
    }
    require(start.get("scientific_environment") == expected_selected,
            f"PRIOR_LOCKED_SCIENTIFIC_ENVIRONMENT:{item['item_id']}")
    return receipt


def inspect_item_readonly(item_id: str) -> dict[str, Any]:
    _configure_engine()
    return ENGINE.inspect_item_readonly(item_id)


def preflight_readonly(lock_path: Path = DEFAULT_LOCK) -> dict[str, Any]:
    try:
        require(lock_path.absolute() == DEFAULT_LOCK.absolute(), "NONCANONICAL_V5_LOCK_PATH")
        bindings = resolve_frontend_bindings()
        r01 = prior_r01_authority(bindings)
        r02 = prior_r02_authority(bindings)
        r03 = prior_r03_authority(bindings)
        if not lock_path.exists() and not lock_path.is_symlink():
            if not ANALYSIS_V5_DESIGN_FREEZE.exists() and not ANALYSIS_V5_DESIGN_FREEZE.is_symlink():
                return {
                    "status": "WAITING_ANALYSIS_V5_STATIC_DESIGN_FREEZE", "read_only": True,
                    "prior_r01_authority": r01, "prior_r02_authority": r02,
                    "prior_r03_authority": r03,
                    "analysis_v5_design_freeze": str(ANALYSIS_V5_DESIGN_FREEZE),
                    "backend_lock_build_permitted": False,
                    "backend_item_launch_permitted": False,
                    "lock_path": str(lock_path.absolute()), "lock_present": False,
                    "item_order": list(ITEM_ORDER),
                }
            freeze = collect_analysis_v5_design_freeze_binding()
            require_campaign_unstarted()
            core = contract_core(bindings, collect_static_identities(),
                                 current_namespace("net"), current_namespace("user"))
            return {
                "status": "READY_TO_BUILD_KLT_ONLY_REMAINING_V5_EXECUTION_LOCK",
                "read_only": True, "prior_r01_authority": r01,
                "prior_r02_authority": r02, "prior_r03_authority": r03,
                "analysis_v5_design_freeze": freeze,
                "candidate_core_sha256": compact_sha256(core),
                "lock_path": str(lock_path.absolute()), "lock_present": False,
                "item_order": list(ITEM_ORDER),
            }
        lock, lock_identity = verify_lock(lock_path, bindings)
        return {
            "status": "PASS_LOCKED_READY_FOR_AUTHORIZED_REMAINING_KLT_ITEM",
            "read_only": True, "prior_r01_authority": r01,
            "prior_r02_authority": r02, "prior_r03_authority": r03,
            "lock": lock_identity, "contract_sha256": lock["contract_sha256"],
            "item_order": list(ITEM_ORDER),
        }
    except (BackendProtocolError, OSError, ValueError, RuntimeError) as error:
        return {"status": "BLOCKED_PREFLIGHT", "read_only": True,
                "error": f"{type(error).__name__}:{error}",
                "lock_path": str(lock_path.absolute()), "item_order": list(ITEM_ORDER)}


def audit_readonly(lock_path: Path = DEFAULT_LOCK) -> dict[str, Any]:
    preflight = preflight_readonly(lock_path)
    rows = [inspect_item_readonly(item) for item in ITEM_ORDER]
    return {"status": "READ_ONLY_AUDIT", "read_only": True,
            "preflight": preflight, "item_order": list(ITEM_ORDER), "items": rows,
            "r01_r02_r03_rerun_permitted": False,
            "maximum_valid_repeat_count": 2}


def execute_item(
    lock_path: Path, item_id: str, authorization_token: str,
) -> tuple[int, dict[str, Any]]:
    require(lock_path.absolute() == DEFAULT_LOCK.absolute(), "NONCANONICAL_V5_LOCK_PATH")
    require(item_id in ITEM_ORDER, f"ITEM_ID:{item_id}")
    require(authorization_token == AUTHORIZATION_TOKENS[item_id], "AUTHORIZATION_TOKEN")
    _configure_engine()
    return ENGINE.execute_item(lock_path, item_id, authorization_token)


def build_lock(lock_path: Path, authorization_token: str) -> dict[str, Any]:
    require(lock_path.absolute() == DEFAULT_LOCK.absolute(), "NONCANONICAL_V5_LOCK_PATH")
    require(authorization_token == BUILD_LOCK_TOKEN, "BUILD_LOCK_AUTHORIZATION_TOKEN")
    require(not lock_path.exists() and not lock_path.is_symlink(), "LOCK_ALREADY_EXISTS")
    bindings = resolve_frontend_bindings()
    prior_r01_authority(bindings); prior_r02_authority(bindings); prior_r03_authority(bindings)
    collect_analysis_v5_design_freeze_binding(); require_campaign_unstarted()
    payload = expected_lock_from_current_authority(
        bindings, datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    ENGINE.safety_module().atomic_publish(
        lock_path, payload, propagate_interruption_after_commit=True
    )
    return {"status": "KLT_ONLY_REMAINING_V5_EXECUTION_LOCK_PUBLISHED",
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
        print(f"A08_KLT_ONLY_REMAINING_V5_ERROR:{type(error).__name__}:{error}",
              file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
