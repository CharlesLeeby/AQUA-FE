#!/usr/bin/env python3
"""Additive A08 analysis after consumed R01--R03 infrastructure NAs.

Importing this module is inert.  The static design freeze must precede every
backend-v5 lock or R04/R05 artifact.  Only accepted backend-v5 R04/R05
trajectories can enter the frozen common-support evaluator.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import sys
from types import ModuleType
from typing import Any, Mapping, Optional, Sequence


WORKSPACE = Path("/home/ma/AQUA-FE_WS")
EXPERIMENT = Path("/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1")

ANALYSIS_V4_PROTOCOL = WORKSPACE / "papers/a08_hfnet_vs_klt_only_common_support_v4_protocol.md"
ANALYSIS_V4_RUNNER = WORKSPACE / "scripts/run_a08_hfnet_vs_klt_only_common_support_v4.py"
ANALYSIS_V4_TESTS = WORKSPACE / "scripts/tests/test_run_a08_hfnet_vs_klt_only_common_support_v4.py"
ANALYSIS_V4_DESIGN_FREEZE = WORKSPACE / "papers/a08_hfnet_vs_klt_only_common_support_v4_design_freeze.json"
ANALYSIS_V4_LOCK = WORKSPACE / "papers/a08_hfnet_vs_klt_only_common_support_v4_execution_lock.json"
ANALYSIS_V4_OUTPUT = EXPERIMENT / "hfnet_vs_klt_only_common_support_v4"
ANALYSIS_V4_CLAIM = EXPERIMENT / "hfnet_vs_klt_only_common_support_start_claim_v4.json"

BACKEND_V4_PROTOCOL = WORKSPACE / (
    "papers/a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v4_protocol.md"
)
BACKEND_V4_RUNNER = WORKSPACE / (
    "scripts/run_a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v4.py"
)
BACKEND_V4_GUARD = WORKSPACE / (
    "scripts/run_a08_recovered_july_history_matched_backend_klt_only_replay_guard_v4.sh"
)
BACKEND_V4_LIFECYCLE_WRAPPER = WORKSPACE / "scripts/run_a08_vins_node_lifecycle_wrapper_v4.py"
BACKEND_V4_SIGNAL_MASK_LAUNCHER = WORKSPACE / "scripts/run_a08_unblocked_overlay_exec_v4.py"
BACKEND_V4_TESTS = WORKSPACE / (
    "scripts/tests/test_run_a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v4.py"
)
BACKEND_V4_LOCK = WORKSPACE / (
    "papers/a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v4_execution_lock.json"
)
BACKEND_V4_ROOT = EXPERIMENT / "backend_klt_only_remaining_replays_v4"
BACKEND_V4_RUNTIME_ROOT = EXPERIMENT / "runtime/backend_klt_only_remaining_replays_v4"
BACKEND_V4_RECEIPT_NAME = "formal_run_receipt_v4.json"
R03_RECEIPT = BACKEND_V4_ROOT / "KLT_R03" / BACKEND_V4_RECEIPT_NAME

BACKEND_V5_PROTOCOL = WORKSPACE / (
    "papers/a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v5_protocol.md"
)
BACKEND_V5_RUNNER = WORKSPACE / (
    "scripts/run_a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v5.py"
)
BACKEND_V5_GUARD = WORKSPACE / (
    "scripts/run_a08_recovered_july_history_matched_backend_klt_only_replay_guard_v5.sh"
)
# Backend v5 intentionally reuses the frozen, identity-bound v4 lifecycle
# wrapper and signal-mask launcher.  Only its replay guard is new.
BACKEND_V5_LIFECYCLE_WRAPPER = BACKEND_V4_LIFECYCLE_WRAPPER
BACKEND_V5_SIGNAL_MASK_LAUNCHER = BACKEND_V4_SIGNAL_MASK_LAUNCHER
BACKEND_V5_TESTS = WORKSPACE / (
    "scripts/tests/test_run_a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v5.py"
)
BACKEND_V5_LOCK = WORKSPACE / (
    "papers/a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v5_execution_lock.json"
)
BACKEND_V5_ROOT = EXPERIMENT / "backend_klt_only_remaining_replays_v5"
BACKEND_V5_RUNTIME_ROOT = EXPERIMENT / "runtime/backend_klt_only_remaining_replays_v5"
BACKEND_V5_RECEIPT_NAME = "formal_run_receipt_v5.json"
BACKEND_V5_PYTHON38 = Path("/usr/bin/python3.8")
BACKEND_V5_VINS_NODE = Path(
    "/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node"
)
BACKEND_OVERLAY_RUN_ROOT = (
    EXPERIMENT / "recovered_july_core_overlay_v1/logs/aqualoc_archaeo_vins"
)

PROTOCOL = WORKSPACE / "papers/a08_hfnet_vs_klt_only_common_support_v5_protocol.md"
RUNNER = WORKSPACE / "scripts/run_a08_hfnet_vs_klt_only_common_support_v5.py"
TESTS = WORKSPACE / "scripts/tests/test_run_a08_hfnet_vs_klt_only_common_support_v5.py"
DESIGN_FREEZE = WORKSPACE / "papers/a08_hfnet_vs_klt_only_common_support_v5_design_freeze.json"
DEFAULT_LOCK = WORKSPACE / "papers/a08_hfnet_vs_klt_only_common_support_v5_execution_lock.json"

OUTPUT_ROOT = EXPERIMENT / "hfnet_vs_klt_only_common_support_v5"
CLAIM_PATH = EXPERIMENT / "hfnet_vs_klt_only_common_support_start_claim_v5.json"
STAGING_ROOT = EXPERIMENT / ".hfnet_vs_klt_only_common_support_v5.staging"
EVO_WORK_ROOT = EXPERIMENT / ".hfnet_vs_klt_only_common_support_v5.evo_work"
FAILURE_STAGING_ROOT = EXPERIMENT / ".hfnet_vs_klt_only_common_support_v5.failure_staging"

FULL_ITEM_ORDER = tuple(f"KLT_R{repeat:02d}" for repeat in range(1, 6))
V5_ITEM_ORDER = ("KLT_R04", "KLT_R05")
ORIGINAL_TEN_SLOT_ORDER = tuple(
    slot for repeat in range(1, 6)
    for slot in (f"KLT_R{repeat:02d}", f"XFEAT_R{repeat:02d}")
)
R01_DISPOSITION = (
    "NA_BACKEND_INFRASTRUCTURE_FD_INHERITANCE_FAILURE_"
    "NO_REPLAY_NO_REPLACEMENT"
)
R01_FAILURE_CODE = "ROSBAG_PYTHON_SUBPROCESS_CLOSE_FDS_DROPPED_SEALED_FD9"
R02_DISPOSITION = (
    "NA_BACKEND_INFRASTRUCTURE_VINS_SIGTERM_CLEANUP_TIMEOUT_"
    "AFTER_COMPLETE_REPLAY_NO_REPLACEMENT"
)
R02_FAILURE_CODE = "OVERLAY_CLEANUP_WAIT_BLOCKED_ON_SIGTERM_MASKED_VINS_PROCESS"
R03_DISPOSITION = (
    "NA_BACKEND_INFRASTRUCTURE_RUNTIME_ENV_AUDIT_CONTRACT_MISMATCH_"
    "AFTER_COMPLETE_REPLAY_NO_REPLACEMENT"
)
R03_FAILURE_CODE = (
    "LOCKED_ITEM_ENV_OMITTED_OVERLAY_ROS_HOSTNAME_LOCALHOST_"
    "LIFECYCLE_AUDIT_MISMATCH"
)
XFEAT_DISPOSITION = "NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED"

DESIGN_FREEZE_SCHEMA = "aqua-fe-a08-hfnet-vs-klt-only-common-support-design-freeze-v5"
DESIGN_FREEZE_STATUS = (
    "FROZEN_AFTER_R01_R02_R03_INFRASTRUCTURE_FAILURES_"
    "BEFORE_R04_R05_BACKEND_AND_ACCURACY"
)
LOCK_SCHEMA = "aqua-fe-a08-hfnet-vs-klt-only-common-support-lock-v5"
LOCK_STATUS = "FROZEN_AFTER_TWO_V5_TERMINAL_RECEIPTS_BEFORE_ACCURACY_VISIBLE"
CLAIM_SCHEMA = "aqua-fe-a08-hfnet-vs-klt-only-common-support-claim-v5"
RECEIPT_SCHEMA = "aqua-fe-a08-hfnet-vs-klt-only-common-support-receipt-v5"
FORMAL_SCHEMA = "aqua-fe-a08-formal-hfnet-vs-klt-only-common-support-summary-v5"

FREEZE_TOKEN = (
    "A08_FREEZE_HFNET_VS_KLT_ONLY_COMMON_SUPPORT_V5_AFTER_R01_R02_R03_"
    "BEFORE_R04_R05_BACKEND"
)
BUILD_LOCK_TOKEN = (
    "A08_BUILD_HFNET_VS_KLT_ONLY_COMMON_SUPPORT_V5_LOCK_AFTER_TWO_TERMINALS_"
    "BEFORE_ACCURACY"
)
RUN_TOKEN = "A08_RUN_HFNET_VS_KLT_ONLY_COMMON_SUPPORT_V5_EXACTLY_ONCE_NO_RETRY"

GRID_NAME = "exact_integer_ns_grid_v5.json"
RAW_SUMMARY_NAME = "common_support_summary.json"
GRID_AUDIT_NAME = "common_grid_audit.csv"
RAW_METRICS_NAME = "common_support_metrics.csv"
RAW_DIAGNOSTIC_MANIFEST_NAME = "raw_numeric_diagnostics_boundary_v5.json"
REPEAT_TABLE_NAME = "original_ten_slot_dispositions_v5.csv"
FORMAL_SUMMARY_NAME = "formal_hfnet_vs_klt_only_summary_v5.json"
EVO_SUMMARY_NAME = "evo_crosscheck.json"
RECEIPT_NAME = "formal_analysis_receipt_v5.json"
PARTIAL_EVIDENCE_NAME = "uncommitted_partial_evidence_v5.json"

FROZEN_ANALYSIS_V4_EXPECTED = {
    "protocol": (9_217, "1880f16fce15964a5cc8c4d4b1f523fc2d99bf37dd0f1a7a2c4faa72908e12a1"),
    "runner": (59_673, "4a7be30e81341cf7ae1b4ebef0e3544a24a052498f7ead2ac3286e6aa7cd4cf9"),
    "tests": (28_900, "72148353de37fa554144bbb0df19708cb5df1816d3dfad550490b04ed0576e1d"),
    "design_freeze": (25_864, "2320b6c904fd10c6d2afa435aa771b750d641c50e62ee6f2511fade077e6cd34"),
}
FROZEN_BACKEND_V4_EXPECTED = {
    "protocol": (9_441, "e4fc7ca38ed22e2b350a507dde0a0d9e354c7dd2f427a5fdbd01fb0cd00b1467"),
    "runner": (64_551, "b0c5d3e77233bff595f372882cec6c99208fe198d11e4482f7e10c4836e58786"),
    "guard": (18_863, "1be1fafeb59cd1b1e44458e5165214423e87de09434920df16d2a7c34f9bcd47"),
    "lifecycle_wrapper": (15_881, "c2aa603efd85b1800757be6d002aced88a0d89d2043ff5ee43dfa3457a0b9244"),
    "signal_mask_launcher": (6_340, "8d9b188734d6fcae268496f572c965f341249830405745dfe8d09e831e522722"),
    "tests": (14_615, "96dac289a3a4d46410d6b7d9b216d172ffae76f7dca5fd459e7978a4e9b4f4f2"),
    "execution_lock": (100_210, "e28d61cf17116bc0fade98bf84f0a88f48831bbff442096abf877ef7226e15da"),
}

R03_TERMINAL_EXPECTED: tuple[int, str] = (
    16_673,
    "8c40956b037acf078a820c0f3fb870d9607818bcd5bdd4a649e6df969a2bdf10",
)
R03_EXPECTED_TRAJECTORY_ROWS = 2_319
R03_ARTIFACT_ISSUE = "VINS_LIFECYCLE_GATE:LIFECYCLE_NOT_ACCEPTED,start:environment"
R03_INTEGRITY_ISSUE = "VINS_LIFECYCLE_MANIFEST_CONTRACT"
R03_INTEGRITY_LATCH = "ARTIFACT_INTEGRITY:VINS_LIFECYCLE_MANIFEST_CONTRACT"
R03_PRIOR_DEEP_FAILURE = "PRIOR_EXECUTION_INTEGRITY:KLT_R03"
V5_ENVIRONMENT_AMENDMENT = {"ROS_HOSTNAME": "localhost"}


def _raw_identity(path: Path) -> tuple[int, str]:
    raw = path.read_bytes()
    return len(raw), hashlib.sha256(raw).hexdigest()


def _load_frozen_analysis_v4() -> ModuleType:
    path = ANALYSIS_V4_RUNNER.absolute()
    if (
        not path.exists() or path.is_symlink()
        or not stat.S_ISREG(path.lstat().st_mode)
        or path.resolve(strict=True) != path
        or _raw_identity(path) != FROZEN_ANALYSIS_V4_EXPECTED["runner"]
    ):
        raise RuntimeError("FROZEN_ANALYSIS_V4_RUNNER_IDENTITY_DRIFT")
    specification = importlib.util.spec_from_file_location(
        "a08_hfnet_klt_analysis_v4_frozen_engine_for_v5", path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("FROZEN_ANALYSIS_V4_IMPORT_SPEC")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


V4 = _load_frozen_analysis_v4()
ENGINE = V4.ENGINE
AnalysisProtocolError = V4.AnalysisProtocolError
require = V4.require
identity = V4.identity
stable_json = V4.stable_json
compact_sha256 = V4.compact_sha256
atomic_publish = V4.atomic_publish
common = V4.common
PRIMARY_METRICS = V4.PRIMARY_METRICS

_V4_EXACT_GRID_EVIDENCE = V4.exact_grid_evidence
_V4_DESIGN_CONTRACT_SNAPSHOT = V4.design_contract_snapshot
_V4_COLLECT_KLT_FRONTEND_BINDING = V4.collect_klt_frontend_binding
_V4_COLLECT_XFEAT_EXCLUSION = V4.collect_xfeat_exclusion
_V4_PRIOR_R01_BINDING = V4.prior_r01_binding
_V4_PRIOR_R02_BINDING = V4.prior_r02_binding
_V4_LOAD_BACKEND_AUTHORITY = V4.load_backend_v4_authority_module
_V4_VALIDATE_BACKEND_TERMINAL = V4._V3_VALIDATE_BACKEND_TERMINAL
_V4_ORIGINAL_TEN_SLOT_ROWS = V4.original_ten_slot_rows
_V4_BUILD_FORMAL_SUMMARY = V4.build_formal_summary
_V4_BUILD_ERROR_FORMAL_SUMMARY = V4.build_error_formal_summary
_V4_VALIDATE_FORMAL_POPULATION = V4.validate_formal_population_binding
_V4_MAKE_TERMINAL_RECEIPT = V4.make_terminal_receipt


def exact_grid_evidence() -> dict[str, Any]:
    value = _V4_EXACT_GRID_EVIDENCE()
    value["schema_version"] = "aqua-fe-a08-exact-integer-ns-grid-v5"
    return value


def collect_klt_frontend_binding() -> dict[str, Any]:
    return _V4_COLLECT_KLT_FRONTEND_BINDING()


def collect_xfeat_exclusion() -> dict[str, Any]:
    value = _V4_COLLECT_XFEAT_EXCLUSION()
    require(value.get("disposition") == XFEAT_DISPOSITION, "XFEAT_DISPOSITION")
    return value


def prior_r01_binding() -> dict[str, Any]:
    value = _V4_PRIOR_R01_BINDING()
    require(
        value.get("disposition") == R01_DISPOSITION
        and value.get("failure_code") == R01_FAILURE_CODE
        and value.get("artifact_accepted") is False
        and value.get("rerun_or_replacement_permitted") is False,
        "R01_FROZEN_BOUNDARY",
    )
    return value


def prior_r02_binding() -> dict[str, Any]:
    value = _V4_PRIOR_R02_BINDING()
    require(
        value.get("disposition") == R02_DISPOSITION
        and value.get("failure_code") == R02_FAILURE_CODE
        and value.get("artifact_accepted") is False
        and value.get("trajectory_admitted") is False
        and value.get("rerun_or_replacement_permitted") is False,
        "R02_FROZEN_BOUNDARY",
    )
    return value


def _check_frozen_lineage_identities() -> dict[str, Any]:
    paths = {
        "analysis_v4_protocol": ANALYSIS_V4_PROTOCOL,
        "analysis_v4_runner": ANALYSIS_V4_RUNNER,
        "analysis_v4_tests": ANALYSIS_V4_TESTS,
        "analysis_v4_design_freeze": ANALYSIS_V4_DESIGN_FREEZE,
        "backend_v4_protocol": BACKEND_V4_PROTOCOL,
        "backend_v4_runner": BACKEND_V4_RUNNER,
        "backend_v4_guard": BACKEND_V4_GUARD,
        "backend_v4_lifecycle_wrapper": BACKEND_V4_LIFECYCLE_WRAPPER,
        "backend_v4_signal_mask_launcher": BACKEND_V4_SIGNAL_MASK_LAUNCHER,
        "backend_v4_tests": BACKEND_V4_TESTS,
        "backend_v4_execution_lock": BACKEND_V4_LOCK,
    }
    values = {label: identity(path) for label, path in paths.items()}
    for short, expected in FROZEN_ANALYSIS_V4_EXPECTED.items():
        key = f"analysis_v4_{short}"
        observed = values[key]
        require((observed["size_bytes"], observed["sha256"]) == expected,
                f"FROZEN_ANALYSIS_V4_IDENTITY:{short}")
    for short, expected in FROZEN_BACKEND_V4_EXPECTED.items():
        key = f"backend_v4_{short}"
        observed = values[key]
        require((observed["size_bytes"], observed["sha256"]) == expected,
                f"FROZEN_BACKEND_V4_IDENTITY:{short}")
    freeze, _ = stable_json(ANALYSIS_V4_DESIGN_FREEZE)
    require(
        freeze.get("schema_version")
        == "aqua-fe-a08-hfnet-vs-klt-only-common-support-design-freeze-v4"
        and freeze.get("status")
        == "FROZEN_AFTER_R01_R02_INFRASTRUCTURE_FAILURES_BEFORE_R03_R05_BACKEND_AND_ACCURACY",
        "FROZEN_ANALYSIS_V4_DESIGN_FREEZE_SEMANTICS",
    )
    return values


def load_backend_v4_authority_module() -> ModuleType:
    return _V4_LOAD_BACKEND_AUTHORITY()


def validate_r03_terminal_receipt(
    receipt: Mapping[str, Any], receipt_id: Mapping[str, Any],
    lock_id: Mapping[str, Any], locked_item: Mapping[str, Any],
    reconstructed_artifact: Mapping[str, Any],
    *, expected_identity: Optional[tuple[int, str]] = None,
) -> dict[str, Any]:
    expected = R03_TERMINAL_EXPECTED if expected_identity is None else expected_identity
    require(
        (receipt_id.get("size_bytes"), receipt_id.get("sha256")) == expected,
        "R03_TERMINAL_RECEIPT_IDENTITY",
    )
    integrity = receipt.get("execution_integrity")
    runtime = receipt.get("runtime")
    group = runtime.get("process_group") if isinstance(runtime, dict) else None
    artifact = receipt.get("artifact_contract")
    outputs = artifact.get("outputs") if isinstance(artifact, dict) else None
    semantic = artifact.get("semantic_checks") if isinstance(artifact, dict) else None
    trajectory = semantic.get("trajectory") if isinstance(semantic, dict) else None
    usability = semantic.get("backend_usability") if isinstance(semantic, dict) else None
    replay = semantic.get("replay_manifest") if isinstance(semantic, dict) else None
    guard = semantic.get("replay_only_guard") if isinstance(semantic, dict) else None
    network = semantic.get("network_namespace") if isinstance(semantic, dict) else None
    lifecycle = semantic.get("vins_lifecycle") if isinstance(semantic, dict) else None
    signal_mask = semantic.get("overlay_signal_mask") if isinstance(semantic, dict) else None
    require(
        receipt.get("schema_version")
        == "aqua-fe-a08-recovered-july-backend-klt-only-remaining-receipt-v4"
        and receipt.get("status") == "FAILED_BACKEND_REPLAY_NO_REPLACEMENT"
        and receipt.get("item_id") == "KLT_R03"
        and receipt.get("repeat_index") == 3
        and receipt.get("execution_lock") == lock_id
        and receipt.get("launch_allowance_consumed") is True
        and receipt.get("retry_count") == 0
        and receipt.get("replacement_permitted") is False
        and receipt.get("supervisor_errors") == []
        and receipt.get("trajectory_convention") == "world_T_body",
        "R03_TERMINAL_CONTROL",
    )
    require(
        isinstance(integrity, dict)
        and integrity.get("status") == "FAIL"
        and integrity.get("irreversible_fault_latch_clear") is False
        and integrity.get("claim_stable") is True
        and integrity.get("workspace_binding_stable") is True
        and integrity.get("owned_processes_drained") is True
        and integrity.get("artifact_integrity_issues") == [R03_INTEGRITY_ISSUE]
        and receipt.get("integrity_fault_latch") == [R03_INTEGRITY_LATCH],
        "R03_EXPECTED_INFRASTRUCTURE_INTEGRITY_LATCH",
    )
    require(
        isinstance(runtime, dict)
        and runtime.get("popen_invocation_count") == 1
        and runtime.get("child_started") is True
        and runtime.get("timed_out") is False
        and runtime.get("raw_return_code") == 0
        and isinstance(group, dict)
        and group.get("leader_reaped") is True
        and group.get("process_group_empty") is True
        and group.get("owned_descendants_empty") is True
        and group.get("normal_exit_path") is True,
        "R03_COMPLETE_NORMAL_RUNTIME",
    )
    require(
        isinstance(artifact, dict)
        and artifact == reconstructed_artifact
        and artifact.get("status") == "FAIL"
        and artifact.get("issues") == [R03_ARTIFACT_ISSUE]
        and artifact.get("evidence_tree_integrity") is True
        and artifact.get("integrity_issues") == [R03_INTEGRITY_ISSUE]
        and isinstance(outputs, dict)
        and set(outputs) == set(locked_item.get("expected_outputs", [])),
        "R03_RECONSTRUCTED_COMPLETE_UNACCEPTED_ARTIFACTS",
    )
    require(
        isinstance(trajectory, dict)
        and trajectory.get("rows") == R03_EXPECTED_TRAJECTORY_ROWS
        and trajectory.get("convention") == "world_T_body"
        and isinstance(usability, dict)
        and usability.get("status") == "PASS"
        and usability.get("values", {}).get("output_poses") == 2319.0
        and usability.get("values", {}).get("matched") == 2319.0
        and usability.get("values", {}).get("output_coverage_ratio") == 0.99485
        and isinstance(replay, dict)
        and replay.get("status") == "PASS"
        and replay.get("missing_keys") == []
        and replay.get("conflicting_keys") == []
        and replay.get("child_self_fd_value_keys") == []
        and replay.get("explicit_lineage_conflict") is False
        and replay.get("sealed_fd_owner_pid") == runtime.get("pid")
        and isinstance(guard, dict)
        and guard.get("status") == "PASS"
        and guard.get("sealed_fd_owner_pid") == runtime.get("pid")
        and isinstance(network, dict) and network.get("status") == "PASS"
        and isinstance(signal_mask, dict) and signal_mask.get("status") == "PASS"
        and signal_mask.get("contract_integrity") is True
        and signal_mask.get("blocked_signals_after") == []
        and isinstance(lifecycle, dict) and lifecycle.get("status") == "FAIL"
        and lifecycle.get("contract_integrity") is False
        and lifecycle.get("failure_codes") == ["LIFECYCLE_NOT_ACCEPTED", "start:environment"]
        and lifecycle.get("real_child_reaped") is True
        and lifecycle.get("shutdown_stage_audit", {}).get("status") == "PASS"
        and lifecycle.get("wrapper_signal_sequence_audit", {}).get("status") == "PASS",
        "R03_COMPLETE_REPLAY_SINGLE_ENV_AUDIT_MISMATCH",
    )
    locked_env = locked_item.get("env")
    require(isinstance(locked_env, dict) and "ROS_HOSTNAME" not in locked_env,
            "R03_LOCKED_ENV_MUST_OMIT_ROS_HOSTNAME")
    start_manifest, start_id = stable_json(
        Path(str(outputs["vins_lifecycle_start_manifest_v4.json"]["path"]))
    )
    selected = {
        key: locked_env[key]
        for key in load_backend_v4_authority_module().SCIENTIFIC_ENV_KEYS
        if key in locked_env
    }
    require(
        start_manifest.get("scientific_environment")
        == {**selected, "ROS_HOSTNAME": "localhost"}
        and lifecycle.get("start_identity") == start_id,
        "R03_EXACT_OVERLAY_ROS_HOSTNAME_LOCALHOST_DELTA",
    )
    process_log = receipt.get("process_log")
    require(isinstance(process_log, dict), "R03_PROCESS_LOG_IDENTITY")
    require(identity(Path(str(process_log.get("path", "")))) == process_log,
            "R03_PROCESS_LOG_LIVE_IDENTITY")
    claim = receipt.get("claim")
    require(isinstance(claim, dict) and identity(Path(str(claim.get("path", "")))) == claim,
            "R03_CLAIM_LIVE_IDENTITY")
    for relative, claim in outputs.items():
        require(
            isinstance(claim, dict)
            and identity(Path(str(claim.get("path", "")))) == claim,
            f"R03_ARTIFACT_LIVE_IDENTITY:{relative}",
        )
    return {
        "item_id": "KLT_R03",
        "disposition": R03_DISPOSITION,
        "failure_code": R03_FAILURE_CODE,
        "receipt": dict(receipt_id),
        "v4_execution_lock": dict(lock_id),
        "analysis_v4_design_freeze": identity(ANALYSIS_V4_DESIGN_FREEZE),
        "v4_artifact_receipt_reconstruction": "PASS",
        "v4_base_prior_receipt_audit": "FAIL_EXPECTED_R03_INFRASTRUCTURE",
        "v4_base_prior_failure_code": R03_PRIOR_DEEP_FAILURE,
        "v4_strict_prior_receipt_audit": "FAIL_EXPECTED_R03_INFRASTRUCTURE",
        "v4_strict_prior_failure_code": R03_PRIOR_DEEP_FAILURE,
        "receipt_status": receipt["status"],
        "execution_integrity": "FAIL_EXPECTED_INFRASTRUCTURE_AUDIT_CONTRACT",
        "integrity_fault_latch": [R03_INTEGRITY_LATCH],
        "runtime_timed_out": False,
        "raw_return_code": 0,
        "artifact_contract_status": "FAIL",
        "artifact_issue": R03_ARTIFACT_ISSUE,
        "artifact_integrity_issue": R03_INTEGRITY_ISSUE,
        "artifact_integrity_issues": [R03_INTEGRITY_ISSUE],
        "evidence_tree_integrity": True,
        "complete_artifacts_identity_bound": True,
        "artifact_accepted": False,
        "complete_artifacts": True,
        "complete_artifact_identities": dict(outputs),
        "process_log": dict(process_log),
        "trajectory_complete": True,
        "trajectory_rows": R03_EXPECTED_TRAJECTORY_ROWS,
        "trajectory_identity": dict(outputs["vins_output/vio.csv"]),
        "trajectory_admitted": False,
        "diagnostic_ape_identity": dict(outputs["ape.txt"]),
        "diagnostic_ape_admitted_to_common_support": False,
        "backend_usability_status": "PASS",
        "replay_manifest_semantic_status": "PASS",
        "replay_guard_status": "PASS",
        "overlay_signal_mask_status": "PASS",
        "vins_lifecycle_status": "FAIL_EXPECTED_LOCKED_ENV_AUDIT_MISMATCH",
        "locked_item_ros_hostname_present": False,
        "observed_overlay_ros_hostname": "localhost",
        "runtime_lifecycle_ros_hostname": "localhost",
        "all_other_selected_scientific_environment_equal": True,
        "only_permitted_v5_environment_addition": dict(V5_ENVIRONMENT_AMENDMENT),
        "replay_completed": True,
        "post_result_cleanup_completed": True,
        "counts_as_valid_repeat": False,
        "rerun_or_replacement_permitted": False,
    }


def prior_r03_binding() -> dict[str, Any]:
    require(R03_RECEIPT.exists() and not R03_RECEIPT.is_symlink(),
            "R03_TERMINAL_RECEIPT_NOT_AVAILABLE")
    module = load_backend_v4_authority_module()
    bindings = module.resolve_frontend_bindings()
    lock, lock_id = module.verify_lock(BACKEND_V4_LOCK, bindings)
    require(lock.get("item_order") == ["KLT_R03", "KLT_R04", "KLT_R05"],
            "BACKEND_V4_LOCK_ORDER")
    receipt, receipt_id = stable_json(R03_RECEIPT)
    item = lock["items"]["KLT_R03"]
    base_artifact = module.BASE_ARTIFACT_AUDIT(item)
    require(
        base_artifact.get("status") == "PASS"
        and base_artifact.get("issues") == []
        and base_artifact.get("integrity_issues") == []
        and base_artifact.get("outputs")
            == receipt.get("artifact_contract", {}).get("outputs"),
        "R03_V4_BASE_ARTIFACT_AUDIT",
    )
    reconstructed = module.artifact_audit(item)
    require(reconstructed == receipt.get("artifact_contract"),
            "R03_V4_ARTIFACT_RECEIPT_RECONSTRUCTION")
    for label, deep in (
        ("BASE", module.BASE_PRIOR_RECEIPT),
        ("STRICT", module.prior_receipt),
    ):
        try:
            module._configure_engine()
            deep(lock_id, item)
        except Exception as error:
            require(
                type(error).__name__ == "BackendProtocolError"
                and str(error) == R03_PRIOR_DEEP_FAILURE,
                f"R03_V4_{label}_PRIOR_UNEXPECTED_FAILURE",
            )
        else:
            raise AnalysisProtocolError(f"R03_V4_{label}_PRIOR_MUST_FAIL_INTEGRITY")
    value = validate_r03_terminal_receipt(
        receipt, receipt_id, lock_id, item, reconstructed
    )
    value["v4_base_artifact_audit"] = "PASS"
    return value


def load_backend_v5_authority_module() -> ModuleType:
    for path, label in (
        (BACKEND_V5_PROTOCOL, "protocol"), (BACKEND_V5_RUNNER, "runner"),
        (BACKEND_V5_GUARD, "guard"),
        (BACKEND_V5_LIFECYCLE_WRAPPER, "lifecycle-wrapper"),
        (BACKEND_V5_SIGNAL_MASK_LAUNCHER, "signal-mask-launcher"),
        (BACKEND_V5_TESTS, "tests"),
    ):
        common.regular_file(path, f"backend-v5-{label}")
    specification = importlib.util.spec_from_file_location(
        "a08_klt_remaining_backend_v5_authority_for_analysis", BACKEND_V5_RUNNER
    )
    require(specification is not None and specification.loader is not None,
            "BACKEND_V5_AUTHORITY_IMPORT_SPEC")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    for name in (
        "resolve_frontend_bindings", "verify_lock", "prior_receipt",
        "prior_r01_authority", "prior_r02_authority", "prior_r03_authority",
        "ITEM_ORDER",
        "BACKEND_ROOT", "DEFAULT_LOCK", "RECEIPT_NAME", "LOCK_SCHEMA",
        "LOCK_STATUS", "RECEIPT_SCHEMA", "PROTOCOL", "RUNNER",
        "REPLAY_ONLY_GUARD", "LIFECYCLE_WRAPPER", "PROCESS_FREE_TESTS",
        "SIGNAL_MASK_LAUNCHER", "PYTHON38", "REAL_VINS",
    ):
        require(hasattr(module, name), f"BACKEND_V5_INTERFACE:{name}")
    require(tuple(module.ITEM_ORDER) == V5_ITEM_ORDER, "BACKEND_V5_ITEM_ORDER")
    require(Path(module.BACKEND_ROOT) == BACKEND_V5_ROOT, "BACKEND_V5_ROOT")
    require(Path(module.DEFAULT_LOCK) == BACKEND_V5_LOCK, "BACKEND_V5_LOCK")
    require(module.RECEIPT_NAME == BACKEND_V5_RECEIPT_NAME, "BACKEND_V5_RECEIPT")
    require(Path(module.PROTOCOL) == BACKEND_V5_PROTOCOL, "BACKEND_V5_PROTOCOL")
    require(Path(module.RUNNER) == BACKEND_V5_RUNNER, "BACKEND_V5_RUNNER")
    require(Path(module.REPLAY_ONLY_GUARD) == BACKEND_V5_GUARD, "BACKEND_V5_GUARD")
    require(Path(module.LIFECYCLE_WRAPPER) == BACKEND_V5_LIFECYCLE_WRAPPER,
            "BACKEND_V5_LIFECYCLE_WRAPPER")
    require(Path(module.SIGNAL_MASK_LAUNCHER) == BACKEND_V5_SIGNAL_MASK_LAUNCHER,
            "BACKEND_V5_SIGNAL_MASK_LAUNCHER")
    require(Path(module.PROCESS_FREE_TESTS) == BACKEND_V5_TESTS, "BACKEND_V5_TESTS")
    require(Path(module.PYTHON38) == BACKEND_V5_PYTHON38, "BACKEND_V5_PYTHON38")
    require(Path(module.REAL_VINS) == BACKEND_V5_VINS_NODE, "BACKEND_V5_VINS_NODE")
    return module


def _r01_population_row(prior: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "item_id": "KLT_R01", "arm": "klt", "repeat_index": 1,
        "disposition": R01_DISPOSITION, "accepted_for_joint_mask": False,
        "trajectory": None, "scientific_failure_retained_as_na": False,
        "backend_infrastructure_failure_retained_as_na": True,
        "backend_launched": True, "backend_replay_started": False,
        "backend_replay_completed": False, "post_result_cleanup_failed": False,
        "replacement_permitted": False, "receipt": prior["receipt"],
    }


def _r02_population_row(prior: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "item_id": "KLT_R02", "arm": "klt", "repeat_index": 2,
        "disposition": R02_DISPOSITION, "accepted_for_joint_mask": False,
        "trajectory": None, "scientific_failure_retained_as_na": False,
        "backend_infrastructure_failure_retained_as_na": True,
        "backend_launched": True, "backend_replay_started": True,
        "backend_replay_completed": True, "post_result_cleanup_failed": True,
        "complete_unaccepted_trajectory": prior["trajectory_identity"],
        "replacement_permitted": False, "receipt": prior["receipt"],
    }


def _r03_population_row(prior: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "item_id": "KLT_R03", "arm": "klt", "repeat_index": 3,
        "disposition": R03_DISPOSITION, "accepted_for_joint_mask": False,
        "trajectory": None, "scientific_failure_retained_as_na": False,
        "backend_infrastructure_failure_retained_as_na": True,
        "backend_launched": True, "backend_replay_started": True,
        "backend_replay_completed": True, "post_result_cleanup_failed": False,
        "complete_unaccepted_trajectory": prior["trajectory_identity"],
        "replacement_permitted": False, "receipt": prior["receipt"],
    }


def collect_backend_binding() -> dict[str, Any]:
    _configure_engine()
    module = load_backend_v5_authority_module()
    bindings = module.resolve_frontend_bindings()
    require(isinstance(bindings, dict), "BACKEND_V5_FRONTEND_BINDINGS")
    local_klt = collect_klt_frontend_binding()
    local_xfeat = collect_xfeat_exclusion()
    backend_klt = bindings.get("klt")
    backend_xfeat = bindings.get("excluded_xfeat")
    require(
        isinstance(backend_klt, dict)
        and backend_klt.get("receipt") == local_klt["receipt"]
        and backend_klt.get("accepted_receipt") == local_klt["receipt"],
        "BACKEND_V5_KLT_FRONTEND_BINDING",
    )
    require(
        isinstance(backend_xfeat, dict)
        and backend_xfeat.get("disposition") == local_xfeat["disposition"]
        and backend_xfeat.get("accepted_receipt_present") is False
        and backend_xfeat.get("backend_launched_count") == 0
        and backend_xfeat.get("learning_contribution_claim_permitted") is False,
        "BACKEND_V5_XFEAT_EXCLUSION_BINDING",
    )
    lock, lock_id = module.verify_lock(BACKEND_V5_LOCK, bindings)
    require(lock.get("schema_version") == module.LOCK_SCHEMA, "BACKEND_V5_LOCK_SCHEMA")
    require(lock.get("status") == module.LOCK_STATUS, "BACKEND_V5_LOCK_STATUS")
    require(lock.get("item_order") == list(V5_ITEM_ORDER), "BACKEND_V5_LOCK_ORDER")
    prior01 = prior_r01_binding()
    prior02 = prior_r02_binding()
    prior03 = prior_r03_binding()
    live01 = module.prior_r01_authority(bindings)
    live02 = module.prior_r02_authority(bindings)
    live03 = module.prior_r03_authority(bindings)
    require(live01.get("disposition") == R01_DISPOSITION, "BACKEND_V5_PRIOR_R01")
    require(
        live02.get("disposition") == R02_DISPOSITION
        and live02.get("failure_code") == R02_FAILURE_CODE
        and live02.get("artifact_accepted") is False
        and live02.get("rerun_or_replacement_permitted") is False,
        "BACKEND_V5_PRIOR_R02",
    )
    require(
        live03.get("disposition") == R03_DISPOSITION
        and live03.get("failure_code") == R03_FAILURE_CODE
        and live03.get("v4_execution_lock") == prior03["v4_execution_lock"]
        and live03.get("analysis_v4_design_freeze")
            == prior03["analysis_v4_design_freeze"]
        and live03.get("v4_terminal_receipt") == prior03["receipt"]
        and live03.get("v4_base_artifact_audit") == "PASS"
        and live03.get("v4_artifact_receipt_reconstruction") == "PASS"
        and live03.get("v4_base_prior_receipt_audit")
            == "FAIL_EXPECTED_R03_INFRASTRUCTURE"
        and live03.get("v4_base_prior_failure_code") == R03_PRIOR_DEEP_FAILURE
        and live03.get("v4_strict_prior_receipt_audit")
            == "FAIL_EXPECTED_R03_INFRASTRUCTURE"
        and live03.get("v4_strict_prior_failure_code") == R03_PRIOR_DEEP_FAILURE
        and live03.get("execution_integrity")
            == "FAIL_EXPECTED_INFRASTRUCTURE_AUDIT_CONTRACT"
        and live03.get("integrity_fault_latch") == [R03_INTEGRITY_LATCH]
        and live03.get("runtime_timed_out") is False
        and live03.get("raw_return_code") == 0
        and live03.get("artifact_contract_status") == "FAIL"
        and live03.get("artifact_issue") == R03_ARTIFACT_ISSUE
        and live03.get("artifact_integrity_issue") == R03_INTEGRITY_ISSUE
        and live03.get("artifact_integrity_issues") == [R03_INTEGRITY_ISSUE]
        and live03.get("evidence_tree_integrity") is True
        and live03.get("complete_artifacts_identity_bound") is True
        and live03.get("artifact_accepted") is False
        and live03.get("complete_artifacts") is True
        and live03.get("complete_artifact_identities")
            == prior03["complete_artifact_identities"]
        and live03.get("process_log") == prior03["process_log"]
        and live03.get("trajectory_complete") is True
        and live03.get("trajectory_rows") == R03_EXPECTED_TRAJECTORY_ROWS
        and live03.get("trajectory_identity") == prior03["trajectory_identity"]
        and live03.get("trajectory_admitted") is False
        and live03.get("diagnostic_ape_identity")
            == prior03["diagnostic_ape_identity"]
        and live03.get("diagnostic_ape_admitted_to_common_support") is False
        and live03.get("backend_usability_status") == "PASS"
        and live03.get("replay_manifest_semantic_status") == "PASS"
        and live03.get("replay_guard_status") == "PASS"
        and live03.get("overlay_signal_mask_status") == "PASS"
        and live03.get("vins_lifecycle_status")
            == "FAIL_EXPECTED_LOCKED_ENV_AUDIT_MISMATCH"
        and live03.get("replay_completed") is True
        and live03.get("post_result_cleanup_completed") is True
        and live03.get("locked_item_ros_hostname_present") is False
        and live03.get("observed_overlay_ros_hostname") == "localhost"
        and live03.get("runtime_lifecycle_ros_hostname") == "localhost"
        and live03.get("all_other_selected_scientific_environment_equal") is True
        and live03.get("only_permitted_v5_environment_addition")
            == V5_ENVIRONMENT_AMENDMENT
        and live03.get("counts_as_valid_repeat") is False
        and live03.get("rerun_permitted") is False
        and live03.get("replacement_permitted") is False
        and live03.get("rerun_or_replacement_permitted") is False,
        "BACKEND_V5_PRIOR_R03_EVIDENCE_BOUNDARY",
    )
    items = lock.get("items")
    require(isinstance(items, dict) and list(items) == list(V5_ITEM_ORDER),
            "BACKEND_V5_LOCK_ITEMS")
    rows = [
        _r01_population_row(prior01), _r02_population_row(prior02),
        _r03_population_row(prior03),
    ]
    receipts = {
        "KLT_R01": prior01["receipt"], "KLT_R02": prior02["receipt"],
        "KLT_R03": prior03["receipt"],
    }
    for item_id in V5_ITEM_ORDER:
        receipt_path = BACKEND_V5_ROOT / item_id / BACKEND_V5_RECEIPT_NAME
        receipt, receipt_id = stable_json(receipt_path)
        deep = module.prior_receipt(lock_id, items[item_id])
        require(deep == receipt, f"BACKEND_V5_DEEP_TERMINAL:{item_id}")
        row = _V4_VALIDATE_BACKEND_TERMINAL(
            module, item_id, receipt, lock_id, items[item_id]
        )
        row["backend_infrastructure_failure_retained_as_na"] = False
        row["receipt"] = receipt_id
        rows.append(row)
        receipts[item_id] = receipt_id
    valid = sum(
        bool(row["accepted_for_joint_mask"])
        for row in rows if row["item_id"] in V5_ITEM_ORDER
    )
    require(not rows[0]["accepted_for_joint_mask"]
            and not rows[1]["accepted_for_joint_mask"]
            and not rows[2]["accepted_for_joint_mask"],
            "R01_R02_R03_MUST_NEVER_ENTER_JOINT_MASK")
    return {
        "execution_lock": lock_id,
        "execution_contract_sha256": lock.get("contract_sha256"),
        "terminal_receipts": receipts, "planned_repeats": rows,
        "planned_count": 5, "v5_executable_count": 2,
        "v5_terminal_count": 2, "maximum_valid_count": 2,
        "valid_count": valid, "failed_count": 5 - valid,
        "infrastructure_na_count": 3,
        "prior_r01": prior01, "prior_r02": prior02, "prior_r03": prior03,
        "frontend_bindings": bindings,
    }


def collect_static_identities() -> dict[str, Any]:
    frozen = _check_frozen_lineage_identities()
    values = {
        "runner": identity(RUNNER), "protocol": identity(PROTOCOL),
        "process_free_tests": identity(TESTS),
        **{f"frozen_{key}": value for key, value in frozen.items()},
        "common_security_and_numeric_library": identity(ENGINE.COMMON_LIBRARY),
        "primary_evaluator": identity(ENGINE.EVALUATOR),
        "trajectory_eval_core": identity(ENGINE.EVALUATOR_CORE),
        "epoch_nanosecond_adapter": identity(ENGINE.EPOCH_ADAPTER),
        "backend_v5_protocol": identity(BACKEND_V5_PROTOCOL),
        "backend_v5_runner": identity(BACKEND_V5_RUNNER),
        "backend_v5_guard": identity(BACKEND_V5_GUARD),
        "backend_v5_lifecycle_wrapper": identity(BACKEND_V5_LIFECYCLE_WRAPPER),
        "backend_v5_signal_mask_launcher": identity(BACKEND_V5_SIGNAL_MASK_LAUNCHER),
        "backend_v5_process_free_tests": identity(BACKEND_V5_TESTS),
        "backend_v5_python38": identity(BACKEND_V5_PYTHON38),
        "backend_v5_vins_node": identity(BACKEND_V5_VINS_NODE),
        "analysis_v4_design_freeze": identity(ANALYSIS_V4_DESIGN_FREEZE),
        "backend_v4_execution_lock": identity(BACKEND_V4_LOCK),
        "v4_r03_terminal_receipt": identity(R03_RECEIPT),
    }
    r03 = values["v4_r03_terminal_receipt"]
    require((r03["size_bytes"], r03["sha256"]) == R03_TERMINAL_EXPECTED,
            "STATIC_R03_TERMINAL_IDENTITY")
    return values


def design_contract_snapshot() -> dict[str, Any]:
    value = json.loads(json.dumps(_V4_DESIGN_CONTRACT_SNAPSHOT()))
    value["campaign"] = "A08_HFNET_VS_KLT_ONLY_COMMON_SUPPORT_ADDITIVE_V5"
    value["grid"] = exact_grid_evidence()
    value["population_and_failure_rules"].pop(
        "two_infrastructure_na_slots_retained", None
    )
    value["population_and_failure_rules"].update({
        "backend_item_order": list(FULL_ITEM_ORDER),
        "v5_backend_item_order": list(V5_ITEM_ORDER),
        "klt_planned_count": 5, "maximum_valid_klt_count": 2,
        "klt_valid_repeat_rule": "ONLY_PASS_BACKEND_REPLAY_ACCEPTED_AMONG_R04_R05",
        "klt_summary": "coordinatewise_median_over_all_valid_R04_R05_repeats",
        "r01_disposition": R01_DISPOSITION, "r01_failure_code": R01_FAILURE_CODE,
        "r01_counts_as_valid": False,
        "r01_rerun_or_replacement_permitted": False,
        "r02_disposition": R02_DISPOSITION, "r02_failure_code": R02_FAILURE_CODE,
        "r02_counts_as_valid": False,
        "r02_complete_trajectory_admitted": False,
        "r02_rerun_or_replacement_permitted": False,
        "r03_disposition": R03_DISPOSITION, "r03_failure_code": R03_FAILURE_CODE,
        "r03_counts_as_valid": False,
        "r03_complete_trajectory_admitted": False,
        "r03_rerun_or_replacement_permitted": False,
        "three_infrastructure_na_slots_retained": True,
        "best_repeat_selection_permitted": False,
    })
    value["execution_rules"].update({
        "design_freeze_before_v5_backend_terminal_results": True,
        "dynamic_lock_after_two_v5_terminal_receipts_before_accuracy": True,
        "dynamic_lock_after_three_v4_terminal_receipts_before_accuracy": False,
        "r03_terminal_artifacts_opened_only_for_exclusion_and_lineage": True,
        "backend_v5_unblocks_inherited_hup_int_term_before_overlay_exec": True,
        "backend_v5_vins_lifecycle_wrapper_is_separately_identity_bound": True,
    })
    value["v5_environment_amendment"] = {
        "only_permitted_scientific_environment_addition":
            dict(V5_ENVIRONMENT_AMENDMENT),
        "all_other_scientific_signal_lifecycle_values_unchanged": True,
        "reuse_frozen_v4_lifecycle_wrapper": True,
        "reuse_frozen_v4_signal_mask_launcher": True,
    }
    return value


def backend_v5_terminal_presence() -> dict[str, str]:
    paths = {"backend_v5_execution_lock": BACKEND_V5_LOCK, **{
        item: BACKEND_V5_ROOT / item / BACKEND_V5_RECEIPT_NAME
        for item in V5_ITEM_ORDER
    }}
    result: dict[str, str] = {}
    for label, path in paths.items():
        if not path.exists() and not path.is_symlink():
            result[label] = "MISSING"
        elif path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
            result[label] = "INVALID_KIND"
        else:
            result[label] = "PRESENT_REGULAR"
    return result


def backend_v5_authority_source_presence() -> dict[str, str]:
    paths = {
        "backend_v5_protocol": BACKEND_V5_PROTOCOL,
        "backend_v5_runner": BACKEND_V5_RUNNER,
        "backend_v5_guard": BACKEND_V5_GUARD,
        "backend_v5_lifecycle_wrapper": BACKEND_V5_LIFECYCLE_WRAPPER,
        "backend_v5_signal_mask_launcher": BACKEND_V5_SIGNAL_MASK_LAUNCHER,
        "backend_v5_process_free_tests": BACKEND_V5_TESTS,
        "backend_v5_python38": BACKEND_V5_PYTHON38,
        "backend_v5_vins_node": BACKEND_V5_VINS_NODE,
    }
    result: dict[str, str] = {}
    for label, path in paths.items():
        if not path.exists() and not path.is_symlink():
            result[label] = "MISSING"
        elif path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
            result[label] = "INVALID_KIND"
        else:
            result[label] = "PRESENT_REGULAR"
    return result


def backend_v5_campaign_prelaunch_presence() -> dict[str, str]:
    paths: dict[str, Path] = {
        "backend_v5_root": BACKEND_V5_ROOT,
        "backend_v5_runtime_root": BACKEND_V5_RUNTIME_ROOT,
    }
    for item in V5_ITEM_ORDER:
        repeat = int(item[-2:])
        tag = f"a08_recoveredjuly_hist0000_4660_backend_klt_only_r{repeat:02d}_v5"
        paths[f"workspace:{item}"] = (
            BACKEND_OVERLAY_RUN_ROOT / f"external_klt_every2_{tag}"
        )
    return {
        label: ("PRESENT" if path.exists() or path.is_symlink() else "ABSENT")
        for label, path in paths.items()
    }


def v4_remaining_r04_r05_presence() -> dict[str, str]:
    paths: dict[str, Path] = {}
    for item in V5_ITEM_ORDER:
        repeat = int(item[-2:])
        tag = f"a08_recoveredjuly_hist0000_4660_backend_klt_only_r{repeat:02d}_v4"
        paths.update({
            f"output:{item}": BACKEND_V4_ROOT / item,
            f"runtime:{item}": BACKEND_V4_RUNTIME_ROOT / item,
            f"workspace:{item}": (
                BACKEND_OVERLAY_RUN_ROOT / f"external_klt_every2_{tag}"
            ),
        })
    return {
        label: ("PRESENT" if path.exists() or path.is_symlink() else "ABSENT")
        for label, path in paths.items()
    }


def _require_prior_analysis_diversions_untouched() -> None:
    V4._require_prior_analysis_diversions_untouched()
    for path, code in (
        (ANALYSIS_V4_LOCK, "FROZEN_ANALYSIS_V4_LOCK_MUST_REMAIN_ABSENT"),
        (ANALYSIS_V4_OUTPUT, "FROZEN_ANALYSIS_V4_OUTPUT_MUST_REMAIN_ABSENT"),
        (ANALYSIS_V4_CLAIM, "FROZEN_ANALYSIS_V4_CLAIM_MUST_REMAIN_ABSENT"),
    ):
        ENGINE.regular_absence(path, code)


def build_design_freeze_payload(created_at_utc: str) -> dict[str, Any]:
    presence = backend_v5_terminal_presence()
    require(all(value == "MISSING" for value in presence.values()),
            "DESIGN_FREEZE_MUST_PRECEDE_V5_BACKEND_LOCK_AND_RESULTS")
    prelaunch = backend_v5_campaign_prelaunch_presence()
    require(all(value == "ABSENT" for value in prelaunch.values()),
            "DESIGN_FREEZE_MUST_PRECEDE_ANY_V5_BACKEND_TOUCH")
    old_remaining = v4_remaining_r04_r05_presence()
    require(all(value == "ABSENT" for value in old_remaining.values()),
            "OLD_V4_R04_R05_MUST_REMAIN_UNTOUCHED")
    ENGINE.regular_absence(DEFAULT_LOCK, "DESIGN_FREEZE_MUST_PRECEDE_V5_ANALYSIS_LOCK")
    require(analysis_output_state() == "ABSENT",
            "DESIGN_FREEZE_MUST_PRECEDE_V5_ANALYSIS_OUTPUT")
    _require_prior_analysis_diversions_untouched()
    prior01 = prior_r01_binding()
    prior02 = prior_r02_binding()
    prior03 = prior_r03_binding()
    payload = {
        "schema_version": DESIGN_FREEZE_SCHEMA, "status": DESIGN_FREEZE_STATUS,
        "created_at_utc": created_at_utc,
        "static_identities": collect_static_identities(),
        "sealed_support": common.collect_support_binding(),
        "klt_frontend": collect_klt_frontend_binding(),
        "excluded_xfeat": collect_xfeat_exclusion(),
        "evo_authority": common.collect_evo_authority(),
        "prior_r01": prior01, "prior_r02": prior02, "prior_r03": prior03,
        "design_contract": design_contract_snapshot(),
        "backend_v5_terminal_presence_at_freeze": presence,
        "backend_v5_campaign_prelaunch_presence_at_freeze": prelaunch,
        "v4_remaining_r04_r05_presence_at_freeze": old_remaining,
        "claim_boundary": {
            "r01_r02_r03_terminal_failures_opened_only_for_exclusion": True,
            "r03_complete_artifacts_identity_bound_but_unaccepted": True,
            "r03_trajectory_opened_for_common_support": False,
            "backend_v5_execution_lock_built": False,
            "v5_backend_items_started": 0,
            "ape_or_rpe_computed_for_v5": False,
            "final_dynamic_analysis_lock_built": False,
            "ros_or_vins_started_for_v5": False,
        },
    }
    payload["freeze_sha256"] = compact_sha256(payload)
    return payload


def publish_design_freeze(authorization_token: str) -> dict[str, Any]:
    require(authorization_token == FREEZE_TOKEN, "DESIGN_FREEZE_AUTHORIZATION_TOKEN")
    ENGINE.regular_absence(DESIGN_FREEZE, "DESIGN_FREEZE_ALREADY_EXISTS")
    payload = build_design_freeze_payload(
        datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    atomic_publish(DESIGN_FREEZE, payload)
    return {
        "status": "ADDITIVE_V5_STATIC_DESIGN_FREEZE_PUBLISHED_NO_ACCURACY_COMPUTED",
        "design_freeze": identity(DESIGN_FREEZE), "accuracy_computed": False,
    }


def collect_design_freeze_binding() -> dict[str, Any]:
    value, freeze_id = stable_json(DESIGN_FREEZE)
    require(value.get("schema_version") == DESIGN_FREEZE_SCHEMA, "DESIGN_FREEZE_SCHEMA")
    require(value.get("status") == DESIGN_FREEZE_STATUS, "DESIGN_FREEZE_STATUS")
    digest = value.get("freeze_sha256")
    unsigned = dict(value); unsigned.pop("freeze_sha256", None)
    require(digest == compact_sha256(unsigned), "DESIGN_FREEZE_DIGEST")
    require(value.get("static_identities") == collect_static_identities(),
            "DESIGN_FREEZE_STATIC_IDENTITIES")
    require(value.get("sealed_support") == common.collect_support_binding(),
            "DESIGN_FREEZE_SUPPORT")
    require(value.get("klt_frontend") == collect_klt_frontend_binding(),
            "DESIGN_FREEZE_KLT_FRONTEND")
    require(value.get("excluded_xfeat") == collect_xfeat_exclusion(),
            "DESIGN_FREEZE_XFEAT")
    require(value.get("evo_authority") == common.collect_evo_authority(),
            "DESIGN_FREEZE_EVO")
    require(value.get("prior_r01") == prior_r01_binding(), "DESIGN_FREEZE_R01")
    require(value.get("prior_r02") == prior_r02_binding(), "DESIGN_FREEZE_R02")
    require(value.get("prior_r03") == prior_r03_binding(), "DESIGN_FREEZE_R03")
    require(value.get("design_contract") == design_contract_snapshot(),
            "DESIGN_FREEZE_CONTRACT")
    expected_presence = {"backend_v5_execution_lock": "MISSING", **{
        item: "MISSING" for item in V5_ITEM_ORDER
    }}
    expected_prelaunch = {
        "backend_v5_root": "ABSENT", "backend_v5_runtime_root": "ABSENT",
        **{f"workspace:{item}": "ABSENT" for item in V5_ITEM_ORDER},
    }
    expected_old = {
        f"{kind}:{item}": "ABSENT" for item in V5_ITEM_ORDER
        for kind in ("output", "runtime", "workspace")
    }
    require(value.get("backend_v5_terminal_presence_at_freeze") == expected_presence,
            "DESIGN_FREEZE_PRIOR_V5_TERMINAL_ABSENCE")
    require(value.get("backend_v5_campaign_prelaunch_presence_at_freeze") == expected_prelaunch,
            "DESIGN_FREEZE_PRIOR_V5_TOUCH_ABSENCE")
    require(value.get("v4_remaining_r04_r05_presence_at_freeze") == expected_old,
            "DESIGN_FREEZE_OLD_V4_R04_R05_UNTOUCHED")
    live_old = v4_remaining_r04_r05_presence()
    require(all(state == "ABSENT" for state in live_old.values()),
            "FROZEN_V4_R04_R05_MUST_REMAIN_UNTOUCHED")
    _require_prior_analysis_diversions_untouched()
    boundary = value.get("claim_boundary")
    require(
        isinstance(boundary, dict)
        and boundary.get("r01_r02_r03_terminal_failures_opened_only_for_exclusion") is True
        and boundary.get("r03_complete_artifacts_identity_bound_but_unaccepted") is True
        and boundary.get("r03_trajectory_opened_for_common_support") is False
        and boundary.get("backend_v5_execution_lock_built") is False
        and boundary.get("v5_backend_items_started") == 0
        and boundary.get("ape_or_rpe_computed_for_v5") is False
        and boundary.get("final_dynamic_analysis_lock_built") is False
        and boundary.get("ros_or_vins_started_for_v5") is False,
        "DESIGN_FREEZE_CLAIM_BOUNDARY",
    )
    return {"identity": freeze_id, "created_at_utc": value.get("created_at_utc"),
            "freeze_sha256": digest}


def design_freeze_audit_readonly() -> dict[str, Any]:
    try:
        return {
            "status": "PASS_DESIGN_FROZEN_AFTER_R01_R02_R03_BEFORE_R04_R05",
            "read_only": True, "design_freeze": collect_design_freeze_binding(),
            "accuracy_computed": False,
        }
    except (AnalysisProtocolError, OSError, ValueError) as error:
        presence = backend_v5_terminal_presence()
        late = any(value != "MISSING" for value in presence.values())
        return {
            "status": ("BLOCKED_LATE_OR_INVALID_V5_DESIGN_FREEZE"
                       if late else "BLOCKED_DESIGN_FREEZE"),
            "read_only": True, "error": f"{type(error).__name__}:{error}",
            "backend_v5_terminal_presence": presence, "accuracy_computed": False,
        }


def collect_authority() -> dict[str, Any]:
    return {
        "design_freeze": collect_design_freeze_binding(),
        "support": common.collect_support_binding(),
        "klt_frontend": collect_klt_frontend_binding(),
        "excluded_xfeat": collect_xfeat_exclusion(),
        "backend": collect_backend_binding(),
        "static_identities": collect_static_identities(),
        "evo": common.collect_evo_authority(),
    }


def contract_core(authority: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": LOCK_SCHEMA, "status": LOCK_STATUS,
        "campaign": "A08_HFNET_VS_KLT_ONLY_COMMON_SUPPORT_ADDITIVE_V5",
        "authority": dict(authority), "grid": exact_grid_evidence(),
        "design_contract": design_contract_snapshot(),
    }


def build_lock_payload(authority: Mapping[str, Any], created_at_utc: str) -> dict[str, Any]:
    payload = {**contract_core(authority), "created_at_utc": created_at_utc}
    payload["contract_sha256"] = compact_sha256(payload)
    return payload


def verify_lock(lock_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    lock, lock_id = stable_json(lock_path)
    created = lock.get("created_at_utc")
    require(isinstance(created, str) and created, "ANALYSIS_LOCK_CREATED_AT")
    require(lock == build_lock_payload(collect_authority(), created),
            "ANALYSIS_LOCK_AUTHORITY_DRIFT")
    return lock, lock_id


def analysis_output_state() -> str:
    _configure_engine()
    return ENGINE.analysis_output_state()


def original_ten_slot_rows(
    backend: Mapping[str, Any], arms: Optional[Mapping[str, Any]], ranking: bool,
) -> list[dict[str, Any]]:
    rows = _V4_ORIGINAL_TEN_SLOT_ROWS(backend, arms, ranking)
    for row in rows:
        if row["item_id"] == "KLT_R02":
            row.update({
                "backend_launched": True, "backend_replay_started": True,
                "backend_replay_completed": True,
                "post_result_cleanup_failed": True,
                "scientific_failure_retained_as_na": False,
                "backend_infrastructure_failure_retained_as_na": True,
            })
        elif row["item_id"] == "KLT_R03":
            row.update({
                "backend_launched": True, "backend_replay_started": True,
                "backend_replay_completed": True,
                "post_result_cleanup_failed": False,
                "scientific_failure_retained_as_na": False,
                "backend_infrastructure_failure_retained_as_na": True,
            })
        elif row["item_id"].startswith("KLT_") and row["item_id"] != "KLT_R01":
            row["backend_infrastructure_failure_retained_as_na"] = False
    return rows


def _decorate_formal(formal: dict[str, Any]) -> dict[str, Any]:
    for row in formal.get("planned_klt_repeats", []):
        if row.get("item_id") == "KLT_R02":
            row.update({
                "scientific_failure_retained_as_na": False,
                "backend_infrastructure_failure_retained_as_na": True,
                "backend_replay_started": True, "backend_replay_completed": True,
                "post_result_cleanup_failed": True,
            })
        elif row.get("item_id") == "KLT_R03":
            row.update({
                "scientific_failure_retained_as_na": False,
                "backend_infrastructure_failure_retained_as_na": True,
                "backend_replay_started": True, "backend_replay_completed": True,
                "post_result_cleanup_failed": False,
            })
        elif row.get("item_id") != "KLT_R01":
            row["backend_infrastructure_failure_retained_as_na"] = False
    formal["r01_disposition"] = R01_DISPOSITION
    formal["r02_disposition"] = R02_DISPOSITION
    formal["r03_disposition"] = R03_DISPOSITION
    formal["maximum_valid_klt_count"] = 2
    formal["valid_klt_repeat_rule"] = "ONLY_PASS_BACKEND_REPLAY_ACCEPTED_AMONG_R04_R05"
    return formal


def build_formal_summary(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _decorate_formal(_V4_BUILD_FORMAL_SUMMARY(*args, **kwargs))


def build_error_formal_summary(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _decorate_formal(_V4_BUILD_ERROR_FORMAL_SUMMARY(*args, **kwargs))


def validate_formal_population_binding(
    formal: Mapping[str, Any], lock: Mapping[str, Any]
) -> None:
    _V4_VALIDATE_FORMAL_POPULATION(formal, lock)
    planned = {row["item_id"]: row for row in formal["planned_klt_repeats"]}
    slots = {row["item_id"]: row for row in formal["original_ten_slot_dispositions"]}
    for row in (planned["KLT_R02"], slots["KLT_R02"]):
        require(
            row.get("terminal_disposition") == R02_DISPOSITION
            and row.get("accepted_for_single_joint_mask") is False
            and row.get("scientific_failure_retained_as_na") is False
            and row.get("backend_infrastructure_failure_retained_as_na") is True
            and row.get("backend_replay_started") is True
            and row.get("backend_replay_completed") is True
            and row.get("post_result_cleanup_failed") is True,
            "FORMAL_R02_INFRASTRUCTURE_NA_BOUNDARY",
        )
    for row in (planned["KLT_R03"], slots["KLT_R03"]):
        require(
            row.get("terminal_disposition") == R03_DISPOSITION
            and row.get("accepted_for_single_joint_mask") is False
            and row.get("scientific_failure_retained_as_na") is False
            and row.get("backend_infrastructure_failure_retained_as_na") is True
            and row.get("backend_replay_started") is True
            and row.get("backend_replay_completed") is True
            and row.get("post_result_cleanup_failed") is False,
            "FORMAL_R03_INFRASTRUCTURE_NA_BOUNDARY",
        )


def repeat_table_csv_text(formal: Mapping[str, Any]) -> str:
    fields = [
        "item_id", "arm", "repeat_index", "terminal_disposition",
        "backend_launched", "backend_replay_started", "backend_replay_completed",
        "post_result_cleanup_failed", "accepted_for_single_joint_mask",
        "scientific_failure_retained_as_na",
        "backend_infrastructure_failure_retained_as_na",
        "frontend_structural_failure_retained_as_na", "replacement_permitted",
        *PRIMARY_METRICS,
    ]
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
    for row in formal["original_ten_slot_dispositions"]:
        writer.writerow({**{key: row[key] for key in fields if key in row},
                         **row["formal_metrics"]})
    return handle.getvalue()


def make_terminal_receipt(*args: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V4_MAKE_TERMINAL_RECEIPT(*args, **kwargs)
    value.update({
        "r01_disposition": R01_DISPOSITION, "r02_disposition": R02_DISPOSITION,
        "r03_disposition": R03_DISPOSITION, "maximum_valid_klt_count": 2,
        "valid_klt_repeat_rule": "ONLY_PASS_BACKEND_REPLAY_ACCEPTED_AMONG_R04_R05",
    })
    return value


def _configure_engine() -> None:
    assignments = {
        "BACKEND_ROOT": BACKEND_V5_ROOT, "BACKEND_LOCK": BACKEND_V5_LOCK,
        "BACKEND_RUNNER": BACKEND_V5_RUNNER, "BACKEND_PROTOCOL": BACKEND_V5_PROTOCOL,
        "BACKEND_RECEIPT_NAME": BACKEND_V5_RECEIPT_NAME,
        "BACKEND_RUNTIME_ROOT": BACKEND_V5_RUNTIME_ROOT,
        "BACKEND_OVERLAY_RUN_ROOT": BACKEND_OVERLAY_RUN_ROOT,
        "OUTPUT_ROOT": OUTPUT_ROOT, "CLAIM_PATH": CLAIM_PATH,
        "STAGING_ROOT": STAGING_ROOT, "EVO_WORK_ROOT": EVO_WORK_ROOT,
        "FAILURE_STAGING_ROOT": FAILURE_STAGING_ROOT,
        "PROTOCOL": PROTOCOL, "RUNNER": RUNNER, "TESTS": TESTS,
        "DESIGN_FREEZE": DESIGN_FREEZE, "DEFAULT_LOCK": DEFAULT_LOCK,
        "ITEM_ORDER": FULL_ITEM_ORDER, "ORIGINAL_TEN_SLOT_ORDER": ORIGINAL_TEN_SLOT_ORDER,
        "XFEAT_EXCLUSION_STATUS": XFEAT_DISPOSITION,
        "DESIGN_FREEZE_SCHEMA": DESIGN_FREEZE_SCHEMA, "LOCK_SCHEMA": LOCK_SCHEMA,
        "CLAIM_SCHEMA": CLAIM_SCHEMA, "RECEIPT_SCHEMA": RECEIPT_SCHEMA,
        "FORMAL_SCHEMA": FORMAL_SCHEMA, "LOCK_STATUS": LOCK_STATUS,
        "FREEZE_TOKEN": FREEZE_TOKEN, "BUILD_LOCK_TOKEN": BUILD_LOCK_TOKEN,
        "RUN_TOKEN": RUN_TOKEN, "GRID_NAME": GRID_NAME,
        "RAW_SUMMARY_NAME": RAW_SUMMARY_NAME, "GRID_AUDIT_NAME": GRID_AUDIT_NAME,
        "RAW_METRICS_NAME": RAW_METRICS_NAME,
        "RAW_DIAGNOSTIC_MANIFEST_NAME": RAW_DIAGNOSTIC_MANIFEST_NAME,
        "REPEAT_TABLE_NAME": REPEAT_TABLE_NAME,
        "FORMAL_SUMMARY_NAME": FORMAL_SUMMARY_NAME,
        "EVO_SUMMARY_NAME": EVO_SUMMARY_NAME, "RECEIPT_NAME": RECEIPT_NAME,
        "PARTIAL_EVIDENCE_NAME": PARTIAL_EVIDENCE_NAME,
        "exact_grid_evidence": exact_grid_evidence,
        "collect_klt_frontend_binding": collect_klt_frontend_binding,
        "collect_xfeat_exclusion": collect_xfeat_exclusion,
        "load_backend_authority_module": load_backend_v5_authority_module,
        "collect_backend_binding": collect_backend_binding,
        "collect_static_identities": collect_static_identities,
        "design_contract_snapshot": design_contract_snapshot,
        "backend_terminal_presence": backend_v5_terminal_presence,
        "backend_campaign_prelaunch_presence": backend_v5_campaign_prelaunch_presence,
        "build_design_freeze_payload": build_design_freeze_payload,
        "publish_design_freeze": publish_design_freeze,
        "collect_design_freeze_binding": collect_design_freeze_binding,
        "design_freeze_audit_readonly": design_freeze_audit_readonly,
        "collect_authority": collect_authority, "contract_core": contract_core,
        "build_lock_payload": build_lock_payload, "verify_lock": verify_lock,
        "original_ten_slot_rows": original_ten_slot_rows,
        "build_formal_summary": build_formal_summary,
        "build_error_formal_summary": build_error_formal_summary,
        "validate_formal_population_binding": validate_formal_population_binding,
        "repeat_table_csv_text": repeat_table_csv_text,
        "make_terminal_receipt": make_terminal_receipt,
    }
    for name, value in assignments.items(): setattr(ENGINE, name, value)


def require_canonical_analysis_lock_path(lock_path: Path) -> None:
    require(lock_path.absolute() == DEFAULT_LOCK.absolute(),
            "ANALYSIS_LOCK_PATH_MUST_BE_CANONICAL")


def preflight_readonly(lock_path: Path = DEFAULT_LOCK) -> dict[str, Any]:
    try:
        require_canonical_analysis_lock_path(lock_path)
    except AnalysisProtocolError as error:
        return {"status": "BLOCKED_PREFLIGHT", "read_only": True,
                "error": f"{type(error).__name__}:{error}", "accuracy_computed": False}
    if not DESIGN_FREEZE.exists() and not DESIGN_FREEZE.is_symlink():
        if lock_path.exists() or lock_path.is_symlink():
            return {
                "status": "BLOCKED_PREMATURE_ANALYSIS_V5_LOCK_BEFORE_STATIC_FREEZE",
                "read_only": True, "analysis_lock_present": True,
                "accuracy_computed": False,
            }
        if not R03_RECEIPT.exists() and not R03_RECEIPT.is_symlink():
            return {
                "status": "WAITING_V4_R03_NATURAL_TERMINAL_RECEIPT",
                "read_only": True, "r03_receipt": str(R03_RECEIPT),
                "r03_interruption_or_replacement_permitted": False,
                "design_freeze_present": False, "accuracy_computed": False,
            }
        source_presence = backend_v5_authority_source_presence()
        unavailable_sources = [
            key for key, value in source_presence.items()
            if value != "PRESENT_REGULAR"
        ]
        if unavailable_sources:
            return {
                "status": "WAITING_BACKEND_V5_CANDIDATE_AUTHORITIES",
                "read_only": True, "backend_v5_source_presence": source_presence,
                "unavailable": unavailable_sources,
                "design_freeze_present": False, "accuracy_computed": False,
            }
        try:
            payload = build_design_freeze_payload("READ_ONLY_CANDIDATE")
            return {
                "status": "READY_TO_PUBLISH_ANALYSIS_V5_STATIC_DESIGN_FREEZE",
                "read_only": True, "candidate_freeze_sha256": payload["freeze_sha256"],
                "design_freeze_present": False, "accuracy_computed": False,
            }
        except (AnalysisProtocolError, OSError, ValueError) as error:
            return {"status": "BLOCKED_DESIGN_FREEZE", "read_only": True,
                    "error": f"{type(error).__name__}:{error}",
                    "accuracy_computed": False}
    freeze = design_freeze_audit_readonly()
    if freeze["status"] != "PASS_DESIGN_FROZEN_AFTER_R01_R02_R03_BEFORE_R04_R05":
        return {"status": "BLOCKED_DESIGN_FREEZE", "read_only": True,
                "design_freeze_audit": freeze, "accuracy_computed": False}
    presence = backend_v5_terminal_presence()
    unavailable = [key for key, value in presence.items() if value != "PRESENT_REGULAR"]
    if unavailable:
        if lock_path.exists() or lock_path.is_symlink():
            return {
                "status": (
                    "BLOCKED_PREMATURE_ANALYSIS_V5_LOCK_BEFORE_TWO_"
                    "BACKEND_TERMINAL_RECEIPTS"
                ),
                "read_only": True, "terminal_presence": presence,
                "unavailable": unavailable, "analysis_lock_present": True,
                "accuracy_computed": False,
            }
        return {
            "status": "WAITING_FOR_BACKEND_V5_LOCK_AND_TWO_TERMINAL_RECEIPTS",
            "read_only": True, "terminal_presence": presence,
            "unavailable": unavailable,
            "analysis_lock_present": lock_path.exists() or lock_path.is_symlink(),
            "r01_disposition": R01_DISPOSITION, "r02_disposition": R02_DISPOSITION,
            "r03_disposition": R03_DISPOSITION,
            "excluded_xfeat_disposition": XFEAT_DISPOSITION,
            "accuracy_computed": False,
        }
    try:
        _configure_engine()
        if not lock_path.exists() and not lock_path.is_symlink():
            require(analysis_output_state() == "ABSENT", "ANALYSIS_OUTPUT_PREEXISTS")
            authority = collect_authority()
            return {
                "status": "READY_TO_BUILD_ANALYSIS_V5_LOCK_NO_ACCURACY_COMPUTED",
                "read_only": True, "terminal_presence": presence,
                "klt_planned_count": 5,
                "klt_valid_count": authority["backend"]["valid_count"],
                "maximum_valid_klt_count": 2,
                "candidate_contract_sha256": compact_sha256(contract_core(authority)),
                "accuracy_computed": False,
            }
        lock, lock_id = verify_lock(lock_path); state = analysis_output_state()
        require(state in {"ABSENT", "TERMINAL_RECEIPT_PRESENT",
                          "TERMINAL_RECEIPT_PRESENT_WITH_UNCOMMITTED_PARTIAL"},
                f"ANALYSIS_ALLOWANCE_CONSUMED_WITHOUT_VALID_TERMINAL:{state}")
        return {
            "status": ("PASS_LOCKED_READY_FOR_ONE_ANALYSIS" if state == "ABSENT"
                       else "PASS_LOCKED_TERMINAL_RECEIPT_PRESENT_AUDIT_REQUIRED"),
            "read_only": True, "lock": lock_id,
            "contract_sha256": lock["contract_sha256"],
            "analysis_output_state": state, "accuracy_computed": False,
        }
    except (AnalysisProtocolError, OSError, ValueError) as error:
        return {"status": "BLOCKED_PREFLIGHT", "read_only": True,
                "terminal_presence": presence,
                "error": f"{type(error).__name__}:{error}", "accuracy_computed": False}


def build_lock(lock_path: Path, authorization_token: str) -> dict[str, Any]:
    require_canonical_analysis_lock_path(lock_path)
    require(authorization_token == BUILD_LOCK_TOKEN, "BUILD_LOCK_AUTHORIZATION_TOKEN")
    ENGINE.regular_absence(lock_path, "ANALYSIS_LOCK_ALREADY_EXISTS")
    require(analysis_output_state() == "ABSENT", "ANALYSIS_OUTPUT_PREEXISTS")
    collect_design_freeze_binding()
    presence = backend_v5_terminal_presence()
    require(all(value == "PRESENT_REGULAR" for value in presence.values()),
            "TWO_V5_TERMINAL_RECEIPTS_REQUIRED")
    authority = collect_authority()
    require(authority["backend"]["planned_count"] == 5, "PLANNED_COUNT")
    require(authority["backend"]["maximum_valid_count"] == 2, "MAX_VALID_COUNT")
    payload = build_lock_payload(
        authority, datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    atomic_publish(lock_path, payload)
    return {
        "status": "FINAL_ANALYSIS_V5_LOCK_PUBLISHED_NO_ACCURACY_COMPUTED",
        "lock": identity(lock_path), "klt_planned_count": 5,
        "klt_valid_count": authority["backend"]["valid_count"],
        "maximum_valid_klt_count": 2, "r01_disposition": R01_DISPOSITION,
        "r02_disposition": R02_DISPOSITION, "r03_disposition": R03_DISPOSITION,
        "excluded_xfeat_disposition": XFEAT_DISPOSITION,
        "accuracy_computed": False,
    }


def execute_analysis(lock_path: Path, authorization_token: str) -> tuple[int, dict[str, Any]]:
    _configure_engine(); return ENGINE.execute_analysis(lock_path, authorization_token)


def audit_readonly(lock_path: Path = DEFAULT_LOCK) -> dict[str, Any]:
    _configure_engine(); result = ENGINE.audit_readonly(lock_path)
    result.update({"r01_disposition": R01_DISPOSITION,
                   "r02_disposition": R02_DISPOSITION,
                   "r03_disposition": R03_DISPOSITION,
                   "maximum_valid_klt_count": 2})
    return result


accepted_arm_paths = ENGINE.accepted_arm_paths
exact_grid_seconds = ENGINE.exact_grid_seconds
evaluate_joint_inputs = ENGINE.evaluate_joint_inputs
support_gate = ENGINE.support_gate
median_metrics = ENGINE.median_metrics
null_metrics = ENGINE.null_metrics
formal_metrics_are_all_na = ENGINE.formal_metrics_are_all_na
force_all_formal_metrics_na_for_integrity = ENGINE.force_all_formal_metrics_na_for_integrity
audit_terminal_semantics = ENGINE.audit_terminal_semantics


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight"); commands.add_parser("audit")
    freeze = commands.add_parser("freeze-design")
    freeze.add_argument("--authorization-token", required=True)
    build = commands.add_parser("build-lock")
    build.add_argument("--authorization-token", required=True)
    run = commands.add_parser("run"); run.add_argument("--authorization-token", required=True)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv); lock_path = args.lock.absolute()
    if args.command == "preflight":
        result = preflight_readonly(lock_path)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0 if result["status"].startswith(("PASS_", "READY_", "WAITING_")) else 2
    if args.command == "audit":
        result = audit_readonly(lock_path)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0 if result["status"].startswith(("PASS_", "WAITING_")) else 2
    try:
        if args.command == "freeze-design":
            result = publish_design_freeze(args.authorization_token); code = 0
        elif args.command == "build-lock":
            result = build_lock(lock_path, args.authorization_token); code = 0
        else:
            code, result = execute_analysis(lock_path, args.authorization_token)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False)); return code
    except (AnalysisProtocolError, OSError, ValueError, RuntimeError) as error:
        print(f"A08_HFNET_KLT_V5_ERROR:{type(error).__name__}:{error}", file=sys.stderr)
        return 2


_configure_engine()


if __name__ == "__main__":
    raise SystemExit(main())
