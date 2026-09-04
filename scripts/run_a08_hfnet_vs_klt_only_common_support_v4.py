#!/usr/bin/env python3
"""Additive A08 analysis after the consumed R01 and R02 infrastructure NAs.

Importing this module is inert.  This candidate intentionally cannot publish
its static freeze until the natural v3 R02 terminal receipt has an explicitly
filled identity.  Only accepted v4 R03--R05 trajectories can enter the frozen
common-support evaluator.
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

ANALYSIS_V3_PROTOCOL = WORKSPACE / "papers/a08_hfnet_vs_klt_only_common_support_v3_protocol.md"
ANALYSIS_V3_RUNNER = WORKSPACE / "scripts/run_a08_hfnet_vs_klt_only_common_support_v3.py"
ANALYSIS_V3_TESTS = WORKSPACE / "scripts/tests/test_run_a08_hfnet_vs_klt_only_common_support_v3.py"
ANALYSIS_V3_DESIGN_FREEZE = WORKSPACE / "papers/a08_hfnet_vs_klt_only_common_support_v3_design_freeze.json"
ANALYSIS_V3_LOCK = WORKSPACE / "papers/a08_hfnet_vs_klt_only_common_support_v3_execution_lock.json"
ANALYSIS_V3_OUTPUT = EXPERIMENT / "hfnet_vs_klt_only_common_support_v3"
ANALYSIS_V3_CLAIM = EXPERIMENT / "hfnet_vs_klt_only_common_support_start_claim_v3.json"

BACKEND_V3_PROTOCOL = WORKSPACE / (
    "papers/a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v3_protocol.md"
)
BACKEND_V3_RUNNER = WORKSPACE / (
    "scripts/run_a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v3.py"
)
BACKEND_V3_GUARD = WORKSPACE / (
    "scripts/run_a08_recovered_july_history_matched_backend_klt_only_replay_guard_v3.sh"
)
BACKEND_V3_TESTS = WORKSPACE / (
    "scripts/tests/test_run_a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v3.py"
)
BACKEND_V3_LOCK = WORKSPACE / (
    "papers/a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v3_execution_lock.json"
)
BACKEND_V3_ROOT = EXPERIMENT / "backend_klt_only_remaining_replays_v3"
BACKEND_V3_RUNTIME_ROOT = EXPERIMENT / "runtime/backend_klt_only_remaining_replays_v3"
BACKEND_V3_RECEIPT_NAME = "formal_run_receipt_v3.json"
R02_RECEIPT = BACKEND_V3_ROOT / "KLT_R02" / BACKEND_V3_RECEIPT_NAME

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
BACKEND_V4_PYTHON38 = Path("/usr/bin/python3.8")
BACKEND_V4_VINS_NODE = Path(
    "/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node"
)
BACKEND_OVERLAY_RUN_ROOT = (
    EXPERIMENT / "recovered_july_core_overlay_v1/logs/aqualoc_archaeo_vins"
)

PROTOCOL = WORKSPACE / "papers/a08_hfnet_vs_klt_only_common_support_v4_protocol.md"
RUNNER = WORKSPACE / "scripts/run_a08_hfnet_vs_klt_only_common_support_v4.py"
TESTS = WORKSPACE / "scripts/tests/test_run_a08_hfnet_vs_klt_only_common_support_v4.py"
DESIGN_FREEZE = WORKSPACE / "papers/a08_hfnet_vs_klt_only_common_support_v4_design_freeze.json"
DEFAULT_LOCK = WORKSPACE / "papers/a08_hfnet_vs_klt_only_common_support_v4_execution_lock.json"

OUTPUT_ROOT = EXPERIMENT / "hfnet_vs_klt_only_common_support_v4"
CLAIM_PATH = EXPERIMENT / "hfnet_vs_klt_only_common_support_start_claim_v4.json"
STAGING_ROOT = EXPERIMENT / ".hfnet_vs_klt_only_common_support_v4.staging"
EVO_WORK_ROOT = EXPERIMENT / ".hfnet_vs_klt_only_common_support_v4.evo_work"
FAILURE_STAGING_ROOT = EXPERIMENT / ".hfnet_vs_klt_only_common_support_v4.failure_staging"

FULL_ITEM_ORDER = tuple(f"KLT_R{repeat:02d}" for repeat in range(1, 6))
V4_ITEM_ORDER = ("KLT_R03", "KLT_R04", "KLT_R05")
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
XFEAT_DISPOSITION = "NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED"

DESIGN_FREEZE_SCHEMA = "aqua-fe-a08-hfnet-vs-klt-only-common-support-design-freeze-v4"
DESIGN_FREEZE_STATUS = (
    "FROZEN_AFTER_R01_R02_INFRASTRUCTURE_FAILURES_"
    "BEFORE_R03_R05_BACKEND_AND_ACCURACY"
)
LOCK_SCHEMA = "aqua-fe-a08-hfnet-vs-klt-only-common-support-lock-v4"
LOCK_STATUS = "FROZEN_AFTER_THREE_V4_TERMINAL_RECEIPTS_BEFORE_ACCURACY_VISIBLE"
CLAIM_SCHEMA = "aqua-fe-a08-hfnet-vs-klt-only-common-support-claim-v4"
RECEIPT_SCHEMA = "aqua-fe-a08-hfnet-vs-klt-only-common-support-receipt-v4"
FORMAL_SCHEMA = "aqua-fe-a08-formal-hfnet-vs-klt-only-common-support-summary-v4"

FREEZE_TOKEN = (
    "A08_FREEZE_HFNET_VS_KLT_ONLY_COMMON_SUPPORT_V4_AFTER_R01_R02_"
    "BEFORE_R03_R05_BACKEND"
)
BUILD_LOCK_TOKEN = (
    "A08_BUILD_HFNET_VS_KLT_ONLY_COMMON_SUPPORT_V4_LOCK_AFTER_THREE_TERMINALS_"
    "BEFORE_ACCURACY"
)
RUN_TOKEN = "A08_RUN_HFNET_VS_KLT_ONLY_COMMON_SUPPORT_V4_EXACTLY_ONCE_NO_RETRY"

GRID_NAME = "exact_integer_ns_grid_v4.json"
RAW_SUMMARY_NAME = "common_support_summary.json"
GRID_AUDIT_NAME = "common_grid_audit.csv"
RAW_METRICS_NAME = "common_support_metrics.csv"
RAW_DIAGNOSTIC_MANIFEST_NAME = "raw_numeric_diagnostics_boundary_v4.json"
REPEAT_TABLE_NAME = "original_ten_slot_dispositions_v4.csv"
FORMAL_SUMMARY_NAME = "formal_hfnet_vs_klt_only_summary_v4.json"
EVO_SUMMARY_NAME = "evo_crosscheck.json"
RECEIPT_NAME = "formal_analysis_receipt_v4.json"
PARTIAL_EVIDENCE_NAME = "uncommitted_partial_evidence_v4.json"

FROZEN_ANALYSIS_V3_EXPECTED = {
    "protocol": (8_011, "e5e39b12e47ff40e15366fea3d1c64aa11c82bd33d0101c9b23f81ba0aa5ad92"),
    "runner": (45_766, "ada1acf2858eacdcbfccd31d023289adca796112ceef11047b575c3540fc826e"),
    "tests": (17_897, "61c395a448380972e504b40368979892343acfc086773922a4b5e33d67cf5422"),
    "design_freeze": (15_827, "97b613c5d7bfc216e725f8a927b85f0a1c8fe14da568430a4daa1221b8db7d86"),
}
FROZEN_BACKEND_V3_EXPECTED = {
    "protocol": (8_021, "de6db42cf857b7bea26985bad15e1d9cb08f4a113978af5d9d231e7b00bd4836"),
    "runner": (44_728, "4a8739ae65b7c321bd425a6aa0c71e06d5b4c7dacaf9b4c0dd0eb19ee7dd6524"),
    "guard": (12_477, "6c86a721192a14856ec34af89fd6ae781f8335d27096c04bf8f577d402269848"),
    "tests": (18_946, "8e3fae8c1e0ec1acbb56d149dd43f2eda0ced0f14330f3cdb703a9b416b9b258"),
    "execution_lock": (91_243, "63c485d15ea77b52df3ff0266332dc1e58446a6d8c0da3539bb2bee717ff3e64"),
}

# Intentionally late-bound.  Fill only after the natural terminal receipt is
# stable and independently audited.  None makes every freeze transition fail.
R02_TERMINAL_EXPECTED: Optional[tuple[int, str]] = (
    12_840,
    "022dd34eff25edf3e012ae6ea81d691c20351525d3fee964121366779d69bf2d",
)
R02_EXPECTED_TRAJECTORY_ROWS = 2_319
R02_REPLAY_MANIFEST_MISSING_KEYS = (
    "accepted_feature_bag",
    "accepted_feature_bag_sha256",
    "accepted_feature_bag_size_bytes",
    "sealed_fd_owner_pid",
    "sealed_play_bag",
    "stable_owner_fd_guard",
    "strict_replay_only_fd_guard",
)
R02_ARTIFACT_ISSUE = (
    "REPLAY_MANIFEST_GATE:missing="
    + ",".join(R02_REPLAY_MANIFEST_MISSING_KEYS)
    + ";conflicting="
)
R02_V3_WRAPPER_DEEP_FAILURE = "PRIOR_STABLE_FD_OWNER_REPLAY_BINDING:KLT_R02"


def _raw_identity(path: Path) -> tuple[int, str]:
    raw = path.read_bytes()
    return len(raw), hashlib.sha256(raw).hexdigest()


def _load_frozen_analysis_v3() -> ModuleType:
    path = ANALYSIS_V3_RUNNER.absolute()
    if (
        not path.exists() or path.is_symlink()
        or not stat.S_ISREG(path.lstat().st_mode)
        or path.resolve(strict=True) != path
        or _raw_identity(path) != FROZEN_ANALYSIS_V3_EXPECTED["runner"]
    ):
        raise RuntimeError("FROZEN_ANALYSIS_V3_RUNNER_IDENTITY_DRIFT")
    specification = importlib.util.spec_from_file_location(
        "a08_hfnet_klt_analysis_v3_frozen_engine_for_v4", path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("FROZEN_ANALYSIS_V3_IMPORT_SPEC")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


V3 = _load_frozen_analysis_v3()
ENGINE = V3.BASE
AnalysisProtocolError = V3.AnalysisProtocolError
require = V3.require
identity = V3.identity
stable_json = V3.stable_json
compact_sha256 = V3.compact_sha256
atomic_publish = V3.atomic_publish
common = V3.common
PRIMARY_METRICS = V3.PRIMARY_METRICS

_V3_EXACT_GRID_EVIDENCE = V3.exact_grid_evidence
_V3_DESIGN_CONTRACT_SNAPSHOT = V3.design_contract_snapshot
_V3_COLLECT_KLT_FRONTEND_BINDING = V3.collect_klt_frontend_binding
_V3_COLLECT_XFEAT_EXCLUSION = V3.collect_xfeat_exclusion
_V3_PRIOR_R01_BINDING = V3.prior_r01_binding
_V3_LOAD_BACKEND_AUTHORITY = V3.load_backend_v3_authority_module
_V3_VALIDATE_BACKEND_TERMINAL = V3._V2_VALIDATE_BACKEND_TERMINAL
_V3_ORIGINAL_TEN_SLOT_ROWS = V3.original_ten_slot_rows
_V3_BUILD_FORMAL_SUMMARY = V3.build_formal_summary
_V3_BUILD_ERROR_FORMAL_SUMMARY = V3.build_error_formal_summary
_V3_VALIDATE_FORMAL_POPULATION = V3.validate_formal_population_binding
_V3_MAKE_TERMINAL_RECEIPT = V3.make_terminal_receipt


def exact_grid_evidence() -> dict[str, Any]:
    value = _V3_EXACT_GRID_EVIDENCE()
    value["schema_version"] = "aqua-fe-a08-exact-integer-ns-grid-v4"
    return value


def collect_klt_frontend_binding() -> dict[str, Any]:
    return _V3_COLLECT_KLT_FRONTEND_BINDING()


def collect_xfeat_exclusion() -> dict[str, Any]:
    value = _V3_COLLECT_XFEAT_EXCLUSION()
    require(value.get("disposition") == XFEAT_DISPOSITION, "XFEAT_DISPOSITION")
    return value


def prior_r01_binding() -> dict[str, Any]:
    value = _V3_PRIOR_R01_BINDING()
    require(
        value.get("disposition") == R01_DISPOSITION
        and value.get("failure_code") == R01_FAILURE_CODE
        and value.get("artifact_accepted") is False
        and value.get("rerun_or_replacement_permitted") is False,
        "R01_FROZEN_BOUNDARY",
    )
    return value


def _check_frozen_lineage_identities() -> dict[str, Any]:
    paths = {
        "analysis_v3_protocol": ANALYSIS_V3_PROTOCOL,
        "analysis_v3_runner": ANALYSIS_V3_RUNNER,
        "analysis_v3_tests": ANALYSIS_V3_TESTS,
        "analysis_v3_design_freeze": ANALYSIS_V3_DESIGN_FREEZE,
        "backend_v3_protocol": BACKEND_V3_PROTOCOL,
        "backend_v3_runner": BACKEND_V3_RUNNER,
        "backend_v3_guard": BACKEND_V3_GUARD,
        "backend_v3_tests": BACKEND_V3_TESTS,
        "backend_v3_execution_lock": BACKEND_V3_LOCK,
    }
    values = {label: identity(path) for label, path in paths.items()}
    for short, expected in FROZEN_ANALYSIS_V3_EXPECTED.items():
        key = f"analysis_v3_{short}"
        observed = values[key]
        require((observed["size_bytes"], observed["sha256"]) == expected,
                f"FROZEN_ANALYSIS_V3_IDENTITY:{short}")
    for short, expected in FROZEN_BACKEND_V3_EXPECTED.items():
        key = f"backend_v3_{short}"
        observed = values[key]
        require((observed["size_bytes"], observed["sha256"]) == expected,
                f"FROZEN_BACKEND_V3_IDENTITY:{short}")
    freeze, _ = stable_json(ANALYSIS_V3_DESIGN_FREEZE)
    require(
        freeze.get("schema_version")
        == "aqua-fe-a08-hfnet-vs-klt-only-common-support-design-freeze-v3"
        and freeze.get("status")
        == "FROZEN_AFTER_R01_INFRASTRUCTURE_FAILURE_BEFORE_R02_R05_BACKEND_AND_ACCURACY",
        "FROZEN_ANALYSIS_V3_DESIGN_FREEZE_SEMANTICS",
    )
    return values


def load_backend_v3_authority_module() -> ModuleType:
    return _V3_LOAD_BACKEND_AUTHORITY()


def validate_r02_terminal_receipt(
    receipt: Mapping[str, Any], receipt_id: Mapping[str, Any],
    lock_id: Mapping[str, Any], locked_item: Mapping[str, Any],
    *, expected_identity: Optional[tuple[int, str]] = None,
) -> dict[str, Any]:
    expected = R02_TERMINAL_EXPECTED if expected_identity is None else expected_identity
    require(expected is not None, "R02_TERMINAL_EXPECTED_IDENTITY_NOT_FILLED")
    require(
        (receipt_id.get("size_bytes"), receipt_id.get("sha256")) == expected,
        "R02_TERMINAL_RECEIPT_IDENTITY",
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
    require(
        receipt.get("schema_version")
        == "aqua-fe-a08-recovered-july-backend-klt-only-remaining-receipt-v3"
        and receipt.get("status") == "FAILED_BACKEND_REPLAY_NO_REPLACEMENT"
        and receipt.get("item_id") == "KLT_R02"
        and receipt.get("repeat_index") == 2
        and receipt.get("execution_lock") == lock_id
        and receipt.get("launch_allowance_consumed") is True
        and receipt.get("retry_count") == 0
        and receipt.get("replacement_permitted") is False
        and receipt.get("supervisor_errors") == []
        and receipt.get("trajectory_convention") == "world_T_body",
        "R02_TERMINAL_CONTROL",
    )
    require(
        isinstance(integrity, dict)
        and integrity.get("status") == "PASS"
        and integrity.get("irreversible_fault_latch_clear") is True
        and integrity.get("claim_stable") is True
        and integrity.get("workspace_binding_stable") is True
        and integrity.get("owned_processes_drained") is True
        and integrity.get("artifact_integrity_issues") == []
        and receipt.get("integrity_fault_latch") == [],
        "R02_EXECUTION_INTEGRITY",
    )
    require(
        isinstance(runtime, dict)
        and runtime.get("popen_invocation_count") == 1
        and runtime.get("child_started") is True
        and runtime.get("timed_out") is True
        and runtime.get("raw_return_code") == -9
        and isinstance(group, dict)
        and group.get("leader_reaped") is True
        and group.get("process_group_empty") is True
        and group.get("owned_descendants_empty") is True,
        "R02_CLEANUP_TIMEOUT_RUNTIME",
    )
    require(
        isinstance(artifact, dict)
        and artifact.get("status") == "FAIL"
        and artifact.get("issues") == [R02_ARTIFACT_ISSUE]
        and artifact.get("evidence_tree_integrity") is True
        and artifact.get("integrity_issues") == []
        and isinstance(outputs, dict)
        and set(outputs) == set(locked_item.get("expected_outputs", [])),
        "R02_COMPLETE_UNACCEPTED_ARTIFACTS",
    )
    require(
        isinstance(trajectory, dict)
        and trajectory.get("rows") == R02_EXPECTED_TRAJECTORY_ROWS
        and trajectory.get("convention") == "world_T_body"
        and isinstance(usability, dict)
        and usability.get("status") == "PASS"
        and usability.get("values", {}).get("output_poses")
        == float(R02_EXPECTED_TRAJECTORY_ROWS)
        and isinstance(replay, dict)
        and replay.get("status") == "FAIL"
        and replay.get("missing_keys") == list(R02_REPLAY_MANIFEST_MISSING_KEYS)
        and replay.get("conflicting_keys") == []
        and replay.get("child_self_fd_value_keys") == []
        and replay.get("explicit_lineage_conflict") is False
        and replay.get("sealed_fd_owner_pid") == runtime.get("pid")
        and isinstance(guard, dict)
        and guard.get("status") == "PASS"
        and guard.get("sealed_fd_owner_pid") == runtime.get("pid")
        and isinstance(network, dict) and network.get("status") == "PASS",
        "R02_COMPLETE_REPLAY_SEMANTICS",
    )
    process_log = receipt.get("process_log")
    require(isinstance(process_log, dict), "R02_PROCESS_LOG_IDENTITY")
    require(identity(Path(str(process_log.get("path", "")))) == process_log,
            "R02_PROCESS_LOG_LIVE_IDENTITY")
    for relative, claim in outputs.items():
        require(
            isinstance(claim, dict)
            and identity(Path(str(claim.get("path", "")))) == claim,
            f"R02_ARTIFACT_LIVE_IDENTITY:{relative}",
        )
    return {
        "item_id": "KLT_R02",
        "disposition": R02_DISPOSITION,
        "failure_code": R02_FAILURE_CODE,
        "receipt": dict(receipt_id),
        "v3_execution_lock": dict(lock_id),
        "base_deep_terminal_evidence_audit": "PASS",
        "v3_strict_deep_terminal_evidence_audit":
            "FAIL_EXPECTED_LEGACY_REPLAY_MANIFEST_SCHEMA",
        "v3_strict_deep_failure_code": R02_V3_WRAPPER_DEEP_FAILURE,
        "receipt_status": receipt["status"],
        "execution_integrity": "PASS",
        "runtime_timed_out": True,
        "raw_return_code": -9,
        "artifact_contract_status": "FAIL",
        "artifact_issue": R02_ARTIFACT_ISSUE,
        "evidence_tree_integrity": True,
        "complete_artifacts_identity_bound": True,
        "artifact_accepted": False,
        "complete_artifacts": True,
        "complete_artifact_identities": dict(outputs),
        "process_log": dict(process_log),
        "trajectory_complete": True,
        "trajectory_rows": R02_EXPECTED_TRAJECTORY_ROWS,
        "trajectory_identity": dict(outputs["vins_output/vio.csv"]),
        "trajectory_admitted": False,
        "diagnostic_ape_identity": dict(outputs["ape.txt"]),
        "diagnostic_ape_admitted_to_common_support": False,
        "backend_usability_status": "PASS",
        "replay_manifest_semantic_status": "FAIL_EXPECTED_LEGACY_SCHEMA",
        "replay_manifest_missing_keys": list(R02_REPLAY_MANIFEST_MISSING_KEYS),
        "guard_post_replay_append_not_executed_before_supervisor_timeout": True,
        "replay_completed": True,
        "post_result_cleanup_failed": True,
        "counts_as_valid_repeat": False,
        "rerun_or_replacement_permitted": False,
    }


def prior_r02_binding() -> dict[str, Any]:
    require(R02_RECEIPT.exists() and not R02_RECEIPT.is_symlink(),
            "R02_TERMINAL_RECEIPT_NOT_AVAILABLE")
    require(R02_TERMINAL_EXPECTED is not None,
            "R02_TERMINAL_EXPECTED_IDENTITY_NOT_FILLED")
    module = load_backend_v3_authority_module()
    bindings = module.resolve_frontend_bindings()
    lock, lock_id = module.verify_lock(BACKEND_V3_LOCK, bindings)
    require(lock.get("item_order") == ["KLT_R02", "KLT_R03", "KLT_R04", "KLT_R05"],
            "BACKEND_V3_LOCK_ORDER")
    receipt, receipt_id = stable_json(R02_RECEIPT)
    module._configure_engine()
    base_deep = module.BASE_PRIOR_RECEIPT(lock_id, lock["items"]["KLT_R02"])
    require(base_deep == receipt, "R02_BACKEND_V3_BASE_DEEP_RECEIPT")
    try:
        module.prior_receipt(lock_id, lock["items"]["KLT_R02"])
    except Exception as error:
        require(
            type(error).__name__ == "BackendProtocolError"
            and str(error) == R02_V3_WRAPPER_DEEP_FAILURE,
            "R02_BACKEND_V3_WRAPPER_UNEXPECTED_FAILURE",
        )
    else:
        raise AnalysisProtocolError("R02_BACKEND_V3_WRAPPER_MUST_FAIL_LEGACY_MANIFEST")
    return validate_r02_terminal_receipt(
        receipt, receipt_id, lock_id, lock["items"]["KLT_R02"]
    )


def load_backend_v4_authority_module() -> ModuleType:
    for path, label in (
        (BACKEND_V4_PROTOCOL, "protocol"), (BACKEND_V4_RUNNER, "runner"),
        (BACKEND_V4_GUARD, "guard"),
        (BACKEND_V4_LIFECYCLE_WRAPPER, "lifecycle-wrapper"),
        (BACKEND_V4_SIGNAL_MASK_LAUNCHER, "signal-mask-launcher"),
        (BACKEND_V4_TESTS, "tests"),
    ):
        common.regular_file(path, f"backend-v4-{label}")
    specification = importlib.util.spec_from_file_location(
        "a08_klt_remaining_backend_v4_authority_for_analysis", BACKEND_V4_RUNNER
    )
    require(specification is not None and specification.loader is not None,
            "BACKEND_V4_AUTHORITY_IMPORT_SPEC")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    for name in (
        "resolve_frontend_bindings", "verify_lock", "prior_receipt",
        "prior_r01_authority", "prior_r02_authority", "ITEM_ORDER",
        "BACKEND_ROOT", "DEFAULT_LOCK", "RECEIPT_NAME", "LOCK_SCHEMA",
        "LOCK_STATUS", "RECEIPT_SCHEMA", "PROTOCOL", "RUNNER",
        "REPLAY_ONLY_GUARD", "LIFECYCLE_WRAPPER", "PROCESS_FREE_TESTS",
        "SIGNAL_MASK_LAUNCHER", "PYTHON38", "REAL_VINS",
    ):
        require(hasattr(module, name), f"BACKEND_V4_INTERFACE:{name}")
    require(tuple(module.ITEM_ORDER) == V4_ITEM_ORDER, "BACKEND_V4_ITEM_ORDER")
    require(Path(module.BACKEND_ROOT) == BACKEND_V4_ROOT, "BACKEND_V4_ROOT")
    require(Path(module.DEFAULT_LOCK) == BACKEND_V4_LOCK, "BACKEND_V4_LOCK")
    require(module.RECEIPT_NAME == BACKEND_V4_RECEIPT_NAME, "BACKEND_V4_RECEIPT")
    require(Path(module.PROTOCOL) == BACKEND_V4_PROTOCOL, "BACKEND_V4_PROTOCOL")
    require(Path(module.RUNNER) == BACKEND_V4_RUNNER, "BACKEND_V4_RUNNER")
    require(Path(module.REPLAY_ONLY_GUARD) == BACKEND_V4_GUARD, "BACKEND_V4_GUARD")
    require(Path(module.LIFECYCLE_WRAPPER) == BACKEND_V4_LIFECYCLE_WRAPPER,
            "BACKEND_V4_LIFECYCLE_WRAPPER")
    require(Path(module.SIGNAL_MASK_LAUNCHER) == BACKEND_V4_SIGNAL_MASK_LAUNCHER,
            "BACKEND_V4_SIGNAL_MASK_LAUNCHER")
    require(Path(module.PROCESS_FREE_TESTS) == BACKEND_V4_TESTS, "BACKEND_V4_TESTS")
    require(Path(module.PYTHON38) == BACKEND_V4_PYTHON38, "BACKEND_V4_PYTHON38")
    require(Path(module.REAL_VINS) == BACKEND_V4_VINS_NODE, "BACKEND_V4_VINS_NODE")
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


def collect_backend_binding() -> dict[str, Any]:
    _configure_engine()
    module = load_backend_v4_authority_module()
    bindings = module.resolve_frontend_bindings()
    require(isinstance(bindings, dict), "BACKEND_V4_FRONTEND_BINDINGS")
    local_klt = collect_klt_frontend_binding()
    local_xfeat = collect_xfeat_exclusion()
    backend_klt = bindings.get("klt")
    backend_xfeat = bindings.get("excluded_xfeat")
    require(
        isinstance(backend_klt, dict)
        and backend_klt.get("receipt") == local_klt["receipt"]
        and backend_klt.get("accepted_receipt") == local_klt["receipt"],
        "BACKEND_V4_KLT_FRONTEND_BINDING",
    )
    require(
        isinstance(backend_xfeat, dict)
        and backend_xfeat.get("disposition") == local_xfeat["disposition"]
        and backend_xfeat.get("accepted_receipt_present") is False
        and backend_xfeat.get("backend_launched_count") == 0
        and backend_xfeat.get("learning_contribution_claim_permitted") is False,
        "BACKEND_V4_XFEAT_EXCLUSION_BINDING",
    )
    lock, lock_id = module.verify_lock(BACKEND_V4_LOCK, bindings)
    require(lock.get("schema_version") == module.LOCK_SCHEMA, "BACKEND_V4_LOCK_SCHEMA")
    require(lock.get("status") == module.LOCK_STATUS, "BACKEND_V4_LOCK_STATUS")
    require(lock.get("item_order") == list(V4_ITEM_ORDER), "BACKEND_V4_LOCK_ORDER")
    prior01 = prior_r01_binding()
    prior02 = prior_r02_binding()
    live01 = module.prior_r01_authority(bindings)
    live02 = module.prior_r02_authority(bindings)
    require(live01.get("disposition") == R01_DISPOSITION, "BACKEND_V4_PRIOR_R01")
    require(
        live02.get("disposition") == R02_DISPOSITION
        and live02.get("failure_code") == R02_FAILURE_CODE
        and live02.get("v3_terminal_receipt") == prior02["receipt"],
        "BACKEND_V4_PRIOR_R02",
    )
    require(
        live02.get("v3_execution_lock") == prior02["v3_execution_lock"]
        and live02.get("base_deep_terminal_evidence_audit") == "PASS"
        and live02.get("v3_strict_deep_terminal_evidence_audit")
            == "FAIL_EXPECTED_LEGACY_REPLAY_MANIFEST_SCHEMA"
        and live02.get("v3_strict_deep_failure_code")
            == R02_V3_WRAPPER_DEEP_FAILURE
        and live02.get("execution_integrity") == "PASS"
        and live02.get("runtime_timed_out") is True
        and live02.get("raw_return_code") == -9
        and live02.get("artifact_contract_status") == "FAIL"
        and live02.get("artifact_issue") == R02_ARTIFACT_ISSUE
        and live02.get("complete_artifacts") is True
        and live02.get("trajectory_complete") is True
        and live02.get("trajectory_admitted") is False
        and live02.get("replay_completed") is True
        and live02.get("post_result_cleanup_failed") is True
        and live02.get("rerun_or_replacement_permitted") is False,
        "BACKEND_V4_PRIOR_R02_EVIDENCE_BOUNDARY",
    )
    items = lock.get("items")
    require(isinstance(items, dict) and list(items) == list(V4_ITEM_ORDER),
            "BACKEND_V4_LOCK_ITEMS")
    rows = [_r01_population_row(prior01), _r02_population_row(prior02)]
    receipts = {"KLT_R01": prior01["receipt"], "KLT_R02": prior02["receipt"]}
    for item_id in V4_ITEM_ORDER:
        receipt_path = BACKEND_V4_ROOT / item_id / BACKEND_V4_RECEIPT_NAME
        receipt, receipt_id = stable_json(receipt_path)
        deep = module.prior_receipt(lock_id, items[item_id])
        require(deep == receipt, f"BACKEND_V4_DEEP_TERMINAL:{item_id}")
        row = _V3_VALIDATE_BACKEND_TERMINAL(
            module, item_id, receipt, lock_id, items[item_id]
        )
        row["backend_infrastructure_failure_retained_as_na"] = False
        row["receipt"] = receipt_id
        rows.append(row)
        receipts[item_id] = receipt_id
    valid = sum(
        bool(row["accepted_for_joint_mask"])
        for row in rows if row["item_id"] in V4_ITEM_ORDER
    )
    require(not rows[0]["accepted_for_joint_mask"]
            and not rows[1]["accepted_for_joint_mask"],
            "R01_R02_MUST_NEVER_ENTER_JOINT_MASK")
    return {
        "execution_lock": lock_id,
        "execution_contract_sha256": lock.get("contract_sha256"),
        "terminal_receipts": receipts, "planned_repeats": rows,
        "planned_count": 5, "v4_executable_count": 3,
        "v4_terminal_count": 3, "maximum_valid_count": 3,
        "valid_count": valid, "failed_count": 5 - valid,
        "infrastructure_na_count": 2,
        "prior_r01": prior01, "prior_r02": prior02,
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
        "backend_v4_protocol": identity(BACKEND_V4_PROTOCOL),
        "backend_v4_runner": identity(BACKEND_V4_RUNNER),
        "backend_v4_guard": identity(BACKEND_V4_GUARD),
        "backend_v4_lifecycle_wrapper": identity(BACKEND_V4_LIFECYCLE_WRAPPER),
        "backend_v4_signal_mask_launcher": identity(BACKEND_V4_SIGNAL_MASK_LAUNCHER),
        "backend_v4_process_free_tests": identity(BACKEND_V4_TESTS),
        "backend_v4_python38": identity(BACKEND_V4_PYTHON38),
        "backend_v4_vins_node": identity(BACKEND_V4_VINS_NODE),
        "analysis_v3_design_freeze": identity(ANALYSIS_V3_DESIGN_FREEZE),
        "backend_v3_execution_lock": identity(BACKEND_V3_LOCK),
        "v3_r02_terminal_receipt": identity(R02_RECEIPT),
    }
    require(R02_TERMINAL_EXPECTED is not None,
            "R02_TERMINAL_EXPECTED_IDENTITY_NOT_FILLED")
    r02 = values["v3_r02_terminal_receipt"]
    require((r02["size_bytes"], r02["sha256"]) == R02_TERMINAL_EXPECTED,
            "STATIC_R02_TERMINAL_IDENTITY")
    return values


def design_contract_snapshot() -> dict[str, Any]:
    value = json.loads(json.dumps(_V3_DESIGN_CONTRACT_SNAPSHOT()))
    value["campaign"] = "A08_HFNET_VS_KLT_ONLY_COMMON_SUPPORT_ADDITIVE_V4"
    value["grid"] = exact_grid_evidence()
    value["population_and_failure_rules"].update({
        "backend_item_order": list(FULL_ITEM_ORDER),
        "v4_backend_item_order": list(V4_ITEM_ORDER),
        "klt_planned_count": 5, "maximum_valid_klt_count": 3,
        "klt_valid_repeat_rule": "ONLY_PASS_BACKEND_REPLAY_ACCEPTED_AMONG_R03_R05",
        "klt_summary": "coordinatewise_median_over_all_valid_R03_R05_repeats",
        "r01_disposition": R01_DISPOSITION, "r01_counts_as_valid": False,
        "r01_rerun_or_replacement_permitted": False,
        "r02_disposition": R02_DISPOSITION, "r02_failure_code": R02_FAILURE_CODE,
        "r02_counts_as_valid": False,
        "r02_complete_trajectory_admitted": False,
        "r02_rerun_or_replacement_permitted": False,
        "two_infrastructure_na_slots_retained": True,
        "best_repeat_selection_permitted": False,
    })
    value["execution_rules"].update({
        "design_freeze_before_v4_backend_terminal_results": True,
        "dynamic_lock_after_three_v4_terminal_receipts_before_accuracy": True,
        "dynamic_lock_after_four_v3_terminal_receipts_before_accuracy": False,
        "r02_terminal_artifacts_opened_only_for_exclusion_and_lineage": True,
        "backend_v4_unblocks_inherited_hup_int_term_before_overlay_exec": True,
        "backend_v4_vins_lifecycle_wrapper_is_separately_identity_bound": True,
    })
    return value


def backend_v4_terminal_presence() -> dict[str, str]:
    paths = {"backend_v4_execution_lock": BACKEND_V4_LOCK, **{
        item: BACKEND_V4_ROOT / item / BACKEND_V4_RECEIPT_NAME
        for item in V4_ITEM_ORDER
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


def backend_v4_authority_source_presence() -> dict[str, str]:
    paths = {
        "backend_v4_protocol": BACKEND_V4_PROTOCOL,
        "backend_v4_runner": BACKEND_V4_RUNNER,
        "backend_v4_guard": BACKEND_V4_GUARD,
        "backend_v4_lifecycle_wrapper": BACKEND_V4_LIFECYCLE_WRAPPER,
        "backend_v4_signal_mask_launcher": BACKEND_V4_SIGNAL_MASK_LAUNCHER,
        "backend_v4_process_free_tests": BACKEND_V4_TESTS,
        "backend_v4_python38": BACKEND_V4_PYTHON38,
        "backend_v4_vins_node": BACKEND_V4_VINS_NODE,
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


def backend_v4_campaign_prelaunch_presence() -> dict[str, str]:
    paths: dict[str, Path] = {
        "backend_v4_root": BACKEND_V4_ROOT,
        "backend_v4_runtime_root": BACKEND_V4_RUNTIME_ROOT,
    }
    for item in V4_ITEM_ORDER:
        repeat = int(item[-2:])
        tag = f"a08_recoveredjuly_hist0000_4660_backend_klt_only_r{repeat:02d}_v4"
        paths[f"workspace:{item}"] = (
            BACKEND_OVERLAY_RUN_ROOT / f"external_klt_every2_{tag}"
        )
    return {
        label: ("PRESENT" if path.exists() or path.is_symlink() else "ABSENT")
        for label, path in paths.items()
    }


def v3_remaining_r03_r05_presence() -> dict[str, str]:
    paths: dict[str, Path] = {}
    for item in V4_ITEM_ORDER:
        repeat = int(item[-2:])
        tag = f"a08_recoveredjuly_hist0000_4660_backend_klt_only_r{repeat:02d}_v3"
        paths.update({
            f"output:{item}": BACKEND_V3_ROOT / item,
            f"runtime:{item}": BACKEND_V3_RUNTIME_ROOT / item,
            f"workspace:{item}": (
                BACKEND_OVERLAY_RUN_ROOT / f"external_klt_every2_{tag}"
            ),
        })
    return {
        label: ("PRESENT" if path.exists() or path.is_symlink() else "ABSENT")
        for label, path in paths.items()
    }


def _require_prior_analysis_diversions_untouched() -> None:
    V3._require_analysis_diversion_untouched()
    for path, code in (
        (ANALYSIS_V3_LOCK, "FROZEN_ANALYSIS_V3_LOCK_MUST_REMAIN_ABSENT"),
        (ANALYSIS_V3_OUTPUT, "FROZEN_ANALYSIS_V3_OUTPUT_MUST_REMAIN_ABSENT"),
        (ANALYSIS_V3_CLAIM, "FROZEN_ANALYSIS_V3_CLAIM_MUST_REMAIN_ABSENT"),
    ):
        ENGINE.regular_absence(path, code)


def build_design_freeze_payload(created_at_utc: str) -> dict[str, Any]:
    presence = backend_v4_terminal_presence()
    require(all(value == "MISSING" for value in presence.values()),
            "DESIGN_FREEZE_MUST_PRECEDE_V4_BACKEND_LOCK_AND_RESULTS")
    prelaunch = backend_v4_campaign_prelaunch_presence()
    require(all(value == "ABSENT" for value in prelaunch.values()),
            "DESIGN_FREEZE_MUST_PRECEDE_ANY_V4_BACKEND_TOUCH")
    old_remaining = v3_remaining_r03_r05_presence()
    require(all(value == "ABSENT" for value in old_remaining.values()),
            "OLD_V3_R03_R05_MUST_REMAIN_UNTOUCHED")
    ENGINE.regular_absence(DEFAULT_LOCK, "DESIGN_FREEZE_MUST_PRECEDE_V4_ANALYSIS_LOCK")
    require(analysis_output_state() == "ABSENT",
            "DESIGN_FREEZE_MUST_PRECEDE_V4_ANALYSIS_OUTPUT")
    _require_prior_analysis_diversions_untouched()
    prior01 = prior_r01_binding()
    prior02 = prior_r02_binding()
    payload = {
        "schema_version": DESIGN_FREEZE_SCHEMA, "status": DESIGN_FREEZE_STATUS,
        "created_at_utc": created_at_utc,
        "static_identities": collect_static_identities(),
        "sealed_support": common.collect_support_binding(),
        "klt_frontend": collect_klt_frontend_binding(),
        "excluded_xfeat": collect_xfeat_exclusion(),
        "evo_authority": common.collect_evo_authority(),
        "prior_r01": prior01, "prior_r02": prior02,
        "design_contract": design_contract_snapshot(),
        "backend_v4_terminal_presence_at_freeze": presence,
        "backend_v4_campaign_prelaunch_presence_at_freeze": prelaunch,
        "v3_remaining_r03_r05_presence_at_freeze": old_remaining,
        "claim_boundary": {
            "r01_r02_terminal_failures_opened_only_for_exclusion": True,
            "r02_complete_artifacts_identity_bound_but_unaccepted": True,
            "r02_trajectory_opened_for_common_support": False,
            "backend_v4_execution_lock_built": False,
            "v4_backend_items_started": 0,
            "ape_or_rpe_computed_for_v4": False,
            "final_dynamic_analysis_lock_built": False,
            "ros_or_vins_started_for_v4": False,
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
        "status": "ADDITIVE_V4_STATIC_DESIGN_FREEZE_PUBLISHED_NO_ACCURACY_COMPUTED",
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
    require(value.get("design_contract") == design_contract_snapshot(),
            "DESIGN_FREEZE_CONTRACT")
    expected_presence = {"backend_v4_execution_lock": "MISSING", **{
        item: "MISSING" for item in V4_ITEM_ORDER
    }}
    expected_prelaunch = {
        "backend_v4_root": "ABSENT", "backend_v4_runtime_root": "ABSENT",
        **{f"workspace:{item}": "ABSENT" for item in V4_ITEM_ORDER},
    }
    expected_old = {
        f"{kind}:{item}": "ABSENT" for item in V4_ITEM_ORDER
        for kind in ("output", "runtime", "workspace")
    }
    require(value.get("backend_v4_terminal_presence_at_freeze") == expected_presence,
            "DESIGN_FREEZE_PRIOR_V4_TERMINAL_ABSENCE")
    require(value.get("backend_v4_campaign_prelaunch_presence_at_freeze") == expected_prelaunch,
            "DESIGN_FREEZE_PRIOR_V4_TOUCH_ABSENCE")
    require(value.get("v3_remaining_r03_r05_presence_at_freeze") == expected_old,
            "DESIGN_FREEZE_OLD_V3_R03_R05_UNTOUCHED")
    boundary = value.get("claim_boundary")
    require(
        isinstance(boundary, dict)
        and boundary.get("r02_complete_artifacts_identity_bound_but_unaccepted") is True
        and boundary.get("r02_trajectory_opened_for_common_support") is False
        and boundary.get("backend_v4_execution_lock_built") is False
        and boundary.get("v4_backend_items_started") == 0
        and boundary.get("ape_or_rpe_computed_for_v4") is False
        and boundary.get("ros_or_vins_started_for_v4") is False,
        "DESIGN_FREEZE_CLAIM_BOUNDARY",
    )
    return {"identity": freeze_id, "created_at_utc": value.get("created_at_utc"),
            "freeze_sha256": digest}


def design_freeze_audit_readonly() -> dict[str, Any]:
    try:
        return {
            "status": "PASS_DESIGN_FROZEN_AFTER_R01_R02_BEFORE_R03_R05",
            "read_only": True, "design_freeze": collect_design_freeze_binding(),
            "accuracy_computed": False,
        }
    except (AnalysisProtocolError, OSError, ValueError) as error:
        presence = backend_v4_terminal_presence()
        late = any(value != "MISSING" for value in presence.values())
        return {
            "status": ("BLOCKED_LATE_OR_INVALID_V4_DESIGN_FREEZE"
                       if late else "BLOCKED_DESIGN_FREEZE"),
            "read_only": True, "error": f"{type(error).__name__}:{error}",
            "backend_v4_terminal_presence": presence, "accuracy_computed": False,
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
        "campaign": "A08_HFNET_VS_KLT_ONLY_COMMON_SUPPORT_ADDITIVE_V4",
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
    rows = _V3_ORIGINAL_TEN_SLOT_ROWS(backend, arms, ranking)
    for row in rows:
        if row["item_id"] == "KLT_R02":
            row.update({
                "backend_launched": True, "backend_replay_started": True,
                "backend_replay_completed": True,
                "post_result_cleanup_failed": True,
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
        elif row.get("item_id") != "KLT_R01":
            row["backend_infrastructure_failure_retained_as_na"] = False
    formal["r01_disposition"] = R01_DISPOSITION
    formal["r02_disposition"] = R02_DISPOSITION
    formal["maximum_valid_klt_count"] = 3
    formal["valid_klt_repeat_rule"] = "ONLY_PASS_BACKEND_REPLAY_ACCEPTED_AMONG_R03_R05"
    return formal


def build_formal_summary(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _decorate_formal(_V3_BUILD_FORMAL_SUMMARY(*args, **kwargs))


def build_error_formal_summary(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _decorate_formal(_V3_BUILD_ERROR_FORMAL_SUMMARY(*args, **kwargs))


def validate_formal_population_binding(
    formal: Mapping[str, Any], lock: Mapping[str, Any]
) -> None:
    _V3_VALIDATE_FORMAL_POPULATION(formal, lock)
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
    value = _V3_MAKE_TERMINAL_RECEIPT(*args, **kwargs)
    value.update({
        "r01_disposition": R01_DISPOSITION, "r02_disposition": R02_DISPOSITION,
        "maximum_valid_klt_count": 3,
        "valid_klt_repeat_rule": "ONLY_PASS_BACKEND_REPLAY_ACCEPTED_AMONG_R03_R05",
    })
    return value


def _configure_engine() -> None:
    assignments = {
        "BACKEND_ROOT": BACKEND_V4_ROOT, "BACKEND_LOCK": BACKEND_V4_LOCK,
        "BACKEND_RUNNER": BACKEND_V4_RUNNER, "BACKEND_PROTOCOL": BACKEND_V4_PROTOCOL,
        "BACKEND_RECEIPT_NAME": BACKEND_V4_RECEIPT_NAME,
        "BACKEND_RUNTIME_ROOT": BACKEND_V4_RUNTIME_ROOT,
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
        "load_backend_authority_module": load_backend_v4_authority_module,
        "collect_backend_binding": collect_backend_binding,
        "collect_static_identities": collect_static_identities,
        "design_contract_snapshot": design_contract_snapshot,
        "backend_terminal_presence": backend_v4_terminal_presence,
        "backend_campaign_prelaunch_presence": backend_v4_campaign_prelaunch_presence,
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
        if not R02_RECEIPT.exists() and not R02_RECEIPT.is_symlink():
            return {
                "status": "WAITING_V3_R02_NATURAL_TERMINAL_RECEIPT",
                "read_only": True, "r02_receipt": str(R02_RECEIPT),
                "r02_interruption_or_replacement_permitted": False,
                "design_freeze_present": False, "accuracy_computed": False,
            }
        if R02_TERMINAL_EXPECTED is None:
            return {
                "status": "WAITING_R02_TERMINAL_EXACT_IDENTITY_FREEZE_CONSTANT",
                "read_only": True, "r02_receipt": identity(R02_RECEIPT),
                "design_freeze_present": False, "accuracy_computed": False,
            }
        source_presence = backend_v4_authority_source_presence()
        unavailable_sources = [
            key for key, value in source_presence.items()
            if value != "PRESENT_REGULAR"
        ]
        if unavailable_sources:
            return {
                "status": "WAITING_BACKEND_V4_CANDIDATE_AUTHORITIES",
                "read_only": True, "backend_v4_source_presence": source_presence,
                "unavailable": unavailable_sources,
                "design_freeze_present": False, "accuracy_computed": False,
            }
        try:
            payload = build_design_freeze_payload("READ_ONLY_CANDIDATE")
            return {
                "status": "READY_TO_PUBLISH_ANALYSIS_V4_STATIC_DESIGN_FREEZE",
                "read_only": True, "candidate_freeze_sha256": payload["freeze_sha256"],
                "design_freeze_present": False, "accuracy_computed": False,
            }
        except (AnalysisProtocolError, OSError, ValueError) as error:
            return {"status": "BLOCKED_DESIGN_FREEZE", "read_only": True,
                    "error": f"{type(error).__name__}:{error}",
                    "accuracy_computed": False}
    freeze = design_freeze_audit_readonly()
    if freeze["status"] != "PASS_DESIGN_FROZEN_AFTER_R01_R02_BEFORE_R03_R05":
        return {"status": "BLOCKED_DESIGN_FREEZE", "read_only": True,
                "design_freeze_audit": freeze, "accuracy_computed": False}
    presence = backend_v4_terminal_presence()
    unavailable = [key for key, value in presence.items() if value != "PRESENT_REGULAR"]
    if unavailable:
        return {
            "status": "WAITING_FOR_BACKEND_V4_LOCK_AND_THREE_TERMINAL_RECEIPTS",
            "read_only": True, "terminal_presence": presence,
            "unavailable": unavailable,
            "analysis_lock_present": lock_path.exists() or lock_path.is_symlink(),
            "r01_disposition": R01_DISPOSITION, "r02_disposition": R02_DISPOSITION,
            "excluded_xfeat_disposition": XFEAT_DISPOSITION,
            "accuracy_computed": False,
        }
    try:
        _configure_engine()
        if not lock_path.exists() and not lock_path.is_symlink():
            require(analysis_output_state() == "ABSENT", "ANALYSIS_OUTPUT_PREEXISTS")
            authority = collect_authority()
            return {
                "status": "READY_TO_BUILD_ANALYSIS_V4_LOCK_NO_ACCURACY_COMPUTED",
                "read_only": True, "terminal_presence": presence,
                "klt_planned_count": 5,
                "klt_valid_count": authority["backend"]["valid_count"],
                "maximum_valid_klt_count": 3,
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
    presence = backend_v4_terminal_presence()
    require(all(value == "PRESENT_REGULAR" for value in presence.values()),
            "THREE_V4_TERMINAL_RECEIPTS_REQUIRED")
    authority = collect_authority()
    require(authority["backend"]["planned_count"] == 5, "PLANNED_COUNT")
    require(authority["backend"]["maximum_valid_count"] == 3, "MAX_VALID_COUNT")
    payload = build_lock_payload(
        authority, datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    atomic_publish(lock_path, payload)
    return {
        "status": "FINAL_ANALYSIS_V4_LOCK_PUBLISHED_NO_ACCURACY_COMPUTED",
        "lock": identity(lock_path), "klt_planned_count": 5,
        "klt_valid_count": authority["backend"]["valid_count"],
        "maximum_valid_klt_count": 3, "r01_disposition": R01_DISPOSITION,
        "r02_disposition": R02_DISPOSITION,
        "excluded_xfeat_disposition": XFEAT_DISPOSITION,
        "accuracy_computed": False,
    }


def execute_analysis(lock_path: Path, authorization_token: str) -> tuple[int, dict[str, Any]]:
    _configure_engine(); return ENGINE.execute_analysis(lock_path, authorization_token)


def audit_readonly(lock_path: Path = DEFAULT_LOCK) -> dict[str, Any]:
    _configure_engine(); result = ENGINE.audit_readonly(lock_path)
    result.update({"r01_disposition": R01_DISPOSITION,
                   "r02_disposition": R02_DISPOSITION,
                   "maximum_valid_klt_count": 3})
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
        print(f"A08_HFNET_KLT_V4_ERROR:{type(error).__name__}:{error}", file=sys.stderr)
        return 2


_configure_engine()


if __name__ == "__main__":
    raise SystemExit(main())
