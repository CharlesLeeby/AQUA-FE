#!/usr/bin/env python3
"""A08 HFNet-vs-KLT-only one-shot common-support analysis v2.

Importing this module is inert.  ``freeze-design``, ``build-lock`` and ``run``
are distinct, no-replace transitions.  The first transition is permitted only
before any KLT-only backend terminal result exists; the second never computes
accuracy; the third consumes one analysis allowance and has zero retries.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import sys
from typing import Any, Mapping, Optional, Sequence

import numpy as np


WORKSPACE = Path("/home/ma/AQUA-FE_WS")
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from scripts import run_a08_recovered_july_joint_common_support_v1 as common


AnalysisProtocolError = common.AnalysisProtocolError
require = common.require
canonical_bytes = common.canonical_bytes
compact_sha256 = common.compact_sha256
identity = common.identity
stable_json = common.stable_json
validate_identity_claim = common.validate_identity_claim
atomic_publish = common.atomic_publish
commit_directory_noreplace = common.commit_directory_noreplace

SUPPORT_INPUT_ROOT = common.SUPPORT_INPUT_ROOT
SUPPORT_RECEIPT = common.SUPPORT_RECEIPT
REFERENCE_TUM = common.REFERENCE_TUM
HFNET_TRAJECTORY = common.HFNET_TRAJECTORY
SHARED_EXTRINSIC = common.SHARED_EXTRINSIC

CONTROL_EXPERIMENT = common.CONTROL_EXPERIMENT
BACKEND_ROOT = CONTROL_EXPERIMENT / "backend_klt_only_replays_v2"
BACKEND_LOCK = (
    WORKSPACE
    / "papers/a08_recovered_july_history_matched_backend_klt_only_replays_v2_execution_lock.json"
)
BACKEND_RUNNER = (
    WORKSPACE
    / "scripts/run_a08_recovered_july_history_matched_backend_klt_only_replays_v2.py"
)
BACKEND_PROTOCOL = (
    WORKSPACE
    / "papers/a08_recovered_july_history_matched_backend_klt_only_replays_v2_protocol.md"
)
BACKEND_RECEIPT_NAME = "formal_run_receipt_v2.json"
BACKEND_RUNTIME_ROOT = CONTROL_EXPERIMENT / "runtime/backend_klt_only_replays_v2"
BACKEND_OVERLAY_RUN_ROOT = (
    CONTROL_EXPERIMENT / "recovered_july_core_overlay_v1/logs/aqualoc_archaeo_vins"
)

FRONTEND_ROOT = CONTROL_EXPERIMENT / "frontends_v1"
KLT_FRONTEND_RECEIPT = FRONTEND_ROOT / "klt_attempt002_export_receipt_v1.json"
XFEAT_FAILURE_RECEIPT = FRONTEND_ROOT / "xfeat_attempt002_export_failure_v1.json"
XFEAT_ACCEPTED_RECEIPT = FRONTEND_ROOT / "xfeat_attempt002_export_receipt_v1.json"
XFEAT_FORENSIC_AUDIT = (
    WORKSPACE / "papers/a08_xfeat_attempt002_terminal_forensic_audit_v1.md"
)

OUTPUT_ROOT = CONTROL_EXPERIMENT / "hfnet_vs_klt_only_common_support_v2"
CLAIM_PATH = CONTROL_EXPERIMENT / "hfnet_vs_klt_only_common_support_start_claim_v2.json"
STAGING_ROOT = CONTROL_EXPERIMENT / ".hfnet_vs_klt_only_common_support_v2.staging"
EVO_WORK_ROOT = CONTROL_EXPERIMENT / ".hfnet_vs_klt_only_common_support_v2.evo_work"
FAILURE_STAGING_ROOT = (
    CONTROL_EXPERIMENT / ".hfnet_vs_klt_only_common_support_v2.failure_staging"
)

PROTOCOL = WORKSPACE / "papers/a08_hfnet_vs_klt_only_common_support_v2_protocol.md"
RUNNER = WORKSPACE / "scripts/run_a08_hfnet_vs_klt_only_common_support_v2.py"
TESTS = WORKSPACE / "scripts/tests/test_run_a08_hfnet_vs_klt_only_common_support_v2.py"
COMMON_LIBRARY = common.RUNNER
EVALUATOR = common.EVALUATOR
EVALUATOR_CORE = common.EVALUATOR_CORE
EPOCH_ADAPTER = common.EPOCH_ADAPTER
DESIGN_FREEZE = WORKSPACE / "papers/a08_hfnet_vs_klt_only_common_support_v2_design_freeze.json"
DEFAULT_LOCK = WORKSPACE / "papers/a08_hfnet_vs_klt_only_common_support_v2_execution_lock.json"

LEGACY_BACKEND_LOCK = common.BACKEND_LOCK
LEGACY_ANALYSIS_LOCK = common.DEFAULT_LOCK
LEGACY_ANALYSIS_OUTPUT = common.OUTPUT_ROOT

ITEM_ORDER = tuple(f"KLT_R{repeat:02d}" for repeat in range(1, 6))
ORIGINAL_TEN_SLOT_ORDER = tuple(
    item
    for repeat in range(1, 6)
    for item in (f"KLT_R{repeat:02d}", f"XFEAT_R{repeat:02d}")
)
START_NS = common.START_NS
END_NS = common.END_NS
GRID_STEP_NS = common.GRID_STEP_NS
GRID_COUNT = common.GRID_COUNT
GRID_NS = common.GRID_NS
PRIMARY_METRICS = common.PRIMARY_METRICS

KLT_FRONTEND_EXPECTED = (
    363_673,
    "69a857307f088e58ea18abbb6c25cd2069b7b15783fc2d17548e1fb001c4d2b8",
)
XFEAT_FAILURE_EXPECTED = (
    4_017,
    "15eaad3e5b02f54b4f141db416e9b1db868bea15fcb66fe8bee11318765df22c",
)
XFEAT_FORENSIC_EXPECTED = (
    3_695,
    "4087a9cded9617e20c4f8e383bc4280c1a1c1cafe5d9fd49fbaa9fb2005bbf5a",
)
XFEAT_EXCLUSION_STATUS = "NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED"

KLT_FRONTEND_SCHEMA = "aqua-fe-a08-recovered-july-natural-history-frontend-receipt-v1"
XFEAT_FAILURE_SCHEMA = "aqua-fe-a08-recovered-july-frontend-failure-v1"
DESIGN_FREEZE_SCHEMA = "aqua-fe-a08-hfnet-vs-klt-only-common-support-design-freeze-v2"
LOCK_SCHEMA = "aqua-fe-a08-hfnet-vs-klt-only-common-support-lock-v2"
CLAIM_SCHEMA = "aqua-fe-a08-hfnet-vs-klt-only-common-support-claim-v2"
RECEIPT_SCHEMA = "aqua-fe-a08-hfnet-vs-klt-only-common-support-receipt-v2"
FORMAL_SCHEMA = "aqua-fe-a08-formal-hfnet-vs-klt-only-common-support-summary-v2"
LOCK_STATUS = "FROZEN_AFTER_FIVE_KLT_TERMINAL_REPLAYS_BEFORE_ACCURACY_VISIBLE"

FREEZE_TOKEN = "A08_FREEZE_HFNET_VS_KLT_ONLY_COMMON_SUPPORT_V2_BEFORE_BACKEND_RESULTS"
BUILD_LOCK_TOKEN = "A08_BUILD_HFNET_VS_KLT_ONLY_COMMON_SUPPORT_V2_LOCK_BEFORE_ACCURACY"
RUN_TOKEN = "A08_RUN_HFNET_VS_KLT_ONLY_COMMON_SUPPORT_V2_EXACTLY_ONCE_NO_RETRY"

GRID_NAME = "exact_integer_ns_grid_v2.json"
RAW_SUMMARY_NAME = "common_support_summary.json"
GRID_AUDIT_NAME = "common_grid_audit.csv"
RAW_METRICS_NAME = "common_support_metrics.csv"
RAW_DIAGNOSTIC_MANIFEST_NAME = "raw_numeric_diagnostics_boundary_v2.json"
REPEAT_TABLE_NAME = "original_ten_slot_dispositions_v2.csv"
FORMAL_SUMMARY_NAME = "formal_hfnet_vs_klt_only_summary_v2.json"
EVO_SUMMARY_NAME = "evo_crosscheck.json"
RECEIPT_NAME = "formal_analysis_receipt_v2.json"
PARTIAL_EVIDENCE_NAME = "uncommitted_partial_evidence_v2.json"


def exact_grid_evidence() -> dict[str, Any]:
    value = common.exact_grid_evidence()
    value["schema_version"] = "aqua-fe-a08-exact-integer-ns-grid-v2"
    return value


def regular_absence(path: Path, code: str) -> None:
    require(not path.exists() and not path.is_symlink(), code)


def collect_klt_frontend_binding() -> dict[str, Any]:
    receipt, receipt_id = stable_json(KLT_FRONTEND_RECEIPT)
    require(
        (receipt_id["size_bytes"], receipt_id["sha256"]) == KLT_FRONTEND_EXPECTED,
        "KLT_FRONTEND_FROZEN_IDENTITY",
    )
    require(receipt.get("schema_version") == KLT_FRONTEND_SCHEMA,
            "KLT_FRONTEND_SCHEMA")
    require(receipt.get("status") == "PASS_FRONTEND_EXPORT_ACCEPTED",
            "KLT_FRONTEND_STATUS")
    require(receipt.get("stage") == "klt", "KLT_FRONTEND_STAGE")
    return {"receipt": receipt_id, "status": receipt["status"], "stage": "klt"}


def collect_xfeat_exclusion() -> dict[str, Any]:
    forensic_id = identity(XFEAT_FORENSIC_AUDIT)
    require(
        (forensic_id["size_bytes"], forensic_id["sha256"])
        == XFEAT_FORENSIC_EXPECTED,
        "XFEAT_FORENSIC_FROZEN_IDENTITY",
    )
    failure, failure_id = stable_json(XFEAT_FAILURE_RECEIPT)
    require(
        (failure_id["size_bytes"], failure_id["sha256"])
        == XFEAT_FAILURE_EXPECTED,
        "XFEAT_FAILURE_FROZEN_IDENTITY",
    )
    require(failure.get("schema_version") == XFEAT_FAILURE_SCHEMA,
            "XFEAT_FAILURE_SCHEMA")
    require(
        failure.get("status") == "FAILED_NO_AUTOMATIC_RETRY"
        and failure.get("qualified_status") == "FAILED_ATTEMPT002_NO_FURTHER_ATTEMPT"
        and failure.get("stage") == "xfeat"
        and failure.get("error") == "FEATURE_POINT_COUNT_RANGE"
        and failure.get("popen_started") is True
        and failure.get("vins_or_accuracy_executed") is False,
        "XFEAT_FAILURE_CONTRACT",
    )
    for label in ("process_start_claim", "log"):
        validate_identity_claim(failure.get(label), f"xfeat-failure:{label}")
    regular_absence(XFEAT_ACCEPTED_RECEIPT, "XFEAT_ACCEPTED_RECEIPT_MUST_REMAIN_ABSENT")
    return {
        "disposition": XFEAT_EXCLUSION_STATUS,
        "forensic_audit": forensic_id,
        "terminal_failure_receipt": failure_id,
        "accepted_frontend_receipt_path": str(XFEAT_ACCEPTED_RECEIPT),
        "accepted_frontend_receipt_present": False,
        "structural_failure_code": "FEATURE_POINT_COUNT_RANGE",
        "original_planned_backend_slots": 5,
        "backend_items_launched": 0,
        "backend_trajectory_admitted": False,
        "method_native_profile": "klt_safe_fallback",
        "fallback_byte_identical_to_accepted_klt_inputs": True,
        "learning_contribution_claim_permitted": False,
    }


def load_backend_authority_module() -> Any:
    common.regular_file(BACKEND_RUNNER, "backend-v2-authority-runner")
    common.regular_file(BACKEND_PROTOCOL, "backend-v2-authority-protocol")
    specification = importlib.util.spec_from_file_location(
        "a08_klt_only_backend_v2_authority", BACKEND_RUNNER
    )
    require(
        specification is not None and specification.loader is not None,
        "BACKEND_V2_AUTHORITY_IMPORT_SPEC",
    )
    module = importlib.util.module_from_spec(specification)
    sys.modules["a08_klt_only_backend_v2_authority"] = module
    specification.loader.exec_module(module)
    for name in (
        "resolve_frontend_bindings", "verify_lock", "prior_receipt",
        "ITEM_ORDER", "BACKEND_ROOT", "DEFAULT_LOCK", "RECEIPT_NAME",
        "LOCK_SCHEMA", "LOCK_STATUS", "RECEIPT_SCHEMA",
    ):
        require(hasattr(module, name), f"BACKEND_V2_INTERFACE:{name}")
    require(tuple(module.ITEM_ORDER) == ITEM_ORDER, "BACKEND_V2_ITEM_ORDER_INTERFACE")
    require(Path(module.BACKEND_ROOT) == BACKEND_ROOT, "BACKEND_V2_ROOT_INTERFACE")
    require(Path(module.DEFAULT_LOCK) == BACKEND_LOCK, "BACKEND_V2_LOCK_INTERFACE")
    require(module.RECEIPT_NAME == BACKEND_RECEIPT_NAME,
            "BACKEND_V2_RECEIPT_NAME_INTERFACE")
    require(str(module.LOCK_SCHEMA).endswith("v2"), "BACKEND_V2_LOCK_SCHEMA_SUFFIX")
    require(str(module.RECEIPT_SCHEMA).endswith("v2"),
            "BACKEND_V2_RECEIPT_SCHEMA_SUFFIX")
    return module


def validate_backend_terminal_receipt(
    module: Any,
    item_id: str,
    receipt: Mapping[str, Any],
    backend_lock_identity: Mapping[str, Any],
    locked_item: Mapping[str, Any],
) -> dict[str, Any]:
    repeat = int(item_id[-2:])
    require(receipt.get("schema_version") == module.RECEIPT_SCHEMA,
            f"BACKEND_RECEIPT_SCHEMA:{item_id}")
    disposition = receipt.get("status")
    require(
        disposition
        in {"PASS_BACKEND_REPLAY_ACCEPTED", "FAILED_BACKEND_REPLAY_NO_REPLACEMENT"},
        f"BACKEND_RECEIPT_DISPOSITION:{item_id}",
    )
    require(
        receipt.get("item_id") == item_id
        and receipt.get("arm") == "klt"
        and receipt.get("repeat_index") == repeat,
        f"BACKEND_RECEIPT_ITEM:{item_id}",
    )
    require(receipt.get("execution_lock") == backend_lock_identity,
            f"BACKEND_RECEIPT_LOCK:{item_id}")
    require(
        receipt.get("launch_allowance_consumed") is True
        and receipt.get("retry_count") == 0
        and receipt.get("replacement_permitted") is False,
        f"BACKEND_RECEIPT_POLICY:{item_id}",
    )
    integrity = receipt.get("execution_integrity")
    require(
        isinstance(integrity, dict)
        and integrity.get("status") == "PASS"
        and integrity.get("irreversible_fault_latch_clear") is True
        and receipt.get("integrity_fault_latch") == [],
        f"BACKEND_EXECUTION_INTEGRITY:{item_id}",
    )
    require(receipt.get("trajectory_convention") == "world_T_body",
            f"BACKEND_TRAJECTORY_CONVENTION:{item_id}")
    require(
        locked_item.get("item_id") == item_id
        and locked_item.get("arm") == "klt"
        and locked_item.get("repeat_index") == repeat,
        f"BACKEND_LOCKED_ITEM:{item_id}",
    )
    artifact = receipt.get("artifact_contract")
    require(
        isinstance(artifact, dict)
        and artifact.get("evidence_tree_integrity") is True
        and artifact.get("integrity_issues") == [],
        f"BACKEND_ARTIFACT_INTEGRITY:{item_id}",
    )
    outputs = artifact.get("outputs")
    require(isinstance(outputs, dict), f"BACKEND_ARTIFACT_OUTPUTS:{item_id}")
    require(
        {"network_namespace_manifest.json", "replay_only_guard_manifest.json"}
        <= set(outputs),
        f"BACKEND_BOUNDARY_MANIFESTS:{item_id}",
    )
    accepted = disposition == "PASS_BACKEND_REPLAY_ACCEPTED"
    trajectory: Optional[dict[str, Any]] = None
    if accepted:
        claim = outputs.get("vins_output/vio.csv")
        require(
            isinstance(claim, dict)
            and Path(str(claim.get("path", "")))
            == BACKEND_ROOT / item_id / "vins_output/vio.csv",
            f"BACKEND_ACCEPTED_TRAJECTORY_PATH:{item_id}",
        )
        trajectory = validate_identity_claim(claim, f"trajectory:{item_id}")
    return {
        "item_id": item_id,
        "arm": "klt",
        "repeat_index": repeat,
        "disposition": disposition,
        "accepted_for_joint_mask": accepted,
        "trajectory": trajectory,
        "scientific_failure_retained_as_na": not accepted,
        "replacement_permitted": False,
    }


def collect_backend_binding() -> dict[str, Any]:
    module = load_backend_authority_module()
    bindings = module.resolve_frontend_bindings()
    require(isinstance(bindings, dict), "BACKEND_V2_FRONTEND_BINDINGS_TYPE")
    lock, lock_id = module.verify_lock(BACKEND_LOCK, bindings)
    require(isinstance(lock, dict) and isinstance(lock_id, dict),
            "BACKEND_V2_DEEP_LOCK_RESULT")
    require(lock.get("schema_version") == module.LOCK_SCHEMA,
            "BACKEND_V2_LOCK_SCHEMA")
    require(lock.get("status") == module.LOCK_STATUS, "BACKEND_V2_LOCK_STATUS")
    require(lock.get("item_order") == list(ITEM_ORDER), "BACKEND_V2_LOCK_ITEM_ORDER")
    require(lock.get("frontend_authority") == bindings,
            "BACKEND_V2_LIVE_FRONTEND_BINDING")
    static = lock.get("static_identities")
    require(
        isinstance(static, dict)
        and static.get("runner") == identity(BACKEND_RUNNER)
        and static.get("protocol") == identity(BACKEND_PROTOCOL),
        "BACKEND_V2_STATIC_IDENTITY",
    )
    klt = collect_klt_frontend_binding()
    excluded = collect_xfeat_exclusion()
    klt_binding = bindings.get("klt")
    xfeat_binding = bindings.get("excluded_xfeat")
    require(
        isinstance(klt_binding, dict)
        and klt_binding.get("receipt") == klt["receipt"]
        and klt_binding.get("accepted_receipt") == klt["receipt"],
        "BACKEND_V2_KLT_FRONTEND_RECEIPT_BINDING",
    )
    require(
        isinstance(xfeat_binding, dict)
        and xfeat_binding.get("disposition") == excluded["disposition"]
        and xfeat_binding.get("forensic_audit") == excluded["forensic_audit"]
        and xfeat_binding.get("terminal_failure_receipt")
        == excluded["terminal_failure_receipt"]
        and xfeat_binding.get("accepted_receipt_present") is False
        and xfeat_binding.get("backend_launched_count") == 0
        and xfeat_binding.get("learning_contribution_claim_permitted") is False,
        "BACKEND_V2_XFEAT_EXCLUSION_BINDING",
    )
    items = lock.get("items")
    require(isinstance(items, dict) and list(items) == list(ITEM_ORDER),
            "BACKEND_V2_LOCK_ITEMS")
    rows: list[dict[str, Any]] = []
    receipt_ids: dict[str, Any] = {}
    for item_id in ITEM_ORDER:
        receipt_path = BACKEND_ROOT / item_id / BACKEND_RECEIPT_NAME
        receipt, receipt_id = stable_json(receipt_path)
        deeply_verified = module.prior_receipt(lock_id, items[item_id])
        require(deeply_verified == receipt,
                f"BACKEND_V2_DEEP_TERMINAL_RECEIPT:{item_id}")
        row = validate_backend_terminal_receipt(
            module, item_id, receipt, lock_id, items[item_id]
        )
        row["receipt"] = receipt_id
        rows.append(row)
        receipt_ids[item_id] = receipt_id
    return {
        "execution_lock": lock_id,
        "execution_contract_sha256": lock.get("contract_sha256"),
        "terminal_receipts": receipt_ids,
        "planned_repeats": rows,
        "planned_count": 5,
        "valid_count": sum(row["accepted_for_joint_mask"] for row in rows),
        "failed_count": sum(not row["accepted_for_joint_mask"] for row in rows),
        "frontend_bindings": bindings,
    }


def collect_static_identities() -> dict[str, Any]:
    return {
        "runner": identity(RUNNER),
        "protocol": identity(PROTOCOL),
        "process_free_tests": identity(TESTS),
        "common_security_and_numeric_library": identity(COMMON_LIBRARY),
        "primary_evaluator": identity(EVALUATOR),
        "trajectory_eval_core": identity(EVALUATOR_CORE),
        "epoch_nanosecond_adapter": identity(EPOCH_ADAPTER),
        "backend_replay_authority_runner": identity(BACKEND_RUNNER),
        "backend_replay_protocol": identity(BACKEND_PROTOCOL),
    }


def design_contract_snapshot() -> dict[str, Any]:
    return {
        "campaign": "A08_HFNET_VS_KLT_ONLY_COMMON_SUPPORT_V2",
        "grid": exact_grid_evidence(),
        "numeric_rules": {
            "reference_rate_hz": 1.0,
            "estimate_rate_hz": 10.0,
            "evaluation_rate_hz": 1.0,
            "max_reference_gap_s": 2.5,
            "max_estimate_gap_s": 0.25,
            "all_time_offsets_s": 0.0,
            "rpe_delta_s": 1.0,
            "min_ape_poses": 30,
            "min_ape_span_s": 10.0,
            "fixed_denominator": 33,
            "min_common_coverage": 0.70,
            "min_rpe_pairs": 10,
            "proper_fixed_scale_se3": True,
            "sim3_or_scale_fit": False,
            "shared_full_precision_body_T_cam0_for_every_arm": True,
            "single_joint_mask_across_hfnet_and_all_accepted_klt_repeats": True,
            "evo_abs_tolerance_m": 1e-5,
            "all_six_primary_metrics_must_be_finite_nonnegative": True,
        },
        "population_and_failure_rules": {
            "backend_item_order": list(ITEM_ORDER),
            "klt_planned_count": 5,
            "klt_valid_count_from_terminal_dispositions": True,
            "klt_summary": "coordinatewise_median_over_all_valid_planned_repeats",
            "best_repeat_selection_permitted": False,
            "backend_scientific_failure_is_na_not_replaced": True,
            "backend_integrity_failure_blocks": True,
            "original_ten_slot_order": list(ORIGINAL_TEN_SLOT_ORDER),
            "xfeat_disposition": XFEAT_EXCLUSION_STATUS,
            "xfeat_backend_items_launched": 0,
            "xfeat_in_joint_mask_or_ranking": False,
            "xfeat_learning_contribution_claim_permitted": False,
            "any_formal_gate_or_integrity_failure_sets_all_hfnet_klt_metrics_na": True,
        },
        "execution_rules": {
            "design_freeze_before_backend_terminal_results": True,
            "dynamic_lock_after_five_terminal_receipts_before_accuracy": True,
            "single_analysis_allowance": True,
            "automatic_retry_count": 0,
            "post_claim_actions_inside_terminalization_boundary": True,
            "atomic_noreplace_publication": True,
            "incomplete_consumed_state_is_blocked": True,
            "read_only_audit_recomputes_primary_from_locked_inputs": True,
        },
    }


def backend_terminal_presence() -> dict[str, str]:
    paths = {"backend_lock": BACKEND_LOCK, **{
        item: BACKEND_ROOT / item / BACKEND_RECEIPT_NAME for item in ITEM_ORDER
    }}
    result: dict[str, str] = {}
    for name, path in paths.items():
        if not path.exists() and not path.is_symlink():
            result[name] = "MISSING"
        elif path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
            result[name] = "INVALID_KIND"
        else:
            result[name] = "PRESENT_REGULAR"
    return result


def backend_campaign_prelaunch_presence() -> dict[str, str]:
    paths: dict[str, Path] = {
        "backend_root": BACKEND_ROOT,
        "backend_runtime_root": BACKEND_RUNTIME_ROOT,
    }
    for repeat, item in enumerate(ITEM_ORDER, start=1):
        tag = f"a08_recoveredjuly_hist0000_4660_backend_klt_only_r{repeat:02d}_v2"
        paths[f"workspace:{item}"] = (
            BACKEND_OVERLAY_RUN_ROOT / f"external_klt_every2_{tag}"
        )
    return {
        name: ("PRESENT" if path.exists() or path.is_symlink() else "ABSENT")
        for name, path in paths.items()
    }


def build_design_freeze_payload(created_at_utc: str) -> dict[str, Any]:
    presence = backend_terminal_presence()
    require(all(value == "MISSING" for value in presence.values()),
            "DESIGN_FREEZE_MUST_PRECEDE_BACKEND_LOCK_AND_TERMINAL_RESULTS")
    prelaunch = backend_campaign_prelaunch_presence()
    require(all(value == "ABSENT" for value in prelaunch.values()),
            "DESIGN_FREEZE_MUST_PRECEDE_ANY_BACKEND_CAMPAIGN_TOUCH")
    regular_absence(DEFAULT_LOCK, "DESIGN_FREEZE_MUST_PRECEDE_ANALYSIS_LOCK")
    require(analysis_output_state() == "ABSENT",
            "DESIGN_FREEZE_MUST_PRECEDE_ANALYSIS_OUTPUT")
    regular_absence(LEGACY_BACKEND_LOCK, "LEGACY_BACKEND_V1_LOCK_MUST_REMAIN_ABSENT")
    regular_absence(LEGACY_ANALYSIS_LOCK, "LEGACY_ANALYSIS_V1_LOCK_MUST_REMAIN_ABSENT")
    require(not LEGACY_ANALYSIS_OUTPUT.exists() and not LEGACY_ANALYSIS_OUTPUT.is_symlink(),
            "LEGACY_ANALYSIS_V1_OUTPUT_MUST_REMAIN_ABSENT")
    payload = {
        "schema_version": DESIGN_FREEZE_SCHEMA,
        "status": "FROZEN_AFTER_XFEAT_EXCLUSION_BEFORE_KLT_BACKEND_RESULTS_AND_ACCURACY",
        "created_at_utc": created_at_utc,
        "static_identities": collect_static_identities(),
        "sealed_support": common.collect_support_binding(),
        "klt_frontend": collect_klt_frontend_binding(),
        "excluded_xfeat": collect_xfeat_exclusion(),
        "evo_authority": common.collect_evo_authority(),
        "design_contract": design_contract_snapshot(),
        "backend_terminal_presence_at_freeze": presence,
        "backend_campaign_prelaunch_presence_at_freeze": prelaunch,
        "claim_boundary": {
            "xfeat_terminal_failure_opened_for_exclusion": True,
            "backend_lock_opened": False,
            "backend_terminal_receipts_opened": False,
            "ape_or_rpe_computed": False,
            "final_dynamic_analysis_lock_built": False,
            "ros_or_vins_started": False,
        },
    }
    payload["freeze_sha256"] = compact_sha256(payload)
    return payload


def publish_design_freeze(authorization_token: str) -> dict[str, Any]:
    require(authorization_token == FREEZE_TOKEN, "DESIGN_FREEZE_AUTHORIZATION_TOKEN")
    regular_absence(DESIGN_FREEZE, "DESIGN_FREEZE_ALREADY_EXISTS")
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = build_design_freeze_payload(created)
    atomic_publish(DESIGN_FREEZE, payload)
    return {
        "status": "STATIC_DESIGN_FREEZE_PUBLISHED_NO_ACCURACY_COMPUTED",
        "design_freeze": identity(DESIGN_FREEZE),
        "accuracy_computed": False,
    }


def collect_design_freeze_binding() -> dict[str, Any]:
    value, freeze_id = stable_json(DESIGN_FREEZE)
    require(value.get("schema_version") == DESIGN_FREEZE_SCHEMA,
            "DESIGN_FREEZE_SCHEMA")
    require(
        value.get("status")
        == "FROZEN_AFTER_XFEAT_EXCLUSION_BEFORE_KLT_BACKEND_RESULTS_AND_ACCURACY",
        "DESIGN_FREEZE_STATUS",
    )
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
            "DESIGN_FREEZE_XFEAT_EXCLUSION")
    require(value.get("evo_authority") == common.collect_evo_authority(),
            "DESIGN_FREEZE_EVO_AUTHORITY")
    require(value.get("design_contract") == design_contract_snapshot(),
            "DESIGN_FREEZE_CONTRACT")
    require(
        value.get("backend_terminal_presence_at_freeze")
        == {"backend_lock": "MISSING", **{item: "MISSING" for item in ITEM_ORDER}},
        "DESIGN_FREEZE_PRIOR_TERMINAL_ABSENCE",
    )
    require(
        value.get("backend_campaign_prelaunch_presence_at_freeze")
        == {
            "backend_root": "ABSENT",
            "backend_runtime_root": "ABSENT",
            **{f"workspace:{item}": "ABSENT" for item in ITEM_ORDER},
        },
        "DESIGN_FREEZE_PRIOR_CAMPAIGN_TOUCH_ABSENCE",
    )
    boundary = value.get("claim_boundary")
    require(
        isinstance(boundary, dict)
        and boundary.get("backend_lock_opened") is False
        and boundary.get("backend_terminal_receipts_opened") is False
        and boundary.get("ape_or_rpe_computed") is False
        and boundary.get("ros_or_vins_started") is False,
        "DESIGN_FREEZE_CLAIM_BOUNDARY",
    )
    return {"identity": freeze_id, "created_at_utc": value.get("created_at_utc")}


def design_freeze_audit_readonly() -> dict[str, Any]:
    try:
        return {
            "status": "PASS_DESIGN_FROZEN_BEFORE_KLT_BACKEND_RESULTS",
            "read_only": True,
            "design_freeze": collect_design_freeze_binding(),
            "accuracy_computed": False,
        }
    except (AnalysisProtocolError, OSError, ValueError) as error:
        presence = backend_terminal_presence()
        late = any(value != "MISSING" for value in presence.values())
        return {
            "status": (
                "BLOCKED_LATE_OR_INVALID_DESIGN_FREEZE_BACKEND_RESULT_VISIBLE"
                if late else "BLOCKED_DESIGN_FREEZE"
            ),
            "read_only": True,
            "error": f"{type(error).__name__}:{error}",
            "backend_terminal_presence": presence,
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
        "campaign": "A08_HFNET_VS_KLT_ONLY_COMMON_SUPPORT_V2",
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
    expected = build_lock_payload(collect_authority(), created)
    require(lock == expected, "ANALYSIS_LOCK_AUTHORITY_DRIFT")
    return lock, lock_id


def analysis_output_state() -> str:
    output_present = OUTPUT_ROOT.exists() or OUTPUT_ROOT.is_symlink()
    claim_present = CLAIM_PATH.exists() or CLAIM_PATH.is_symlink()
    staging_present = any(
        path.exists() or path.is_symlink()
        for path in (STAGING_ROOT, EVO_WORK_ROOT, FAILURE_STAGING_ROOT)
    )
    if output_present:
        if OUTPUT_ROOT.is_symlink() or not OUTPUT_ROOT.is_dir():
            return "INVALID_TERMINAL_KIND"
        if not claim_present:
            return "TERMINAL_WITHOUT_START_CLAIM"
        if (OUTPUT_ROOT / RECEIPT_NAME).is_file() and not (
            OUTPUT_ROOT / RECEIPT_NAME
        ).is_symlink():
            return (
                "TERMINAL_RECEIPT_PRESENT_WITH_UNCOMMITTED_PARTIAL"
                if staging_present else "TERMINAL_RECEIPT_PRESENT"
            )
        return "TERMINAL_DIRECTORY_WITHOUT_RECEIPT"
    if claim_present:
        if CLAIM_PATH.is_symlink() or not stat.S_ISREG(CLAIM_PATH.lstat().st_mode):
            return "INVALID_CLAIM_KIND"
        return "CLAIMED_WITHOUT_TERMINAL_RECEIPT"
    if staging_present:
        return "UNCLAIMED_STAGING_PRESENT"
    return "ABSENT"


def require_canonical_analysis_lock_path(lock_path: Path) -> None:
    require(
        lock_path.absolute() == DEFAULT_LOCK.absolute(),
        "ANALYSIS_LOCK_PATH_MUST_BE_CANONICAL",
    )


def preflight_readonly(lock_path: Path = DEFAULT_LOCK) -> dict[str, Any]:
    try:
        require_canonical_analysis_lock_path(lock_path)
    except AnalysisProtocolError as error:
        return {
            "status": "BLOCKED_PREFLIGHT",
            "read_only": True,
            "error": f"{type(error).__name__}:{error}",
            "accuracy_computed": False,
        }
    freeze = design_freeze_audit_readonly()
    if freeze["status"] != "PASS_DESIGN_FROZEN_BEFORE_KLT_BACKEND_RESULTS":
        return {
            "status": "BLOCKED_DESIGN_FREEZE",
            "read_only": True,
            "design_freeze_audit": freeze,
            "accuracy_computed": False,
        }
    presence = backend_terminal_presence()
    unavailable = [name for name, value in presence.items() if value != "PRESENT_REGULAR"]
    if unavailable:
        return {
            "status": "WAITING_FOR_KLT_ONLY_BACKEND_FINAL_LOCK_AND_FIVE_TERMINAL_RECEIPTS",
            "read_only": True,
            "terminal_presence": presence,
            "unavailable": unavailable,
            "analysis_lock_present": lock_path.exists() or lock_path.is_symlink(),
            "excluded_xfeat_disposition": XFEAT_EXCLUSION_STATUS,
            "accuracy_computed": False,
        }
    try:
        if not lock_path.exists() and not lock_path.is_symlink():
            require(analysis_output_state() == "ABSENT", "ANALYSIS_OUTPUT_PREEXISTS")
            authority = collect_authority()
            return {
                "status": "READY_TO_BUILD_ANALYSIS_LOCK_NO_ACCURACY_COMPUTED",
                "read_only": True,
                "terminal_presence": presence,
                "klt_valid_count": authority["backend"]["valid_count"],
                "excluded_xfeat_disposition": XFEAT_EXCLUSION_STATUS,
                "candidate_contract_sha256": compact_sha256(contract_core(authority)),
                "accuracy_computed": False,
            }
        lock, lock_id = verify_lock(lock_path)
        state = analysis_output_state()
        require(
            state in {
                "ABSENT",
                "TERMINAL_RECEIPT_PRESENT",
                "TERMINAL_RECEIPT_PRESENT_WITH_UNCOMMITTED_PARTIAL",
            },
            f"ANALYSIS_ALLOWANCE_CONSUMED_WITHOUT_VALID_TERMINAL:{state}",
        )
        return {
            "status": (
                "PASS_LOCKED_READY_FOR_ONE_ANALYSIS"
                if state == "ABSENT"
                else "PASS_LOCKED_TERMINAL_RECEIPT_PRESENT_AUDIT_REQUIRED"
            ),
            "read_only": True,
            "lock": lock_id,
            "contract_sha256": lock["contract_sha256"],
            "analysis_output_state": state,
            "excluded_xfeat_disposition": XFEAT_EXCLUSION_STATUS,
            "accuracy_computed": False,
        }
    except (AnalysisProtocolError, OSError, ValueError) as error:
        return {
            "status": "BLOCKED_PREFLIGHT",
            "read_only": True,
            "terminal_presence": presence,
            "error": f"{type(error).__name__}:{error}",
            "accuracy_computed": False,
        }


def exact_grid_seconds() -> np.ndarray:
    return np.asarray(
        [np.longdouble(value) / np.longdouble(1_000_000_000) for value in GRID_NS],
        dtype=np.longdouble,
    )


def accepted_arm_paths(backend: Mapping[str, Any]) -> dict[str, Path]:
    result = {"HFNET": HFNET_TRAJECTORY}
    for row in backend["planned_repeats"]:
        if row["accepted_for_joint_mask"]:
            result[row["item_id"]] = Path(row["trajectory"]["path"])
    return result


def evaluate_joint_inputs(
    lock: Mapping[str, Any],
) -> tuple[dict[str, Any], Any, dict[str, Any], dict[str, Any], dict[str, Any]]:
    evaluator, core = common._load_numeric_modules()
    grid = exact_grid_seconds()
    reference_series = evaluator.load_tum_reference(REFERENCE_TUM)
    reference = core.resample_trajectory(
        reference_series.stamps,
        reference_series.positions,
        grid,
        2.5,
        reference_series.quaternions_xyzw,
        sample_kind="reference",
    )
    transform = evaluator.load_body_t_sensor(SHARED_EXTRINSIC)
    arm_paths = accepted_arm_paths(lock["authority"]["backend"])
    arms: dict[str, Any] = {}
    legacy: dict[str, Any] = {}
    prepared_reference_stamps, _, _, _ = core.prepare_reference_samples(
        reference_series.stamps,
        reference_series.positions,
        reference_series.quaternions_xyzw,
    )
    for name, path in arm_paths.items():
        body = evaluator.load_vins_body_csv(path)
        if body.quaternions_xyzw is None:
            raise AnalysisProtocolError(f"ARM_ORIENTATION_MISSING:{name}")
        core.validate_estimate_samples(
            body.stamps, body.positions, body.quaternions_xyzw
        )
        camera_positions, camera_quaternions = core.transform_body_poses_to_sensor(
            body.positions, body.quaternions_xyzw, transform
        )
        arms[name] = core.resample_trajectory(
            body.stamps,
            camera_positions,
            grid,
            0.25,
            camera_quaternions,
            sample_kind="estimate",
        )
        legacy[name] = evaluator.legacy_nearest_reuse_stats(
            body.stamps, prepared_reference_stamps
        )
    evaluation = core.evaluate_common_translation(
        reference,
        arms,
        window_start_s=np.longdouble(START_NS) / np.longdouble(1_000_000_000),
        window_end_s=np.longdouble(END_NS) / np.longdouble(1_000_000_000),
        max_segment_gap_s=2.5,
        rpe_delta_s=1.0,
        min_ape_poses=30,
        min_ape_span_s=10.0,
        min_common_coverage=0.70,
        min_rpe_pairs=10,
    )
    numeric_protocol = {
        "contrast_name": "A08_HFNET_VS_KLT_ONLY_COMMON_SUPPORT_V2",
        "reference": str(REFERENCE_TUM),
        "evaluation_rate_hz": 1.0,
        "nominal_reference_rate_hz": 1.0,
        "nominal_estimate_rate_hz": 10.0,
        "window_start_ns": START_NS,
        "window_end_ns": END_NS,
        "max_reference_gap_s": 2.5,
        "max_estimate_gap_s": 0.25,
        "rpe_delta_s": 1.0,
        "body_to_camera_applied": True,
        "shared_full_precision_body_T_cam0": str(SHARED_EXTRINSIC),
        "proper_fixed_scale_se3": True,
        "sim3": False,
        "reference_time_offset_s": 0.0,
        "all_arm_time_offsets_s": 0.0,
        "single_joint_mask": True,
        "joint_mask_population": "reference_and_hfnet_and_all_accepted_klt_repeats",
        "xfeat_excluded_before_backend": True,
        "exact_integer_nanosecond_grid_evidence": GRID_NAME,
    }
    summary = evaluator.clean_json_value(
        evaluator.serializable_summary(
            evaluation, reference, arms, numeric_protocol, legacy
        )
    )
    require(isinstance(summary, dict), "PRIMARY_SUMMARY_TYPE")
    summary["claim_boundary"] = {
        "diagnostic_only_not_formal_ranking": True,
        "formal_ranking_authority": FORMAL_SUMMARY_NAME,
        "terminal_receipt_required": RECEIPT_NAME,
    }
    return summary, reference, arms, evaluation, {
        "evaluator": evaluator, "core": core
    }


def support_gate(summary: Mapping[str, Any]) -> dict[str, Any]:
    return common.support_gate(summary)


def null_metrics() -> dict[str, None]:
    return common.null_metrics()


def numeric_metrics(row: Mapping[str, Any]) -> dict[str, Optional[float]]:
    return common.numeric_metrics(row)


def median_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Optional[float]]:
    return common.median_metrics(rows)


def original_ten_slot_rows(
    backend: Mapping[str, Any],
    primary_arms: Optional[Mapping[str, Any]],
    ranking_available: bool,
) -> list[dict[str, Any]]:
    klt_by_id = {row["item_id"]: row for row in backend["planned_repeats"]}
    rows: list[dict[str, Any]] = []
    for slot_id in ORIGINAL_TEN_SLOT_ORDER:
        repeat = int(slot_id[-2:])
        if slot_id.startswith("XFEAT_"):
            rows.append({
                "item_id": slot_id,
                "arm": "xfeat",
                "repeat_index": repeat,
                "terminal_disposition": XFEAT_EXCLUSION_STATUS,
                "backend_launched": False,
                "accepted_for_single_joint_mask": False,
                "scientific_failure_retained_as_na": False,
                "frontend_structural_failure_retained_as_na": True,
                "replacement_permitted": False,
                "formal_metrics": null_metrics(),
            })
            continue
        planned = klt_by_id[slot_id]
        accepted = bool(planned["accepted_for_joint_mask"])
        raw = primary_arms.get(slot_id) if accepted and primary_arms is not None else None
        rows.append({
            "item_id": slot_id,
            "arm": "klt",
            "repeat_index": repeat,
            "terminal_disposition": planned["disposition"],
            "backend_launched": True,
            "accepted_for_single_joint_mask": accepted,
            "scientific_failure_retained_as_na": not accepted,
            "frontend_structural_failure_retained_as_na": False,
            "replacement_permitted": False,
            "formal_metrics": (
                numeric_metrics(raw)
                if ranking_available and isinstance(raw, Mapping)
                else null_metrics()
            ),
        })
    return rows


def build_formal_summary(
    lock: Mapping[str, Any],
    primary_summary: Mapping[str, Any],
    primary_gate: Mapping[str, Any],
    evo_audit: Mapping[str, Any],
) -> dict[str, Any]:
    backend = lock["authority"]["backend"]
    arms = primary_summary.get("arms")
    require(isinstance(arms, dict), "PRIMARY_ARMS_BLOCK")
    expected_arms = list(accepted_arm_paths(backend))
    completeness = common.primary_arm_completeness_gate(primary_summary, expected_arms)
    population_checks = {
        "klt_has_at_least_one_valid_planned_repeat": backend["valid_count"] >= 1,
        "xfeat_excluded_before_backend_not_required_for_two_arm_ranking": True,
    }
    population_failures = [
        name for name, passed in population_checks.items() if not passed
    ]
    ranking = bool(
        primary_gate.get("status") == "PASS"
        and not population_failures
        and completeness.get("status") == "PASS"
        and evo_audit.get("status") == "PASS"
    )
    klt_numeric = [
        arms[row["item_id"]]
        for row in backend["planned_repeats"]
        if row["accepted_for_joint_mask"] and isinstance(arms.get(row["item_id"]), dict)
    ]
    hfnet = arms.get("HFNET")
    require(isinstance(hfnet, dict), "PRIMARY_HFNET_MISSING")
    failures: list[str] = []
    failures.extend(f"SUPPORT:{code}" for code in primary_gate.get("failure_codes", []))
    failures.extend(f"POPULATION:{code}" for code in population_failures)
    failures.extend(
        f"PRIMARY_COMPLETENESS:{code}"
        for code in completeness.get("failure_codes", [])
    )
    failures.extend(f"EVO:{code}" for code in evo_audit.get("failure_codes", []))
    return {
        "schema_version": FORMAL_SCHEMA,
        "status": (
            "FORMAL_HFNET_VS_KLT_RANKING_AVAILABLE"
            if ranking else "FORMAL_HFNET_VS_KLT_RANKING_NA_GATE_CLOSED"
        ),
        "ranking_available": ranking,
        "all_formal_hfnet_klt_metrics_na_if_any_gate_fails": True,
        "failure_codes": failures,
        "support_gate": dict(primary_gate),
        "population_gate": {
            "status": "PASS" if not population_failures else "FAIL",
            "checks": population_checks,
            "failure_codes": population_failures,
        },
        "primary_arm_completeness_gate": completeness,
        "evo_gate": dict(evo_audit),
        "single_joint_mask_arm_set": list(arms),
        "hfnet": {
            "label": "HFNet-SLAM external learned-feature system",
            "planned_count": 1,
            "valid_count": 1,
            "formal_metrics": numeric_metrics(hfnet) if ranking else null_metrics(),
        },
        "klt": {
            "label": "Vanilla VINS-Fusion with accepted KLT frontend export",
            "planned_count": 5,
            "valid_count": backend["valid_count"],
            "failed_count": 5 - backend["valid_count"],
            "aggregation": "coordinatewise_median_over_all_valid_planned_repeats",
            "best_run_selected": False,
            "formal_median_metrics": (
                median_metrics(klt_numeric) if ranking else null_metrics()
            ),
        },
        "xfeat_excluded": {
            **lock["authority"]["excluded_xfeat"],
            "formal_median_metrics": null_metrics(),
        },
        "planned_klt_repeats": [
            {
                "item_id": row["item_id"],
                "repeat_index": row["repeat_index"],
                "terminal_disposition": row["disposition"],
                "accepted_for_single_joint_mask": row["accepted_for_joint_mask"],
                "scientific_failure_retained_as_na": not row["accepted_for_joint_mask"],
                "replacement_permitted": False,
                "formal_metrics": (
                    numeric_metrics(arms[row["item_id"]])
                    if ranking and row["accepted_for_joint_mask"]
                    else null_metrics()
                ),
            }
            for row in backend["planned_repeats"]
        ],
        "original_ten_slot_dispositions": original_ten_slot_rows(
            backend, arms, ranking
        ),
        "technical_repeats_are_not_independent_samples": True,
        "development_only_outcome_selected_support_extended": True,
        "reference_is_image_derived_depth_scaled_proxy": True,
        "learned_feature_contribution_claim_from_xfeat_permitted": False,
    }


def build_error_formal_summary(
    lock: Mapping[str, Any], error: str
) -> dict[str, Any]:
    backend = lock["authority"]["backend"]
    return {
        "schema_version": FORMAL_SCHEMA,
        "status": "FORMAL_HFNET_VS_KLT_RANKING_NA_ANALYSIS_ERROR_NO_RETRY",
        "ranking_available": False,
        "all_formal_hfnet_klt_metrics_na_if_any_gate_fails": True,
        "failure_codes": [f"ANALYSIS_ERROR:{error}"],
        "hfnet": {"planned_count": 1, "valid_count": 1,
                  "formal_metrics": null_metrics()},
        "klt": {
            "planned_count": 5,
            "valid_count": backend["valid_count"],
            "failed_count": 5 - backend["valid_count"],
            "aggregation": "coordinatewise_median_over_all_valid_planned_repeats",
            "best_run_selected": False,
            "formal_median_metrics": null_metrics(),
        },
        "xfeat_excluded": {
            **lock["authority"]["excluded_xfeat"],
            "formal_median_metrics": null_metrics(),
        },
        "planned_klt_repeats": [
            {
                "item_id": row["item_id"],
                "repeat_index": row["repeat_index"],
                "terminal_disposition": row["disposition"],
                "accepted_for_single_joint_mask": row["accepted_for_joint_mask"],
                "scientific_failure_retained_as_na": not row["accepted_for_joint_mask"],
                "replacement_permitted": False,
                "formal_metrics": null_metrics(),
            }
            for row in backend["planned_repeats"]
        ],
        "original_ten_slot_dispositions": original_ten_slot_rows(
            backend, None, False
        ),
        "technical_repeats_are_not_independent_samples": True,
        "development_only_outcome_selected_support_extended": True,
        "reference_is_image_derived_depth_scaled_proxy": True,
        "learned_feature_contribution_claim_from_xfeat_permitted": False,
    }


def force_all_formal_metrics_na_for_integrity(
    formal: Mapping[str, Any], failure_codes: Sequence[str]
) -> dict[str, Any]:
    result = json.loads(json.dumps(formal, allow_nan=False))
    result["status"] = "FORMAL_HFNET_VS_KLT_RANKING_NA_EXECUTION_INTEGRITY"
    result["ranking_available"] = False
    existing = result.get("failure_codes")
    result["failure_codes"] = list(existing) if isinstance(existing, list) else []
    result["failure_codes"].extend(
        code for code in failure_codes if code not in result["failure_codes"]
    )
    result["hfnet"]["formal_metrics"] = null_metrics()
    result["klt"]["formal_median_metrics"] = null_metrics()
    result["xfeat_excluded"]["formal_median_metrics"] = null_metrics()
    for key in ("planned_klt_repeats", "original_ten_slot_dispositions"):
        for row in result.get(key, []):
            row["formal_metrics"] = null_metrics()
    result["execution_integrity_gate"] = {
        "status": "FAIL", "failure_codes": list(failure_codes)
    }
    result["terminal_receipt_required_for_interpretation"] = True
    return result


def formal_metrics_are_all_na(formal: Mapping[str, Any]) -> bool:
    blocks: list[Any] = [
        formal.get("hfnet", {}).get("formal_metrics"),
        formal.get("klt", {}).get("formal_median_metrics"),
        formal.get("xfeat_excluded", {}).get("formal_median_metrics"),
    ]
    for key in ("planned_klt_repeats", "original_ten_slot_dispositions"):
        rows = formal.get(key)
        if isinstance(rows, list):
            blocks.extend(
                row.get("formal_metrics") for row in rows if isinstance(row, dict)
            )
    return bool(blocks) and all(
        isinstance(block, dict)
        and set(block) == set(PRIMARY_METRICS)
        and all(block[name] is None for name in PRIMARY_METRICS)
        for block in blocks
    )


def repeat_table_csv_text(formal: Mapping[str, Any]) -> str:
    fields = [
        "item_id", "arm", "repeat_index", "terminal_disposition",
        "backend_launched", "accepted_for_single_joint_mask",
        "scientific_failure_retained_as_na",
        "frontend_structural_failure_retained_as_na",
        "replacement_permitted", *PRIMARY_METRICS,
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


def write_repeat_table(path: Path, formal: Mapping[str, Any]) -> None:
    with path.open("x", newline="", encoding="utf-8") as handle:
        handle.write(repeat_table_csv_text(formal))
        handle.flush()
        os.fsync(handle.fileno())


def output_tree_identities(
    root: Path,
    *,
    advertised_root: Optional[Path] = None,
    exclude_receipt: bool = True,
) -> dict[str, Any]:
    root = root.absolute()
    advertised_root = root if advertised_root is None else advertised_root.absolute()
    require(root.is_dir() and not root.is_symlink(), "OUTPUT_ROOT_KIND")
    result: dict[str, Any] = {}
    for root_raw, directories, files in os.walk(root, followlinks=False):
        current = Path(root_raw)
        for name in directories:
            child = current / name
            require(child.is_dir() and not child.is_symlink(),
                    f"OUTPUT_DIRECTORY_KIND:{child}")
        for name in files:
            child = current / name
            relative = str(child.relative_to(root))
            if exclude_receipt and relative == RECEIPT_NAME:
                continue
            observed = identity(child)
            observed["path"] = str(advertised_root / relative)
            result[relative] = observed
    return {name: result[name] for name in sorted(result)}


def make_terminal_receipt(
    *,
    lock: Mapping[str, Any],
    lock_id: Mapping[str, Any],
    claim_id: Mapping[str, Any],
    started: str,
    formal: Mapping[str, Any],
    errors: Sequence[str],
    authority_post: Mapping[str, Any],
    claim_stable: bool,
    artifacts: Mapping[str, Any],
) -> dict[str, Any]:
    integrity_ok = bool(authority_post.get("status") == "PASS" and claim_stable)
    ranking = bool(formal.get("ranking_available") and integrity_ok)
    return {
        "schema_version": RECEIPT_SCHEMA,
        "status": (
            "PASS_FORMAL_HFNET_VS_KLT_RANKING_AVAILABLE"
            if ranking else "TERMINAL_FORMAL_HFNET_VS_KLT_RANKING_NA_NO_RETRY"
        ),
        "started_at_utc": started,
        "ended_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "analysis_allowance_consumed": True,
        "automatic_retry_count": 0,
        "replacement_analysis_permitted": False,
        "execution_lock": dict(lock_id),
        "claim": dict(claim_id),
        "analysis_errors": list(errors),
        "formal_summary_status": formal["status"],
        "formal_ranking_available": ranking,
        "execution_integrity": {
            "status": "PASS" if integrity_ok else "FAIL",
            "authority_post": dict(authority_post),
            "claim_stable": claim_stable,
        },
        "artifacts_before_receipt": dict(artifacts),
        "terminal_directory_committed_atomically_noreplace": True,
        "formal_summary_requires_this_terminal_receipt": True,
        "single_joint_mask": True,
        "exact_integer_ns_grid_bound": True,
        "klt_planned_count": 5,
        "klt_valid_count": lock["authority"]["backend"]["valid_count"],
        "best_repeat_selection_permitted": False,
        "excluded_xfeat_disposition": XFEAT_EXCLUSION_STATUS,
        "excluded_xfeat_backend_launched": False,
        "excluded_xfeat_learning_contribution_claim_permitted": False,
        "trajectory_convention": "world_T_body_then_shared_body_T_cam0",
    }


def create_primary_staging_root() -> None:
    STAGING_ROOT.mkdir()


def publish_failure_terminal(
    *,
    lock: Mapping[str, Any],
    lock_id: Mapping[str, Any],
    claim_id: Mapping[str, Any],
    started: str,
    errors: Sequence[str],
    partial_staging: Path,
) -> dict[str, Any]:
    regular_absence(OUTPUT_ROOT, "FAILURE_TERMINAL_DESTINATION_EXISTS")
    regular_absence(FAILURE_STAGING_ROOT, "FAILURE_STAGING_ALREADY_EXISTS")
    FAILURE_STAGING_ROOT.mkdir()
    atomic_publish(FAILURE_STAGING_ROOT / GRID_NAME, exact_grid_evidence())
    message = ";".join(errors) if errors else "UNKNOWN_POST_CLAIM_FAILURE"
    formal = force_all_formal_metrics_na_for_integrity(
        build_error_formal_summary(lock, message),
        ["EXECUTION_INTEGRITY:POST_CLAIM_TERMINALIZATION"],
    )
    write_repeat_table(FAILURE_STAGING_ROOT / REPEAT_TABLE_NAME, formal)
    atomic_publish(FAILURE_STAGING_ROOT / FORMAL_SUMMARY_NAME, formal)
    try:
        partial = {
            "status": "PRESERVED_UNCOMMITTED_PARTIAL_EVIDENCE",
            "tree": (
                output_tree_identities(
                    partial_staging,
                    advertised_root=partial_staging,
                    exclude_receipt=False,
                )
                if partial_staging.is_dir() and not partial_staging.is_symlink()
                else {}
            ),
            "evo_work_tree": (
                output_tree_identities(
                    EVO_WORK_ROOT,
                    advertised_root=EVO_WORK_ROOT,
                    exclude_receipt=False,
                )
                if EVO_WORK_ROOT.is_dir() and not EVO_WORK_ROOT.is_symlink()
                else {}
            ),
        }
    except BaseException as error:
        partial = {
            "status": "PARTIAL_EVIDENCE_AUDIT_FAILED",
            "error": f"{type(error).__name__}:{error}",
        }
    atomic_publish(FAILURE_STAGING_ROOT / PARTIAL_EVIDENCE_NAME, partial)
    artifacts = output_tree_identities(
        FAILURE_STAGING_ROOT,
        advertised_root=OUTPUT_ROOT,
        exclude_receipt=True,
    )
    receipt = make_terminal_receipt(
        lock=lock,
        lock_id=lock_id,
        claim_id=claim_id,
        started=started,
        formal=formal,
        errors=errors,
        authority_post={"status": "FAIL", "reason": "POST_CLAIM_TERMINALIZATION"},
        claim_stable=False,
        artifacts=artifacts,
    )
    atomic_publish(FAILURE_STAGING_ROOT / RECEIPT_NAME, receipt)
    commit_directory_noreplace(FAILURE_STAGING_ROOT, OUTPUT_ROOT)
    return receipt


def execute_analysis(
    lock_path: Path, authorization_token: str
) -> tuple[int, dict[str, Any]]:
    require_canonical_analysis_lock_path(lock_path)
    require(authorization_token == RUN_TOKEN, "RUN_AUTHORIZATION_TOKEN")
    require(analysis_output_state() == "ABSENT", "ANALYSIS_ALLOWANCE_ALREADY_CONSUMED")
    lock, lock_id = verify_lock(lock_path)
    OUTPUT_ROOT.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    claim = {
        "schema_version": CLAIM_SCHEMA,
        "status": "CLAIMED_SINGLE_ANALYSIS_ALLOWANCE_CONSUMED_NO_RETRY",
        "started_at_utc": started,
        "execution_lock": lock_id,
        "contract_sha256": lock["contract_sha256"],
        "automatic_retry_count": 0,
        "replacement_analysis_permitted": False,
        "planned_joint_arm_set": list(
            accepted_arm_paths(lock["authority"]["backend"])
        ),
        "excluded_xfeat_disposition": XFEAT_EXCLUSION_STATUS,
        "accuracy_computed_before_claim": False,
    }
    claim_id: Optional[dict[str, Any]] = None
    errors: list[str] = []
    try:
        # Every post-claim action, including identity capture and mkdir, is
        # inside this terminalization boundary.
        atomic_publish(CLAIM_PATH, claim)
        claim_id = identity(CLAIM_PATH)
        create_primary_staging_root()
        atomic_publish(STAGING_ROOT / GRID_NAME, exact_grid_evidence())
        try:
            primary, reference, arms, evaluation, modules = evaluate_joint_inputs(lock)
        except BaseException as error:
            message = f"{type(error).__name__}:{error}"
            errors.append(message)
            formal = build_error_formal_summary(lock, message)
        else:
            atomic_publish(STAGING_ROOT / RAW_SUMMARY_NAME, primary)
            # Direct CSV writers are intentionally not caught here.  A partial
            # writer is an integrity fault and must remain uncommitted.
            modules["evaluator"].write_grid_audit(
                STAGING_ROOT / GRID_AUDIT_NAME, reference, arms, evaluation
            )
            modules["evaluator"].write_metrics_csv(
                STAGING_ROOT / RAW_METRICS_NAME, primary
            )
            atomic_publish(
                STAGING_ROOT / RAW_DIAGNOSTIC_MANIFEST_NAME,
                {
                    "schema_version": "aqua-fe-a08-raw-numeric-diagnostics-boundary-v2",
                    "status": "DIAGNOSTIC_ONLY_NOT_FORMAL_RANKING",
                    "artifacts": [RAW_SUMMARY_NAME, GRID_AUDIT_NAME, RAW_METRICS_NAME],
                    "formal_ranking_authority": FORMAL_SUMMARY_NAME,
                    "terminal_receipt_required": RECEIPT_NAME,
                },
            )
            gate = support_gate(primary)
            population_ready = lock["authority"]["backend"]["valid_count"] >= 1
            if gate["status"] == "PASS" and population_ready:
                # evo writes into a separate uncommitted work root.  Only a
                # complete, validated cross-check directory enters staging.
                EVO_WORK_ROOT.mkdir()
                try:
                    evo = modules["evaluator"].run_segmented_evo_crosscheck(
                        EVO_WORK_ROOT, reference, arms, evaluation, 1.0, 1.0
                    )
                    evo_audit = common.validate_evo_crosscheck(
                        evo,
                        primary,
                        list(arms),
                        lock["authority"]["evo"]["version"],
                        tolerance_m=1e-5,
                    )
                    commit_directory_noreplace(
                        EVO_WORK_ROOT / "evo_crosscheck",
                        STAGING_ROOT / "evo_crosscheck",
                    )
                    EVO_WORK_ROOT.rmdir()
                    atomic_publish(STAGING_ROOT / EVO_SUMMARY_NAME, evo)
                except BaseException as error:
                    # A partially written evo tree is not a normal gate result.
                    # It is kept outside staging and terminalized as integrity NA.
                    raise AnalysisProtocolError(
                        f"EVO_EXECUTION_OR_VALIDATION:{type(error).__name__}:{error}"
                    ) from error
            elif gate["status"] != "PASS":
                evo_audit = {
                    "status": "NOT_RUN_SUPPORT_GATE_CLOSED",
                    "failure_codes": ["SUPPORT_GATE_CLOSED_BEFORE_EVO"],
                    "tolerance_m": 1e-5,
                }
            else:
                evo_audit = {
                    "status": "NOT_RUN_POPULATION_GATE_CLOSED",
                    "failure_codes": ["KLT_HAS_ZERO_VALID_PLANNED_REPEATS"],
                    "tolerance_m": 1e-5,
                }
            formal = build_formal_summary(lock, primary, gate, evo_audit)

        try:
            post_lock, post_lock_id = verify_lock(lock_path)
            authority_post = {
                "status": (
                    "PASS" if post_lock == lock and post_lock_id == lock_id else "FAIL"
                ),
                "lock": post_lock_id,
            }
        except BaseException as error:
            authority_post = {
                "status": "FAIL", "error": f"{type(error).__name__}:{error}"
            }
        try:
            claim_stable = identity(CLAIM_PATH) == claim_id
        except BaseException:
            claim_stable = False
        integrity_failures: list[str] = []
        if authority_post.get("status") != "PASS":
            integrity_failures.append("EXECUTION_INTEGRITY:POST_AUTHORITY_FAILURE")
        if not claim_stable:
            integrity_failures.append("EXECUTION_INTEGRITY:CLAIM_NOT_STABLE")
        integrity_ok = not integrity_failures
        if integrity_ok:
            formal["execution_integrity_gate"] = {
                "status": "PASS", "failure_codes": []
            }
            formal["terminal_receipt_required_for_interpretation"] = True
        else:
            formal = force_all_formal_metrics_na_for_integrity(
                formal, integrity_failures
            )
        write_repeat_table(STAGING_ROOT / REPEAT_TABLE_NAME, formal)
        atomic_publish(STAGING_ROOT / FORMAL_SUMMARY_NAME, formal)
        artifacts = output_tree_identities(
            STAGING_ROOT,
            advertised_root=OUTPUT_ROOT,
            exclude_receipt=True,
        )
        receipt = make_terminal_receipt(
            lock=lock,
            lock_id=lock_id,
            claim_id=claim_id,
            started=started,
            formal=formal,
            errors=errors,
            authority_post=authority_post,
            claim_stable=claim_stable,
            artifacts=artifacts,
        )
        atomic_publish(STAGING_ROOT / RECEIPT_NAME, receipt)
        commit_directory_noreplace(STAGING_ROOT, OUTPUT_ROOT)
        return (0 if integrity_ok and not errors else 3), receipt
    except BaseException as error:
        # If claim publication failed before ownership became visible, the
        # allowance was not consumed and there is no terminal to publish.  If
        # the no-replace link is visible (for example a parent-fsync exception),
        # it is already a consumed allowance and must be terminalized.
        claim_visible = CLAIM_PATH.exists() or CLAIM_PATH.is_symlink()
        if not claim_visible:
            raise
        errors.append(f"TERMINALIZATION:{type(error).__name__}:{error}")
        if OUTPUT_ROOT.is_dir() and not OUTPUT_ROOT.is_symlink():
            try:
                committed, _ = stable_json(OUTPUT_ROOT / RECEIPT_NAME)
                return 3, committed
            except BaseException:
                pass
        if claim_id is None:
            live_claim, live_claim_id = stable_json(CLAIM_PATH)
            require(live_claim == claim, "CLAIM_PUBLICATION_OWNERSHIP_UNCERTAIN")
            claim_id = live_claim_id
        failure = publish_failure_terminal(
            lock=lock,
            lock_id=lock_id,
            claim_id=claim_id,
            started=started,
            errors=errors,
            partial_staging=STAGING_ROOT,
        )
        return 3, failure


def build_lock(lock_path: Path, authorization_token: str) -> dict[str, Any]:
    require_canonical_analysis_lock_path(lock_path)
    require(authorization_token == BUILD_LOCK_TOKEN, "BUILD_LOCK_AUTHORIZATION_TOKEN")
    regular_absence(lock_path, "ANALYSIS_LOCK_ALREADY_EXISTS")
    require(analysis_output_state() == "ABSENT", "ANALYSIS_OUTPUT_PREEXISTS")
    collect_design_freeze_binding()
    presence = backend_terminal_presence()
    require(all(value == "PRESENT_REGULAR" for value in presence.values()),
            "FIVE_KLT_TERMINAL_RECEIPTS_REQUIRED")
    authority = collect_authority()
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = build_lock_payload(authority, created)
    atomic_publish(lock_path, payload)
    return {
        "status": "FINAL_ANALYSIS_LOCK_PUBLISHED_NO_ACCURACY_COMPUTED",
        "lock": identity(lock_path),
        "klt_valid_count": authority["backend"]["valid_count"],
        "excluded_xfeat_disposition": XFEAT_EXCLUSION_STATUS,
        "accuracy_computed": False,
    }


def validate_output_allowlist(expected_arms: Sequence[str]) -> dict[str, Any]:
    root_allowed = {
        GRID_NAME,
        RAW_SUMMARY_NAME,
        GRID_AUDIT_NAME,
        RAW_METRICS_NAME,
        RAW_DIAGNOSTIC_MANIFEST_NAME,
        REPEAT_TABLE_NAME,
        FORMAL_SUMMARY_NAME,
        EVO_SUMMARY_NAME,
        RECEIPT_NAME,
        PARTIAL_EVIDENCE_NAME,
    }
    files: list[str] = []
    directories: list[str] = []
    for root_raw, child_directories, child_files in os.walk(
        OUTPUT_ROOT, followlinks=False
    ):
        current = Path(root_raw)
        for name in child_directories:
            child = current / name
            require(child.is_dir() and not child.is_symlink(),
                    f"AUDIT_OUTPUT_DIRECTORY_KIND:{child}")
            directories.append(str(child.relative_to(OUTPUT_ROOT)))
        for name in child_files:
            child = current / name
            common.regular_file(child.absolute(), "audit-output")
            files.append(str(child.relative_to(OUTPUT_ROOT)))
    require(set(directories) <= {"evo_crosscheck"}, "AUDIT_OUTPUT_DIRECTORIES")
    arm_pattern = "(?:" + "|".join(re.escape(name) for name in expected_arms) + ")"
    evo_patterns = (
        r"reference_common\.tum",
        rf"{arm_pattern}_common_aligned\.tum",
        rf"{arm_pattern}_evo_ape\.log",
        r"reference_segment_[0-9]{3}\.tum",
        rf"{arm_pattern}_segment_[0-9]{{3}}\.tum",
        rf"{arm_pattern}_evo_rpe_segment_[0-9]{{3}}\.log",
    )
    unexpected: list[str] = []
    for relative in files:
        path = Path(relative)
        if len(path.parts) == 1:
            if relative not in root_allowed:
                unexpected.append(relative)
        elif path.parts[0] == "evo_crosscheck" and len(path.parts) == 2:
            if not any(re.fullmatch(pattern, path.parts[1]) for pattern in evo_patterns):
                unexpected.append(relative)
        else:
            unexpected.append(relative)
    require(not unexpected, "AUDIT_UNEXPECTED_OUTPUTS:" + ",".join(unexpected))
    return {"files": sorted(files), "directories": sorted(directories)}


def validate_formal_population_binding(
    formal: Mapping[str, Any], lock: Mapping[str, Any]
) -> None:
    excluded = formal.get("xfeat_excluded")
    require(isinstance(excluded, dict), "FORMAL_XFEAT_EXCLUSION_BLOCK")
    locked_excluded = lock["authority"]["excluded_xfeat"]
    require(
        all(excluded.get(key) == value for key, value in locked_excluded.items())
        and excluded.get("disposition") == XFEAT_EXCLUSION_STATUS
        and excluded.get("accepted_frontend_receipt_present") is False
        and excluded.get("backend_items_launched") == 0
        and excluded.get("backend_trajectory_admitted") is False
        and excluded.get("learning_contribution_claim_permitted") is False
        and excluded.get("formal_median_metrics") == null_metrics(),
        "FORMAL_XFEAT_EXCLUSION_BINDING",
    )
    require(
        formal.get("learned_feature_contribution_claim_from_xfeat_permitted") is False,
        "FORMAL_XFEAT_LEARNING_CLAIM_BOUNDARY",
    )
    klt_rows = formal.get("planned_klt_repeats")
    locked_rows = lock["authority"]["backend"]["planned_repeats"]
    require(
        isinstance(klt_rows, list)
        and [row.get("item_id") for row in klt_rows if isinstance(row, dict)]
        == list(ITEM_ORDER),
        "FORMAL_KLT_REPEAT_ORDER",
    )
    for observed, locked in zip(klt_rows, locked_rows):
        require(
            observed.get("repeat_index") == locked["repeat_index"]
            and observed.get("terminal_disposition") == locked["disposition"]
            and observed.get("accepted_for_single_joint_mask")
            is locked["accepted_for_joint_mask"]
            and observed.get("replacement_permitted") is False,
            f"FORMAL_KLT_REPEAT_BINDING:{locked['item_id']}",
        )
    slots = formal.get("original_ten_slot_dispositions")
    require(
        isinstance(slots, list)
        and [row.get("item_id") for row in slots if isinstance(row, dict)]
        == list(ORIGINAL_TEN_SLOT_ORDER),
        "FORMAL_ORIGINAL_TEN_SLOT_ORDER",
    )
    locked_by_id = {row["item_id"]: row for row in locked_rows}
    for row in slots:
        item_id = row["item_id"]
        if item_id.startswith("XFEAT_"):
            require(
                row.get("arm") == "xfeat"
                and row.get("terminal_disposition") == XFEAT_EXCLUSION_STATUS
                and row.get("backend_launched") is False
                and row.get("accepted_for_single_joint_mask") is False
                and row.get("frontend_structural_failure_retained_as_na") is True
                and row.get("replacement_permitted") is False
                and row.get("formal_metrics") == null_metrics(),
                f"FORMAL_XFEAT_SLOT:{item_id}",
            )
        else:
            locked = locked_by_id[item_id]
            require(
                row.get("arm") == "klt"
                and row.get("terminal_disposition") == locked["disposition"]
                and row.get("backend_launched") is True
                and row.get("accepted_for_single_joint_mask")
                is locked["accepted_for_joint_mask"]
                and row.get("replacement_permitted") is False,
                f"FORMAL_KLT_SLOT:{item_id}",
            )


def validate_primary_metrics_csv_file(
    path: Path, recomputed_primary: Mapping[str, Any]
) -> None:
    with path.open("r", newline="", encoding="utf-8") as handle:
        observed = handle.read()
    require(
        observed == common.primary_metrics_csv_text(recomputed_primary),
        "PRIMARY_METRICS_CSV_RECOMPUTATION",
    )


def audit_terminal_semantics(
    lock: Mapping[str, Any], lock_id: Mapping[str, Any]
) -> dict[str, Any]:
    receipt, receipt_id = stable_json(OUTPUT_ROOT / RECEIPT_NAME)
    require(receipt.get("schema_version") == RECEIPT_SCHEMA,
            "ANALYSIS_RECEIPT_SCHEMA")
    require(
        receipt.get("status")
        in {
            "PASS_FORMAL_HFNET_VS_KLT_RANKING_AVAILABLE",
            "TERMINAL_FORMAL_HFNET_VS_KLT_RANKING_NA_NO_RETRY",
        },
        "ANALYSIS_RECEIPT_STATUS",
    )
    require(receipt.get("execution_lock") == lock_id, "ANALYSIS_RECEIPT_LOCK")
    require(
        receipt.get("analysis_allowance_consumed") is True
        and receipt.get("automatic_retry_count") == 0
        and receipt.get("replacement_analysis_permitted") is False,
        "ANALYSIS_RECEIPT_POLICY",
    )
    require(
        receipt.get("terminal_directory_committed_atomically_noreplace") is True
        and receipt.get("formal_summary_requires_this_terminal_receipt") is True
        and receipt.get("single_joint_mask") is True
        and receipt.get("exact_integer_ns_grid_bound") is True
        and receipt.get("klt_planned_count") == 5
        and receipt.get("klt_valid_count")
        == lock["authority"]["backend"]["valid_count"]
        and receipt.get("best_repeat_selection_permitted") is False
        and receipt.get("excluded_xfeat_disposition") == XFEAT_EXCLUSION_STATUS
        and receipt.get("excluded_xfeat_backend_launched") is False
        and receipt.get("excluded_xfeat_learning_contribution_claim_permitted") is False,
        "ANALYSIS_RECEIPT_CLAIM_BOUNDARY",
    )
    claim_id = validate_identity_claim(receipt.get("claim"), "analysis-claim")
    require(Path(claim_id["path"]) == CLAIM_PATH, "ANALYSIS_CLAIM_PATH")
    claim, live_claim_id = stable_json(CLAIM_PATH)
    require(live_claim_id == claim_id, "ANALYSIS_CLAIM_IDENTITY")
    expected_arms = list(accepted_arm_paths(lock["authority"]["backend"]))
    require(
        claim.get("schema_version") == CLAIM_SCHEMA
        and claim.get("status")
        == "CLAIMED_SINGLE_ANALYSIS_ALLOWANCE_CONSUMED_NO_RETRY"
        and claim.get("execution_lock") == lock_id
        and claim.get("contract_sha256") == lock["contract_sha256"]
        and claim.get("automatic_retry_count") == 0
        and claim.get("replacement_analysis_permitted") is False
        and claim.get("planned_joint_arm_set") == expected_arms
        and claim.get("excluded_xfeat_disposition") == XFEAT_EXCLUSION_STATUS
        and claim.get("accuracy_computed_before_claim") is False,
        "ANALYSIS_CLAIM_CONTRACT",
    )
    recorded = receipt.get("artifacts_before_receipt")
    require(isinstance(recorded, dict), "ANALYSIS_RECEIPT_ARTIFACTS")
    live = output_tree_identities(
        OUTPUT_ROOT, advertised_root=OUTPUT_ROOT, exclude_receipt=True
    )
    require(recorded == live, "ANALYSIS_OUTPUT_DRIFT")
    tree = validate_output_allowlist(expected_arms)
    for required in (GRID_NAME, FORMAL_SUMMARY_NAME, REPEAT_TABLE_NAME):
        require(required in recorded, f"ANALYSIS_REQUIRED_ARTIFACT:{required}")

    grid, _ = stable_json(OUTPUT_ROOT / GRID_NAME)
    require(grid == exact_grid_evidence(), "ANALYSIS_EXACT_INTEGER_NS_GRID")
    formal, formal_id = stable_json(OUTPUT_ROOT / FORMAL_SUMMARY_NAME)
    require(recorded[FORMAL_SUMMARY_NAME] == formal_id,
            "FORMAL_SUMMARY_IDENTITY")
    require(formal.get("schema_version") == FORMAL_SCHEMA,
            "FORMAL_SUMMARY_SCHEMA")
    require(formal.get("terminal_receipt_required_for_interpretation") is True,
            "FORMAL_TERMINAL_RECEIPT_BOUNDARY")
    ranking = receipt.get("formal_ranking_available")
    require(isinstance(ranking, bool), "FORMAL_RANKING_BOOLEAN")
    require(formal.get("ranking_available") is ranking,
            "RECEIPT_FORMAL_RANKING_MISMATCH")
    require(receipt.get("formal_summary_status") == formal.get("status"),
            "RECEIPT_FORMAL_STATUS_MISMATCH")
    validate_formal_population_binding(formal, lock)
    with (OUTPUT_ROOT / REPEAT_TABLE_NAME).open(
        "r", newline="", encoding="utf-8"
    ) as handle:
        observed_repeat_csv = handle.read()
    require(observed_repeat_csv == repeat_table_csv_text(formal),
            "FORMAL_REPEAT_CSV_RECOMPUTATION")

    partial_manifest_present = PARTIAL_EVIDENCE_NAME in recorded
    external_partial_present = any(
        path.exists() or path.is_symlink()
        for path in (STAGING_ROOT, EVO_WORK_ROOT, FAILURE_STAGING_ROOT)
    )
    if partial_manifest_present:
        partial, _ = stable_json(OUTPUT_ROOT / PARTIAL_EVIDENCE_NAME)
        require(
            partial.get("status") == "PRESERVED_UNCOMMITTED_PARTIAL_EVIDENCE",
            "UNCOMMITTED_PARTIAL_MANIFEST_STATUS",
        )
        require(
            not FAILURE_STAGING_ROOT.exists() and not FAILURE_STAGING_ROOT.is_symlink(),
            "FAILURE_STAGING_MUST_BE_CONSUMED_BY_TERMINAL_COMMIT",
        )
        for label, path in (
            ("primary", STAGING_ROOT), ("evo", EVO_WORK_ROOT)
        ):
            require(
                (not path.exists() and not path.is_symlink())
                or (path.is_dir() and not path.is_symlink()),
                f"UNCOMMITTED_{label.upper()}_PARTIAL_KIND",
            )
        observed_primary_partial = (
            output_tree_identities(
                STAGING_ROOT,
                advertised_root=STAGING_ROOT,
                exclude_receipt=False,
            )
            if STAGING_ROOT.is_dir() and not STAGING_ROOT.is_symlink()
            else {}
        )
        observed_evo_partial = (
            output_tree_identities(
                EVO_WORK_ROOT,
                advertised_root=EVO_WORK_ROOT,
                exclude_receipt=False,
            )
            if EVO_WORK_ROOT.is_dir() and not EVO_WORK_ROOT.is_symlink()
            else {}
        )
        require(partial.get("tree") == observed_primary_partial,
                "UNCOMMITTED_PRIMARY_PARTIAL_DRIFT")
        require(partial.get("evo_work_tree") == observed_evo_partial,
                "UNCOMMITTED_EVO_PARTIAL_DRIFT")
    else:
        require(not external_partial_present, "UNBOUND_EXTERNAL_PARTIAL_STAGING")

    execution_integrity = receipt.get("execution_integrity")
    require(isinstance(execution_integrity, dict), "ANALYSIS_EXECUTION_INTEGRITY")
    authority_post = execution_integrity.get("authority_post")
    claim_stable = execution_integrity.get("claim_stable")
    recomputed_integrity_ok = bool(
        isinstance(authority_post, dict)
        and authority_post.get("status") == "PASS"
        and authority_post.get("lock") == lock_id
        and claim_stable is True
    )
    require(
        execution_integrity.get("status")
        == ("PASS" if recomputed_integrity_ok else "FAIL"),
        "ANALYSIS_EXECUTION_INTEGRITY_SELF_CONSISTENCY",
    )
    formal_integrity_gate = formal.get("execution_integrity_gate")
    require(isinstance(formal_integrity_gate, dict),
            "FORMAL_EXECUTION_INTEGRITY_GATE")
    require(
        formal_integrity_gate.get("status")
        == ("PASS" if recomputed_integrity_ok else "FAIL"),
        "RECEIPT_FORMAL_EXECUTION_INTEGRITY_MISMATCH",
    )
    primary: Optional[dict[str, Any]] = None
    recomputed: Optional[tuple[Any, Any, Any, Any, Any]] = None
    if RAW_SUMMARY_NAME in recorded:
        primary, primary_id = stable_json(OUTPUT_ROOT / RAW_SUMMARY_NAME)
        require(recorded[RAW_SUMMARY_NAME] == primary_id,
                "PRIMARY_SUMMARY_IDENTITY")
        protocol = primary.get("protocol")
        arms_block = primary.get("arms")
        require(
            isinstance(protocol, dict)
            and protocol.get("single_joint_mask") is True
            and protocol.get("joint_mask_population")
            == "reference_and_hfnet_and_all_accepted_klt_repeats"
            and protocol.get("xfeat_excluded_before_backend") is True
            and protocol.get("shared_full_precision_body_T_cam0")
            == str(SHARED_EXTRINSIC)
            and protocol.get("proper_fixed_scale_se3") is True
            and protocol.get("sim3") is False
            and protocol.get("reference_time_offset_s") == 0.0
            and protocol.get("all_arm_time_offsets_s") == 0.0,
            "PRIMARY_NUMERIC_PROTOCOL",
        )
        require(isinstance(arms_block, dict) and list(arms_block) == expected_arms,
                "PRIMARY_SINGLE_JOINT_ARM_SET")
        recomputed = evaluate_joint_inputs(lock)
        recomputed_primary, reference, recomputed_arms, evaluation, _ = recomputed
        require(primary == recomputed_primary, "PRIMARY_LOCKED_INPUT_RECOMPUTATION")
        require(
            RAW_DIAGNOSTIC_MANIFEST_NAME in recorded
            and GRID_AUDIT_NAME in recorded
            and RAW_METRICS_NAME in recorded,
            "PRIMARY_AUDIT_ARTIFACTS_REQUIRED",
        )
        boundary, _ = stable_json(OUTPUT_ROOT / RAW_DIAGNOSTIC_MANIFEST_NAME)
        require(
            boundary
            == {
                "schema_version": "aqua-fe-a08-raw-numeric-diagnostics-boundary-v2",
                "status": "DIAGNOSTIC_ONLY_NOT_FORMAL_RANKING",
                "artifacts": [RAW_SUMMARY_NAME, GRID_AUDIT_NAME, RAW_METRICS_NAME],
                "formal_ranking_authority": FORMAL_SUMMARY_NAME,
                "terminal_receipt_required": RECEIPT_NAME,
            },
            "RAW_DIAGNOSTIC_BOUNDARY_CONTRACT",
        )
        common.validate_grid_audit_file(
            OUTPUT_ROOT / GRID_AUDIT_NAME,
            reference,
            recomputed_arms,
            evaluation,
        )
        validate_primary_metrics_csv_file(
            OUTPUT_ROOT / RAW_METRICS_NAME, recomputed_primary
        )

    if ranking:
        require(receipt.get("status") == "PASS_FORMAL_HFNET_VS_KLT_RANKING_AVAILABLE",
                "RANKING_RECEIPT_STATUS")
        require(
            execution_integrity.get("status") == "PASS"
            and execution_integrity.get("claim_stable") is True
            and execution_integrity.get("authority_post", {}).get("status") == "PASS",
            "RANKING_EXECUTION_INTEGRITY",
        )
        require(primary is not None and recomputed is not None,
                "RANKING_PRIMARY_REQUIRED")
        require(EVO_SUMMARY_NAME in recorded, "RANKING_EVO_REQUIRED")
        evo, _ = stable_json(OUTPUT_ROOT / EVO_SUMMARY_NAME)
        evo_audit = common.validate_evo_crosscheck(
            evo,
            primary,
            expected_arms,
            lock["authority"]["evo"]["version"],
            tolerance_m=1e-5,
        )
        require(evo_audit["status"] == "PASS", "RANKING_EVO_REAUDIT")
        expected_formal = build_formal_summary(
            lock, primary, support_gate(primary), evo_audit
        )
        expected_formal["execution_integrity_gate"] = {
            "status": "PASS", "failure_codes": []
        }
        expected_formal["terminal_receipt_required_for_interpretation"] = True
        require(formal == expected_formal, "FORMAL_SUMMARY_RECOMPUTATION")
    else:
        require(
            receipt.get("status")
            == "TERMINAL_FORMAL_HFNET_VS_KLT_RANKING_NA_NO_RETRY",
            "NA_RECEIPT_STATUS",
        )
        require(formal_metrics_are_all_na(formal), "FORMAL_NA_INVARIANT")
        if execution_integrity.get("status") == "PASS" and primary is not None:
            gate = support_gate(primary)
            if EVO_SUMMARY_NAME in recorded:
                evo, _ = stable_json(OUTPUT_ROOT / EVO_SUMMARY_NAME)
                evo_audit = common.validate_evo_crosscheck(
                    evo,
                    primary,
                    expected_arms,
                    lock["authority"]["evo"]["version"],
                    tolerance_m=1e-5,
                )
            elif gate["status"] != "PASS":
                evo_audit = {
                    "status": "NOT_RUN_SUPPORT_GATE_CLOSED",
                    "failure_codes": ["SUPPORT_GATE_CLOSED_BEFORE_EVO"],
                    "tolerance_m": 1e-5,
                }
            else:
                require(lock["authority"]["backend"]["valid_count"] == 0,
                        "NA_EVO_MISSING_WITH_OPEN_GATES")
                evo_audit = {
                    "status": "NOT_RUN_POPULATION_GATE_CLOSED",
                    "failure_codes": ["KLT_HAS_ZERO_VALID_PLANNED_REPEATS"],
                    "tolerance_m": 1e-5,
                }
            expected_formal = build_formal_summary(lock, primary, gate, evo_audit)
            expected_formal["execution_integrity_gate"] = {
                "status": "PASS", "failure_codes": []
            }
            expected_formal["terminal_receipt_required_for_interpretation"] = True
            require(formal == expected_formal, "FORMAL_NA_SUMMARY_RECOMPUTATION")
        elif execution_integrity.get("status") == "PASS":
            errors = receipt.get("analysis_errors")
            require(isinstance(errors, list) and len(errors) == 1,
                    "ANALYSIS_ERROR_RECEIPT_BOUNDARY")
            expected_formal = build_error_formal_summary(lock, errors[0])
            expected_formal["execution_integrity_gate"] = {
                "status": "PASS", "failure_codes": []
            }
            expected_formal["terminal_receipt_required_for_interpretation"] = True
            require(formal == expected_formal, "ANALYSIS_ERROR_FORMAL_RECOMPUTATION")
        else:
            require(
                execution_integrity.get("claim_stable") is False
                or execution_integrity.get("authority_post", {}).get("status") == "FAIL",
                "INTEGRITY_FAILURE_DETAILS",
            )
    return {
        "status": "PASS_TERMINAL_EVIDENCE_DEEP_AUDIT",
        "receipt": receipt_id,
        "formal_ranking_available": ranking,
        "output_tree": tree,
        "claim": claim_id,
        "excluded_xfeat_disposition": XFEAT_EXCLUSION_STATUS,
    }


def audit_readonly(lock_path: Path = DEFAULT_LOCK) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "WAITING_ANALYSIS_LOCK",
        "read_only": True,
        "analysis_lock": "ABSENT",
        "analysis_output_state": analysis_output_state(),
        "excluded_xfeat_disposition": XFEAT_EXCLUSION_STATUS,
    }
    try:
        require_canonical_analysis_lock_path(lock_path)
    except AnalysisProtocolError as error:
        result.update({
            "status": "FAIL_READ_ONLY_AUDIT",
            "analysis_lock": "FAIL",
            "error": f"{type(error).__name__}:{error}",
        })
        return result
    if not lock_path.exists() and not lock_path.is_symlink():
        if result["analysis_output_state"] != "ABSENT":
            result.update({
                "status": "FAIL_READ_ONLY_AUDIT",
                "analysis_lock": "FAIL",
                "error": (
                    "AnalysisProtocolError:ANALYSIS_OUTPUT_WITHOUT_LOCK:"
                    + str(result["analysis_output_state"])
                ),
            })
        return result
    try:
        lock, lock_id = verify_lock(lock_path)
        state = analysis_output_state()
        require(
            state in {
                "ABSENT",
                "TERMINAL_RECEIPT_PRESENT",
                "TERMINAL_RECEIPT_PRESENT_WITH_UNCOMMITTED_PARTIAL",
            },
            f"AUDIT_INCOMPLETE_OR_INVALID_TERMINAL_STATE:{state}",
        )
        result.update({
            "status": "PASS_LOCK_AUTHORITY_NO_TERMINAL_YET",
            "analysis_lock": "PASS",
            "lock": lock_id,
            "contract_sha256": lock["contract_sha256"],
            "analysis_output_state": state,
        })
        if state in {
            "TERMINAL_RECEIPT_PRESENT",
            "TERMINAL_RECEIPT_PRESENT_WITH_UNCOMMITTED_PARTIAL",
        }:
            terminal = audit_terminal_semantics(lock, lock_id)
            result.update({
                "status": terminal["status"],
                "terminal_receipt": "PASS",
                **terminal,
            })
    except (AnalysisProtocolError, OSError, ValueError) as error:
        result.update({
            "status": "FAIL_READ_ONLY_AUDIT",
            "analysis_lock": "FAIL",
            "error": f"{type(error).__name__}:{error}",
        })
    return result


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
        return 0 if result["status"].startswith(("PASS_", "READY_")) else 2
    if args.command == "audit":
        result = audit_readonly(lock_path)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0 if result["status"].startswith("PASS_") else 2
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
    except (AnalysisProtocolError, OSError, ValueError) as error:
        print(f"A08_HFNET_KLT_V2_ERROR:{type(error).__name__}:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
