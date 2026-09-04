#!/usr/bin/env python3
"""Permanently gate-closed A08 three-arm common-support supervisor.

Importing this module is inert.  ``preflight`` and ``audit`` are read-only.
The XFeat frontend failed its frozen structural gate, so ``build-lock`` and
``run`` are permanently disabled.  The remaining helpers are retained for
process-free regression tests and for read-only forensic review only.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
from datetime import datetime, timezone
import hashlib
import io
import importlib.metadata
import importlib.util
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
SUPPORT_INPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/"
    "a08_hfnet_history_matched_support_extension_v1/evaluation_inputs"
)
SUPPORT_RECEIPT = SUPPORT_INPUT_ROOT / "support_preparation_receipt_v1.json"
REFERENCE_TUM = SUPPORT_INPUT_ROOT / "a08_reference_source_4000_4660.tum"
HFNET_TRAJECTORY = (
    SUPPORT_INPUT_ROOT / "hfnet_world_T_body_support_source_4000_4660.vio.csv"
)
SHARED_EXTRINSIC = SUPPORT_INPUT_ROOT / "hfnet_aqualoc_body_T_cam0.yaml"

CONTROL_EXPERIMENT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1"
)
BACKEND_ROOT = CONTROL_EXPERIMENT / "backend_replays_v1"
BACKEND_LOCK = (
    WORKSPACE
    / "papers/a08_recovered_july_history_matched_backend_replays_v1_execution_lock.json"
)
BACKEND_RUNNER = (
    WORKSPACE / "scripts/run_a08_recovered_july_history_matched_backend_replays_v1.py"
)
BACKEND_PROTOCOL = (
    WORKSPACE / "papers/a08_recovered_july_history_matched_backend_replays_v1_protocol.md"
)
XFEAT_FRONTEND_RECEIPT = (
    CONTROL_EXPERIMENT / "frontends_v1/xfeat_attempt002_export_receipt_v1.json"
)
OUTPUT_ROOT = CONTROL_EXPERIMENT / "joint_common_support_analysis_v1"
CLAIM_PATH = CONTROL_EXPERIMENT / "joint_common_support_analysis_start_claim_v1.json"
STAGING_ROOT = CONTROL_EXPERIMENT / ".joint_common_support_analysis_v1.staging"
FAILURE_STAGING_ROOT = (
    CONTROL_EXPERIMENT / ".joint_common_support_analysis_v1.failure_staging"
)

PROTOCOL = WORKSPACE / "papers/a08_recovered_july_joint_common_support_v1_protocol.md"
RUNNER = WORKSPACE / "scripts/run_a08_recovered_july_joint_common_support_v1.py"
TESTS = WORKSPACE / "scripts/tests/test_run_a08_recovered_july_joint_common_support_v1.py"
EVALUATOR = WORKSPACE / "scripts/evaluate_vins_common_support.py"
EVALUATOR_CORE = WORKSPACE / "scripts/trajectory_eval_core.py"
EPOCH_ADAPTER = WORKSPACE / "scripts/evaluate_vins_common_support_epoch_v2.py"
DESIGN_FREEZE = (
    WORKSPACE / "papers/a08_recovered_july_joint_common_support_v1_design_freeze_v2.json"
)
DEFAULT_LOCK = (
    WORKSPACE / "papers/a08_recovered_july_joint_common_support_v1_execution_lock.json"
)

ITEM_ORDER = tuple(
    item
    for repeat in range(1, 6)
    for item in (f"KLT_R{repeat:02d}", f"XFEAT_R{repeat:02d}")
)
START_NS = 1_542_885_161_111_831_216
END_NS = 1_542_885_194_106_222_672
GRID_STEP_NS = 1_000_000_000
GRID_COUNT = 33
GRID_NS = tuple(START_NS + index * GRID_STEP_NS for index in range(GRID_COUNT))

SUPPORT_RECEIPT_EXPECTED = (
    5_286,
    "2fa2150604e2b81ea93556b9c82f4a15ae394429cb7fc51c96d31977a37e37d3",
)
SUPPORT_ARTIFACT_EXPECTED = {
    "reference_tum": (
        REFERENCE_TUM,
        5_082,
        "25ccba084e5b5edd5651d24bec2bf753b119bc8de7174d36b870855680086682",
    ),
    "hfnet_world_T_body_vins_csv_bridge": (
        HFNET_TRAJECTORY,
        70_021,
        "be8a6bd278ad0222adeaf869a50c710d791c6eb5bee6db1afd57e1678ca9b04c",
    ),
    "hfnet_body_T_cam0_config": (
        SHARED_EXTRINSIC,
        415,
        "a76c728b31d47c3a87f54c465fb581007ed2da2b7d7d84df81dbde93e9a886c1",
    ),
}

SUPPORT_SCHEMA = "aqua-fe-a08-hfnet-history-matched-support-extension-preparation-v1"
BACKEND_LOCK_SCHEMA = "aqua-fe-a08-recovered-july-backend-execution-lock-v1"
BACKEND_RECEIPT_SCHEMA = "aqua-fe-a08-recovered-july-backend-replay-receipt-v1"
FRONTEND_RECEIPT_SCHEMA = (
    "aqua-fe-a08-recovered-july-natural-history-frontend-receipt-v1"
)
LOCK_SCHEMA = "aqua-fe-a08-recovered-july-joint-common-support-lock-v1"
CLAIM_SCHEMA = "aqua-fe-a08-recovered-july-joint-common-support-claim-v1"
RECEIPT_SCHEMA = "aqua-fe-a08-recovered-july-joint-common-support-receipt-v1"
DESIGN_FREEZE_SCHEMA = "aqua-fe-a08-recovered-july-joint-common-support-design-freeze-v2"
LOCK_STATUS = "FROZEN_AFTER_TEN_TERMINAL_REPLAYS_BEFORE_ACCURACY_VISIBLE"
BUILD_LOCK_TOKEN = "A08_BUILD_JOINT_COMMON_SUPPORT_LOCK_BEFORE_ACCURACY"
RUN_TOKEN = "A08_RUN_JOINT_COMMON_SUPPORT_EXACTLY_ONCE_NO_RETRY"
CAMPAIGN_PERMANENTLY_GATE_CLOSED = True
PERMANENT_GATE_STATUS = (
    "NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED"
)
PERMANENT_GATE_ERROR = (
    "THREE_ARM_CAMPAIGN_PERMANENTLY_GATE_CLOSED_XFEAT_STRUCTURAL_FAILURE"
)

CLAIM_NAME = "analysis_start_claim_v1.json"
GRID_NAME = "exact_integer_ns_grid_v1.json"
RAW_SUMMARY_NAME = "common_support_summary.json"
GRID_AUDIT_NAME = "common_grid_audit.csv"
RAW_METRICS_NAME = "common_support_metrics.csv"
RAW_DIAGNOSTIC_MANIFEST_NAME = "raw_numeric_diagnostics_boundary_v1.json"
REPEAT_TABLE_NAME = "planned_repeat_dispositions.csv"
FORMAL_SUMMARY_NAME = "formal_three_arm_summary_v1.json"
EVO_SUMMARY_NAME = "evo_crosscheck.json"
RECEIPT_NAME = "formal_analysis_receipt_v1.json"

PRIMARY_METRICS = (
    "ape_rmse_m",
    "ape_median_m",
    "ape_max_m",
    "rpe_rmse_m",
    "rpe_median_m",
    "rpe_max_m",
)


class AnalysisProtocolError(RuntimeError):
    """A frozen A08 analysis contract was not satisfied."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise AnalysisProtocolError(code)


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
        )
        + "\n"
    ).encode("utf-8")


def compact_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular_file(path: Path, label: str) -> None:
    require(path.is_absolute(), f"PATH_NOT_ABSOLUTE:{label}:{path}")
    require(path.exists() and not path.is_symlink(), f"FILE_MISSING_OR_SYMLINK:{label}:{path}")
    require(stat.S_ISREG(path.lstat().st_mode), f"FILE_NOT_REGULAR:{label}:{path}")


def identity(path: Path) -> dict[str, Any]:
    path = path.absolute()
    regular_file(path, "identity")
    before = path.stat()
    digest = sha256_file(path)
    after = path.stat()
    require(
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
        f"FILE_CHANGED_WHILE_HASHING:{path}",
    )
    return {"path": str(path), "size_bytes": after.st_size, "sha256": digest}


def stable_json(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    path = path.absolute()
    regular_file(path, "json")
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    require(
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
        f"JSON_CHANGED_WHILE_READING:{path}",
    )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise AnalysisProtocolError(f"INVALID_JSON:{path}:{error}") from error
    require(isinstance(value, dict), f"JSON_ROOT_NOT_OBJECT:{path}")
    return value, {
        "path": str(path),
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def validate_identity_claim(claim: Any, label: str) -> dict[str, Any]:
    require(isinstance(claim, dict), f"IDENTITY_TYPE:{label}")
    require(set(claim) == {"path", "size_bytes", "sha256"}, f"IDENTITY_KEYS:{label}")
    path = Path(str(claim.get("path", "")))
    require(path.is_absolute(), f"IDENTITY_PATH:{label}")
    require(isinstance(claim.get("size_bytes"), int), f"IDENTITY_SIZE:{label}")
    require(
        isinstance(claim.get("sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", claim["sha256"]) is not None,
        f"IDENTITY_SHA:{label}",
    )
    actual = identity(path)
    require(actual == claim, f"IDENTITY_DRIFT:{label}:{path}")
    return actual


def atomic_publish(path: Path, value: Any) -> None:
    path = path.absolute()
    require(not path.exists() and not path.is_symlink(), f"OUTPUT_ALREADY_EXISTS:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp.{os.getpid()}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(str(temporary), flags, 0o644)
    try:
        payload = canonical_bytes(value)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # ``os.replace`` would overwrite a competing owner that creates
        # ``path`` after the initial absence check.  A same-directory hard
        # link has true create-if-absent semantics: link(2) fails with EEXIST
        # and never replaces the competing file.
        os.link(temporary, path, follow_symlinks=False)
        temporary.unlink()
        directory_fd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def commit_directory_noreplace(staging: Path, destination: Path) -> None:
    """Atomically publish a complete terminal directory without replacement."""

    staging = staging.absolute()
    destination = destination.absolute()
    require(staging.parent == destination.parent, "TERMINAL_COMMIT_NOT_SAME_PARENT")
    require(staging.is_dir() and not staging.is_symlink(), "TERMINAL_STAGING_KIND")
    require(not destination.exists() and not destination.is_symlink(),
            "TERMINAL_DESTINATION_EXISTS")
    directory_fd = os.open(str(staging), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    require(renameat2 is not None, "RENAMEAT2_UNAVAILABLE")
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                          ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    at_fdcwd = -100
    rename_noreplace = 1
    result = renameat2(
        at_fdcwd,
        os.fsencode(staging),
        at_fdcwd,
        os.fsencode(destination),
        rename_noreplace,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), str(destination))
    parent_fd = os.open(str(destination.parent), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def exact_grid_evidence() -> dict[str, Any]:
    require(len(GRID_NS) == GRID_COUNT, "GRID_COUNT_INTERNAL")
    require(GRID_NS[0] == START_NS, "GRID_START_INTERNAL")
    require(all(right - left == GRID_STEP_NS for left, right in zip(GRID_NS, GRID_NS[1:])),
            "GRID_STEP_INTERNAL")
    require(GRID_NS[-1] <= END_NS < GRID_NS[-1] + GRID_STEP_NS,
            "GRID_END_BRACKET_INTERNAL")
    return {
        "schema_version": "aqua-fe-a08-exact-integer-ns-grid-v1",
        "window_start_ns": START_NS,
        "window_end_ns_inclusive": END_NS,
        "grid_step_ns": GRID_STEP_NS,
        "grid_count": GRID_COUNT,
        "grid_last_ns": GRID_NS[-1],
        "window_end_minus_grid_last_ns": END_NS - GRID_NS[-1],
        "timestamps_ns": list(GRID_NS),
        "float_serialization_is_not_timestamp_authority": True,
    }


def collect_support_binding() -> dict[str, Any]:
    receipt, receipt_id = stable_json(SUPPORT_RECEIPT)
    require(
        (receipt_id["size_bytes"], receipt_id["sha256"]) == SUPPORT_RECEIPT_EXPECTED,
        "SUPPORT_RECEIPT_FROZEN_IDENTITY",
    )
    require(receipt.get("schema_version") == SUPPORT_SCHEMA, "SUPPORT_RECEIPT_SCHEMA")
    require(
        receipt.get("status") == "PASS_SUPPORT_ONLY_PREPARATION_NO_ACCURACY",
        "SUPPORT_RECEIPT_STATUS",
    )
    require(receipt.get("fixed_one_hz_grid_point_count") == GRID_COUNT,
            "SUPPORT_GRID_COUNT")
    support = receipt.get("support")
    require(isinstance(support, dict), "SUPPORT_BLOCK")
    require(
        support.get("extension_source_indices_inclusive") == [4000, 4660]
        and support.get("extension_pose_count") == 661
        and support.get("extension_exact_contiguous") is True,
        "SUPPORT_EXTENSION_CONTRACT",
    )
    boundary = receipt.get("claim_boundary")
    require(
        isinstance(boundary, dict)
        and boundary.get("ape_or_rpe_computed") is False
        and boundary.get("fitted_time_offset") is False
        and boundary.get("hfnet_pose_semantics") == "world_T_body"
        and boundary.get("identity_extrinsic_used") is False,
        "SUPPORT_CLAIM_BOUNDARY",
    )
    artifacts = receipt.get("artifacts")
    require(isinstance(artifacts, dict), "SUPPORT_ARTIFACTS")
    bound: dict[str, Any] = {}
    for name, (expected_path, expected_size, expected_sha) in SUPPORT_ARTIFACT_EXPECTED.items():
        claim = artifacts.get(name)
        require(
            isinstance(claim, dict)
            and claim.get("path") == str(expected_path)
            and claim.get("size_bytes") == expected_size
            and claim.get("sha256") == expected_sha,
            f"SUPPORT_ARTIFACT_CLAIM:{name}",
        )
        bound[name] = validate_identity_claim(claim, f"support:{name}")
    return {
        "receipt": receipt_id,
        "artifacts": bound,
        "trajectory_convention": "world_T_body",
        "shared_body_T_cam0_for_every_arm": bound["hfnet_body_T_cam0_config"],
    }


def validate_backend_lock_contract(value: Mapping[str, Any]) -> None:
    require(value.get("schema_version") == BACKEND_LOCK_SCHEMA, "BACKEND_LOCK_SCHEMA")
    require(
        value.get("status") == "FROZEN_AFTER_BOTH_ACCEPTED_FRONTENDS_BEFORE_BACKEND_LAUNCH",
        "BACKEND_LOCK_STATUS",
    )
    require(value.get("item_order") == list(ITEM_ORDER), "BACKEND_ITEM_ORDER")
    contract_digest = value.get("contract_sha256")
    require(
        isinstance(contract_digest, str)
        and re.fullmatch(r"[0-9a-f]{64}", contract_digest) is not None,
        "BACKEND_CONTRACT_SHA",
    )
    unsigned = dict(value)
    unsigned.pop("contract_sha256", None)
    require(compact_sha256(unsigned) == contract_digest, "BACKEND_CONTRACT_DIGEST")


def load_backend_authority_module() -> Any:
    specification = importlib.util.spec_from_file_location(
        "a08_locked_backend_replay_authority", BACKEND_RUNNER
    )
    require(
        specification is not None and specification.loader is not None,
        "BACKEND_AUTHORITY_IMPORT_SPEC",
    )
    module = importlib.util.module_from_spec(specification)
    sys.modules["a08_locked_backend_replay_authority"] = module
    specification.loader.exec_module(module)
    return module


def classify_xfeat_profile(receipt: Mapping[str, Any]) -> dict[str, Any]:
    require(receipt.get("schema_version") == FRONTEND_RECEIPT_SCHEMA,
            "XFEAT_FRONTEND_SCHEMA")
    require(receipt.get("status") == "PASS_FRONTEND_EXPORT_ACCEPTED",
            "XFEAT_FRONTEND_STATUS")
    require(receipt.get("stage") == "xfeat", "XFEAT_FRONTEND_STAGE")
    audit = receipt.get("artifact_audit")
    require(isinstance(audit, dict), "XFEAT_AUDIT")
    final = audit.get("final")
    require(isinstance(final, dict), "XFEAT_FINAL_AUDIT")
    arbitration = final.get("arbitration")
    action = final.get("method_native_action")
    require(isinstance(arbitration, dict), "XFEAT_ARBITRATION")
    require(isinstance(action, dict), "XFEAT_METHOD_NATIVE_ACTION")
    profile = arbitration.get("profile")
    require(isinstance(profile, str) and profile, "XFEAT_PROFILE")
    learned = action.get("exported_learned_full")
    xfeat = action.get("exported_xfeat_full")
    require(isinstance(learned, int) and learned >= 0, "XFEAT_LEARNED_COUNT")
    require(isinstance(xfeat, int) and xfeat >= 0, "XFEAT_SOURCE_COUNT")
    require(learned == xfeat, "XFEAT_ACTION_COUNT_MISMATCH")
    fallback = profile == "klt_safe_fallback"
    if fallback:
        require(learned == 0, "XFEAT_FALLBACK_EXPORTED_LEARNED")
    return {
        "profile": profile,
        "label": (
            "XFeat arbitration system — method-native KLT safe fallback"
            if fallback
            else f"XFeat arbitration system — method-native profile {profile}"
        ),
        "method_native_klt_safe_fallback": fallback,
        "exported_learned_observations": learned,
        "learning_contribution_claim_permitted": bool(not fallback and learned > 0),
    }


def validate_terminal_receipt(
    item_id: str,
    receipt: Mapping[str, Any],
    backend_lock_identity: Mapping[str, Any],
    locked_item: Mapping[str, Any],
) -> dict[str, Any]:
    expected_arm = "klt" if item_id.startswith("KLT_") else "xfeat"
    expected_repeat = int(item_id[-2:])
    require(receipt.get("schema_version") == BACKEND_RECEIPT_SCHEMA,
            f"BACKEND_RECEIPT_SCHEMA:{item_id}")
    disposition = receipt.get("status")
    require(
        disposition
        in {"PASS_BACKEND_REPLAY_ACCEPTED", "FAILED_BACKEND_REPLAY_NO_REPLACEMENT"},
        f"BACKEND_RECEIPT_DISPOSITION:{item_id}",
    )
    require(
        receipt.get("item_id") == item_id
        and receipt.get("arm") == expected_arm
        and receipt.get("repeat_index") == expected_repeat,
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
        and locked_item.get("arm") == expected_arm
        and locked_item.get("repeat_index") == expected_repeat,
        f"BACKEND_LOCKED_ITEM:{item_id}",
    )
    artifact = receipt.get("artifact_contract")
    require(isinstance(artifact, dict), f"BACKEND_ARTIFACT_CONTRACT:{item_id}")
    require(
        artifact.get("evidence_tree_integrity") is True
        and artifact.get("integrity_issues") == [],
        f"BACKEND_ARTIFACT_INTEGRITY:{item_id}",
    )
    runtime = receipt.get("runtime")
    process_group = runtime.get("process_group") if isinstance(runtime, dict) else None
    require(
        isinstance(runtime, dict)
        and runtime.get("popen_invocation_count") == 1
        and runtime.get("child_started") is True
        and isinstance(process_group, dict)
        and process_group.get("leader_reaped") is True
        and process_group.get("process_group_empty") is True
        and process_group.get("owned_descendants_empty") is True,
        f"BACKEND_RUNTIME_INTEGRITY:{item_id}",
    )
    expected_output = BACKEND_ROOT / item_id
    durable: dict[str, Any] = {}
    for label in ("claim", "process_log"):
        claim = receipt.get(label)
        require(isinstance(claim, dict), f"BACKEND_DURABLE_IDENTITY:{item_id}:{label}")
        path = Path(str(claim.get("path", "")))
        require(
            path.parent == expected_output,
            f"BACKEND_DURABLE_PATH:{item_id}:{label}",
        )
        durable[label] = validate_identity_claim(claim, f"{item_id}:{label}")
    recorded_outputs = artifact.get("outputs")
    require(isinstance(recorded_outputs, dict), f"BACKEND_RECORDED_OUTPUTS:{item_id}")
    durable_outputs: dict[str, Any] = {}
    for relative, claim in recorded_outputs.items():
        require(
            isinstance(relative, str)
            and relative
            and not relative.startswith("/")
            and ".." not in Path(relative).parts,
            f"BACKEND_OUTPUT_RELATIVE_PATH:{item_id}:{relative}",
        )
        require(
            isinstance(claim, dict)
            and claim.get("path") == str(expected_output / relative),
            f"BACKEND_OUTPUT_PATH:{item_id}:{relative}",
        )
        durable_outputs[relative] = validate_identity_claim(
            claim, f"{item_id}:output:{relative}"
        )
    require(
        {
            "network_namespace_manifest.json",
            "replay_only_guard_manifest.json",
        }
        <= set(durable_outputs),
        f"BACKEND_BOUNDARY_MANIFESTS:{item_id}",
    )
    accepted = disposition == "PASS_BACKEND_REPLAY_ACCEPTED"
    trajectory: Optional[dict[str, Any]] = None
    if accepted:
        require(artifact.get("status") == "PASS", f"ACCEPTED_ARTIFACT_STATUS:{item_id}")
        claim = durable_outputs.get("vins_output/vio.csv")
        expected_path = BACKEND_ROOT / item_id / "vins_output/vio.csv"
        require(
            isinstance(claim, dict) and claim.get("path") == str(expected_path),
            f"ACCEPTED_TRAJECTORY_PATH:{item_id}",
        )
        trajectory = validate_identity_claim(claim, f"trajectory:{item_id}")
    return {
        "item_id": item_id,
        "arm": expected_arm,
        "repeat_index": expected_repeat,
        "disposition": disposition,
        "accepted_for_joint_mask": accepted,
        "trajectory": trajectory,
        "durable_backend_evidence": durable,
        "recorded_backend_outputs": durable_outputs,
        "planned_failure_is_na_not_replaced": not accepted,
    }


def collect_backend_binding() -> dict[str, Any]:
    lock, lock_id = stable_json(BACKEND_LOCK)
    validate_backend_lock_contract(lock)
    static_claims = lock.get("static_identities")
    require(isinstance(static_claims, dict), "BACKEND_STATIC_IDENTITIES")
    require(
        static_claims.get("runner") == identity(BACKEND_RUNNER),
        "BACKEND_RUNNER_IDENTITY",
    )
    require(
        static_claims.get("protocol") == identity(BACKEND_PROTOCOL),
        "BACKEND_PROTOCOL_IDENTITY",
    )
    backend_authority = load_backend_authority_module()
    live_frontend_bindings = backend_authority.resolve_frontend_bindings()
    deeply_verified_lock, deeply_verified_lock_id = backend_authority.verify_lock(
        BACKEND_LOCK, live_frontend_bindings
    )
    require(
        deeply_verified_lock == lock and deeply_verified_lock_id == lock_id,
        "BACKEND_DEEP_LOCK_AUTHORITY",
    )
    locked_items = lock.get("items")
    require(isinstance(locked_items, dict), "BACKEND_LOCK_ITEMS")
    rows: list[dict[str, Any]] = []
    receipt_ids: dict[str, Any] = {}
    for item_id in ITEM_ORDER:
        receipt_path = BACKEND_ROOT / item_id / "formal_run_receipt_v1.json"
        receipt, receipt_id = stable_json(receipt_path)
        deeply_verified_receipt = backend_authority.prior_receipt(
            lock_id, locked_items.get(item_id, {})
        )
        require(
            deeply_verified_receipt == receipt,
            f"BACKEND_DEEP_TERMINAL_RECEIPT:{item_id}",
        )
        row = validate_terminal_receipt(
            item_id, receipt, lock_id, locked_items.get(item_id, {})
        )
        row["receipt"] = receipt_id
        rows.append(row)
        receipt_ids[item_id] = receipt_id

    frontend_bindings = lock.get("frontend_bindings")
    require(isinstance(frontend_bindings, dict), "BACKEND_FRONTEND_BINDINGS")
    xfeat_binding = frontend_bindings.get("xfeat")
    require(isinstance(xfeat_binding, dict), "BACKEND_XFEAT_BINDING")
    claimed_frontend_receipt = xfeat_binding.get("receipt")
    xfeat_frontend, xfeat_frontend_id = stable_json(XFEAT_FRONTEND_RECEIPT)
    require(claimed_frontend_receipt == xfeat_frontend_id,
            "BACKEND_XFEAT_FRONTEND_RECEIPT_BINDING")
    xfeat_method = classify_xfeat_profile(xfeat_frontend)
    return {
        "execution_lock": lock_id,
        "execution_contract_sha256": lock["contract_sha256"],
        "terminal_receipts": receipt_ids,
        "planned_repeats": rows,
        "valid_counts": {
            arm: sum(
                row["accepted_for_joint_mask"] and row["arm"] == arm for row in rows
            )
            for arm in ("klt", "xfeat")
        },
        "xfeat_frontend_receipt": xfeat_frontend_id,
        "xfeat_method_native_label": xfeat_method,
    }


def collect_evo_authority() -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for name in ("evo_ape", "evo_rpe"):
        raw = shutil.which(name)
        require(raw is not None, f"EVO_ENTRYPOINT_MISSING:{name}")
        path = Path(raw).absolute()
        resolved[name] = identity(path)
    try:
        version = importlib.metadata.version("evo")
    except importlib.metadata.PackageNotFoundError as error:
        raise AnalysisProtocolError("EVO_DISTRIBUTION_MISSING") from error
    require(re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", version) is not None,
            "EVO_VERSION_FORMAT")
    return {"distribution": "evo", "version": version, "entrypoints": resolved}


def collect_static_identities() -> dict[str, Any]:
    return {
        "runner": identity(RUNNER),
        "protocol": identity(PROTOCOL),
        "process_free_tests": identity(TESTS),
        "primary_evaluator": identity(EVALUATOR),
        "trajectory_eval_core": identity(EVALUATOR_CORE),
        "epoch_nanosecond_adapter": identity(EPOCH_ADAPTER),
        "backend_replay_authority_runner": identity(BACKEND_RUNNER),
        "backend_replay_protocol": identity(BACKEND_PROTOCOL),
    }


def design_contract_snapshot() -> dict[str, Any]:
    """Return the result-independent rules sealed before backend outcomes."""

    return {
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
            "fixed_denominator": GRID_COUNT,
            "min_common_coverage": 0.70,
            "min_rpe_pairs": 10,
            "proper_fixed_scale_se3": True,
            "sim3_or_scale_fit": False,
            "shared_full_precision_body_T_cam0_for_every_arm": True,
            "single_joint_mask_across_hfnet_and_all_accepted_repeats": True,
            "evo_abs_tolerance_m": 1e-5,
            "evo_differences_recomputed_from_actual_metrics": True,
            "evo_segment_pair_counts_and_weighted_rpe_recomputed": True,
        },
        "failure_and_summary_rules": {
            "backend_integrity_failure_blocks": True,
            "scientific_failure_is_planned_repeat_na": True,
            "failed_repeat_replacement_permitted": False,
            "planned_count_per_control_arm": 5,
            "arm_summary_is_median_over_all_valid_planned_repeats": True,
            "best_run_selection_permitted": False,
            "any_formal_gate_or_integrity_failure_sets_all_ranking_metrics_na": True,
            "xfeat_klt_safe_fallback_is_learning_contribution": False,
            "technical_repeats_are_independent_samples": False,
            "six_primary_metrics_must_be_finite_nonnegative": True,
            "raw_numeric_outputs_are_diagnostic_only": True,
        },
        "execution_rules": {
            "final_dynamic_lock_required": True,
            "single_analysis_allowance": True,
            "automatic_retry_count": 0,
            "accuracy_before_final_dynamic_lock_permitted": False,
            "post_claim_actions_inside_terminalization_boundary": True,
            "incomplete_consumed_state_is_pass": False,
            "read_only_audit_recomputes_primary_from_locked_inputs": True,
        },
    }


def collect_design_freeze_binding(
    static_identities: Mapping[str, Any], evo_authority: Mapping[str, Any]
) -> dict[str, Any]:
    value, freeze_identity = stable_json(DESIGN_FREEZE)
    require(value.get("schema_version") == DESIGN_FREEZE_SCHEMA,
            "DESIGN_FREEZE_SCHEMA")
    require(
        value.get("status")
        == "FROZEN_BEFORE_BACKEND_TERMINAL_RESULTS_AND_BEFORE_ACCURACY",
        "DESIGN_FREEZE_STATUS",
    )
    require(value.get("static_identities") == dict(static_identities),
            "DESIGN_FREEZE_STATIC_IDENTITIES")
    require(value.get("evo_authority") == dict(evo_authority),
            "DESIGN_FREEZE_EVO_AUTHORITY")
    require(value.get("design_contract") == design_contract_snapshot(),
            "DESIGN_FREEZE_CONTRACT")
    boundary = value.get("claim_boundary")
    require(
        isinstance(boundary, dict)
        and boundary.get("ape_or_rpe_computed") is False
        and boundary.get("backend_terminal_receipts_opened") is False
        and boundary.get("final_dynamic_analysis_lock_built") is False
        and boundary.get("ros_or_vins_started") is False,
        "DESIGN_FREEZE_CLAIM_BOUNDARY",
    )
    return {"identity": freeze_identity, "created_at_utc": value.get("created_at_utc")}


def collect_authority() -> dict[str, Any]:
    static_identities = collect_static_identities()
    evo_authority = collect_evo_authority()
    return {
        "support": collect_support_binding(),
        "backend": collect_backend_binding(),
        "static_identities": static_identities,
        "evo": evo_authority,
        "design_freeze": collect_design_freeze_binding(
            static_identities, evo_authority
        ),
    }


def contract_core(authority: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": LOCK_SCHEMA,
        "status": LOCK_STATUS,
        "campaign": "A08_RECOVERED_JULY_JOINT_COMMON_SUPPORT_V1",
        "authority": dict(authority),
        "grid": exact_grid_evidence(),
        "evaluation_contract": {
            "reference_rate_hz": 1.0,
            "estimate_rate_hz": 10.0,
            "evaluation_rate_hz": 1.0,
            "max_reference_gap_s": 2.5,
            "max_estimate_gap_s": 0.25,
            "all_time_offsets_s": 0.0,
            "rpe_delta_s": 1.0,
            "min_ape_poses": 30,
            "min_ape_span_s": 10.0,
            "fixed_denominator": GRID_COUNT,
            "min_common_coverage": 0.70,
            "min_rpe_pairs": 10,
            "single_joint_mask_across_hfnet_and_all_accepted_repeats": True,
            "body_to_camera": "world_T_body * shared_body_T_cam0",
            "alignment": "proper fixed-scale SE3",
            "sim3_or_scale_fit": False,
            "fitted_time_offset": False,
            "evo_abs_tolerance_m": 1e-5,
        },
        "population_policy": {
            "item_order": list(ITEM_ORDER),
            "planned_count_per_control_arm": 5,
            "accepted_disposition_only": "PASS_BACKEND_REPLAY_ACCEPTED",
            "scientific_failure_is_na": True,
            "failed_repeat_replacement_permitted": False,
            "arm_summary": "median_over_all_valid_planned_repeats",
            "best_run_selection_permitted": False,
            "technical_repeats_are_independent_samples": False,
        },
        "execution_policy": {
            "single_analysis_allowance": True,
            "automatic_retry_count": 0,
            "ranking_gate_failure_sets_all_formal_metrics_na": True,
        },
    }


def build_lock_payload(authority: Mapping[str, Any], created_at_utc: str) -> dict[str, Any]:
    payload = {**contract_core(authority), "created_at_utc": created_at_utc}
    payload["contract_sha256"] = compact_sha256(payload)
    return payload


def verify_lock(lock_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    lock, lock_id = stable_json(lock_path)
    created = lock.get("created_at_utc")
    require(isinstance(created, str) and created, "ANALYSIS_LOCK_CREATED")
    expected = build_lock_payload(collect_authority(), created)
    require(lock == expected, "ANALYSIS_LOCK_AUTHORITY_DRIFT")
    return lock, lock_id


def required_terminal_presence() -> dict[str, str]:
    result: dict[str, str] = {}
    paths = {"backend_lock": BACKEND_LOCK, **{
        item: BACKEND_ROOT / item / "formal_run_receipt_v1.json" for item in ITEM_ORDER
    }}
    for name, path in paths.items():
        if not path.exists() and not path.is_symlink():
            result[name] = "MISSING"
        elif path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
            result[name] = "INVALID_KIND"
        else:
            result[name] = "PRESENT_REGULAR"
    return result


def analysis_output_state() -> str:
    output_present = OUTPUT_ROOT.exists() or OUTPUT_ROOT.is_symlink()
    claim_present = CLAIM_PATH.exists() or CLAIM_PATH.is_symlink()
    staging_present = STAGING_ROOT.exists() or STAGING_ROOT.is_symlink()
    failure_staging_present = (
        FAILURE_STAGING_ROOT.exists() or FAILURE_STAGING_ROOT.is_symlink()
    )
    if output_present:
        if OUTPUT_ROOT.is_symlink() or not OUTPUT_ROOT.is_dir():
            return "INVALID_TERMINAL_KIND"
        if not claim_present:
            return "TERMINAL_WITHOUT_START_CLAIM"
        if (OUTPUT_ROOT / RECEIPT_NAME).is_file() and not (
            OUTPUT_ROOT / RECEIPT_NAME
        ).is_symlink():
            return "TERMINAL_RECEIPT_PRESENT"
        return "TERMINAL_DIRECTORY_WITHOUT_RECEIPT"
    if claim_present:
        if CLAIM_PATH.is_symlink() or not stat.S_ISREG(CLAIM_PATH.lstat().st_mode):
            return "INVALID_CLAIM_KIND"
        return "CLAIMED_WITHOUT_TERMINAL_RECEIPT"
    if staging_present or failure_staging_present:
        return "UNCLAIMED_STAGING_PRESENT"
    return "ABSENT"


def design_freeze_audit_readonly() -> dict[str, Any]:
    try:
        static_identities = collect_static_identities()
        evo_authority = collect_evo_authority()
        binding = collect_design_freeze_binding(static_identities, evo_authority)
        return {
            "status": "PASS_DESIGN_FROZEN_BEFORE_DYNAMIC_RESULTS",
            "read_only": True,
            "design_freeze": binding,
            "accuracy_computed": False,
        }
    except (AnalysisProtocolError, OSError, ValueError) as error:
        return {
            "status": "BLOCKED_DESIGN_FREEZE",
            "read_only": True,
            "error": f"{type(error).__name__}:{error}",
            "accuracy_computed": False,
        }


def preflight_readonly(lock_path: Path = DEFAULT_LOCK) -> dict[str, Any]:
    if CAMPAIGN_PERMANENTLY_GATE_CLOSED:
        return {
            "status": "BLOCKED_THREE_ARM_CAMPAIGN_PERMANENTLY_GATE_CLOSED",
            "read_only": True,
            "reason": PERMANENT_GATE_ERROR,
            "xfeat_disposition": PERMANENT_GATE_STATUS,
            "analysis_lock_creation_permitted": False,
            "analysis_execution_permitted": False,
            "accuracy_computed": False,
        }
    design_audit = design_freeze_audit_readonly()
    if design_audit["status"] != "PASS_DESIGN_FROZEN_BEFORE_DYNAMIC_RESULTS":
        return {
            "status": "BLOCKED_DESIGN_FREEZE",
            "read_only": True,
            "design_freeze_audit": design_audit,
            "accuracy_computed": False,
        }
    presence = required_terminal_presence()
    unavailable = [name for name, state in presence.items() if state != "PRESENT_REGULAR"]
    if unavailable:
        return {
            "status": "WAITING_FOR_BACKEND_FINAL_LOCK_AND_TEN_TERMINAL_RECEIPTS",
            "read_only": True,
            "terminal_presence": presence,
            "unavailable": unavailable,
            "accuracy_computed": False,
            "analysis_lock_present": lock_path.exists() or lock_path.is_symlink(),
            "design_freeze_audit": design_audit,
        }
    try:
        if not lock_path.exists() and not lock_path.is_symlink():
            require(analysis_output_state() == "ABSENT", "ANALYSIS_OUTPUT_PREEXISTS")
            authority = collect_authority()
            return {
                "status": "READY_TO_BUILD_ANALYSIS_LOCK_NO_ACCURACY_COMPUTED",
                "read_only": True,
                "terminal_presence": presence,
                "valid_counts": authority["backend"]["valid_counts"],
                "xfeat_method_native_label": authority["backend"]["xfeat_method_native_label"],
                "candidate_contract_sha256": compact_sha256(contract_core(authority)),
                "accuracy_computed": False,
                "design_freeze_audit": design_audit,
            }
        lock, lock_id = verify_lock(lock_path)
        output_state = analysis_output_state()
        require(
            output_state in {"ABSENT", "TERMINAL_RECEIPT_PRESENT"},
            f"ANALYSIS_ALLOWANCE_CONSUMED_WITHOUT_VALID_TERMINAL:{output_state}",
        )
        return {
            "status": (
                "PASS_LOCKED_READY_FOR_ONE_ANALYSIS"
                if output_state == "ABSENT"
                else "PASS_LOCKED_TERMINAL_RECEIPT_PRESENT_AUDIT_REQUIRED"
            ),
            "read_only": True,
            "lock": lock_id,
            "contract_sha256": lock["contract_sha256"],
            "analysis_output_state": output_state,
            "design_freeze_audit": design_audit,
        }
    except (AnalysisProtocolError, OSError, ValueError) as error:
        return {
            "status": "BLOCKED_PREFLIGHT",
            "read_only": True,
            "terminal_presence": presence,
            "error": f"{type(error).__name__}:{error}",
            "accuracy_computed": False,
            "design_freeze_audit": design_audit,
        }


def _load_numeric_modules() -> tuple[Any, Any]:
    core_spec = importlib.util.spec_from_file_location(
        "trajectory_eval_core", EVALUATOR_CORE
    )
    require(core_spec is not None and core_spec.loader is not None, "CORE_IMPORT_SPEC")
    core = importlib.util.module_from_spec(core_spec)
    sys.modules["trajectory_eval_core"] = core
    core_spec.loader.exec_module(core)
    evaluator_spec = importlib.util.spec_from_file_location(
        "a08_locked_common_support_evaluator", EVALUATOR
    )
    require(
        evaluator_spec is not None and evaluator_spec.loader is not None,
        "EVALUATOR_IMPORT_SPEC",
    )
    evaluator = importlib.util.module_from_spec(evaluator_spec)
    sys.modules["a08_locked_common_support_evaluator"] = evaluator
    evaluator_spec.loader.exec_module(evaluator)
    return evaluator, core


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


def evaluate_joint_inputs(lock: Mapping[str, Any]) -> tuple[dict[str, Any], Any, Any, dict[str, Any], dict[str, Any]]:
    evaluator, core = _load_numeric_modules()
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
        "contrast_name": "A08_HFNET_KLT_XFEAT_JOINT_COMMON_SUPPORT_V1",
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
    support = summary.get("support")
    require(isinstance(support, dict), "PRIMARY_SUPPORT_BLOCK")
    checks = {
        "grid_count_exactly_33": support.get("grid_count") == GRID_COUNT,
        "matched_at_least_30": isinstance(support.get("matched_count"), int)
        and support["matched_count"] >= 30,
        "common_span_at_least_10s": isinstance(support.get("common_span_s"), (int, float))
        and support["common_span_s"] >= 10.0,
        "fixed_denominator_coverage_at_least_0_70": isinstance(
            support.get("matched_count"), int
        ) and support["matched_count"] / GRID_COUNT >= 0.70,
        "exact_1s_rpe_pairs_at_least_10": isinstance(support.get("rpe_pairs"), int)
        and support["rpe_pairs"] >= 10,
        "primary_ape_gate": support.get("ape_valid") is True,
        "primary_rpe_gate": support.get("rpe_valid") is True,
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {"status": "PASS" if not failures else "FAIL", "checks": checks,
            "failure_codes": failures, "fixed_denominator": GRID_COUNT}


def validate_evo_crosscheck(
    evo_summary: Mapping[str, Any],
    primary_summary: Mapping[str, Any],
    expected_arms: Sequence[str],
    expected_version: str,
    tolerance_m: float = 1e-5,
) -> dict[str, Any]:
    failures: list[str] = []
    if evo_summary.get("evo_version") != expected_version:
        failures.append("EVO_VERSION")
    if evo_summary.get("rpe_delta_frames") != 1:
        failures.append("EVO_RPE_DELTA_FRAMES")
    if evo_summary.get("rpe_semantics") != "aligned_global_frame_positional_delta":
        failures.append("EVO_RPE_SEMANTICS")
    arms = evo_summary.get("arms")
    if not isinstance(arms, dict) or set(arms) != set(expected_arms):
        failures.append("EVO_ARM_SET")
        arms = arms if isinstance(arms, dict) else {}
    primary_arms = primary_summary.get("arms")
    primary_support = primary_summary.get("support")
    expected_pairs = (
        primary_support.get("rpe_pairs") if isinstance(primary_support, dict) else None
    )
    details: dict[str, Any] = {}
    for name in expected_arms:
        row = arms.get(name)
        primary = primary_arms.get(name) if isinstance(primary_arms, dict) else None
        checks = {
            "row_present": isinstance(row, dict),
            "primary_present": isinstance(primary, dict),
        }
        if isinstance(row, dict) and isinstance(primary, dict):
            def number(mapping: Mapping[str, Any], key: str) -> float:
                value = mapping.get(key)
                return (
                    float(value)
                    if isinstance(value, (int, float))
                    and math.isfinite(float(value))
                    and float(value) >= 0.0
                    else math.nan
                )

            primary_ape = number(primary, "ape_rmse_m")
            primary_rpe = number(primary, "rpe_rmse_m")
            echoed_ape = number(row, "primary_ape_rmse_m")
            echoed_rpe = number(row, "primary_rpe_rmse_m")
            evo_ape = number(row, "evo_ape_rmse_m")
            evo_rpe = number(row, "evo_segmented_rpe_rmse_m")
            reported_ape_diff = number(row, "ape_abs_diff_m")
            reported_rpe_diff = number(row, "rpe_abs_diff_m")
            recomputed_ape_diff = abs(primary_ape - evo_ape)
            recomputed_rpe_diff = abs(primary_rpe - evo_rpe)
            segments = row.get("segments")
            segment_rows = segments if isinstance(segments, list) else []
            segment_contract = bool(segment_rows)
            segment_pair_sum = 0
            weighted_squared = 0.0
            for segment in segment_rows:
                if not isinstance(segment, dict):
                    segment_contract = False
                    continue
                pair_count = segment.get("pair_count")
                rmse = segment.get("rmse_m")
                if not (
                    isinstance(segment.get("segment_id"), int)
                    and isinstance(pair_count, int)
                    and pair_count > 0
                    and isinstance(rmse, (int, float))
                    and math.isfinite(float(rmse))
                    and float(rmse) >= 0.0
                ):
                    segment_contract = False
                    continue
                segment_pair_sum += pair_count
                weighted_squared += pair_count * float(rmse) ** 2
            recomputed_segmented_rpe = (
                math.sqrt(weighted_squared / segment_pair_sum)
                if segment_pair_sum > 0
                else math.nan
            )
            checks.update({
                "pair_count": row.get("rpe_pair_count") == expected_pairs,
                "primary_ape_finite_nonnegative": math.isfinite(primary_ape),
                "primary_rpe_finite_nonnegative": math.isfinite(primary_rpe),
                "evo_ape_finite_nonnegative": math.isfinite(evo_ape),
                "evo_rpe_finite_nonnegative": math.isfinite(evo_rpe),
                "primary_ape_echo": math.isclose(
                    echoed_ape, primary_ape, rel_tol=0.0, abs_tol=1e-12
                ),
                "primary_rpe_echo": math.isclose(
                    echoed_rpe, primary_rpe, rel_tol=0.0, abs_tol=1e-12
                ),
                "ape_reported_diff_matches_actual": math.isclose(
                    reported_ape_diff,
                    recomputed_ape_diff,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                ),
                "rpe_reported_diff_matches_actual": math.isclose(
                    reported_rpe_diff,
                    recomputed_rpe_diff,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                ),
                "ape_diff_within_tolerance": math.isfinite(recomputed_ape_diff)
                and recomputed_ape_diff <= tolerance_m,
                "rpe_diff_within_tolerance": math.isfinite(recomputed_rpe_diff)
                and recomputed_rpe_diff <= tolerance_m,
                "segment_contract": segment_contract,
                "segment_pair_sum": segment_pair_sum == expected_pairs,
                "segmented_rpe_recomputed": math.isclose(
                    recomputed_segmented_rpe,
                    evo_rpe,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                ),
            })
        failed_checks = [key for key, passed in checks.items() if not passed]
        if failed_checks:
            failures.extend(f"{name}:{code}" for code in failed_checks)
        details[name] = checks
    return {
        "status": "PASS" if not failures else "FAIL",
        "tolerance_m": tolerance_m,
        "expected_evo_version": expected_version,
        "expected_arm_set": list(expected_arms),
        "expected_rpe_pair_count": expected_pairs,
        "checks": details,
        "failure_codes": failures,
    }


def null_metrics() -> dict[str, None]:
    return {name: None for name in PRIMARY_METRICS}


def numeric_metrics(row: Mapping[str, Any]) -> dict[str, Optional[float]]:
    result: dict[str, Optional[float]] = {}
    for name in PRIMARY_METRICS:
        value = row.get(name)
        result[name] = float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else None
    return result


def median_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Optional[float]]:
    result: dict[str, Optional[float]] = {}
    for name in PRIMARY_METRICS:
        values = [float(row[name]) for row in rows if isinstance(row.get(name), (int, float))
                  and math.isfinite(float(row[name]))]
        result[name] = float(np.median(values)) if len(values) == len(rows) and values else None
    return result


def primary_arm_completeness_gate(
    primary_summary: Mapping[str, Any], expected_arms: Sequence[str]
) -> dict[str, Any]:
    arms = primary_summary.get("arms")
    support = primary_summary.get("support")
    expected_matched = support.get("matched_count") if isinstance(support, dict) else None
    expected_pairs = support.get("rpe_pairs") if isinstance(support, dict) else None
    failures: list[str] = []
    checks: dict[str, Any] = {}
    if not isinstance(arms, dict) or set(arms) != set(expected_arms):
        failures.append("PRIMARY_ARM_SET")
        arms = arms if isinstance(arms, dict) else {}
    for name in expected_arms:
        row = arms.get(name)
        arm_checks: dict[str, bool] = {"row_present": isinstance(row, dict)}
        if isinstance(row, dict):
            arm_checks["matched_count_consistent"] = (
                isinstance(expected_matched, int)
                and row.get("matched_count") == expected_matched
            )
            arm_checks["rpe_pair_count_consistent"] = (
                isinstance(expected_pairs, int) and row.get("rpe_pairs") == expected_pairs
            )
            for metric in PRIMARY_METRICS:
                value = row.get(metric)
                arm_checks[f"finite_nonnegative:{metric}"] = bool(
                    isinstance(value, (int, float))
                    and math.isfinite(float(value))
                    and float(value) >= 0.0
                )
        failed = [key for key, passed in arm_checks.items() if not passed]
        failures.extend(f"{name}:{key}" for key in failed)
        checks[name] = arm_checks
    return {
        "status": "PASS" if not failures else "FAIL",
        "expected_arm_set": list(expected_arms),
        "expected_matched_count": expected_matched,
        "expected_rpe_pair_count": expected_pairs,
        "checks": checks,
        "failure_codes": failures,
    }


def build_formal_summary(
    lock: Mapping[str, Any],
    primary_summary: Mapping[str, Any],
    primary_gate: Mapping[str, Any],
    evo_audit: Mapping[str, Any],
) -> dict[str, Any]:
    backend = lock["authority"]["backend"]
    primary_arms = primary_summary.get("arms")
    require(isinstance(primary_arms, dict), "PRIMARY_ARMS_BLOCK")
    valid_counts = backend["valid_counts"]
    expected_arms = ["HFNET"] + [
        row["item_id"] for row in backend["planned_repeats"]
        if row["accepted_for_joint_mask"]
    ]
    completeness = primary_arm_completeness_gate(primary_summary, expected_arms)
    population_checks = {
        "klt_has_at_least_one_valid_planned_repeat": valid_counts["klt"] >= 1,
        "xfeat_has_at_least_one_valid_planned_repeat": valid_counts["xfeat"] >= 1,
    }
    population_failures = [name for name, passed in population_checks.items() if not passed]
    ranking_available = bool(
        primary_gate.get("status") == "PASS"
        and not population_failures
        and completeness.get("status") == "PASS"
        and evo_audit.get("status") == "PASS"
    )
    repeats: list[dict[str, Any]] = []
    arm_numeric: dict[str, list[Mapping[str, Any]]] = {"klt": [], "xfeat": []}
    for planned in backend["planned_repeats"]:
        accepted = planned["accepted_for_joint_mask"]
        raw = primary_arms.get(planned["item_id"]) if accepted else None
        if accepted:
            require(isinstance(raw, dict), f"PRIMARY_ACCEPTED_ARM_MISSING:{planned['item_id']}")
            arm_numeric[planned["arm"]].append(raw)
        repeats.append({
            "item_id": planned["item_id"],
            "arm": planned["arm"],
            "repeat_index": planned["repeat_index"],
            "terminal_disposition": planned["disposition"],
            "accepted_for_single_joint_mask": accepted,
            "formal_metrics": numeric_metrics(raw) if ranking_available and isinstance(raw, dict) else null_metrics(),
            "scientific_failure_retained_as_na": not accepted,
            "replacement_permitted": False,
        })
    arm_summaries: dict[str, Any] = {}
    for arm in ("klt", "xfeat"):
        arm_summaries[arm] = {
            "planned_count": 5,
            "valid_count": valid_counts[arm],
            "failed_count": 5 - valid_counts[arm],
            "aggregation": "median_over_all_valid_planned_repeats",
            "best_run_selected": False,
            "formal_median_metrics": (
                median_metrics(arm_numeric[arm]) if ranking_available else null_metrics()
            ),
        }
    hfnet_metrics = primary_arms.get("HFNET")
    require(isinstance(hfnet_metrics, dict), "PRIMARY_HFNET_MISSING")
    failure_codes = []
    failure_codes.extend(f"SUPPORT:{code}" for code in primary_gate.get("failure_codes", []))
    failure_codes.extend(f"POPULATION:{code}" for code in population_failures)
    failure_codes.extend(
        f"PRIMARY_COMPLETENESS:{code}"
        for code in completeness.get("failure_codes", [])
    )
    failure_codes.extend(f"EVO:{code}" for code in evo_audit.get("failure_codes", []))
    return {
        "schema_version": "aqua-fe-a08-formal-three-arm-common-support-summary-v1",
        "status": "FORMAL_RANKING_AVAILABLE" if ranking_available else "FORMAL_RANKING_NA_GATE_CLOSED",
        "ranking_available": ranking_available,
        "all_formal_ranking_metrics_na_if_any_gate_fails": True,
        "failure_codes": failure_codes,
        "support_gate": dict(primary_gate),
        "population_gate": {
            "status": "PASS" if not population_failures else "FAIL",
            "checks": population_checks,
            "failure_codes": population_failures,
        },
        "primary_arm_completeness_gate": completeness,
        "evo_gate": dict(evo_audit),
        "single_joint_mask_arm_set": list(primary_arms),
        "hfnet": {
            "label": "HFNet-SLAM external learned-feature system",
            "planned_count": 1,
            "valid_count": 1,
            "formal_metrics": numeric_metrics(hfnet_metrics) if ranking_available else null_metrics(),
        },
        "klt": arm_summaries["klt"],
        "xfeat": {
            **arm_summaries["xfeat"],
            **backend["xfeat_method_native_label"],
        },
        "planned_repeats": repeats,
        "technical_repeats_are_not_independent_samples": True,
        "development_only_outcome_selected_support_extended": True,
        "reference_is_image_derived_depth_scaled_proxy": True,
    }


def repeat_table_csv_text(formal: Mapping[str, Any]) -> str:
    fields = [
        "item_id", "arm", "repeat_index", "terminal_disposition",
        "accepted_for_single_joint_mask", "scientific_failure_retained_as_na",
        "replacement_permitted", *PRIMARY_METRICS,
    ]
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=fields)
    writer.writeheader()
    for row in formal["planned_repeats"]:
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


def primary_metrics_csv_text(summary: Mapping[str, Any]) -> str:
    arms = summary.get("arms")
    require(isinstance(arms, dict), "PRIMARY_METRICS_SUMMARY_ARMS")
    fieldnames = sorted(
        {"arm"}
        | {
            key
            for metrics in arms.values()
            if isinstance(metrics, dict)
            for key in metrics
            if key not in {"audit", "rejection_histogram"}
        }
    )
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    for name, metrics in arms.items():
        require(isinstance(metrics, dict), f"PRIMARY_METRICS_ARM:{name}")
        writer.writerow({
            "arm": name,
            **{key: value for key, value in metrics.items() if key in fieldnames},
        })
    return handle.getvalue()


def output_tree_identities(
    root: Path = OUTPUT_ROOT,
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
            require(child.is_dir() and not child.is_symlink(), f"OUTPUT_DIRECTORY_KIND:{child}")
        for name in files:
            child = current / name
            relative = str(child.relative_to(root))
            if exclude_receipt and relative == RECEIPT_NAME:
                continue
            observed = identity(child)
            observed["path"] = str(advertised_root / relative)
            result[relative] = observed
    return {name: result[name] for name in sorted(result)}


def build_error_formal_summary(lock: Mapping[str, Any], error: str) -> dict[str, Any]:
    backend = lock["authority"]["backend"]
    repeats = [{
        "item_id": row["item_id"], "arm": row["arm"],
        "repeat_index": row["repeat_index"],
        "terminal_disposition": row["disposition"],
        "accepted_for_single_joint_mask": row["accepted_for_joint_mask"],
        "scientific_failure_retained_as_na": not row["accepted_for_joint_mask"],
        "replacement_permitted": False, "formal_metrics": null_metrics(),
    } for row in backend["planned_repeats"]]
    return {
        "schema_version": "aqua-fe-a08-formal-three-arm-common-support-summary-v1",
        "status": "FORMAL_RANKING_NA_ANALYSIS_ERROR_NO_RETRY",
        "ranking_available": False,
        "all_formal_ranking_metrics_na_if_any_gate_fails": True,
        "failure_codes": [f"ANALYSIS_ERROR:{error}"],
        "hfnet": {"planned_count": 1, "valid_count": 1, "formal_metrics": null_metrics()},
        "klt": {"planned_count": 5, "valid_count": backend["valid_counts"]["klt"],
                "formal_median_metrics": null_metrics()},
        "xfeat": {"planned_count": 5, "valid_count": backend["valid_counts"]["xfeat"],
                  "formal_median_metrics": null_metrics(),
                  **backend["xfeat_method_native_label"]},
        "planned_repeats": repeats,
    }


def force_all_formal_metrics_na_for_integrity(
    formal: Mapping[str, Any], failure_codes: Sequence[str]
) -> dict[str, Any]:
    """Close every formal number before publication when integrity is not PASS."""

    result = json.loads(json.dumps(formal, allow_nan=False))
    result["status"] = "FORMAL_RANKING_NA_EXECUTION_INTEGRITY"
    result["ranking_available"] = False
    existing = result.get("failure_codes")
    result["failure_codes"] = list(existing) if isinstance(existing, list) else []
    result["failure_codes"].extend(
        code for code in failure_codes if code not in result["failure_codes"]
    )
    hfnet = result.get("hfnet")
    if isinstance(hfnet, dict):
        hfnet["formal_metrics"] = null_metrics()
    for arm in ("klt", "xfeat"):
        block = result.get(arm)
        if isinstance(block, dict):
            block["formal_median_metrics"] = null_metrics()
    repeats = result.get("planned_repeats")
    if isinstance(repeats, list):
        for row in repeats:
            if isinstance(row, dict):
                row["formal_metrics"] = null_metrics()
    result["execution_integrity_gate"] = {
        "status": "FAIL",
        "failure_codes": list(failure_codes),
    }
    result["terminal_receipt_required_for_interpretation"] = True
    return result


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
    ranking_available = bool(formal.get("ranking_available") and integrity_ok)
    return {
        "schema_version": RECEIPT_SCHEMA,
        "status": (
            "PASS_FORMAL_RANKING_AVAILABLE"
            if ranking_available
            else "TERMINAL_FORMAL_RANKING_NA_NO_RETRY"
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
        "formal_ranking_available": ranking_available,
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
        "failed_backend_replays_retained_as_na": True,
        "best_repeat_selection_permitted": False,
        "trajectory_convention": "world_T_body_then_shared_body_T_cam0",
        "xfeat_method_native_label": lock["authority"]["backend"][
            "xfeat_method_native_label"
        ],
    }


def publish_failure_terminal(
    *,
    lock: Mapping[str, Any],
    lock_id: Mapping[str, Any],
    claim_id: Mapping[str, Any],
    started: str,
    errors: Sequence[str],
    partial_staging: Path,
) -> dict[str, Any]:
    """Best-effort terminalization after a post-claim infrastructure fault."""

    require(not OUTPUT_ROOT.exists() and not OUTPUT_ROOT.is_symlink(),
            "FAILURE_TERMINAL_DESTINATION_EXISTS")
    require(
        not FAILURE_STAGING_ROOT.exists() and not FAILURE_STAGING_ROOT.is_symlink(),
        "FAILURE_STAGING_ALREADY_EXISTS",
    )
    FAILURE_STAGING_ROOT.mkdir()
    atomic_publish(FAILURE_STAGING_ROOT / GRID_NAME, exact_grid_evidence())
    error_text = ";".join(errors) if errors else "UNKNOWN_POST_CLAIM_FAILURE"
    formal = force_all_formal_metrics_na_for_integrity(
        build_error_formal_summary(lock, error_text),
        ["EXECUTION_INTEGRITY:POST_CLAIM_TERMINALIZATION"],
    )
    write_repeat_table(FAILURE_STAGING_ROOT / REPEAT_TABLE_NAME, formal)
    atomic_publish(FAILURE_STAGING_ROOT / FORMAL_SUMMARY_NAME, formal)
    partial: dict[str, Any]
    try:
        partial = {
            "status": "PRESERVED_UNCOMMITTED_PARTIAL_EVIDENCE",
            "tree": output_tree_identities(
                partial_staging,
                advertised_root=partial_staging,
                exclude_receipt=False,
            ) if partial_staging.is_dir() and not partial_staging.is_symlink() else {},
        }
    except BaseException as error:
        partial = {
            "status": "PARTIAL_EVIDENCE_AUDIT_FAILED",
            "error": f"{type(error).__name__}:{error}",
        }
    atomic_publish(
        FAILURE_STAGING_ROOT / "uncommitted_partial_evidence_v1.json", partial
    )
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


def create_primary_staging_root() -> None:
    STAGING_ROOT.mkdir()


def execute_analysis(lock_path: Path, authorization_token: str) -> tuple[int, dict[str, Any]]:
    require(not CAMPAIGN_PERMANENTLY_GATE_CLOSED, PERMANENT_GATE_ERROR)
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
        "planned_joint_arm_set": list(accepted_arm_paths(lock["authority"]["backend"])),
        "accuracy_computed_before_claim": False,
    }
    atomic_publish(CLAIM_PATH, claim)
    claim_id: Optional[dict[str, Any]] = None
    errors: list[str] = []
    try:
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
            modules["evaluator"].write_grid_audit(
                STAGING_ROOT / GRID_AUDIT_NAME, reference, arms, evaluation
            )
            modules["evaluator"].write_metrics_csv(
                STAGING_ROOT / RAW_METRICS_NAME, primary
            )
            atomic_publish(
                STAGING_ROOT / RAW_DIAGNOSTIC_MANIFEST_NAME,
                {
                    "schema_version": "aqua-fe-a08-raw-numeric-diagnostics-boundary-v1",
                    "status": "DIAGNOSTIC_ONLY_NOT_FORMAL_RANKING",
                    "artifacts": [
                        RAW_SUMMARY_NAME, GRID_AUDIT_NAME, RAW_METRICS_NAME
                    ],
                    "formal_ranking_authority": FORMAL_SUMMARY_NAME,
                    "terminal_receipt_required": RECEIPT_NAME,
                },
            )
            gate = support_gate(primary)
            population_ready = all(
                lock["authority"]["backend"]["valid_counts"][arm] >= 1
                for arm in ("klt", "xfeat")
            )
            if gate["status"] == "PASS" and population_ready:
                try:
                    evo = modules["evaluator"].run_segmented_evo_crosscheck(
                        STAGING_ROOT, reference, arms, evaluation, 1.0, 1.0
                    )
                    atomic_publish(STAGING_ROOT / EVO_SUMMARY_NAME, evo)
                    evo_audit = validate_evo_crosscheck(
                        evo,
                        primary,
                        list(arms),
                        lock["authority"]["evo"]["version"],
                        tolerance_m=1e-5,
                    )
                except BaseException as error:
                    evo_audit = {
                        "status": "FAIL",
                        "failure_codes": [
                            f"EVO_EXECUTION:{type(error).__name__}:{error}"
                        ],
                        "tolerance_m": 1e-5,
                    }
            elif gate["status"] != "PASS":
                evo_audit = {
                    "status": "NOT_RUN_SUPPORT_GATE_CLOSED",
                    "failure_codes": ["SUPPORT_GATE_CLOSED_BEFORE_EVO"],
                    "tolerance_m": 1e-5,
                }
            else:
                evo_audit = {
                    "status": "NOT_RUN_POPULATION_GATE_CLOSED",
                    "failure_codes": ["CONTROL_ARM_HAS_ZERO_VALID_REPEATS"],
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
        integrity_failure_codes: list[str] = []
        if authority_post.get("status") != "PASS":
            integrity_failure_codes.append("EXECUTION_INTEGRITY:POST_AUTHORITY_FAILURE")
        if not claim_stable:
            integrity_failure_codes.append("EXECUTION_INTEGRITY:CLAIM_NOT_STABLE")
        integrity_ok = not integrity_failure_codes
        if integrity_ok:
            formal["execution_integrity_gate"] = {
                "status": "PASS", "failure_codes": []
            }
            formal["terminal_receipt_required_for_interpretation"] = True
        else:
            formal = force_all_formal_metrics_na_for_integrity(
                formal, integrity_failure_codes
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
        errors.append(f"TERMINALIZATION:{type(error).__name__}:{error}")
        if OUTPUT_ROOT.is_dir() and not OUTPUT_ROOT.is_symlink():
            try:
                committed, _ = stable_json(OUTPUT_ROOT / RECEIPT_NAME)
                return 3, committed
            except BaseException:
                pass
        if claim_id is None:
            claim_id = identity(CLAIM_PATH)
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
    require(not CAMPAIGN_PERMANENTLY_GATE_CLOSED, PERMANENT_GATE_ERROR)
    require(authorization_token == BUILD_LOCK_TOKEN, "BUILD_LOCK_AUTHORIZATION_TOKEN")
    require(not lock_path.exists() and not lock_path.is_symlink(), "ANALYSIS_LOCK_ALREADY_EXISTS")
    require(analysis_output_state() == "ABSENT", "ANALYSIS_OUTPUT_PREEXISTS")
    presence = required_terminal_presence()
    require(all(state == "PRESENT_REGULAR" for state in presence.values()),
            "TEN_TERMINAL_RECEIPTS_REQUIRED")
    authority = collect_authority()
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = build_lock_payload(authority, created)
    atomic_publish(lock_path, payload)
    return {
        "status": "FINAL_ANALYSIS_LOCK_PUBLISHED_NO_ACCURACY_COMPUTED",
        "lock": identity(lock_path),
        "accuracy_computed": False,
    }


def formal_metrics_are_all_na(formal: Mapping[str, Any]) -> bool:
    blocks: list[Any] = []
    hfnet = formal.get("hfnet")
    if isinstance(hfnet, dict):
        blocks.append(hfnet.get("formal_metrics"))
    for arm in ("klt", "xfeat"):
        value = formal.get(arm)
        if isinstance(value, dict):
            blocks.append(value.get("formal_median_metrics"))
    repeats = formal.get("planned_repeats")
    if isinstance(repeats, list):
        blocks.extend(
            row.get("formal_metrics") for row in repeats if isinstance(row, dict)
        )
    return bool(blocks) and all(
        isinstance(block, dict)
        and set(block) == set(PRIMARY_METRICS)
        and all(block[name] is None for name in PRIMARY_METRICS)
        for block in blocks
    )


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
        "uncommitted_partial_evidence_v1.json",
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
            regular_file(child.absolute(), "audit-output")
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


def validate_grid_audit_file(
    path: Path,
    reference: Any,
    arms: Mapping[str, Any],
    evaluation: Mapping[str, Any],
) -> None:
    expected_arms = list(arms)
    with path.open(newline="", encoding="utf-8") as handle:
        grid_reader = csv.DictReader(handle)
        grid_fields = list(grid_reader.fieldnames or [])
        grid_rows = list(grid_reader)
    expected_grid_fields = ["timestamp", "reference_valid"] + [
        f"{name}_valid" for name in expected_arms
    ] + ["common_valid", "segment_id"]
    require(grid_fields == expected_grid_fields, "PRIMARY_GRID_AUDIT_FIELDS")
    require(len(grid_rows) == GRID_COUNT, "PRIMARY_GRID_AUDIT_ROW_COUNT")
    common_mask = np.asarray(evaluation["common_mask"], dtype=bool)
    segments = np.asarray(evaluation["segments"], dtype=int)
    require(
        len(reference.stamps) == len(reference.valid) == GRID_COUNT
        and common_mask.shape == (GRID_COUNT,)
        and segments.shape == (GRID_COUNT,),
        "PRIMARY_GRID_RECOMPUTED_SHAPES",
    )
    for name, arm in arms.items():
        require(len(arm.valid) == GRID_COUNT, f"PRIMARY_GRID_ARM_SHAPE:{name}")
    for index, row in enumerate(grid_rows):
        expected_row = {
            "timestamp": format(float(reference.stamps[index]), ".17g"),
            "reference_valid": str(int(reference.valid[index])),
            "common_valid": str(int(common_mask[index])),
            "segment_id": str(int(segments[index])),
            **{
                f"{name}_valid": str(int(arms[name].valid[index]))
                for name in expected_arms
            },
        }
        require(row == expected_row, f"PRIMARY_GRID_AUDIT_ROW:{index}")


def audit_terminal_semantics(
    lock: Mapping[str, Any], lock_id: Mapping[str, Any]
) -> dict[str, Any]:
    receipt, receipt_id = stable_json(OUTPUT_ROOT / RECEIPT_NAME)
    require(receipt.get("schema_version") == RECEIPT_SCHEMA,
            "ANALYSIS_RECEIPT_SCHEMA")
    require(
        receipt.get("status")
        in {"PASS_FORMAL_RANKING_AVAILABLE", "TERMINAL_FORMAL_RANKING_NA_NO_RETRY"},
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
        and receipt.get("formal_summary_requires_this_terminal_receipt") is True,
        "ANALYSIS_TERMINAL_COMMIT_POLICY",
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
        and claim.get("accuracy_computed_before_claim") is False,
        "ANALYSIS_CLAIM_CONTRACT",
    )

    recorded = receipt.get("artifacts_before_receipt")
    require(isinstance(recorded, dict), "ANALYSIS_RECEIPT_ARTIFACTS")
    live_artifacts = output_tree_identities(
        OUTPUT_ROOT, advertised_root=OUTPUT_ROOT, exclude_receipt=True
    )
    require(recorded == live_artifacts, "ANALYSIS_OUTPUT_DRIFT")
    tree = validate_output_allowlist(expected_arms)
    for required in (GRID_NAME, FORMAL_SUMMARY_NAME, REPEAT_TABLE_NAME):
        require(required in recorded, f"ANALYSIS_REQUIRED_ARTIFACT:{required}")

    grid, _ = stable_json(OUTPUT_ROOT / GRID_NAME)
    require(grid == exact_grid_evidence(), "ANALYSIS_EXACT_GRID")
    formal, formal_id = stable_json(OUTPUT_ROOT / FORMAL_SUMMARY_NAME)
    require(recorded[FORMAL_SUMMARY_NAME] == formal_id, "FORMAL_SUMMARY_IDENTITY")
    require(
        formal.get("schema_version")
        == "aqua-fe-a08-formal-three-arm-common-support-summary-v1",
        "FORMAL_SUMMARY_SCHEMA",
    )
    require(formal.get("terminal_receipt_required_for_interpretation") is True,
            "FORMAL_TERMINAL_RECEIPT_BOUNDARY")
    ranking = receipt.get("formal_ranking_available")
    require(isinstance(ranking, bool), "FORMAL_RANKING_BOOLEAN")
    require(formal.get("ranking_available") is ranking,
            "RECEIPT_FORMAL_RANKING_MISMATCH")
    require(receipt.get("formal_summary_status") == formal.get("status"),
            "RECEIPT_FORMAL_STATUS_MISMATCH")
    require(
        receipt.get("xfeat_method_native_label")
        == lock["authority"]["backend"]["xfeat_method_native_label"]
        == {
            key: formal["xfeat"][key]
            for key in (
                "profile", "label", "method_native_klt_safe_fallback",
                "exported_learned_observations",
                "learning_contribution_claim_permitted",
            )
        },
        "XFEAT_METHOD_NATIVE_LABEL_AUDIT",
    )
    repeats = formal.get("planned_repeats")
    require(
        isinstance(repeats, list)
        and [row.get("item_id") for row in repeats if isinstance(row, dict)]
        == list(ITEM_ORDER),
        "FORMAL_PLANNED_REPEAT_ORDER",
    )
    locked_plans = lock["authority"]["backend"]["planned_repeats"]
    for formal_row, locked_row in zip(repeats, locked_plans):
        require(
            formal_row.get("arm") == locked_row["arm"]
            and formal_row.get("repeat_index") == locked_row["repeat_index"]
            and formal_row.get("terminal_disposition") == locked_row["disposition"]
            and formal_row.get("accepted_for_single_joint_mask")
            is locked_row["accepted_for_joint_mask"]
            and formal_row.get("replacement_permitted") is False,
            f"FORMAL_REPEAT_BINDING:{locked_row['item_id']}",
        )
    with (OUTPUT_ROOT / REPEAT_TABLE_NAME).open(
        newline="", encoding="utf-8"
    ) as handle:
        observed_repeat_csv = handle.read()
    require(
        observed_repeat_csv == repeat_table_csv_text(formal),
        "FORMAL_REPEAT_CSV_RECOMPUTATION",
    )

    primary: Optional[dict[str, Any]] = None
    if RAW_SUMMARY_NAME in recorded:
        primary, primary_id = stable_json(OUTPUT_ROOT / RAW_SUMMARY_NAME)
        require(recorded[RAW_SUMMARY_NAME] == primary_id, "PRIMARY_SUMMARY_IDENTITY")
        protocol = primary.get("protocol")
        arms = primary.get("arms")
        require(
            isinstance(protocol, dict)
            and protocol.get("single_joint_mask") is True
            and protocol.get("shared_full_precision_body_T_cam0")
            == str(SHARED_EXTRINSIC)
            and protocol.get("proper_fixed_scale_se3") is True
            and protocol.get("sim3") is False
            and protocol.get("reference_time_offset_s") == 0.0
            and protocol.get("all_arm_time_offsets_s") == 0.0,
            "PRIMARY_NUMERIC_PROTOCOL",
        )
        require(isinstance(arms, dict) and list(arms) == expected_arms,
                "PRIMARY_SINGLE_JOINT_ARM_SET")
        (
            recomputed_primary,
            recomputed_reference,
            recomputed_arms,
            recomputed_evaluation,
            _,
        ) = evaluate_joint_inputs(lock)
        require(primary == recomputed_primary, "PRIMARY_LOCKED_INPUT_RECOMPUTATION")
        require(RAW_DIAGNOSTIC_MANIFEST_NAME in recorded,
                "RAW_DIAGNOSTIC_BOUNDARY_REQUIRED")
        diagnostic_boundary, _ = stable_json(
            OUTPUT_ROOT / RAW_DIAGNOSTIC_MANIFEST_NAME
        )
        require(
            diagnostic_boundary
            == {
                "schema_version": "aqua-fe-a08-raw-numeric-diagnostics-boundary-v1",
                "status": "DIAGNOSTIC_ONLY_NOT_FORMAL_RANKING",
                "artifacts": [RAW_SUMMARY_NAME, GRID_AUDIT_NAME, RAW_METRICS_NAME],
                "formal_ranking_authority": FORMAL_SUMMARY_NAME,
                "terminal_receipt_required": RECEIPT_NAME,
            },
            "RAW_DIAGNOSTIC_BOUNDARY_CONTRACT",
        )
        require(
            GRID_AUDIT_NAME in recorded and RAW_METRICS_NAME in recorded,
            "PRIMARY_AUDIT_ARTIFACTS_REQUIRED",
        )
        validate_grid_audit_file(
            OUTPUT_ROOT / GRID_AUDIT_NAME,
            recomputed_reference,
            recomputed_arms,
            recomputed_evaluation,
        )
        with (OUTPUT_ROOT / RAW_METRICS_NAME).open(
            newline="", encoding="utf-8"
        ) as handle:
            observed_metrics_csv = handle.read()
        require(
            observed_metrics_csv == primary_metrics_csv_text(recomputed_primary),
            "PRIMARY_METRICS_CSV_RECOMPUTATION",
        )

    execution_integrity = receipt.get("execution_integrity")
    require(isinstance(execution_integrity, dict), "ANALYSIS_EXECUTION_INTEGRITY")
    if ranking:
        require(receipt.get("status") == "PASS_FORMAL_RANKING_AVAILABLE",
                "RANKING_RECEIPT_STATUS")
        require(
            execution_integrity.get("status") == "PASS"
            and execution_integrity.get("claim_stable") is True
            and execution_integrity.get("authority_post", {}).get("status") == "PASS",
            "RANKING_EXECUTION_INTEGRITY",
        )
        require(primary is not None, "RANKING_PRIMARY_SUMMARY_REQUIRED")
        require(
            GRID_AUDIT_NAME in recorded and RAW_METRICS_NAME in recorded,
            "RANKING_PRIMARY_AUDIT_ARTIFACTS_REQUIRED",
        )
        require(EVO_SUMMARY_NAME in recorded, "RANKING_EVO_SUMMARY_REQUIRED")
        evo, _ = stable_json(OUTPUT_ROOT / EVO_SUMMARY_NAME)
        evo_audit = validate_evo_crosscheck(
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
            receipt.get("status") == "TERMINAL_FORMAL_RANKING_NA_NO_RETRY",
            "NA_RECEIPT_STATUS",
        )
        require(formal_metrics_are_all_na(formal), "FORMAL_NA_INVARIANT")
    return {
        "status": "PASS_TERMINAL_EVIDENCE_DEEP_AUDIT",
        "receipt": receipt_id,
        "formal_ranking_available": ranking,
        "output_tree": tree,
        "claim": claim_id,
    }


def audit_readonly(lock_path: Path = DEFAULT_LOCK) -> dict[str, Any]:
    if CAMPAIGN_PERMANENTLY_GATE_CLOSED:
        return {
            "status": "BLOCKED_THREE_ARM_CAMPAIGN_PERMANENTLY_GATE_CLOSED",
            "read_only": True,
            "reason": PERMANENT_GATE_ERROR,
            "xfeat_disposition": PERMANENT_GATE_STATUS,
            "analysis_lock_creation_permitted": False,
            "analysis_execution_permitted": False,
            "analysis_lock_present": lock_path.exists() or lock_path.is_symlink(),
            "analysis_output_state": analysis_output_state(),
        }
    result: dict[str, Any] = {
        "status": "WAITING_ANALYSIS_LOCK",
        "read_only": True,
        "analysis_lock": "ABSENT",
        "analysis_output_state": analysis_output_state(),
    }
    if not lock_path.exists() and not lock_path.is_symlink():
        return result
    try:
        lock, lock_id = verify_lock(lock_path)
        result.update({
            "status": "PASS_LOCK_AUTHORITY_NO_TERMINAL_YET",
            "analysis_lock": "PASS",
            "lock": lock_id,
            "contract_sha256": lock["contract_sha256"],
        })
        output_state = analysis_output_state()
        result["analysis_output_state"] = output_state
        require(
            output_state in {"ABSENT", "TERMINAL_RECEIPT_PRESENT"},
            f"AUDIT_INCOMPLETE_OR_INVALID_TERMINAL_STATE:{output_state}",
        )
        if output_state == "TERMINAL_RECEIPT_PRESENT":
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
        if args.command == "build-lock":
            result = build_lock(lock_path, args.authorization_token)
            code = 0
        else:
            code, result = execute_analysis(lock_path, args.authorization_token)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return code
    except (AnalysisProtocolError, OSError, ValueError) as error:
        print(f"A08_COMMON_SUPPORT_ERROR:{type(error).__name__}:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
