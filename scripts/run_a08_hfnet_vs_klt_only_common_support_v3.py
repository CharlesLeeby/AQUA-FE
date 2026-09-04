#!/usr/bin/env python3
"""Additive A08 HFNet-vs-KLT analysis after the consumed v2 R01 failure.

Importing this module is inert.  The static design freeze, dynamic analysis
lock, and one-shot numerical analysis are three separate no-replace
transitions.  R01 is permanently retained as infrastructure NA; only accepted
R02--R05 trajectories can enter the frozen v2 common-support evaluator.
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

V2_PROTOCOL = WORKSPACE / "papers/a08_hfnet_vs_klt_only_common_support_v2_protocol.md"
V2_RUNNER = WORKSPACE / "scripts/run_a08_hfnet_vs_klt_only_common_support_v2.py"
V2_TESTS = WORKSPACE / "scripts/tests/test_run_a08_hfnet_vs_klt_only_common_support_v2.py"
V2_DESIGN_FREEZE = WORKSPACE / "papers/a08_hfnet_vs_klt_only_common_support_v2_design_freeze.json"
V2_ANALYSIS_LOCK = WORKSPACE / "papers/a08_hfnet_vs_klt_only_common_support_v2_execution_lock.json"
V2_ANALYSIS_OUTPUT = EXPERIMENT / "hfnet_vs_klt_only_common_support_v2"
V2_ANALYSIS_CLAIM = EXPERIMENT / "hfnet_vs_klt_only_common_support_start_claim_v2.json"

V2_BACKEND_LOCK = WORKSPACE / (
    "papers/a08_recovered_july_history_matched_backend_klt_only_replays_v2_"
    "execution_lock.json"
)
V2_BACKEND_ROOT = EXPERIMENT / "backend_klt_only_replays_v2"
V2_BACKEND_RUNTIME_ROOT = EXPERIMENT / "runtime/backend_klt_only_replays_v2"
V2_R01_RECEIPT = V2_BACKEND_ROOT / "KLT_R01/formal_run_receipt_v2.json"

BACKEND_V3_PROTOCOL = WORKSPACE / (
    "papers/a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v3_protocol.md"
)
BACKEND_V3_RUNNER = WORKSPACE / (
    "scripts/run_a08_recovered_july_history_matched_backend_klt_only_"
    "remaining_replays_v3.py"
)
BACKEND_V3_GUARD = WORKSPACE / (
    "scripts/run_a08_recovered_july_history_matched_backend_klt_only_"
    "replay_guard_v3.sh"
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
BACKEND_OVERLAY_RUN_ROOT = (
    EXPERIMENT / "recovered_july_core_overlay_v1/logs/aqualoc_archaeo_vins"
)
BACKEND_V3_RECEIPT_NAME = "formal_run_receipt_v3.json"

PROTOCOL = WORKSPACE / "papers/a08_hfnet_vs_klt_only_common_support_v3_protocol.md"
RUNNER = WORKSPACE / "scripts/run_a08_hfnet_vs_klt_only_common_support_v3.py"
TESTS = WORKSPACE / "scripts/tests/test_run_a08_hfnet_vs_klt_only_common_support_v3.py"
DESIGN_FREEZE = WORKSPACE / "papers/a08_hfnet_vs_klt_only_common_support_v3_design_freeze.json"
DEFAULT_LOCK = WORKSPACE / "papers/a08_hfnet_vs_klt_only_common_support_v3_execution_lock.json"

OUTPUT_ROOT = EXPERIMENT / "hfnet_vs_klt_only_common_support_v3"
CLAIM_PATH = EXPERIMENT / "hfnet_vs_klt_only_common_support_start_claim_v3.json"
STAGING_ROOT = EXPERIMENT / ".hfnet_vs_klt_only_common_support_v3.staging"
EVO_WORK_ROOT = EXPERIMENT / ".hfnet_vs_klt_only_common_support_v3.evo_work"
FAILURE_STAGING_ROOT = EXPERIMENT / ".hfnet_vs_klt_only_common_support_v3.failure_staging"

FULL_ITEM_ORDER = tuple(f"KLT_R{repeat:02d}" for repeat in range(1, 6))
V3_ITEM_ORDER = ("KLT_R02", "KLT_R03", "KLT_R04", "KLT_R05")
ORIGINAL_TEN_SLOT_ORDER = tuple(
    slot
    for repeat in range(1, 6)
    for slot in (f"KLT_R{repeat:02d}", f"XFEAT_R{repeat:02d}")
)
R01_DISPOSITION = (
    "NA_BACKEND_INFRASTRUCTURE_FD_INHERITANCE_FAILURE_"
    "NO_REPLAY_NO_REPLACEMENT"
)
XFEAT_DISPOSITION = "NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED"

DESIGN_FREEZE_SCHEMA = "aqua-fe-a08-hfnet-vs-klt-only-common-support-design-freeze-v3"
DESIGN_FREEZE_STATUS = (
    "FROZEN_AFTER_R01_INFRASTRUCTURE_FAILURE_BEFORE_R02_R05_BACKEND_AND_ACCURACY"
)
LOCK_SCHEMA = "aqua-fe-a08-hfnet-vs-klt-only-common-support-lock-v3"
LOCK_STATUS = "FROZEN_AFTER_FOUR_V3_TERMINAL_RECEIPTS_BEFORE_ACCURACY_VISIBLE"
CLAIM_SCHEMA = "aqua-fe-a08-hfnet-vs-klt-only-common-support-claim-v3"
RECEIPT_SCHEMA = "aqua-fe-a08-hfnet-vs-klt-only-common-support-receipt-v3"
FORMAL_SCHEMA = "aqua-fe-a08-formal-hfnet-vs-klt-only-common-support-summary-v3"

FREEZE_TOKEN = (
    "A08_FREEZE_HFNET_VS_KLT_ONLY_COMMON_SUPPORT_V3_AFTER_R01_"
    "BEFORE_R02_R05_BACKEND"
)
BUILD_LOCK_TOKEN = (
    "A08_BUILD_HFNET_VS_KLT_ONLY_COMMON_SUPPORT_V3_LOCK_AFTER_FOUR_TERMINALS_"
    "BEFORE_ACCURACY"
)
RUN_TOKEN = "A08_RUN_HFNET_VS_KLT_ONLY_COMMON_SUPPORT_V3_EXACTLY_ONCE_NO_RETRY"

GRID_NAME = "exact_integer_ns_grid_v3.json"
RAW_SUMMARY_NAME = "common_support_summary.json"
GRID_AUDIT_NAME = "common_grid_audit.csv"
RAW_METRICS_NAME = "common_support_metrics.csv"
RAW_DIAGNOSTIC_MANIFEST_NAME = "raw_numeric_diagnostics_boundary_v3.json"
REPEAT_TABLE_NAME = "original_ten_slot_dispositions_v3.csv"
FORMAL_SUMMARY_NAME = "formal_hfnet_vs_klt_only_summary_v3.json"
EVO_SUMMARY_NAME = "evo_crosscheck.json"
RECEIPT_NAME = "formal_analysis_receipt_v3.json"
PARTIAL_EVIDENCE_NAME = "uncommitted_partial_evidence_v3.json"

FROZEN_V2_EXPECTED = {
    "protocol": (11_335, "e429f62cd644661d3d9964f466b5b84d989af47313b131b2ba2e660933531132"),
    "runner": (86_460, "f6dc1364607a0332da0f4f552f57716182be87b044d072f592c71c740e8d6ddd"),
    "tests": (30_682, "c7d3deda07945c6759e5a9761e3dbec0f99e09b67aac4bedc98944bdcfe0da76"),
    "design_freeze": (10_631, "1e842f4083de2e7eacdf292f373e82fc1c328e4564c94699e601c0740275c10f"),
}
V2_LOCK_EXPECTED = (90_258, "46e77bf9c812f875e8184d1d9af251fff5097b6bbc9461fff187e408b6b96a3a")
R01_RECEIPT_EXPECTED = (9_999, "92bbcaa486eb353a43db6d9aa772d7022a2e2440794188181909a1f65a55848b")
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
R01_FAILURE_CODE = "ROSBAG_PYTHON_SUBPROCESS_CLOSE_FDS_DROPPED_SEALED_FD9"


def _raw_identity(path: Path) -> tuple[int, str]:
    raw = path.read_bytes()
    return len(raw), hashlib.sha256(raw).hexdigest()


def _load_frozen_v2() -> ModuleType:
    path = V2_RUNNER.absolute()
    if (
        not path.exists() or path.is_symlink()
        or not stat.S_ISREG(path.lstat().st_mode)
        or path.resolve(strict=True) != path
        or _raw_identity(path) != FROZEN_V2_EXPECTED["runner"]
    ):
        raise RuntimeError("FROZEN_ANALYSIS_V2_RUNNER_IDENTITY_DRIFT")
    specification = importlib.util.spec_from_file_location(
        "a08_hfnet_klt_analysis_v2_frozen_engine_for_v3", path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("FROZEN_ANALYSIS_V2_IMPORT_SPEC")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


BASE = _load_frozen_v2()
AnalysisProtocolError = BASE.AnalysisProtocolError
require = BASE.require
identity = BASE.identity
stable_json = BASE.stable_json
compact_sha256 = BASE.compact_sha256
atomic_publish = BASE.atomic_publish
common = BASE.common
PRIMARY_METRICS = BASE.PRIMARY_METRICS

_V2_EXACT_GRID_EVIDENCE = BASE.exact_grid_evidence
_V2_DESIGN_CONTRACT_SNAPSHOT = BASE.design_contract_snapshot
_V2_COLLECT_KLT_FRONTEND_BINDING = BASE.collect_klt_frontend_binding
_V2_COLLECT_XFEAT_EXCLUSION = BASE.collect_xfeat_exclusion
_V2_VALIDATE_BACKEND_TERMINAL = BASE.validate_backend_terminal_receipt
_V2_ORIGINAL_TEN_SLOT_ROWS = BASE.original_ten_slot_rows
_V2_BUILD_FORMAL_SUMMARY = BASE.build_formal_summary
_V2_BUILD_ERROR_FORMAL_SUMMARY = BASE.build_error_formal_summary
_V2_VALIDATE_FORMAL_POPULATION = BASE.validate_formal_population_binding
_V2_MAKE_TERMINAL_RECEIPT = BASE.make_terminal_receipt


def exact_grid_evidence() -> dict[str, Any]:
    value = _V2_EXACT_GRID_EVIDENCE()
    value["schema_version"] = "aqua-fe-a08-exact-integer-ns-grid-v3"
    return value


def collect_klt_frontend_binding() -> dict[str, Any]:
    return _V2_COLLECT_KLT_FRONTEND_BINDING()


def collect_xfeat_exclusion() -> dict[str, Any]:
    value = _V2_COLLECT_XFEAT_EXCLUSION()
    require(value.get("disposition") == XFEAT_DISPOSITION, "XFEAT_DISPOSITION")
    return value


def _check_frozen_v2_identities() -> dict[str, Any]:
    paths = {
        "protocol": V2_PROTOCOL,
        "runner": V2_RUNNER,
        "tests": V2_TESTS,
        "design_freeze": V2_DESIGN_FREEZE,
    }
    result = {label: identity(path) for label, path in paths.items()}
    for label, expected in FROZEN_V2_EXPECTED.items():
        observed = result[label]
        require(
            (observed["size_bytes"], observed["sha256"]) == expected,
            f"FROZEN_ANALYSIS_V2_IDENTITY:{label}",
        )
    return result


def prior_r01_binding() -> dict[str, Any]:
    """Deeply re-audit the consumed v2 R01 without admitting its trajectory."""
    lock_id = identity(V2_BACKEND_LOCK)
    receipt, receipt_id = stable_json(V2_R01_RECEIPT)
    require(
        (lock_id["size_bytes"], lock_id["sha256"]) == V2_LOCK_EXPECTED,
        "V2_EXECUTION_LOCK_IDENTITY",
    )
    require(
        (receipt_id["size_bytes"], receipt_id["sha256"]) == R01_RECEIPT_EXPECTED,
        "V2_R01_RECEIPT_IDENTITY",
    )
    module = load_backend_v3_authority_module()
    bindings = module.resolve_frontend_bindings()
    deep = module.prior_r01_authority(bindings)
    require(
        deep.get("v2_execution_lock") == lock_id
        and deep.get("v2_terminal_receipt") == receipt_id
        and deep.get("disposition") == R01_DISPOSITION
        and deep.get("counts_as_valid_repeat") is False
        and deep.get("rerun_permitted") is False,
        "V2_R01_DEEP_TERMINAL_EVIDENCE",
    )
    integrity = receipt.get("execution_integrity")
    artifact = receipt.get("artifact_contract")
    outputs = artifact.get("outputs") if isinstance(artifact, dict) else None
    vio = outputs.get("vins_output/vio.csv") if isinstance(outputs, dict) else None
    ape = outputs.get("ape.txt") if isinstance(outputs, dict) else None
    require(
        receipt.get("status") == "FAILED_BACKEND_REPLAY_NO_REPLACEMENT"
        and isinstance(integrity, dict)
        and integrity.get("status") == "PASS"
        and integrity.get("irreversible_fault_latch_clear") is True
        and receipt.get("retry_count") == 0
        and receipt.get("replacement_permitted") is False
        and receipt.get("launch_allowance_consumed") is True,
        "V2_R01_TERMINAL_FAILURE_CONTRACT",
    )
    require(
        isinstance(artifact, dict)
        and artifact.get("status") == "FAIL"
        and artifact.get("evidence_tree_integrity") is True
        and artifact.get("integrity_issues") == []
        and isinstance(vio, dict)
        and vio.get("size_bytes") == 0
        and vio.get("sha256") == EMPTY_SHA256
        and isinstance(ape, dict)
        and ape.get("size_bytes") == 0
        and ape.get("sha256") == EMPTY_SHA256,
        "V2_R01_EMPTY_UNACCEPTED_TRAJECTORY",
    )
    process_log = receipt.get("process_log")
    require(isinstance(process_log, dict), "V2_R01_PROCESS_LOG")
    log_path = Path(str(process_log.get("path", "")))
    before = identity(log_path)
    require(before == process_log, "V2_R01_PROCESS_LOG_IDENTITY")
    text = log_path.read_text(encoding="utf-8", errors="replace")
    require(identity(log_path) == before, "V2_R01_PROCESS_LOG_READ_STABILITY")
    require(
        "Opening /proc/self/fd/9" in text
        and "Error opening file: /proc/self/fd/9" in text,
        "V2_R01_FD_INHERITANCE_SIGNATURE",
    )
    return {
        "item_id": "KLT_R01",
        "disposition": R01_DISPOSITION,
        "receipt": receipt_id,
        "v2_execution_lock": lock_id,
        "v2_deep_terminal_evidence_audit": "PASS",
        "vio_empty": True,
        "empty_vio": vio,
        "ape_empty": True,
        "empty_ape": ape,
        "artifact_accepted": False,
        "failure_code": R01_FAILURE_CODE,
        "execution_integrity": "PASS",
        "backend_supervisor_launched": True,
        "backend_replay_started": False,
        "rerun_or_replacement_permitted": False,
        "process_log": before,
    }


def load_backend_v3_authority_module() -> ModuleType:
    for path, code in (
        (BACKEND_V3_RUNNER, "RUNNER"),
        (BACKEND_V3_PROTOCOL, "PROTOCOL"),
        (BACKEND_V3_GUARD, "GUARD"),
    ):
        BASE.common.regular_file(path, f"backend-v3-{code.lower()}")
    specification = importlib.util.spec_from_file_location(
        "a08_klt_remaining_backend_v3_authority_for_analysis", BACKEND_V3_RUNNER
    )
    require(
        specification is not None and specification.loader is not None,
        "BACKEND_V3_AUTHORITY_IMPORT_SPEC",
    )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    for name in (
        "resolve_frontend_bindings", "verify_lock", "prior_receipt",
        "prior_r01_authority", "ITEM_ORDER", "BACKEND_ROOT", "DEFAULT_LOCK",
        "RECEIPT_NAME", "LOCK_SCHEMA", "LOCK_STATUS", "RECEIPT_SCHEMA",
        "PROTOCOL", "RUNNER", "REPLAY_ONLY_GUARD", "PROCESS_FREE_TESTS",
    ):
        require(hasattr(module, name), f"BACKEND_V3_INTERFACE:{name}")
    require(tuple(module.ITEM_ORDER) == V3_ITEM_ORDER, "BACKEND_V3_ITEM_ORDER")
    require(Path(module.BACKEND_ROOT) == BACKEND_V3_ROOT, "BACKEND_V3_ROOT")
    require(Path(module.DEFAULT_LOCK) == BACKEND_V3_LOCK, "BACKEND_V3_LOCK")
    require(module.RECEIPT_NAME == BACKEND_V3_RECEIPT_NAME, "BACKEND_V3_RECEIPT")
    require(Path(module.PROTOCOL) == BACKEND_V3_PROTOCOL, "BACKEND_V3_PROTOCOL")
    require(Path(module.RUNNER) == BACKEND_V3_RUNNER, "BACKEND_V3_RUNNER")
    require(Path(module.REPLAY_ONLY_GUARD) == BACKEND_V3_GUARD, "BACKEND_V3_GUARD")
    require(Path(module.PROCESS_FREE_TESTS) == BACKEND_V3_TESTS, "BACKEND_V3_TESTS")
    return module


def _r01_population_row(prior: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "item_id": "KLT_R01",
        "arm": "klt",
        "repeat_index": 1,
        "disposition": R01_DISPOSITION,
        "accepted_for_joint_mask": False,
        "trajectory": None,
        "scientific_failure_retained_as_na": False,
        "backend_infrastructure_failure_retained_as_na": True,
        "backend_launched": True,
        "backend_replay_started": False,
        "replacement_permitted": False,
        "receipt": prior["receipt"],
    }


def collect_backend_binding() -> dict[str, Any]:
    """Collect R01 from v2 and four terminal R02--R05 receipts from v3."""
    _configure_base()
    module = load_backend_v3_authority_module()
    bindings = module.resolve_frontend_bindings()
    require(isinstance(bindings, dict), "BACKEND_V3_FRONTEND_BINDINGS")
    local_klt = collect_klt_frontend_binding()
    local_xfeat = collect_xfeat_exclusion()
    backend_klt = bindings.get("klt")
    backend_xfeat = bindings.get("excluded_xfeat")
    require(
        isinstance(backend_klt, dict)
        and backend_klt.get("receipt") == local_klt["receipt"]
        and backend_klt.get("accepted_receipt") == local_klt["receipt"],
        "BACKEND_V3_KLT_FRONTEND_BINDING",
    )
    require(
        isinstance(backend_xfeat, dict)
        and backend_xfeat.get("disposition") == local_xfeat["disposition"]
        and backend_xfeat.get("forensic_audit") == local_xfeat["forensic_audit"]
        and backend_xfeat.get("terminal_failure_receipt")
        == local_xfeat["terminal_failure_receipt"]
        and backend_xfeat.get("accepted_receipt_present") is False
        and backend_xfeat.get("backend_launched_count") == 0
        and backend_xfeat.get("learning_contribution_claim_permitted") is False,
        "BACKEND_V3_XFEAT_EXCLUSION_BINDING",
    )
    lock, lock_id = module.verify_lock(BACKEND_V3_LOCK, bindings)
    require(lock.get("schema_version") == module.LOCK_SCHEMA, "BACKEND_V3_LOCK_SCHEMA")
    require(lock.get("status") == module.LOCK_STATUS, "BACKEND_V3_LOCK_STATUS")
    require(lock.get("item_order") == list(V3_ITEM_ORDER), "BACKEND_V3_LOCK_ORDER")
    require(lock.get("frontend_authority") == bindings, "BACKEND_V3_FRONTEND_AUTHORITY")
    live_prior = module.prior_r01_authority(bindings)
    require(
        live_prior.get("disposition") == R01_DISPOSITION
        and live_prior.get("counts_as_valid_repeat") is False
        and live_prior.get("rerun_permitted") is False,
        "BACKEND_V3_PRIOR_R01_BOUNDARY",
    )
    prior = prior_r01_binding()
    require(
        live_prior.get("v2_execution_lock") == prior["v2_execution_lock"]
        and live_prior.get("v2_terminal_receipt") == prior["receipt"],
        "BACKEND_V3_PRIOR_R01_IDENTITY",
    )
    locked_items = lock.get("items")
    require(isinstance(locked_items, dict) and list(locked_items) == list(V3_ITEM_ORDER),
            "BACKEND_V3_LOCK_ITEMS")
    rows = [_r01_population_row(prior)]
    receipts: dict[str, Any] = {"KLT_R01": prior["receipt"]}
    for item_id in V3_ITEM_ORDER:
        receipt_path = BACKEND_V3_ROOT / item_id / BACKEND_V3_RECEIPT_NAME
        receipt, receipt_id = stable_json(receipt_path)
        deep = module.prior_receipt(lock_id, locked_items[item_id])
        require(deep == receipt, f"BACKEND_V3_DEEP_TERMINAL:{item_id}")
        row = _V2_VALIDATE_BACKEND_TERMINAL(
            module, item_id, receipt, lock_id, locked_items[item_id]
        )
        row["backend_infrastructure_failure_retained_as_na"] = False
        row["receipt"] = receipt_id
        rows.append(row)
        receipts[item_id] = receipt_id
    valid = sum(
        bool(row["accepted_for_joint_mask"])
        for row in rows if row["item_id"] in V3_ITEM_ORDER
    )
    require(not rows[0]["accepted_for_joint_mask"], "R01_MUST_NEVER_ENTER_JOINT_MASK")
    return {
        "execution_lock": lock_id,
        "execution_contract_sha256": lock.get("contract_sha256"),
        "terminal_receipts": receipts,
        "planned_repeats": rows,
        "planned_count": 5,
        "v3_executable_count": 4,
        "v3_terminal_count": 4,
        "maximum_valid_count": 4,
        "valid_count": valid,
        "failed_count": 5 - valid,
        "infrastructure_na_count": 1,
        "prior_r01": prior,
        "frontend_bindings": bindings,
    }


def collect_static_identities() -> dict[str, Any]:
    frozen = _check_frozen_v2_identities()
    values = {
        "runner": identity(RUNNER),
        "protocol": identity(PROTOCOL),
        "process_free_tests": identity(TESTS),
        "frozen_analysis_v2_runner": frozen["runner"],
        "frozen_analysis_v2_protocol": frozen["protocol"],
        "frozen_analysis_v2_process_free_tests": frozen["tests"],
        "frozen_analysis_v2_design_freeze": frozen["design_freeze"],
        "common_security_and_numeric_library": identity(BASE.COMMON_LIBRARY),
        "primary_evaluator": identity(BASE.EVALUATOR),
        "trajectory_eval_core": identity(BASE.EVALUATOR_CORE),
        "epoch_nanosecond_adapter": identity(BASE.EPOCH_ADAPTER),
        "backend_v3_protocol": identity(BACKEND_V3_PROTOCOL),
        "backend_v3_runner": identity(BACKEND_V3_RUNNER),
        "backend_v3_guard": identity(BACKEND_V3_GUARD),
        "backend_v3_process_free_tests": identity(BACKEND_V3_TESTS),
        "v2_r01_terminal_receipt": identity(V2_R01_RECEIPT),
        "v2_execution_lock": identity(V2_BACKEND_LOCK),
    }
    require(
        (values["v2_r01_terminal_receipt"]["size_bytes"],
         values["v2_r01_terminal_receipt"]["sha256"]) == R01_RECEIPT_EXPECTED,
        "STATIC_R01_RECEIPT_IDENTITY",
    )
    require(
        (values["v2_execution_lock"]["size_bytes"],
         values["v2_execution_lock"]["sha256"]) == V2_LOCK_EXPECTED,
        "STATIC_V2_BACKEND_LOCK_IDENTITY",
    )
    return values


def design_contract_snapshot() -> dict[str, Any]:
    value = json.loads(json.dumps(_V2_DESIGN_CONTRACT_SNAPSHOT()))
    value["campaign"] = "A08_HFNET_VS_KLT_ONLY_COMMON_SUPPORT_ADDITIVE_V3"
    value["population_and_failure_rules"].update({
        "backend_item_order": list(FULL_ITEM_ORDER),
        "v3_backend_item_order": list(V3_ITEM_ORDER),
        "klt_planned_count": 5,
        "maximum_valid_klt_count": 4,
        "klt_valid_count_from_terminal_dispositions": True,
        "klt_valid_repeat_rule": "ONLY_PASS_BACKEND_REPLAY_ACCEPTED_AMONG_R02_R05",
        "klt_summary": "coordinatewise_median_over_all_valid_R02_R05_repeats",
        "r01_disposition": R01_DISPOSITION,
        "r01_counts_as_valid": False,
        "r01_rerun_or_replacement_permitted": False,
        "r01_infrastructure_na_not_scientific_failure": True,
        "xfeat_disposition": XFEAT_DISPOSITION,
        "best_repeat_selection_permitted": False,
    })
    value["execution_rules"].update({
        "design_freeze_after_r01_failure_before_v3_backend_lock_or_results": True,
        "design_freeze_before_v3_backend_terminal_results": True,
        "dynamic_lock_after_four_v3_terminal_receipts_before_accuracy": True,
        "design_freeze_before_backend_terminal_results": False,
        "dynamic_lock_after_five_terminal_receipts_before_accuracy": False,
    })
    return value


def backend_v3_terminal_presence() -> dict[str, str]:
    paths = {"backend_v3_execution_lock": BACKEND_V3_LOCK, **{
        item: BACKEND_V3_ROOT / item / BACKEND_V3_RECEIPT_NAME
        for item in V3_ITEM_ORDER
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


def backend_v3_campaign_prelaunch_presence() -> dict[str, str]:
    paths: dict[str, Path] = {
        "backend_v3_root": BACKEND_V3_ROOT,
        "backend_v3_runtime_root": BACKEND_V3_RUNTIME_ROOT,
    }
    for item in V3_ITEM_ORDER:
        repeat = int(item[-2:])
        tag = f"a08_recoveredjuly_hist0000_4660_backend_klt_only_r{repeat:02d}_v3"
        paths[f"workspace:{item}"] = (
            BACKEND_OVERLAY_RUN_ROOT / f"external_klt_every2_{tag}"
        )
    return {
        label: ("PRESENT" if path.exists() or path.is_symlink() else "ABSENT")
        for label, path in paths.items()
    }


def v2_remaining_items_presence() -> dict[str, str]:
    """Expose every old v2 R02--R05 touch point as a freeze-time gate."""
    paths: dict[str, Path] = {}
    for item in V3_ITEM_ORDER:
        repeat = int(item[-2:])
        tag = f"a08_recoveredjuly_hist0000_4660_backend_klt_only_r{repeat:02d}_v2"
        paths.update({
            f"output:{item}": V2_BACKEND_ROOT / item,
            f"runtime:{item}": V2_BACKEND_RUNTIME_ROOT / item,
            f"workspace:{item}": (
                BACKEND_OVERLAY_RUN_ROOT / f"external_klt_every2_{tag}"
            ),
        })
    return {
        label: ("PRESENT" if path.exists() or path.is_symlink() else "ABSENT")
        for label, path in paths.items()
    }


def _require_analysis_diversion_untouched() -> None:
    for path, code in (
        (V2_ANALYSIS_LOCK, "FROZEN_V2_ANALYSIS_LOCK_MUST_REMAIN_ABSENT"),
        (V2_ANALYSIS_OUTPUT, "FROZEN_V2_ANALYSIS_OUTPUT_MUST_REMAIN_ABSENT"),
        (V2_ANALYSIS_CLAIM, "FROZEN_V2_ANALYSIS_CLAIM_MUST_REMAIN_ABSENT"),
    ):
        BASE.regular_absence(path, code)
    for path, code in (
        (BASE.LEGACY_BACKEND_LOCK, "LEGACY_BACKEND_V1_LOCK_MUST_REMAIN_ABSENT"),
        (BASE.LEGACY_ANALYSIS_LOCK, "LEGACY_ANALYSIS_V1_LOCK_MUST_REMAIN_ABSENT"),
        (BASE.LEGACY_ANALYSIS_OUTPUT, "LEGACY_ANALYSIS_V1_OUTPUT_MUST_REMAIN_ABSENT"),
    ):
        BASE.regular_absence(path, code)


def build_design_freeze_payload(created_at_utc: str) -> dict[str, Any]:
    presence = backend_v3_terminal_presence()
    require(all(value == "MISSING" for value in presence.values()),
            "DESIGN_FREEZE_MUST_PRECEDE_V3_BACKEND_LOCK_AND_RESULTS")
    prelaunch = backend_v3_campaign_prelaunch_presence()
    require(all(value == "ABSENT" for value in prelaunch.values()),
            "DESIGN_FREEZE_MUST_PRECEDE_ANY_V3_BACKEND_TOUCH")
    old_remaining = v2_remaining_items_presence()
    require(all(value == "ABSENT" for value in old_remaining.values()),
            "OLD_V2_R02_R05_MUST_REMAIN_UNTOUCHED")
    BASE.regular_absence(DEFAULT_LOCK, "DESIGN_FREEZE_MUST_PRECEDE_V3_ANALYSIS_LOCK")
    require(analysis_output_state() == "ABSENT", "DESIGN_FREEZE_MUST_PRECEDE_ANALYSIS_OUTPUT")
    _require_analysis_diversion_untouched()
    prior = prior_r01_binding()
    payload = {
        "schema_version": DESIGN_FREEZE_SCHEMA,
        "status": DESIGN_FREEZE_STATUS,
        "created_at_utc": created_at_utc,
        "static_identities": collect_static_identities(),
        "sealed_support": common.collect_support_binding(),
        "klt_frontend": collect_klt_frontend_binding(),
        "excluded_xfeat": collect_xfeat_exclusion(),
        "evo_authority": common.collect_evo_authority(),
        "prior_r01": prior,
        "design_contract": design_contract_snapshot(),
        "backend_v3_terminal_presence_at_freeze": presence,
        "backend_v3_campaign_prelaunch_presence_at_freeze": prelaunch,
        "v2_remaining_r02_r05_presence_at_freeze": old_remaining,
        "claim_boundary": {
            "r01_terminal_infrastructure_failure_opened_and_frozen_as_na": True,
            "r01_accuracy_opened": False,
            "backend_v3_execution_lock_built": False,
            "v3_backend_items_started": 0,
            "ape_or_rpe_computed": False,
            "final_dynamic_analysis_lock_built": False,
            "ros_or_vins_started_for_v3": False,
        },
    }
    payload["freeze_sha256"] = compact_sha256(payload)
    return payload


def publish_design_freeze(authorization_token: str) -> dict[str, Any]:
    require(authorization_token == FREEZE_TOKEN, "DESIGN_FREEZE_AUTHORIZATION_TOKEN")
    BASE.regular_absence(DESIGN_FREEZE, "DESIGN_FREEZE_ALREADY_EXISTS")
    payload = build_design_freeze_payload(
        datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    atomic_publish(DESIGN_FREEZE, payload)
    return {
        "status": "ADDITIVE_V3_STATIC_DESIGN_FREEZE_PUBLISHED_NO_ACCURACY_COMPUTED",
        "design_freeze": identity(DESIGN_FREEZE),
        "accuracy_computed": False,
    }


def collect_design_freeze_binding() -> dict[str, Any]:
    value, freeze_id = stable_json(DESIGN_FREEZE)
    require(value.get("schema_version") == DESIGN_FREEZE_SCHEMA, "DESIGN_FREEZE_SCHEMA")
    require(value.get("status") == DESIGN_FREEZE_STATUS, "DESIGN_FREEZE_STATUS")
    digest = value.get("freeze_sha256")
    unsigned = dict(value)
    unsigned.pop("freeze_sha256", None)
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
    require(value.get("design_contract") == design_contract_snapshot(),
            "DESIGN_FREEZE_CONTRACT")
    expected_presence = {"backend_v3_execution_lock": "MISSING", **{
        item: "MISSING" for item in V3_ITEM_ORDER
    }}
    expected_prelaunch = {
        "backend_v3_root": "ABSENT", "backend_v3_runtime_root": "ABSENT",
        **{f"workspace:{item}": "ABSENT" for item in V3_ITEM_ORDER},
    }
    require(value.get("backend_v3_terminal_presence_at_freeze") == expected_presence,
            "DESIGN_FREEZE_PRIOR_V3_TERMINAL_ABSENCE")
    require(value.get("backend_v3_campaign_prelaunch_presence_at_freeze") == expected_prelaunch,
            "DESIGN_FREEZE_PRIOR_V3_TOUCH_ABSENCE")
    expected_old_remaining = {
        f"{kind}:{item}": "ABSENT"
        for item in V3_ITEM_ORDER
        for kind in ("output", "runtime", "workspace")
    }
    require(value.get("v2_remaining_r02_r05_presence_at_freeze") == expected_old_remaining,
            "DESIGN_FREEZE_OLD_V2_R02_R05_UNTOUCHED")
    boundary = value.get("claim_boundary")
    require(
        isinstance(boundary, dict)
        and boundary.get("backend_v3_execution_lock_built") is False
        and boundary.get("v3_backend_items_started") == 0
        and boundary.get("ape_or_rpe_computed") is False
        and boundary.get("ros_or_vins_started_for_v3") is False,
        "DESIGN_FREEZE_CLAIM_BOUNDARY",
    )
    return {
        "identity": freeze_id,
        "created_at_utc": value.get("created_at_utc"),
        "freeze_sha256": digest,
    }


def design_freeze_audit_readonly() -> dict[str, Any]:
    try:
        return {
            "status": "PASS_DESIGN_FROZEN_AFTER_R01_BEFORE_R02_R05",
            "read_only": True,
            "design_freeze": collect_design_freeze_binding(),
            "accuracy_computed": False,
        }
    except (AnalysisProtocolError, OSError, ValueError) as error:
        presence = backend_v3_terminal_presence()
        late = any(value != "MISSING" for value in presence.values())
        return {
            "status": (
                "BLOCKED_LATE_OR_INVALID_V3_DESIGN_FREEZE"
                if late else "BLOCKED_DESIGN_FREEZE"
            ),
            "read_only": True,
            "error": f"{type(error).__name__}:{error}",
            "backend_v3_terminal_presence": presence,
            "accuracy_computed": False,
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
        "schema_version": LOCK_SCHEMA,
        "status": LOCK_STATUS,
        "campaign": "A08_HFNET_VS_KLT_ONLY_COMMON_SUPPORT_ADDITIVE_V3",
        "authority": dict(authority),
        "grid": exact_grid_evidence(),
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
    _configure_base()
    return BASE.analysis_output_state()


def original_ten_slot_rows(
    backend: Mapping[str, Any], arms: Optional[Mapping[str, Any]], ranking: bool,
) -> list[dict[str, Any]]:
    rows = _V2_ORIGINAL_TEN_SLOT_ROWS(backend, arms, ranking)
    for row in rows:
        if row["item_id"] == "KLT_R01":
            row.update({
                "backend_launched": True,
                "backend_replay_started": False,
                "scientific_failure_retained_as_na": False,
                "backend_infrastructure_failure_retained_as_na": True,
            })
        elif row["item_id"].startswith("KLT_"):
            row["backend_infrastructure_failure_retained_as_na"] = False
    return rows


def _decorate_formal(formal: dict[str, Any]) -> dict[str, Any]:
    for row in formal.get("planned_klt_repeats", []):
        if row.get("item_id") == "KLT_R01":
            row.update({
                "scientific_failure_retained_as_na": False,
                "backend_infrastructure_failure_retained_as_na": True,
                "backend_replay_started": False,
            })
        else:
            row["backend_infrastructure_failure_retained_as_na"] = False
    formal["r01_disposition"] = R01_DISPOSITION
    formal["maximum_valid_klt_count"] = 4
    formal["valid_klt_repeat_rule"] = "ONLY_PASS_BACKEND_REPLAY_ACCEPTED_AMONG_R02_R05"
    return formal


def build_formal_summary(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _decorate_formal(_V2_BUILD_FORMAL_SUMMARY(*args, **kwargs))


def build_error_formal_summary(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _decorate_formal(_V2_BUILD_ERROR_FORMAL_SUMMARY(*args, **kwargs))


def validate_formal_population_binding(
    formal: Mapping[str, Any], lock: Mapping[str, Any]
) -> None:
    _V2_VALIDATE_FORMAL_POPULATION(formal, lock)
    planned = {row["item_id"]: row for row in formal["planned_klt_repeats"]}
    slots = {row["item_id"]: row for row in formal["original_ten_slot_dispositions"]}
    for row in (planned["KLT_R01"], slots["KLT_R01"]):
        require(
            row.get("terminal_disposition") == R01_DISPOSITION
            and row.get("accepted_for_single_joint_mask") is False
            and row.get("scientific_failure_retained_as_na") is False
            and row.get("backend_infrastructure_failure_retained_as_na") is True
            and row.get("backend_replay_started") is False,
            "FORMAL_R01_INFRASTRUCTURE_NA_BOUNDARY",
        )


def repeat_table_csv_text(formal: Mapping[str, Any]) -> str:
    fields = [
        "item_id", "arm", "repeat_index", "terminal_disposition",
        "backend_launched", "backend_replay_started",
        "accepted_for_single_joint_mask", "scientific_failure_retained_as_na",
        "backend_infrastructure_failure_retained_as_na",
        "frontend_structural_failure_retained_as_na", "replacement_permitted",
        *PRIMARY_METRICS,
    ]
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=fields)
    writer.writeheader()
    for row in formal["original_ten_slot_dispositions"]:
        writer.writerow({
            **{key: row[key] for key in fields if key in row},
            **row["formal_metrics"],
        })
    return handle.getvalue()


def make_terminal_receipt(*args: Any, **kwargs: Any) -> dict[str, Any]:
    value = _V2_MAKE_TERMINAL_RECEIPT(*args, **kwargs)
    value["r01_disposition"] = R01_DISPOSITION
    value["maximum_valid_klt_count"] = 4
    value["valid_klt_repeat_rule"] = "ONLY_PASS_BACKEND_REPLAY_ACCEPTED_AMONG_R02_R05"
    return value


def _configure_base() -> None:
    assignments = {
        "BACKEND_ROOT": BACKEND_V3_ROOT,
        "BACKEND_LOCK": BACKEND_V3_LOCK,
        "BACKEND_RUNNER": BACKEND_V3_RUNNER,
        "BACKEND_PROTOCOL": BACKEND_V3_PROTOCOL,
        "BACKEND_RECEIPT_NAME": BACKEND_V3_RECEIPT_NAME,
        "BACKEND_RUNTIME_ROOT": BACKEND_V3_RUNTIME_ROOT,
        "BACKEND_OVERLAY_RUN_ROOT": BACKEND_OVERLAY_RUN_ROOT,
        "OUTPUT_ROOT": OUTPUT_ROOT,
        "CLAIM_PATH": CLAIM_PATH,
        "STAGING_ROOT": STAGING_ROOT,
        "EVO_WORK_ROOT": EVO_WORK_ROOT,
        "FAILURE_STAGING_ROOT": FAILURE_STAGING_ROOT,
        "PROTOCOL": PROTOCOL,
        "RUNNER": RUNNER,
        "TESTS": TESTS,
        "DESIGN_FREEZE": DESIGN_FREEZE,
        "DEFAULT_LOCK": DEFAULT_LOCK,
        "ITEM_ORDER": FULL_ITEM_ORDER,
        "ORIGINAL_TEN_SLOT_ORDER": ORIGINAL_TEN_SLOT_ORDER,
        "XFEAT_EXCLUSION_STATUS": XFEAT_DISPOSITION,
        "DESIGN_FREEZE_SCHEMA": DESIGN_FREEZE_SCHEMA,
        "LOCK_SCHEMA": LOCK_SCHEMA,
        "CLAIM_SCHEMA": CLAIM_SCHEMA,
        "RECEIPT_SCHEMA": RECEIPT_SCHEMA,
        "FORMAL_SCHEMA": FORMAL_SCHEMA,
        "LOCK_STATUS": LOCK_STATUS,
        "FREEZE_TOKEN": FREEZE_TOKEN,
        "BUILD_LOCK_TOKEN": BUILD_LOCK_TOKEN,
        "RUN_TOKEN": RUN_TOKEN,
        "GRID_NAME": GRID_NAME,
        "RAW_SUMMARY_NAME": RAW_SUMMARY_NAME,
        "GRID_AUDIT_NAME": GRID_AUDIT_NAME,
        "RAW_METRICS_NAME": RAW_METRICS_NAME,
        "RAW_DIAGNOSTIC_MANIFEST_NAME": RAW_DIAGNOSTIC_MANIFEST_NAME,
        "REPEAT_TABLE_NAME": REPEAT_TABLE_NAME,
        "FORMAL_SUMMARY_NAME": FORMAL_SUMMARY_NAME,
        "EVO_SUMMARY_NAME": EVO_SUMMARY_NAME,
        "RECEIPT_NAME": RECEIPT_NAME,
        "PARTIAL_EVIDENCE_NAME": PARTIAL_EVIDENCE_NAME,
        "exact_grid_evidence": exact_grid_evidence,
        "collect_klt_frontend_binding": collect_klt_frontend_binding,
        "collect_xfeat_exclusion": collect_xfeat_exclusion,
        "load_backend_authority_module": load_backend_v3_authority_module,
        "collect_backend_binding": collect_backend_binding,
        "collect_static_identities": collect_static_identities,
        "design_contract_snapshot": design_contract_snapshot,
        "backend_terminal_presence": backend_v3_terminal_presence,
        "backend_campaign_prelaunch_presence": backend_v3_campaign_prelaunch_presence,
        "build_design_freeze_payload": build_design_freeze_payload,
        "publish_design_freeze": publish_design_freeze,
        "collect_design_freeze_binding": collect_design_freeze_binding,
        "design_freeze_audit_readonly": design_freeze_audit_readonly,
        "collect_authority": collect_authority,
        "contract_core": contract_core,
        "build_lock_payload": build_lock_payload,
        "verify_lock": verify_lock,
        "original_ten_slot_rows": original_ten_slot_rows,
        "build_formal_summary": build_formal_summary,
        "build_error_formal_summary": build_error_formal_summary,
        "validate_formal_population_binding": validate_formal_population_binding,
        "repeat_table_csv_text": repeat_table_csv_text,
        "make_terminal_receipt": make_terminal_receipt,
    }
    for name, value in assignments.items():
        setattr(BASE, name, value)


def require_canonical_analysis_lock_path(lock_path: Path) -> None:
    require(lock_path.absolute() == DEFAULT_LOCK.absolute(),
            "ANALYSIS_LOCK_PATH_MUST_BE_CANONICAL")


def preflight_readonly(lock_path: Path = DEFAULT_LOCK) -> dict[str, Any]:
    try:
        require_canonical_analysis_lock_path(lock_path)
    except AnalysisProtocolError as error:
        return {"status": "BLOCKED_PREFLIGHT", "read_only": True,
                "error": f"{type(error).__name__}:{error}", "accuracy_computed": False}
    freeze = design_freeze_audit_readonly()
    if freeze["status"] != "PASS_DESIGN_FROZEN_AFTER_R01_BEFORE_R02_R05":
        return {"status": "BLOCKED_DESIGN_FREEZE", "read_only": True,
                "design_freeze_audit": freeze, "accuracy_computed": False}
    presence = backend_v3_terminal_presence()
    unavailable = [key for key, value in presence.items() if value != "PRESENT_REGULAR"]
    if unavailable:
        return {
            "status": "WAITING_FOR_BACKEND_V3_LOCK_AND_FOUR_TERMINAL_RECEIPTS",
            "read_only": True, "terminal_presence": presence,
            "unavailable": unavailable,
            "analysis_lock_present": lock_path.exists() or lock_path.is_symlink(),
            "r01_disposition": R01_DISPOSITION,
            "excluded_xfeat_disposition": XFEAT_DISPOSITION,
            "accuracy_computed": False,
        }
    try:
        _configure_base()
        if not lock_path.exists() and not lock_path.is_symlink():
            require(analysis_output_state() == "ABSENT", "ANALYSIS_OUTPUT_PREEXISTS")
            authority = collect_authority()
            return {
                "status": "READY_TO_BUILD_ANALYSIS_V3_LOCK_NO_ACCURACY_COMPUTED",
                "read_only": True, "terminal_presence": presence,
                "klt_planned_count": 5,
                "klt_valid_count": authority["backend"]["valid_count"],
                "maximum_valid_klt_count": 4,
                "candidate_contract_sha256": compact_sha256(contract_core(authority)),
                "accuracy_computed": False,
            }
        lock, lock_id = verify_lock(lock_path)
        state = analysis_output_state()
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
    BASE.regular_absence(lock_path, "ANALYSIS_LOCK_ALREADY_EXISTS")
    require(analysis_output_state() == "ABSENT", "ANALYSIS_OUTPUT_PREEXISTS")
    collect_design_freeze_binding()
    presence = backend_v3_terminal_presence()
    require(all(value == "PRESENT_REGULAR" for value in presence.values()),
            "FOUR_V3_TERMINAL_RECEIPTS_REQUIRED")
    authority = collect_authority()
    require(authority["backend"]["planned_count"] == 5, "PLANNED_COUNT")
    require(authority["backend"]["maximum_valid_count"] == 4, "MAX_VALID_COUNT")
    payload = build_lock_payload(
        authority, datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    atomic_publish(lock_path, payload)
    return {
        "status": "FINAL_ANALYSIS_V3_LOCK_PUBLISHED_NO_ACCURACY_COMPUTED",
        "lock": identity(lock_path),
        "klt_planned_count": 5,
        "klt_valid_count": authority["backend"]["valid_count"],
        "maximum_valid_klt_count": 4,
        "r01_disposition": R01_DISPOSITION,
        "excluded_xfeat_disposition": XFEAT_DISPOSITION,
        "accuracy_computed": False,
    }


def execute_analysis(
    lock_path: Path, authorization_token: str
) -> tuple[int, dict[str, Any]]:
    _configure_base()
    return BASE.execute_analysis(lock_path, authorization_token)


def audit_readonly(lock_path: Path = DEFAULT_LOCK) -> dict[str, Any]:
    _configure_base()
    result = BASE.audit_readonly(lock_path)
    result["r01_disposition"] = R01_DISPOSITION
    result["maximum_valid_klt_count"] = 4
    return result


# Public aliases to the identity-pinned v2 numerical and transaction engine.
accepted_arm_paths = BASE.accepted_arm_paths
exact_grid_seconds = BASE.exact_grid_seconds
evaluate_joint_inputs = BASE.evaluate_joint_inputs
support_gate = BASE.support_gate
median_metrics = BASE.median_metrics
null_metrics = BASE.null_metrics
formal_metrics_are_all_na = BASE.formal_metrics_are_all_na
force_all_formal_metrics_na_for_integrity = BASE.force_all_formal_metrics_na_for_integrity
audit_terminal_semantics = BASE.audit_terminal_semantics


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight")
    commands.add_parser("audit")
    freeze = commands.add_parser("freeze-design")
    freeze.add_argument("--authorization-token", required=True)
    build = commands.add_parser("build-lock")
    build.add_argument("--authorization-token", required=True)
    run = commands.add_parser("run")
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
        result = audit_readonly(lock_path)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0 if result["status"].startswith(("PASS_", "WAITING_")) else 2
    try:
        if args.command == "freeze-design":
            result = publish_design_freeze(args.authorization_token)
            code = 0
        elif args.command == "build-lock":
            result = build_lock(lock_path, args.authorization_token)
            code = 0
        else:
            code, result = execute_analysis(lock_path, args.authorization_token)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return code
    except (AnalysisProtocolError, OSError, ValueError, RuntimeError) as error:
        print(f"A08_HFNET_KLT_V3_ERROR:{type(error).__name__}:{error}", file=sys.stderr)
        return 2


_configure_base()


if __name__ == "__main__":
    raise SystemExit(main())
