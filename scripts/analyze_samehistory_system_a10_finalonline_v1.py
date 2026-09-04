#!/usr/bin/env python3
"""Analysis-only audit for the frozen A10 final-online same-history run.

The five project items are one-shot executions.  A missing terminal receipt is
therefore PENDING even if partial output files exist.  The common-support CPU
evaluator is allowed to run only after all five receipts are terminal-success
and all four systems pass the preregistered score-window usability gate.

This script never starts ROS, VINS, an exporter, XFeat, HFNet, or a GPU
process.  Accuracy is descriptive: the fixed score interval contains only 21
native COLMAP proxy rows, below the frozen 30-pose formal APE minimum.  No
winner, significance test, ranking, cross-window mean, or failure-as-zero
imputation is computed.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import csv
import ctypes
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Optional, Sequence


ROOT = Path(__file__).absolute().parents[1]
EXP = Path("/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v1")
DEFAULT_OUTPUT = (
    ROOT / "papers/samehistory_system_comparison_a10_finalonline_v1_analysis"
)
EXECUTION_LOCK = (
    ROOT / "papers/samehistory_system_comparison_a10_finalonline_v1_execution_lock.json"
)
PROTOCOL = ROOT / "papers/samehistory_system_comparison_a10_finalonline_v1_protocol.md"
EVALUATOR = ROOT / "scripts/evaluate_vins_common_support.py"
RECEIPT_NAME = "formal_run_receipt_v1.json"
CLAIM_NAME = "process_start_claim.json"
LOG_NAME = "supervisor_process.log"

SCHEMA = "aqua-fe-a10-samehistory-finalonline-analysis-v1"
SUPERVISOR_SCHEMA = "aqua-fe-a10-samehistory-finalonline-supervisor-v3"
LOCK_SCHEMA = "aqua-fe-a10-samehistory-finalonline-execution-lock-v1"
BRIDGE_SCHEMA = "aqua-fe-hfnet-v6-a10-warmstart-world-body-vins-csv-bridge-v1"

SCORE_START_NS = 1_542_888_916_043_622_160
SCORE_END_NS = 1_542_888_936_039_921_424
SCORE_DURATION_NS = SCORE_END_NS - SCORE_START_NS
SCORE_SOURCE_RANGE = (2400, 2800)
FEED_SOURCE_RANGE = (0, 2800)
REFERENCE_ROWS = 21
MIN_COMMON_ROWS = 15
MIN_SCORE_SPAN_FRACTION = 0.70
MAX_SCORE_GAP_NS = 500_000_000
MIN_RPE_PAIRS = 10
FORMAL_APE_MIN_POSES = 30

RAW_BAG = Path(
    "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v1/raw/"
    "archaeo10_0000_2800.bag"
)
RAW_BAG_EXPECTED = {
    "path": str(RAW_BAG),
    "size_bytes": 765_976_943,
    "sha256": "49864715ec19005daa3492fa043fe87204fb6f8cc802b6b98cba55a8ab4fe87e",
}
EVALUATOR_EXPECTED_SHA256 = (
    "ab6f2b5c1a10a41463657edee2724c022fc0248dc885096acb336e602384c110"
)
EVALUATOR_CORE = ROOT / "scripts/trajectory_eval_core.py"
EVALUATOR_CORE_EXPECTED_SHA256 = (
    "aa9ac4da81df7298d1f1c369548ca98a57235916004337cad66f4cf331560635"
)

CAMERA_TOPIC = "/camera/image_raw"
HFNET_CANONICAL_SCHEMA = "aqua-fe-a10-hfnet-source-stamp-canonicalization-v1"
HFNET_CANONICAL_NAME = "hfnet_world_T_body_source_stamp_canonical_v1.csv"
HFNET_CANONICAL_MANIFEST_NAME = HFNET_CANONICAL_NAME + ".manifest.json"
HFNET_MAX_CANONICAL_DELTA_NS = 128
HFNET_EXPECTED_DELTA_HISTOGRAM_NS: Mapping[str, int] = {
    "-112": 44,
    "-80": 60,
    "-48": 45,
    "-16": 60,
    "16": 46,
    "48": 52,
    "80": 38,
    "112": 56,
}
UNIFORM_1HZ_GRID_SAMPLES = 20

HFNET_ATTEMPT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/"
    "a10_0000_2800_score_2400_2800_warmstart/attempt_001"
)
HFNET_RUN_RESULT = HFNET_ATTEMPT / "run_result.json"
HFNET_RUN_RESULT_EXPECTED = {
    "path": str(HFNET_RUN_RESULT),
    "size_bytes": 21_463,
    "sha256": "88c340849adcc60985711dedd499c74db36e36b3ac103768bc3aa0d615372a46",
}
HFNET_SCORE_CROP = HFNET_ATTEMPT / "result/trajectory_score_2400_2800.txt"
HFNET_SCORE_CROP_EXPECTED = {
    "path": str(HFNET_SCORE_CROP),
    "size_bytes": 45_556,
    "sha256": "b5df265df24baa0d7035ee183de28ca105b2bf6429ebf819d90fd6f275154566",
}
HFNET_BRIDGE = HFNET_ATTEMPT / "bridges/hfnet_world_T_body_vins_csv_v1.csv"
HFNET_BRIDGE_EXPECTED = {
    "path": str(HFNET_BRIDGE),
    "size_bytes": 42_749,
    "sha256": "a268350cda12c0e4b453420853c19e4dd7b4dc2e121d6616344ad247be032ec1",
}
HFNET_BRIDGE_MANIFEST = Path(str(HFNET_BRIDGE) + ".manifest.json")
HFNET_BRIDGE_MANIFEST_EXPECTED = {
    "path": str(HFNET_BRIDGE_MANIFEST),
    "size_bytes": 1_622,
    "sha256": "2fc3a71b3007df1c3d88b0e1d7f54f7cd5eca87d20173f26cbd6226d16a23721",
}

ITEM_ORDER = (
    "klt_export",
    "aquafe_build",
    "vanilla_origin_native_image_context",
    "external_klt_finalonline_backbone",
    "aquafe_finalonline_xfeat_lineage",
)

ITEM_DIRS: Mapping[str, Path] = {
    "klt_export": EXP / "frontends/klt_export",
    "aquafe_build": EXP / "frontends/aquafe_finalonline",
    "vanilla_origin_native_image_context": (
        EXP / "backends/vanilla_origin_native_image_context"
    ),
    "external_klt_finalonline_backbone": (
        EXP / "backends/external_klt_finalonline_backbone"
    ),
    "aquafe_finalonline_xfeat_lineage": (
        EXP / "backends/aquafe_finalonline_xfeat_lineage"
    ),
}

RECEIPTS: Mapping[str, Path] = {
    item_id: ITEM_DIRS[item_id] / RECEIPT_NAME for item_id in ITEM_ORDER
}

VINS_ARMS = (
    "vanilla_origin_native_image_context",
    "external_klt_finalonline_backbone",
    "aquafe_finalonline_xfeat_lineage",
)
METHOD_ORDER = VINS_ARMS + ("hfnet_slam_warmstart",)
EVALUATOR_NAMES: Mapping[str, str] = {
    "vanilla_origin_native_image_context": "VANILLA_ORIGIN_NATIVE_IMAGE_CONTEXT",
    "external_klt_finalonline_backbone": "EXTERNAL_KLT_FINALONLINE_BACKBONE",
    "aquafe_finalonline_xfeat_lineage": "AQUAFE_FINALONLINE_XFEAT_LINEAGE",
    "hfnet_slam_warmstart": "HFNET_SLAM_WARMSTART",
}


@dataclass(frozen=True)
class VinsArmPaths:
    trajectory: Path
    log: Path
    config: Path
    legacy_ape: Path


VINS_PATHS: Mapping[str, VinsArmPaths] = {
    "vanilla_origin_native_image_context": VinsArmPaths(
        trajectory=ITEM_DIRS["vanilla_origin_native_image_context"]
        / "vins_output/vio.csv",
        log=ITEM_DIRS["vanilla_origin_native_image_context"] / "vins.log",
        config=ITEM_DIRS["vanilla_origin_native_image_context"]
        / "vins_aqualoc_archaeo_origin.yaml",
        legacy_ape=ITEM_DIRS["vanilla_origin_native_image_context"] / "ape.txt",
    ),
    "external_klt_finalonline_backbone": VinsArmPaths(
        trajectory=ITEM_DIRS["external_klt_finalonline_backbone"]
        / "vins_output/vio.csv",
        log=ITEM_DIRS["external_klt_finalonline_backbone"] / "vins.log",
        config=ITEM_DIRS["external_klt_finalonline_backbone"]
        / "vins_aqualoc_archaeo_external.yaml",
        legacy_ape=ITEM_DIRS["external_klt_finalonline_backbone"] / "ape.txt",
    ),
    "aquafe_finalonline_xfeat_lineage": VinsArmPaths(
        trajectory=ITEM_DIRS["aquafe_finalonline_xfeat_lineage"]
        / "vins_output/vio.csv",
        log=ITEM_DIRS["aquafe_finalonline_xfeat_lineage"] / "vins.log",
        config=ITEM_DIRS["aquafe_finalonline_xfeat_lineage"]
        / "vins_aqualoc_archaeo_external.yaml",
        legacy_ape=ITEM_DIRS["aquafe_finalonline_xfeat_lineage"] / "ape.txt",
    ),
}

REQUIRED_OUTPUTS: Mapping[str, tuple[Path, ...]] = {
    "klt_export": (
        ITEM_DIRS["klt_export"] / "features.bag",
        ITEM_DIRS["klt_export"] / "frontend_metrics.csv",
        ITEM_DIRS["klt_export"] / "aqualoc_archaeo10_pinhole.yaml",
    ),
    "aquafe_build": (
        ITEM_DIRS["aquafe_build"] / "full_merged.bag",
        ITEM_DIRS["aquafe_build"] / "sidecar.bag",
        ITEM_DIRS["aquafe_build"] / "stats.csv",
    ),
    **{
        arm: (
            VINS_PATHS[arm].trajectory,
            VINS_PATHS[arm].log,
            VINS_PATHS[arm].config,
            VINS_PATHS[arm].legacy_ape,
        )
        for arm in VINS_ARMS
    },
}


class EvidenceError(RuntimeError):
    """A frozen input is contradictory, malformed, or stale."""


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise EvidenceError(f"DUPLICATE_JSON_KEY:{key}")
        value[key] = item
    return value


def read_json(path: Path) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise EvidenceError(f"NONFINITE_JSON_CONSTANT:{path}:{value}")

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except FileNotFoundError as error:
        raise EvidenceError(f"MISSING_JSON:{path}") from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceError(
            f"UNREADABLE_JSON:{path}:{type(error).__name__}"
        ) from error
    if not isinstance(value, dict):
        raise EvidenceError(f"JSON_ROOT_NOT_OBJECT:{path}")
    return value


def sha256(path: Path) -> str:
    return identity(path)["sha256"]


def identity(path: Path) -> dict[str, Any]:
    absolute = path.absolute()
    try:
        descriptor = os.open(
            absolute,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
    except FileNotFoundError as error:
        raise EvidenceError(f"MISSING_FILE:{path}") from error
    except OSError as error:
        raise EvidenceError(f"OPEN_FILE_FAILED:{path}:{error}") from error
    digest = hashlib.sha256()
    size = 0
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise EvidenceError(f"NOT_REGULAR_NONSYMLINK_FILE:{path}")
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            size += len(block)
            digest.update(block)
        after = os.fstat(descriptor)
        signature_before = (
            before.st_dev, before.st_ino, before.st_size,
            before.st_mtime_ns, before.st_ctime_ns,
        )
        signature_after = (
            after.st_dev, after.st_ino, after.st_size,
            after.st_mtime_ns, after.st_ctime_ns,
        )
        if signature_before != signature_after or size != before.st_size:
            raise EvidenceError(f"FILE_CHANGED_WHILE_HASHING:{path}")
    finally:
        os.close(descriptor)
    return {
        "path": str(absolute),
        "size_bytes": size,
        "sha256": digest.hexdigest(),
    }


def optional_identity(path: Path) -> dict[str, Any]:
    if not path.exists() and not path.is_symlink():
        return {"path": str(path), "exists": False}
    try:
        return {"exists": True, **identity(path)}
    except EvidenceError as error:
        return {"path": str(path), "exists": True, "error": str(error)}


def exact_identity(path: Path, expected: Mapping[str, Any], label: str) -> dict[str, Any]:
    actual = identity(path)
    if actual != dict(expected):
        raise EvidenceError(f"{label}_IDENTITY_MISMATCH")
    return actual


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise EvidenceError("NONFINITE_VALUE_IN_ANALYSIS_BUNDLE")
    return value


def exact_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvidenceError(f"INTEGER_REQUIRED:{label}")
    return value


def finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvidenceError(f"FINITE_NUMBER_REQUIRED:{label}")
    result = float(value)
    if not math.isfinite(result):
        raise EvidenceError(f"NONFINITE_NUMBER:{label}")
    return result


def payload_identity(payload: bytes, path: Path) -> dict[str, Any]:
    return {
        "path": str(path.absolute()),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def inspect_lock() -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    if not EXECUTION_LOCK.exists() and not EXECUTION_LOCK.is_symlink():
        return None, {
            "state": "PENDING_MISSING_EXECUTION_LOCK",
            "path": str(EXECUTION_LOCK),
        }
    try:
        lock = read_json(EXECUTION_LOCK)
        lock_identity = identity(EXECUTION_LOCK)
    except EvidenceError as error:
        return None, {
            "state": "INVALID_EXECUTION_LOCK",
            "path": str(EXECUTION_LOCK),
            "errors": [str(error)],
        }
    errors: list[str] = []
    if lock.get("schema_version") != LOCK_SCHEMA:
        errors.append("EXECUTION_LOCK_SCHEMA_DRIFT")
    if lock.get("status") != "FROZEN_BEFORE_SCORED_RUNS":
        errors.append("EXECUTION_LOCK_STATUS_DRIFT")
    try:
        protocol_identity = identity(PROTOCOL)
        if lock.get("protocol") != protocol_identity:
            errors.append("EXECUTION_LOCK_PROTOCOL_IDENTITY_DRIFT")
    except EvidenceError as error:
        errors.append(str(error))
    policy = lock.get("policy")
    if not isinstance(policy, Mapping) or policy.get("item_order") != list(ITEM_ORDER):
        errors.append("EXECUTION_LOCK_ITEM_ORDER_DRIFT")
    elif (
        policy.get("one_process_launch_per_item") is not True
        or policy.get("result_informed_retry") is not False
        or policy.get("dependencies_are_only_declared_item_dependencies") is not True
        or policy.get("independent_backend_failure_is_retained_not_ranked_as_zero") is not True
        or policy.get("large_artifact_root") != str(EXP)
        or policy.get("cwd") != str(ROOT)
    ):
        errors.append("EXECUTION_LOCK_POLICY_DRIFT")

    expected_score = {
        "score_start_ns": SCORE_START_NS,
        "score_end_ns": SCORE_END_NS,
        "nominal_backend_output_rate_hz": 10,
        "crop_interval": "inclusive",
        "minimum_score_temporal_span_coverage": MIN_SCORE_SPAN_FRACTION,
        "maximum_score_output_gap_s": MAX_SCORE_GAP_NS / 1e9,
        "require_initialization_before_or_within_score_window": True,
        "maximum_score_failure_mentions": 0,
        "maximum_score_restart_or_reset_events": 0,
        "unresolved_score_log_event_attribution_is_failure": True,
        "score_failure_is_usability_fail_not_terminal_process_failure": True,
    }
    if lock.get("score_usability") != expected_score:
        errors.append("EXECUTION_LOCK_SCORE_USABILITY_DRIFT")
    expected_common = {
        "denominator_reference_rows": REFERENCE_ROWS,
        "minimum_common_rows": MIN_COMMON_ROWS,
        "minimum_common_coverage": MIN_COMMON_ROWS / REFERENCE_ROWS,
        "minimum_descriptive_rpe_pairs": MIN_RPE_PAIRS,
        "formal_ape_minimum_poses": FORMAL_APE_MIN_POSES,
        "formal_ape_gate_open": False,
    }
    # The lock spells the preregistered decimal threshold as 0.70 rather than
    # the exact 15/21 ratio; both constraints are checked independently later.
    expected_common["minimum_common_coverage"] = 0.70
    if lock.get("common_support") != expected_common:
        errors.append("EXECUTION_LOCK_COMMON_SUPPORT_DRIFT")

    identities = lock.get("identities")
    relevant_identity_paths: Mapping[str, Path] = {
        "analysis_only_analyzer": Path(__file__),
        "supervisor": ROOT / "scripts/run_samehistory_system_a10_finalonline_v1.py",
        "hfnet_a10_bridge": ROOT / "scripts/bridge_hfnet_v6_a10_warmstart_world_body_to_vins_csv_v1.py",
        "common_support_evaluator": EVALUATOR,
        "common_support_evaluator_core": EVALUATOR_CORE,
        "raw_bag": RAW_BAG,
        "hfnet_run_result": HFNET_RUN_RESULT,
        "hfnet_score_crop": HFNET_SCORE_CROP,
        "hfnet_vins_bridge": HFNET_BRIDGE,
        "hfnet_vins_bridge_manifest": HFNET_BRIDGE_MANIFEST,
    }
    verified_identities: dict[str, Any] = {}
    if not isinstance(identities, Mapping):
        errors.append("EXECUTION_LOCK_IDENTITIES_MISSING")
    else:
        for name, path in relevant_identity_paths.items():
            try:
                actual = identity(path)
                verified_identities[name] = actual
                if identities.get(name) != actual:
                    errors.append(f"EXECUTION_LOCK_IDENTITY_DRIFT:{name}")
            except EvidenceError as error:
                errors.append(f"EXECUTION_LOCK_IDENTITY_INVALID:{name}:{error}")
    items = lock.get("items")
    if not isinstance(items, Mapping) or set(items) != set(ITEM_ORDER):
        errors.append("EXECUTION_LOCK_ITEM_SET_DRIFT")
    else:
        for item_id in ITEM_ORDER:
            item = items.get(item_id)
            if not isinstance(item, Mapping) or item.get("output_dir") != str(ITEM_DIRS[item_id]):
                errors.append(f"EXECUTION_LOCK_OUTPUT_DIR_DRIFT:{item_id}")
                continue
            outputs = item.get("expected_outputs")
            archives = item.get("archival_outputs")
            checks = item.get("semantic_checks")
            if (
                not isinstance(outputs, list)
                or not outputs
                or len(outputs) != len(set(outputs))
                or not all(isinstance(value, str) for value in outputs)
                or not isinstance(archives, Mapping)
                or not all(isinstance(key, str) and isinstance(value, str) and value.strip() for key, value in archives.items())
                or not isinstance(checks, list)
                or not all(isinstance(check, Mapping) for check in checks)
            ):
                errors.append(f"EXECUTION_LOCK_OUTPUT_SCHEMA_DRIFT:{item_id}")
                continue
            unsafe = False
            for relative in outputs:
                candidate = Path(relative)
                if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
                    unsafe = True
            checked_paths = {check.get("path") for check in checks}
            if (
                unsafe
                or not set(archives).issubset(outputs)
                or checked_paths & set(archives)
                or set(outputs) != checked_paths | set(archives)
            ):
                errors.append(f"EXECUTION_LOCK_OUTPUT_COVERAGE_DRIFT:{item_id}")
    full_lock_reaudit: dict[str, Any] = {"state": "NOT_RUN"}
    try:
        namespace = frozen_supervisor_audit_namespace(lock)
        verified_lock, verified, supervisor_lock_snapshot = namespace["verify_lock"](
            EXECUTION_LOCK
        )
        if verified_lock != lock:
            raise EvidenceError("SUPERVISOR_FULL_LOCK_VALUE_DIVERGES")
        if not identity_claim_matches(lock_identity, supervisor_lock_snapshot):
            raise EvidenceError("SUPERVISOR_FULL_LOCK_SNAPSHOT_DIVERGES")
        full_lock_reaudit = {
            "state": "PASS",
            "verified_identity_key_set": sorted(verified),
            "verified_identities": {
                name: {
                    key: claim[key]
                    for key in ("path", "size_bytes", "sha256")
                }
                for name, claim in sorted(verified.items())
            },
            "all_item_declarations_revalidated": True,
        }
    except BaseException as error:
        message = f"SUPERVISOR_FULL_LOCK_REAUDIT_FAILED:{type(error).__name__}:{error}"
        errors.append(message)
        full_lock_reaudit = {"state": "FAIL", "error": message}
    return lock, {
        "state": "PASS" if not errors else "INVALID_EXECUTION_LOCK",
        "identity": lock_identity,
        "verified_relevant_identities": verified_identities,
        "supervisor_full_lock_reaudit": full_lock_reaudit,
        "errors": errors,
    }


def identity_claim_matches(claim: object, actual: Mapping[str, Any]) -> bool:
    return isinstance(claim, Mapping) and all(
        claim.get(key) == actual.get(key) for key in ("path", "size_bytes", "sha256")
    )


def expected_effective_environment(
    lock: Mapping[str, Any], item: Mapping[str, Any]
) -> dict[str, str]:
    policy = lock.get("policy")
    base = policy.get("base_environment") if isinstance(policy, Mapping) else None
    declared = item.get("env")
    if not isinstance(base, Mapping) or not isinstance(declared, Mapping):
        raise EvidenceError("LOCK_EFFECTIVE_ENVIRONMENT_SCHEMA_INVALID")
    if set(base) & set(declared) or "PWD" in base or "PWD" in declared:
        raise EvidenceError("LOCK_EFFECTIVE_ENVIRONMENT_OVERLAP")
    result: dict[str, str] = {}
    for source in (base, declared):
        for key, value in source.items():
            if (
                not isinstance(key, str)
                or not key
                or "=" in key
                or "\x00" in key
                or not isinstance(value, str)
                or "\x00" in value
            ):
                raise EvidenceError("LOCK_EFFECTIVE_ENVIRONMENT_VALUE_INVALID")
            result[key] = value
    result["PWD"] = str(ROOT)
    return result


def semantic_signature(
    value: Mapping[str, Any], base: Path, *, declaration: bool
) -> tuple[Any, ...]:
    kind = value.get("type")
    raw_path = value.get("path")
    if not isinstance(kind, str) or not isinstance(raw_path, str):
        raise EvidenceError("SEMANTIC_CHECK_SIGNATURE_INVALID")
    path = str((base / raw_path).absolute()) if declaration else raw_path
    if declaration and Path(raw_path).is_absolute():
        raise EvidenceError("SEMANTIC_CHECK_DECLARATION_PATH_ABSOLUTE")
    keys = {
        "rosbag_topic": ("topic",),
        "rosbag_timeline_equal": ("topic", "other_path"),
        "rosbag_topic_equal": ("topic", "other_path"),
        "rosbag_feature_extension": ("base_path",),
    }.get(kind, ())
    extras: list[tuple[str, Any]] = []
    for key in keys:
        if key in value:
            extras.append((key, value.get(key)))
    return kind, path, tuple(extras)


def validate_semantic_result_set(
    item: Mapping[str, Any], artifact_layer: Mapping[str, Any], base: Path
) -> list[str]:
    errors: list[str] = []
    results = artifact_layer.get("semantic_checks")
    declarations = item.get("semantic_checks")
    if not isinstance(results, list) or not isinstance(declarations, list):
        return ["SEMANTIC_CHECKS_MISSING"]
    if not results or not isinstance(results[0], Mapping) or (
        results[0].get("type") != "output_tree"
        or results[0].get("status") != "PASS"
    ):
        errors.append("OUTPUT_TREE_SEMANTIC_CHECK_MISSING")
        result_rows = results
    else:
        result_rows = results[1:]
    if any(
        not isinstance(check, Mapping) or check.get("status") != "PASS"
        for check in result_rows
    ):
        errors.append("SEMANTIC_CHECK_NOT_PASS")
        return errors
    try:
        expected = Counter(
            semantic_signature(check, base, declaration=True)
            for check in declarations
            if isinstance(check, Mapping)
        )
        actual = Counter(
            semantic_signature(check, base, declaration=False)
            for check in result_rows
            if isinstance(check, Mapping)
        )
        if expected != actual:
            errors.append("SEMANTIC_CHECK_DECLARATION_RESULT_SET_MISMATCH")
    except EvidenceError as error:
        errors.append(str(error))
    return errors


_SUPERVISOR_AUDIT_NAMESPACE: Optional[dict[str, Any]] = None


def frozen_supervisor_audit_namespace(lock: Mapping[str, Any]) -> dict[str, Any]:
    """Load only the lock-pinned supervisor definitions for read-only re-audit."""
    global _SUPERVISOR_AUDIT_NAMESPACE
    if _SUPERVISOR_AUDIT_NAMESPACE is not None:
        return _SUPERVISOR_AUDIT_NAMESPACE
    identities = lock.get("identities")
    expected = identities.get("supervisor") if isinstance(identities, Mapping) else None
    supervisor_path = ROOT / "scripts/run_samehistory_system_a10_finalonline_v1.py"
    actual_before = identity(supervisor_path)
    if not isinstance(expected, Mapping) or dict(expected) != actual_before:
        raise EvidenceError("SUPERVISOR_NOT_LOCK_PINNED_FOR_SEMANTIC_REAUDIT")
    try:
        source = supervisor_path.read_bytes()
    except OSError as error:
        raise EvidenceError(f"SUPERVISOR_SOURCE_READ_FAILED:{error}") from error
    source_claim = {
        "path": str(supervisor_path.absolute()),
        "size_bytes": len(source),
        "sha256": hashlib.sha256(source).hexdigest(),
    }
    actual_after = identity(supervisor_path)
    if source_claim != actual_before or actual_after != actual_before:
        raise EvidenceError("SUPERVISOR_CHANGED_DURING_SEMANTIC_REAUDIT_LOAD")
    namespace: dict[str, Any] = {
        "__name__": "_a10_frozen_supervisor_readonly_audit",
        "__file__": str(supervisor_path),
        "__package__": None,
    }
    try:
        exec(compile(source, str(supervisor_path), "exec"), namespace)
    except BaseException as error:
        raise EvidenceError(
            f"SUPERVISOR_AUDIT_DEFINITION_LOAD_FAILED:{type(error).__name__}:{error}"
        ) from error
    for name in ("validate_output_tree", "semantic_check"):
        if not callable(namespace.get(name)):
            raise EvidenceError(f"SUPERVISOR_AUDIT_FUNCTION_MISSING:{name}")
    _SUPERVISOR_AUDIT_NAMESPACE = namespace
    return namespace


def independent_semantic_reaudit(
    item_id: str, item: Mapping[str, Any], lock: Mapping[str, Any]
) -> dict[str, Any]:
    """Re-run every lock-declared output check without launching a child process."""
    namespace = frozen_supervisor_audit_namespace(lock)
    validate_output_tree = namespace["validate_output_tree"]
    semantic_check = namespace["semantic_check"]
    try:
        tree = validate_output_tree(item, receipt_may_exist=True)
        # The supervisor recorded output_tree immediately before publishing its
        # receipt.  The only newly present file is that immutable receipt itself.
        receipt_path = str(RECEIPTS[item_id].absolute())
        seen_files = list(tree.get("seen_files", []))
        if receipt_path not in seen_files:
            raise EvidenceError("SEMANTIC_REAUDIT_RECEIPT_NOT_IN_OUTPUT_TREE")
        tree = dict(tree)
        tree["seen_files"] = [path for path in seen_files if path != receipt_path]
        results: list[dict[str, Any]] = [
            {"type": "output_tree", **tree, "status": "PASS"}
        ]
        declarations = item.get("semantic_checks")
        if not isinstance(declarations, list):
            raise EvidenceError("SEMANTIC_REAUDIT_DECLARATIONS_MISSING")
        for declaration in declarations:
            if not isinstance(declaration, Mapping):
                raise EvidenceError("SEMANTIC_REAUDIT_DECLARATION_NOT_OBJECT")
            result = semantic_check(item, declaration)
            if not isinstance(result, Mapping) or result.get("status") != "PASS":
                raise EvidenceError("SEMANTIC_REAUDIT_RESULT_NOT_PASS")
            results.append(clean_json(dict(result)))
        if item.get("kind") == "learned_sidecar_build":
            extension = next(
                (row for row in results if row.get("type") == "rosbag_feature_extension"),
                None,
            )
            stats = next(
                (row for row in results if row.get("type") == "csv_rows"), None
            )
            injected = (
                stats.get("column_sums", {}).get("selector_injected_observations")
                if isinstance(stats, Mapping)
                else None
            )
            if (
                not isinstance(extension, Mapping)
                or injected != extension.get("added_observations")
            ):
                raise EvidenceError(
                    "SEMANTIC_REAUDIT_LEARNED_BUILD_INJECTION_SUM_MISMATCH"
                )
    except EvidenceError:
        raise
    except BaseException as error:
        raise EvidenceError(
            f"SEMANTIC_REAUDIT_FAILED:{type(error).__name__}:{error}"
        ) from error
    payload = json.dumps(
        clean_json(results), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return {
        "state": "PASS",
        "lock_declaration_count": len(declarations),
        "result_count_including_output_tree": len(results),
        "results_sha256": hashlib.sha256(payload).hexdigest(),
        "results": results,
    }


def audit_receipt(
    item_id: str,
    lock: Optional[Mapping[str, Any]],
    lock_identity: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    path = RECEIPTS[item_id]
    if not path.exists() and not path.is_symlink():
        return {
            "item_id": item_id,
            "path": str(path),
            "state": "PENDING_MISSING_RECEIPT",
            "terminal": False,
            "successful": False,
            "errors": ["FORMAL_RUN_RECEIPT_MISSING"],
        }
    try:
        value = read_json(path)
        receipt_identity = identity(path)
    except EvidenceError as error:
        return {
            "item_id": item_id,
            "path": str(path),
            "state": "INVALID_RECEIPT",
            "terminal": False,
            "successful": False,
            "errors": [str(error)],
        }

    errors: list[str] = []
    blocking_reasons: list[str] = []
    terminal_layer = value.get("terminal_process")
    artifact_layer = value.get("artifact_contract")
    execution_layer = value.get("execution_integrity")
    score_layer = value.get("score_usability")
    status_value = terminal_layer.get("status") if isinstance(terminal_layer, Mapping) else None
    terminal = status_value in {"TERMINAL_PROCESS_RC0", "TERMINAL_PROCESS_FAILED"}
    if value.get("schema_version") != SUPERVISOR_SCHEMA:
        errors.append("RECEIPT_SCHEMA_DRIFT")
    if value.get("item_id") != item_id:
        errors.append("RECEIPT_ITEM_ID_MISMATCH")
    if not terminal:
        errors.append("RECEIPT_NOT_TERMINAL")
    if value.get("launch_allowance_consumed") is not True:
        errors.append("LAUNCH_ALLOWANCE_NOT_CONSUMED")
    if value.get("status") != status_value:
        errors.append("TOP_LEVEL_TERMINAL_STATUS_ALIAS_MISMATCH")
    if not isinstance(artifact_layer, Mapping):
        errors.append("ARTIFACT_CONTRACT_LAYER_MISSING")
        artifact_layer = {}
    if not isinstance(execution_layer, Mapping):
        errors.append("EXECUTION_INTEGRITY_LAYER_MISSING")
        execution_layer = {}
    if not isinstance(score_layer, Mapping):
        errors.append("SCORE_USABILITY_LAYER_MISSING")
        score_layer = {}
    if lock_identity is None:
        errors.append("EXECUTION_LOCK_NOT_AVAILABLE_FOR_BINDING")
    elif value.get("execution_lock") != dict(lock_identity):
        errors.append("RECEIPT_EXECUTION_LOCK_IDENTITY_MISMATCH")

    claim_path = ITEM_DIRS[item_id] / CLAIM_NAME
    claim: Mapping[str, Any] = {}
    claim_identity: Optional[dict[str, Any]] = None
    try:
        claim = read_json(claim_path)
        claim_identity = identity(claim_path)
        if value.get("claim") != claim_identity:
            errors.append("RECEIPT_CLAIM_IDENTITY_MISMATCH")
        if claim.get("schema_version") != SUPERVISOR_SCHEMA:
            errors.append("CLAIM_SCHEMA_DRIFT")
        if claim.get("item_id") != item_id:
            errors.append("CLAIM_ITEM_ID_MISMATCH")
        if claim.get("retry_count") != 0:
            errors.append("CLAIM_RETRY_COUNT_NOT_ZERO")
        if claim.get("popen_invocation_count_at_claim") != 0:
            errors.append("CLAIM_PRELAUNCH_POPEN_COUNT_NOT_ZERO")
        if claim.get("launch_allowance_consumed") is not True:
            errors.append("CLAIM_LAUNCH_ALLOWANCE_NOT_CONSUMED")
        if lock_identity is not None and claim.get("execution_lock") != dict(lock_identity):
            errors.append("CLAIM_EXECUTION_LOCK_IDENTITY_MISMATCH")
    except EvidenceError as error:
        errors.append(f"CLAIM_INVALID:{error}")

    item = None
    if isinstance(lock, Mapping) and isinstance(lock.get("items"), Mapping):
        candidate = lock["items"].get(item_id)
        if isinstance(candidate, Mapping):
            item = candidate
    if item is None:
        errors.append("EXECUTION_LOCK_ITEM_UNAVAILABLE_FOR_RECEIPT_AUDIT")
    elif claim:
        try:
            if value.get("kind") != item.get("kind"):
                errors.append("RECEIPT_KIND_LOCK_MISMATCH")
            if claim.get("argv") != item.get("argv"):
                errors.append("CLAIM_ARGV_LOCK_MISMATCH")
            if claim.get("effective_environment") != expected_effective_environment(lock, item):
                errors.append("CLAIM_EFFECTIVE_ENVIRONMENT_LOCK_MISMATCH")
        except EvidenceError as error:
            errors.append(str(error))

    process_log_identity: Optional[dict[str, Any]] = None
    process_log_claim = value.get("process_log")
    if process_log_claim is not None:
        process_log_path = ITEM_DIRS[item_id] / LOG_NAME
        try:
            process_log_identity = identity(process_log_path)
            if not identity_claim_matches(process_log_claim, process_log_identity):
                errors.append("RECEIPT_PROCESS_LOG_IDENTITY_MISMATCH")
        except EvidenceError as error:
            errors.append(f"RECEIPT_PROCESS_LOG_INVALID:{error}")
    elif status_value == "TERMINAL_PROCESS_RC0":
        errors.append("RECEIPT_RC0_PROCESS_LOG_MISSING")

    output_identity_errors: list[str] = []
    semantic_reaudit: dict[str, Any] = {"state": "NOT_APPLICABLE"}
    recorded_outputs = artifact_layer.get("outputs")
    if not isinstance(recorded_outputs, Mapping):
        output_identity_errors.append("RECEIPT_OUTPUT_MAP_MISSING")
    elif item is not None:
        expected_paths = {
            str((ITEM_DIRS[item_id] / relative).absolute())
            for relative in item.get("expected_outputs", [])
            if isinstance(relative, str)
        }
        recorded_paths = set(recorded_outputs)
        if not recorded_paths.issubset(expected_paths):
            output_identity_errors.append("RECEIPT_OUTPUT_MAP_HAS_UNDECLARED_PATH")
        if artifact_layer.get("status") == "PASS" and recorded_paths != expected_paths:
            output_identity_errors.append("RECEIPT_OUTPUT_MAP_NOT_EXACT")
        for raw_path in sorted(recorded_paths & expected_paths):
            required = Path(raw_path)
            try:
                actual = identity(required)
            except EvidenceError as error:
                output_identity_errors.append(str(error))
                continue
            if not identity_claim_matches(recorded_outputs.get(str(required)), actual):
                output_identity_errors.append(
                    f"RECEIPT_OUTPUT_IDENTITY_MISMATCH:{required}"
                )
    errors.extend(output_identity_errors)

    layer_contract_errors: list[str] = []
    if terminal:
        popen_count = terminal_layer.get("popen_invocation_count")
        child_started = terminal_layer.get("child_started")
        raw_return_code = terminal_layer.get("raw_return_code")
        timed_out = terminal_layer.get("timed_out")
        raw_fields_typed = bool(
            isinstance(popen_count, int)
            and not isinstance(popen_count, bool)
            and isinstance(child_started, bool)
            and isinstance(timed_out, bool)
            and (
                raw_return_code is None
                or (
                    isinstance(raw_return_code, int)
                    and not isinstance(raw_return_code, bool)
                )
            )
        )
        if not raw_fields_typed:
            layer_contract_errors.append("TERMINAL_RAW_FIELD_TYPES_INVALID")
        if item is not None and terminal_layer.get("timeout_seconds") != item.get(
            "timeout_seconds"
        ):
            layer_contract_errors.append("TERMINAL_TIMEOUT_LOCK_MISMATCH")
        if status_value == "TERMINAL_PROCESS_RC0":
            if (
                not raw_fields_typed
                or popen_count != 1
                or child_started is not True
                or raw_return_code != 0
                or timed_out is not False
            ):
                layer_contract_errors.append("RC0_TERMINAL_RAW_FIELDS_MISMATCH")
        else:
            if (
                not raw_fields_typed
                or popen_count not in {0, 1}
                or (popen_count == 0 and child_started is not False)
                or (popen_count == 0 and raw_return_code is not None)
                or (
                    popen_count == 1
                    and child_started is True
                    and raw_return_code == 0
                    and timed_out is False
                )
            ):
                layer_contract_errors.append("FAILED_TERMINAL_RAW_FIELDS_MISMATCH")
        process_group = terminal_layer.get("process_group")
        if not isinstance(process_group, Mapping) or any(
            process_group.get(key) is not True
            for key in ("leader_reaped", "process_group_empty", "owned_descendants_empty")
        ):
            layer_contract_errors.append("PROCESS_GROUP_NOT_DRAINED")
    if artifact_layer.get("status") not in {"PASS", "FAIL"}:
        layer_contract_errors.append("ARTIFACT_STATUS_INVALID")
    if execution_layer.get("status") not in {"PASS", "FAIL"}:
        layer_contract_errors.append("EXECUTION_STATUS_INVALID")
    if score_layer.get("status") not in {"PASS", "FAIL", "NOT_APPLICABLE"}:
        layer_contract_errors.append("SCORE_STATUS_INVALID")
    if artifact_layer.get("status") == "PASS":
        if artifact_layer.get("issues") != []:
            layer_contract_errors.append("ARTIFACT_PASS_WITH_ISSUES")
        if item is not None:
            layer_contract_errors.extend(
                validate_semantic_result_set(item, artifact_layer, ITEM_DIRS[item_id])
            )
            if isinstance(lock, Mapping):
                try:
                    recomputed = independent_semantic_reaudit(item_id, item, lock)
                    claimed_results = artifact_layer.get("semantic_checks")
                    if claimed_results != recomputed["results"]:
                        layer_contract_errors.append(
                            "RECEIPT_SEMANTIC_RESULTS_DIVERGE_FROM_INDEPENDENT_REAUDIT"
                        )
                        semantic_reaudit = {
                            key: value
                            for key, value in recomputed.items()
                            if key != "results"
                        }
                        semantic_reaudit["state"] = "DIVERGED"
                    else:
                        semantic_reaudit = {
                            key: value
                            for key, value in recomputed.items()
                            if key != "results"
                        }
                        semantic_reaudit["matches_receipt_exactly"] = True
                except EvidenceError as error:
                    layer_contract_errors.append(str(error))
                    semantic_reaudit = {
                        "state": "FAIL",
                        "error": str(error),
                    }
    if execution_layer.get("status") == "PASS":
        if execution_layer.get("supervisor_error") is not None:
            layer_contract_errors.append("EXECUTION_PASS_WITH_SUPERVISOR_ERROR")
        for field in (
            "authority_before_popen", "authority_post", "dependency_bindings_post", "postflight"
        ):
            section = execution_layer.get(field)
            if not isinstance(section, Mapping) or section.get("status") != "PASS":
                layer_contract_errors.append(f"{field.upper()}_NOT_PASS")
        if item is not None and isinstance(lock, Mapping):
            try:
                expected_environment = expected_effective_environment(lock, item)
                if execution_layer.get("effective_environment") != expected_environment:
                    layer_contract_errors.append(
                        "EXECUTION_EFFECTIVE_ENVIRONMENT_LOCK_MISMATCH"
                    )
                for field in ("authority_before_popen", "authority_post"):
                    section = execution_layer.get(field)
                    if not isinstance(section, Mapping) or section.get("differences") != []:
                        layer_contract_errors.append(
                            f"{field.upper()}_AUTHORITY_DIFFERENCES_NOT_EMPTY"
                        )
                namespace = frozen_supervisor_audit_namespace(lock)
                lock_snapshot, _payload = namespace["snapshot"](
                    EXECUTION_LOCK, with_data=True
                )
                dependency_bindings = namespace["validate_dependencies"](
                    lock, lock_snapshot, item_id
                )
                if execution_layer.get("dependency_bindings_before") != dependency_bindings:
                    layer_contract_errors.append(
                        "DEPENDENCY_BINDINGS_BEFORE_DIVERGE_FROM_CURRENT_FROZEN_EVIDENCE"
                    )
                if execution_layer.get("dependency_bindings_post") != {
                    "status": "PASS",
                    "bindings": dependency_bindings,
                }:
                    layer_contract_errors.append(
                        "DEPENDENCY_BINDINGS_POST_DIVERGE_FROM_CURRENT_FROZEN_EVIDENCE"
                    )
            except BaseException as error:
                layer_contract_errors.append(
                    "EXECUTION_BINDING_REAUDIT_FAILED:"
                    f"{type(error).__name__}:{error}"
                )
    expected_score_status = "PASS" if item_id in VINS_ARMS else "NOT_APPLICABLE"
    score_crosscheck: dict[str, Any] = {"state": "NOT_APPLICABLE"}
    if item_id not in VINS_ARMS:
        if dict(score_layer) != {"status": "NOT_APPLICABLE", "failure_codes": []}:
            layer_contract_errors.append("FRONTEND_SCORE_LAYER_NOT_EXACT")
    elif (
        artifact_layer.get("status") == "PASS"
        and execution_layer.get("status") == "PASS"
    ):
        score_crosscheck = crosscheck_receipt_score_layer(item_id, score_layer)
        if score_crosscheck.get("state") != "PASS":
            layer_contract_errors.append(
                "RECEIPT_SCORE_USABILITY_FULL_AUDIT_DIVERGES"
            )
    if status_value != "TERMINAL_PROCESS_RC0":
        blocking_reasons.append("TERMINAL_PROCESS_NOT_RC0")
    if artifact_layer.get("status") != "PASS":
        blocking_reasons.append("ARTIFACT_CONTRACT_NOT_PASS")
    if execution_layer.get("status") != "PASS":
        blocking_reasons.append("EXECUTION_INTEGRITY_NOT_PASS")
    if item_id in VINS_ARMS and score_layer.get("status") != "PASS":
        blocking_reasons.append("SCORE_USABILITY_NOT_PASS")
    expected_disposition = (
        "ACCEPTED"
        if not blocking_reasons
        else "PROCESS_FAILED"
        if status_value != "TERMINAL_PROCESS_RC0"
        else "EXECUTION_INTEGRITY_FAILED"
        if execution_layer.get("status") != "PASS"
        else "ARTIFACT_CONTRACT_FAILED"
        if artifact_layer.get("status") != "PASS"
        else "RETAINED_UNUSABLE_SCORE"
    )
    if value.get("overall_disposition") != expected_disposition:
        layer_contract_errors.append("OVERALL_DISPOSITION_MISMATCH")
    errors.extend(layer_contract_errors)

    terminal_valid = bool(terminal and not errors)
    process_artifact_execution_successful = bool(
        terminal_valid
        and status_value == "TERMINAL_PROCESS_RC0"
        and artifact_layer.get("status") == "PASS"
        and execution_layer.get("status") == "PASS"
    )
    score_successful = score_layer.get("status") == expected_score_status
    successful = bool(process_artifact_execution_successful and score_successful)
    state = (
        "TERMINAL_SUCCESS"
        if successful
        else "TERMINAL_RETAINED_UNUSABLE_SCORE"
        if process_artifact_execution_successful and item_id in VINS_ARMS
        else "TERMINAL_RETAINED_FAILURE"
        if terminal_valid
        else "TERMINAL_INVALID"
        if terminal
        else "INVALID_RECEIPT"
    )
    return {
        "item_id": item_id,
        "path": str(path),
        "state": state,
        "terminal": terminal,
        "terminal_valid": terminal_valid,
        "process_artifact_execution_successful": process_artifact_execution_successful,
        "score_successful": score_successful,
        "successful": successful,
        "receipt_status": status_value,
        "artifact_contract_status": artifact_layer.get("status"),
        "execution_integrity_status": execution_layer.get("status"),
        "score_usability_status": score_layer.get("status"),
        "score_usability": clean_json(dict(score_layer)),
        "score_usability_crosscheck": score_crosscheck,
        "independent_semantic_reaudit": semantic_reaudit,
        "overall_disposition": value.get("overall_disposition"),
        "raw_return_code": terminal_layer.get("raw_return_code") if isinstance(terminal_layer, Mapping) else None,
        "timed_out": terminal_layer.get("timed_out") if isinstance(terminal_layer, Mapping) else None,
        "supervisor_error": execution_layer.get("supervisor_error"),
        "started_at_local": value.get("started_at_local"),
        "ended_at_local": value.get("ended_at_local"),
        "wall_time_seconds": value.get("wall_time_seconds"),
        "identity": receipt_identity,
        "claim_identity": claim_identity,
        "process_log_identity": process_log_identity,
        "artifact_outputs": clean_json(dict(recorded_outputs))
        if isinstance(recorded_outputs, Mapping)
        else None,
        "blocking_reasons": blocking_reasons,
        "errors": errors,
    }


INTEGER_NS = re.compile(r"\d+")


def parse_integer_ns(raw: str) -> int:
    text = raw.strip()
    if INTEGER_NS.fullmatch(text) is None:
        raise ValueError("timestamp is not an integer nanosecond value")
    return int(text)


def decimal_seconds_to_ns(raw: str) -> int:
    try:
        value = Decimal(raw) * Decimal("1000000000")
    except InvalidOperation as error:
        raise ValueError("invalid decimal seconds") from error
    if not value.is_finite():
        raise ValueError("non-finite decimal seconds")
    rounded = value.to_integral_value(rounding=ROUND_HALF_EVEN)
    if abs(value - rounded) > Decimal("0.5"):
        raise ValueError("timestamp cannot be represented as integer nanoseconds")
    return int(rounded)


def summarize_trajectory_stamps(
    path: Path,
    file_identity: Mapping[str, Any],
    stamps: Sequence[int],
    *,
    row_count: int,
    errors: Sequence[str],
) -> dict[str, Any]:
    error_list = list(errors)
    stamp_list = list(stamps)
    if not stamp_list:
        error_list.append("NO_VALID_POSES")
    if any(right <= left for left, right in zip(stamp_list, stamp_list[1:])):
        error_list.append("TIMESTAMPS_NOT_STRICTLY_INCREASING")
    score_stamps = [
        stamp for stamp in stamp_list if SCORE_START_NS <= stamp <= SCORE_END_NS
    ]
    score_span_ns = (
        score_stamps[-1] - score_stamps[0] if len(score_stamps) >= 2 else 0
    )
    gaps = [right - left for left, right in zip(score_stamps, score_stamps[1:])]
    boundary_and_adjacent_gaps = (
        [score_stamps[0] - SCORE_START_NS, *gaps, SCORE_END_NS - score_stamps[-1]]
        if score_stamps else []
    )
    return {
        "state": "VALID" if not error_list else "INVALID",
        "path": str(path),
        "identity": dict(file_identity),
        "valid": not error_list,
        "errors": error_list,
        "pose_count": row_count,
        "valid_pose_count": len(stamp_list),
        "first_timestamp_ns": stamp_list[0] if stamp_list else None,
        "last_timestamp_ns": stamp_list[-1] if stamp_list else None,
        "strictly_increasing": bool(stamp_list) and not any(
            right <= left for left, right in zip(stamp_list, stamp_list[1:])
        ),
        "score_pose_count": len(score_stamps),
        "score_first_timestamp_ns": score_stamps[0] if score_stamps else None,
        "score_last_timestamp_ns": score_stamps[-1] if score_stamps else None,
        "score_temporal_span_s": score_span_ns / 1e9,
        "score_temporal_span_fraction": score_span_ns / SCORE_DURATION_NS,
        "score_first_boundary_gap_s": (
            (score_stamps[0] - SCORE_START_NS) / 1e9 if score_stamps else None
        ),
        "score_last_boundary_gap_s": (
            (SCORE_END_NS - score_stamps[-1]) / 1e9 if score_stamps else None
        ),
        "score_median_adjacent_gap_s": (
            sorted(gaps)[len(gaps) // 2] / 1e9 if gaps else None
        ),
        "score_max_adjacent_gap_s": max(gaps) / 1e9 if gaps else None,
        "score_max_output_gap_including_boundaries_s": (
            max(boundary_and_adjacent_gaps) / 1e9
            if boundary_and_adjacent_gaps else None
        ),
        "score_adjacent_gap_gt_0_5s_count": sum(
            gap > MAX_SCORE_GAP_NS for gap in gaps
        ),
        "stamps_ns": stamp_list,
    }


def audit_trajectory(path: Path) -> dict[str, Any]:
    """Strictly audit a native VINS CSV (exactly 11 columns)."""
    if not path.exists() and not path.is_symlink():
        return {
            "state": "MISSING",
            "path": str(path),
            "valid": False,
            "errors": ["TRAJECTORY_MISSING"],
            "stamps_ns": [],
        }
    errors: list[str] = []
    stamps: list[int] = []
    malformed = 0
    nonfinite = 0
    invalid_quaternion_norm = 0
    try:
        file_identity = identity(path)
        with path.open(newline="", encoding="utf-8", errors="strict") as handle:
            for line_number, row in enumerate(csv.reader(handle), 1):
                fields = list(row)
                if len(fields) == 12 and fields[-1] == "":
                    fields.pop()
                if len(fields) != 11:
                    malformed += 1
                    continue
                try:
                    stamp = parse_integer_ns(fields[0])
                    numeric = [float(value) for value in fields[1:]]
                except ValueError:
                    malformed += 1
                    continue
                if not all(math.isfinite(value) for value in numeric):
                    nonfinite += 1
                    continue
                quaternion = numeric[3:7]
                quaternion_norm = math.sqrt(sum(value * value for value in quaternion))
                if not 0.95 <= quaternion_norm <= 1.05:
                    invalid_quaternion_norm += 1
                    continue
                stamps.append(stamp)
    except (EvidenceError, OSError, UnicodeError) as error:
        return {
            "state": "INVALID",
            "path": str(path),
            "valid": False,
            "errors": [f"TRAJECTORY_READ_ERROR:{type(error).__name__}:{error}"],
            "stamps_ns": [],
        }
    if malformed:
        errors.append(f"MALFORMED_ROWS:{malformed}")
    if nonfinite:
        errors.append(f"NONFINITE_ROWS:{nonfinite}")
    if invalid_quaternion_norm:
        errors.append(f"INVALID_QUATERNION_NORM_ROWS:{invalid_quaternion_norm}")
    return summarize_trajectory_stamps(
        path,
        file_identity,
        stamps,
        row_count=len(stamps) + malformed + nonfinite + invalid_quaternion_norm,
        errors=errors,
    )


def parse_score_log_events(path: Path) -> dict[str, Any]:
    """Byte-for-byte equivalent score-event parser to supervisor-v3."""

    ansi = re.compile(r"\x1b\[[0-9;]*m")
    ros_sim = re.compile(r"\[[^\],]+,\s*([0-9]+(?:\.[0-9]+)?)\]")
    plain_time = re.compile(r"\btime:\s*([0-9]+(?:\.[0-9]+)?)")
    failure_pattern = re.compile(
        r"linear solver failure|\bfail(?:ed|ure)?\b|\bfatal\b.*\btrack|"
        r"\btracking\s+(?:is\s+)?lost\b",
        re.IGNORECASE,
    )
    restart_pattern = re.compile(
        r"clear\s*state|\b(?:restart(?:ed|ing)?|reset(?:ting)?|reboot)\b",
        re.IGNORECASE,
    )
    init_pattern = re.compile(r"initialization finish", re.IGNORECASE)

    def seconds_to_ns(raw: str) -> int:
        whole, dot, fractional = raw.partition(".")
        fraction = (fractional + "000000000")[:9] if dot else "000000000"
        return int(whole) * 1_000_000_000 + int(fraction)

    parsed_lines: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8", errors="strict").splitlines(), start=1
    ):
        line = ansi.sub("", raw_line)
        direct = ros_sim.search(line) or plain_time.search(line)
        parsed_lines.append(
            {
                "line": line_number,
                "text": line,
                "sim_stamp_ns": (
                    seconds_to_ns(direct.group(1)) if direct is not None else None
                ),
            }
        )

    previous: list[Optional[int]] = []
    latest: Optional[int] = None
    for row in parsed_lines:
        if row["sim_stamp_ns"] is not None:
            latest = int(row["sim_stamp_ns"])
        previous.append(latest)
    following: list[Optional[int]] = [None] * len(parsed_lines)
    latest = None
    for index in range(len(parsed_lines) - 1, -1, -1):
        if parsed_lines[index]["sim_stamp_ns"] is not None:
            latest = int(parsed_lines[index]["sim_stamp_ns"])
        following[index] = latest

    def segment(stamp: int) -> str:
        if stamp < SCORE_START_NS:
            return "PREFIX"
        if stamp <= SCORE_END_NS:
            return "SCORE"
        return "POST_SCORE"

    events: list[dict[str, Any]] = []
    initialization_events: list[dict[str, Any]] = []
    for index, row in enumerate(parsed_lines):
        line_number, line = int(row["line"]), str(row["text"])
        exact_stamp = row["sim_stamp_ns"]
        if exact_stamp is not None:
            attribution = segment(int(exact_stamp))
        else:
            contextual_segments = {
                segment(stamp)
                for stamp in (previous[index], following[index])
                if stamp is not None
            }
            attribution = (
                next(iter(contextual_segments))
                if len(contextual_segments) == 1
                else "UNRESOLVED"
            )
        categories: list[str] = []
        if failure_pattern.search(line):
            categories.append("failure")
        if restart_pattern.search(line):
            categories.append("restart_or_reset")
        if init_pattern.search(line):
            initialization_events.append(
                {
                    "line": line_number,
                    "sim_stamp_ns": exact_stamp,
                    "attribution": attribution,
                    "within_or_before_score_end": attribution in {"PREFIX", "SCORE"},
                }
            )
        if categories:
            events.append(
                {
                    "line": line_number,
                    "categories": categories,
                    "sim_stamp_ns": exact_stamp,
                    "score_attribution": attribution,
                    "text_sha256": hashlib.sha256(line.encode()).hexdigest(),
                }
            )
    score_events = [event for event in events if event["score_attribution"] == "SCORE"]
    unresolved = [event for event in events if event["score_attribution"] == "UNRESOLVED"]
    return {
        "events": events,
        "score_failure_events": sum(
            "failure" in event["categories"] for event in score_events
        ),
        "score_restart_or_reset_events": sum(
            "restart_or_reset" in event["categories"] for event in score_events
        ),
        "unresolved_event_count": len(unresolved),
        "initialization_events": initialization_events,
    }


def audit_vins_log(path: Path) -> dict[str, Any]:
    try:
        file_identity = identity(path)
        core = parse_score_log_events(path)
    except (EvidenceError, OSError, UnicodeError, ValueError) as error:
        return {
            "state": "INVALID",
            "path": str(path),
            "errors": [f"VINS_LOG_READ_ERROR:{type(error).__name__}:{error}"],
        }
    return {
        "state": "READ",
        "path": str(path),
        "identity": file_identity,
        "errors": [],
        "receipt_log_event_audit": core,
        "events": core["events"],
        "score_failure_mentions": core["score_failure_events"],
        "score_restart_or_reset_events": core["score_restart_or_reset_events"],
        "unresolved_failure_or_reset_events": core["unresolved_event_count"],
        "initialization_events_at_or_before_score_end": sum(
            event.get("within_or_before_score_end") is True
            for event in core["initialization_events"]
        ),
    }


def parse_ape_values(path: Path) -> dict[str, int | float]:
    values: dict[str, int | float] = {}
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    if not lines:
        raise EvidenceError(f"APE_EMPTY:{path}")
    for line_number, line in enumerate(lines, start=1):
        if not line or line.count("=") != 1:
            raise EvidenceError(f"APE_LINE_INVALID:{path}:{line_number}")
        key, raw = line.split("=", 1)
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key) or key in values:
            raise EvidenceError(f"APE_KEY_INVALID_OR_DUPLICATE:{path}:{line_number}")
        try:
            value = float(raw)
        except ValueError as error:
            raise EvidenceError(f"APE_VALUE_INVALID:{path}:{line_number}") from error
        if not math.isfinite(value):
            raise EvidenceError(f"APE_VALUE_NONFINITE:{path}:{line_number}")
        values[key] = value
    if "init_success" not in values or abs(float(values["init_success"]) - round(float(values["init_success"]))) > 1e-9:
        raise EvidenceError(f"APE_INIT_SUCCESS_INVALID:{path}")
    values["init_success"] = int(round(float(values["init_success"])))
    return values


def reaudit_score_usability(
    trajectory: Mapping[str, Any], log: Mapping[str, Any], ape_init_success: Any
) -> dict[str, Any]:
    failures: list[str] = []
    score_rows = exact_integer(trajectory.get("score_pose_count"), "score_pose_count")
    first_stamp = trajectory.get("score_first_timestamp_ns")
    last_stamp = trajectory.get("score_last_timestamp_ns")
    coverage = finite_number(
        trajectory.get("score_temporal_span_fraction"), "score_temporal_span_fraction"
    )
    maximum_gap_raw = trajectory.get("score_max_adjacent_gap_s")
    maximum_gap = (
        finite_number(maximum_gap_raw, "score_max_adjacent_gap_s")
        if maximum_gap_raw is not None else None
    )
    result: dict[str, Any] = {
        "score_start_ns": SCORE_START_NS,
        "score_end_ns": SCORE_END_NS,
        "crop_interval": "inclusive",
        "failure_codes": failures,
        "full_trajectory_rows": exact_integer(
            trajectory.get("valid_pose_count"), "valid_pose_count"
        ),
        "score_trajectory_rows": score_rows,
        "score_first_stamp_ns": first_stamp,
        "score_last_stamp_ns": last_stamp,
        "score_temporal_span_coverage": coverage,
        "maximum_score_output_gap_s": maximum_gap,
    }
    if score_rows < 2:
        failures.append("INSUFFICIENT_SCORE_TRAJECTORY_ROWS")
    if coverage < MIN_SCORE_SPAN_FRACTION:
        failures.append("SCORE_TEMPORAL_SPAN_COVERAGE_BELOW_GATE")
    if maximum_gap is None or maximum_gap > MAX_SCORE_GAP_NS / 1e9:
        failures.append("SCORE_OUTPUT_GAP_ABOVE_GATE")
    result["ape_init_success"] = ape_init_success
    if ape_init_success != 1:
        failures.append("APE_INITIALIZATION_NOT_SUCCESSFUL")
    core = log.get("receipt_log_event_audit")
    if not isinstance(core, Mapping):
        raise EvidenceError("VINS_LOG_CORE_AUDIT_MISSING")
    core_value = clean_json(dict(core))
    result["log_event_audit"] = core_value
    initialized_in_time = any(
        isinstance(event, Mapping)
        and event.get("within_or_before_score_end") is True
        for event in core_value.get("initialization_events", [])
    )
    result["initialization_before_or_within_score_end"] = initialized_in_time
    if not initialized_in_time:
        failures.append("NO_INITIALIZATION_EVENT_BEFORE_SCORE_END")
    if exact_integer(core_value.get("score_failure_events"), "score_failure_events") > 0:
        failures.append("SCORE_FAILURE_EVENT_GATE_EXCEEDED")
    if exact_integer(
        core_value.get("score_restart_or_reset_events"),
        "score_restart_or_reset_events",
    ) > 0:
        failures.append("SCORE_RESTART_RESET_GATE_EXCEEDED")
    if exact_integer(core_value.get("unresolved_event_count"), "unresolved_event_count"):
        failures.append("UNRESOLVED_LOG_EVENT_ATTRIBUTION")
    result["failure_codes"] = failures
    result["status"] = "PASS" if not failures else "FAIL"
    return result


def crosscheck_receipt_score_layer(
    arm: str, receipt_score: Mapping[str, Any]
) -> dict[str, Any]:
    paths = VINS_PATHS[arm]
    trajectory = audit_trajectory(paths.trajectory)
    log = audit_vins_log(paths.log)
    errors: list[str] = []
    if not trajectory.get("valid"):
        errors.append("SCORE_CROSSCHECK_TRAJECTORY_INVALID")
    if log.get("state") != "READ":
        errors.append("SCORE_CROSSCHECK_LOG_INVALID")
    try:
        ape_values = parse_ape_values(paths.legacy_ape)
    except (EvidenceError, OSError, UnicodeError) as error:
        ape_values = {}
        errors.append(f"SCORE_CROSSCHECK_APE_INVALID:{error}")
    recomputed: Optional[dict[str, Any]] = None
    if not errors:
        try:
            recomputed = reaudit_score_usability(
                trajectory, log, ape_values.get("init_success")
            )
        except EvidenceError as error:
            errors.append(f"SCORE_CROSSCHECK_RECOMPUTE_INVALID:{error}")
    exact_match = recomputed is not None and dict(receipt_score) == recomputed
    if not exact_match:
        errors.append("SCORE_CROSSCHECK_RECEIPT_FIELDS_NOT_EXACT")
    return {
        "state": "PASS" if not errors else "DIVERGED",
        "exact_full_layer_match": exact_match,
        "recomputed_score_usability": recomputed,
        "errors": errors,
    }


def vins_usability(arm: str, receipt: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    paths = VINS_PATHS[arm]
    trajectory = audit_trajectory(paths.trajectory)
    log = audit_vins_log(paths.log)
    failures: list[str] = []
    if not trajectory.get("valid"):
        failures.append("TRAJECTORY_NOT_FINITE_STRICT_INTEGER_NS")
    if log.get("state") != "READ":
        failures.append("VINS_LOG_INVALID_OR_MISSING")
    try:
        ape_values = parse_ape_values(paths.legacy_ape)
    except (EvidenceError, OSError, UnicodeError) as error:
        ape_values = {}
        failures.append(f"APE_AUDIT_INVALID:{error}")
    score_reaudit: Optional[dict[str, Any]] = None
    if not failures:
        try:
            score_reaudit = reaudit_score_usability(
                trajectory, log, ape_values.get("init_success")
            )
            failures.extend(score_reaudit["failure_codes"])
        except EvidenceError as error:
            failures.append(f"SCORE_REAUDIT_INVALID:{error}")
    receipt_score = receipt.get("score_usability") if isinstance(receipt, Mapping) else None
    if not isinstance(receipt_score, Mapping):
        failures.append("RECEIPT_SCORE_USABILITY_MISSING")
    elif score_reaudit is None or dict(receipt_score) != score_reaudit:
        failures.append("RECEIPT_SCORE_USABILITY_FULL_AUDIT_DIVERGES")
    if not isinstance(receipt_score, Mapping) or receipt_score.get("status") != "PASS":
        failures.append("RECEIPT_SCORE_USABILITY_NOT_PASS")
    return {
        "method": arm,
        "status": "PASS" if not failures else "FAIL",
        "failure_codes": list(dict.fromkeys(failures)),
        "trajectory": {
            key: value for key, value in trajectory.items() if key != "stamps_ns"
        },
        "runtime_log": log,
        "ape_values": ape_values,
        "score_reaudit": score_reaudit,
        "receipt_score_usability": receipt_score,
    }


def validate_hfnet_run_result() -> tuple[dict[str, Any], dict[str, Any]]:
    actual = exact_identity(HFNET_RUN_RESULT, HFNET_RUN_RESULT_EXPECTED, "HFNET_RUN_RESULT")
    value = read_json(HFNET_RUN_RESULT)
    errors: list[str] = []
    if value.get("schema_version") != (
        "aqua-fe-hfnet-v6-a10-0000-2800-score-2400-2800-warmstart-result-v1"
    ):
        errors.append("HFNET_RUN_RESULT_SCHEMA_DRIFT")
    if value.get("status") != "PASS_DEVELOPMENT_RUNABILITY_RESCUE":
        errors.append("HFNET_RUN_RESULT_STATUS_DRIFT")
    if value.get("errors") != [] or value.get("failure_codes") != []:
        errors.append("HFNET_RUN_RESULT_HAS_FAILURES")
    execution = value.get("execution")
    if not isinstance(execution, Mapping) or (
        execution.get("popen_invocations") != 1
        or execution.get("raw_returncode") != 0
        or execution.get("retry_performed") is not False
        or execution.get("retry_permitted") is not False
        or execution.get("timed_out") is not False
        or execution.get("child_reaped_before_post_audit") is not True
    ):
        errors.append("HFNET_EXECUTION_CONTRACT_DRIFT")
    adjudication = value.get("score_adjudication")
    score = adjudication.get("score") if isinstance(adjudication, Mapping) else None
    runtime = adjudication.get("runtime_log") if isinstance(adjudication, Mapping) else None
    if not isinstance(adjudication, Mapping) or adjudication.get("passed") is not True:
        errors.append("HFNET_SCORE_NOT_PASSED")
    if not isinstance(score, Mapping) or (
        score.get("indices_inclusive") != [2400, 2800]
        or score.get("camera_count") != 401
        or score.get("pose_count") != 401
        or score.get("exact_401_of_401_contiguous") is not True
        or score.get("trajectory_crop") != HFNET_SCORE_CROP_EXPECTED
    ):
        errors.append("HFNET_SCORE_SUPPORT_DRIFT")
    if not isinstance(runtime, Mapping) or (
        runtime.get("valid") is not True
        or runtime.get("pre_score_initialized") is not True
        or runtime.get("score_window_reset_events") != []
        or runtime.get("score_window_init_frame_ids") != []
        or len(runtime.get("reset_events", [])) != 22
        or runtime.get("init_frame_ids", [])[-1:] != [2355]
    ):
        errors.append("HFNET_RUNTIME_HISTORY_DRIFT")
    return value, {"identity": actual, "errors": errors}


def audit_hfnet_bridge() -> dict[str, Any]:
    if not HFNET_BRIDGE.exists() and not HFNET_BRIDGE.is_symlink():
        return {
            "state": "PENDING_MISSING_SEALED_BRIDGE",
            "path": str(HFNET_BRIDGE),
            "valid": False,
            "errors": ["HFNET_BRIDGE_MISSING"],
        }
    errors: list[str] = []
    try:
        bridge_identity = exact_identity(
            HFNET_BRIDGE, HFNET_BRIDGE_EXPECTED, "HFNET_BRIDGE"
        )
        manifest = read_json(HFNET_BRIDGE_MANIFEST)
        manifest_identity = exact_identity(
            HFNET_BRIDGE_MANIFEST, HFNET_BRIDGE_MANIFEST_EXPECTED,
            "HFNET_BRIDGE_MANIFEST",
        )
        _run_result, run_audit = validate_hfnet_run_result()
        score_crop_identity = exact_identity(
            HFNET_SCORE_CROP, HFNET_SCORE_CROP_EXPECTED, "HFNET_SCORE_CROP"
        )
    except EvidenceError as error:
        return {
            "state": "INVALID_SEALED_BRIDGE",
            "path": str(HFNET_BRIDGE),
            "valid": False,
            "errors": [str(error)],
        }
    errors.extend(run_audit["errors"])
    if manifest.get("schema_version") != BRIDGE_SCHEMA:
        errors.append("HFNET_BRIDGE_MANIFEST_SCHEMA_DRIFT")
    if manifest.get("status") != "PASS_SEALED_BRIDGE":
        errors.append("HFNET_BRIDGE_MANIFEST_STATUS_DRIFT")
    if manifest.get("output") != HFNET_BRIDGE_EXPECTED:
        errors.append("HFNET_BRIDGE_MANIFEST_OUTPUT_DRIFT")
    if manifest.get("source") != HFNET_SCORE_CROP_EXPECTED:
        errors.append("HFNET_BRIDGE_MANIFEST_SOURCE_DRIFT")
    if manifest.get("row_count") != 401:
        errors.append("HFNET_BRIDGE_ROW_COUNT_DRIFT")
    semantics = manifest.get("semantics")
    if not isinstance(semantics, Mapping) or (
        semantics.get("input_pose") != "world_T_body"
        or semantics.get("output_pose") != "world_T_body"
        or semantics.get("input_quaternion_order") != "xyzw"
        or semantics.get("output_file_quaternion_order") != "wxyz"
        or semantics.get("pose_transform_or_inversion_applied") is not False
        or semantics.get("extrinsic_composition_applied") is not False
        or semantics.get("alignment_applied") is not False
        or semantics.get("interpolation_or_resampling_applied") is not False
        or semantics.get("timestamp_scale_offset_or_snapping_applied") is not False
    ):
        errors.append("HFNET_BRIDGE_SEMANTICS_DRIFT")
    return {
        "state": "PASS" if not errors else "INVALID_SEALED_BRIDGE",
        "path": str(HFNET_BRIDGE),
        "valid": not errors,
        "identity": bridge_identity,
        "manifest_identity": manifest_identity,
        "manifest": manifest,
        "run_result_audit": run_audit,
        "score_crop_identity": score_crop_identity,
        "errors": errors,
    }


def read_hfnet_bridge_rows(
    path: Path,
) -> tuple[dict[str, Any], list[list[str]], list[int]]:
    file_identity = identity(path)
    try:
        payload = path.read_bytes()
        text = payload.decode("ascii")
    except (OSError, UnicodeError) as error:
        raise EvidenceError(f"HFNET_BRIDGE_ASCII_READ_FAILED:{error}") from error
    if not text.endswith("\n") or "\r" in text:
        raise EvidenceError("HFNET_BRIDGE_LINE_ENDING_DRIFT")
    lines = text[:-1].split("\n") if text else []
    rows: list[list[str]] = []
    stamps: list[int] = []
    for line_number, line in enumerate(lines, start=1):
        fields = line.split(",")
        if (
            len(fields) != 8
            or any(not field or field != field.strip() for field in fields)
        ):
            raise EvidenceError(f"HFNET_BRIDGE_8_COLUMN_SCHEMA:{line_number}")
        try:
            stamp = parse_integer_ns(fields[0])
            numeric = [float(value) for value in fields[1:]]
        except ValueError as error:
            raise EvidenceError(f"HFNET_BRIDGE_NUMERIC_ROW:{line_number}") from error
        if not all(math.isfinite(value) for value in numeric):
            raise EvidenceError(f"HFNET_BRIDGE_NONFINITE_ROW:{line_number}")
        quaternion_norm = math.sqrt(sum(value * value for value in numeric[3:7]))
        if not 0.95 <= quaternion_norm <= 1.05:
            raise EvidenceError(f"HFNET_BRIDGE_QUATERNION_ROW:{line_number}")
        rows.append(fields)
        stamps.append(stamp)
    if len(rows) != 401:
        raise EvidenceError(f"HFNET_BRIDGE_ROW_COUNT:{len(rows)}")
    if any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise EvidenceError("HFNET_BRIDGE_TIMESTAMPS_NOT_STRICT")
    return file_identity, rows, stamps


def raw_camera_score_stamps() -> tuple[dict[str, Any], list[int], dict[str, Any]]:
    raw_identity = exact_identity(RAW_BAG, RAW_BAG_EXPECTED, "RAW_BAG")
    try:
        import rosbag
    except ImportError as error:
        raise EvidenceError("ROSBAG_PYTHON_UNAVAILABLE") from error
    score_stamps: list[int] = []
    try:
        with rosbag.Bag(str(RAW_BAG), "r") as bag:
            connections = list(bag._get_connections(topics=[CAMERA_TOPIC]))
            if len(connections) != 1:
                raise EvidenceError(
                    f"RAW_CAMERA_CONNECTION_COUNT_DRIFT:{len(connections)}"
                )
            connection = connections[0]
            if (
                connection.topic != CAMERA_TOPIC
                or connection.datatype != "sensor_msgs/Image"
                or connection.md5sum != "060021388200f6f0f447d0fcd9c64743"
            ):
                raise EvidenceError("RAW_CAMERA_CONNECTION_SCHEMA_DRIFT")
            index_groups = list(bag._get_indexes(connections))
            if len(index_groups) != 1:
                raise EvidenceError(
                    f"RAW_CAMERA_INDEX_GROUP_COUNT_DRIFT:{len(index_groups)}"
                )
            entries = list(index_groups[0])
            if len(entries) != FEED_SOURCE_RANGE[1] + 1:
                raise EvidenceError(f"RAW_CAMERA_COUNT_DRIFT:{len(entries)}")
            selected_entries = entries[
                SCORE_SOURCE_RANGE[0] : SCORE_SOURCE_RANGE[1] + 1
            ]
            for source_index, entry in enumerate(
                selected_entries, start=SCORE_SOURCE_RANGE[0]
            ):
                topic, raw_message, recorded = bag._read_message(
                    entry.position, raw=True
                )
                if topic != CAMERA_TOPIC or not isinstance(raw_message, tuple):
                    raise EvidenceError("RAW_CAMERA_RECORD_SCHEMA_INVALID")
                serialized = raw_message[1]
                if not isinstance(serialized, bytes) or len(serialized) < 12:
                    raise EvidenceError("RAW_CAMERA_SERIALIZED_HEADER_INVALID")
                _seq, seconds, nanoseconds = struct.unpack_from("<III", serialized, 0)
                if nanoseconds >= 1_000_000_000:
                    raise EvidenceError("RAW_CAMERA_NANOSECOND_DOMAIN_INVALID")
                header_stamp = seconds * 1_000_000_000 + nanoseconds
                recorded_stamp = recorded.to_nsec()
                indexed_stamp = entry.time.to_nsec()
                if header_stamp != recorded_stamp or recorded_stamp != indexed_stamp:
                    raise EvidenceError(
                        "RAW_CAMERA_HEADER_RECORD_INDEX_STAMP_MISMATCH:"
                        f"{source_index}:{header_stamp}:{recorded_stamp}:{indexed_stamp}"
                    )
                score_stamps.append(header_stamp)
    except EvidenceError:
        raise
    except Exception as error:
        raise EvidenceError(
            f"RAW_CAMERA_BAG_READ_FAILED:{type(error).__name__}:{error}"
        ) from error
    if (
        len(score_stamps) != 401
        or score_stamps[0] != SCORE_START_NS
        or score_stamps[-1] != SCORE_END_NS
        or any(right <= left for left, right in zip(score_stamps, score_stamps[1:]))
    ):
        raise EvidenceError("RAW_CAMERA_SCORE_STAMP_CONTRACT_DRIFT")
    source_audit = {
        "selection_mechanism": (
            "ROS1 bag connection index source positions with per-selected-row raw "
            "sensor_msgs/Image header decode"
        ),
        "topic": CAMERA_TOPIC,
        "connection_count": 1,
        "connection_id": connection.id,
        "datatype": connection.datatype,
        "md5sum": connection.md5sum,
        "topic_message_count": len(entries),
        "source_indices_inclusive": list(SCORE_SOURCE_RANGE),
        "selected_count": len(score_stamps),
        "header_stamp_equals_bag_record_stamp_for_every_selected_row": True,
        "bag_record_stamp_equals_connection_index_stamp_for_every_selected_row": True,
    }
    return raw_identity, score_stamps, source_audit


def audit_hfnet_canonicalization(
    bridge_audit: Mapping[str, Any],
) -> tuple[dict[str, Any], Optional[bytes]]:
    if not bridge_audit.get("valid"):
        return {
            "state": "PENDING" if bridge_audit.get("state") == "PENDING_MISSING_SEALED_BRIDGE" else "INVALID",
            "errors": list(bridge_audit.get("errors") or []),
        }, None
    try:
        bridge_identity, rows, sealed_stamps = read_hfnet_bridge_rows(HFNET_BRIDGE)
        raw_identity, canonical_stamps, source_audit = raw_camera_score_stamps()
        if len(rows) != len(canonical_stamps):
            raise EvidenceError("HFNET_CANONICAL_ROW_COUNT_MISMATCH")
        deltas = [
            sealed - canonical
            for sealed, canonical in zip(sealed_stamps, canonical_stamps)
        ]
        if any(abs(delta) > HFNET_MAX_CANONICAL_DELTA_NS for delta in deltas):
            raise EvidenceError("HFNET_CANONICAL_DELTA_EXCEEDS_128NS")
        histogram = {
            str(delta): count
            for delta, count in sorted(Counter(deltas).items())
        }
        if histogram != dict(HFNET_EXPECTED_DELTA_HISTOGRAM_NS):
            raise EvidenceError(f"HFNET_CANONICAL_DELTA_HISTOGRAM_DRIFT:{histogram}")
        canonical_lines = [
            str(stamp) + "," + ",".join(fields[1:])
            for stamp, fields in zip(canonical_stamps, rows)
        ]
        payload = ("\n".join(canonical_lines) + "\n").encode("ascii")
        original_pose_payload = ("\n".join(",".join(fields[1:]) for fields in rows) + "\n").encode("ascii")
        canonical_pose_payload = ("\n".join(line.split(",", 1)[1] for line in canonical_lines) + "\n").encode("ascii")
        if original_pose_payload != canonical_pose_payload:
            raise EvidenceError("HFNET_CANONICAL_POSE_TEXT_CHANGED")
        content = {
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        stamp_payload = ("\n".join(str(value) for value in canonical_stamps) + "\n").encode("ascii")
        trajectory = summarize_trajectory_stamps(
            Path(HFNET_CANONICAL_NAME),
            {"role": "ANALYSIS_GENERATED_CANONICAL_HFNET", **content},
            canonical_stamps,
            row_count=len(rows),
            errors=[],
        )
        audit = {
            "schema_version": HFNET_CANONICAL_SCHEMA,
            "state": "PASS",
            "source_bridge": bridge_identity,
            "raw_bag": raw_identity,
            "camera_topic": CAMERA_TOPIC,
            "raw_camera_source_audit": source_audit,
            "source_indices_inclusive": list(SCORE_SOURCE_RANGE),
            "row_count": len(rows),
            "sealed_first_stamp_ns": sealed_stamps[0],
            "sealed_last_stamp_ns": sealed_stamps[-1],
            "canonical_first_stamp_ns": canonical_stamps[0],
            "canonical_last_stamp_ns": canonical_stamps[-1],
            "maximum_absolute_delta_ns": max(abs(value) for value in deltas),
            "allowed_maximum_absolute_delta_ns": HFNET_MAX_CANONICAL_DELTA_NS,
            "delta_definition": "sealed_stamp_ns-minus-raw_camera_header_stamp_ns",
            "complete_delta_histogram_ns": histogram,
            "canonical_stamp_sequence_sha256": hashlib.sha256(stamp_payload).hexdigest(),
            "pose_field_text_unchanged": True,
            "pose_field_text_sha256": hashlib.sha256(original_pose_payload).hexdigest(),
            "canonical_content": content,
            "canonicalization_semantics": (
                "analysis-only source-index timestamp spelling canonicalization; "
                "no pose, order, alignment, interpolation, resampling, or result-informed offset"
            ),
            "trajectory": trajectory,
            "errors": [],
        }
        return audit, payload
    except (EvidenceError, OSError, UnicodeError) as error:
        return {
            "schema_version": HFNET_CANONICAL_SCHEMA,
            "state": "INVALID",
            "errors": [str(error)],
        }, None


def hfnet_usability(
    bridge_audit: Mapping[str, Any], canonical_audit: Mapping[str, Any]
) -> dict[str, Any]:
    if not bridge_audit.get("valid"):
        return {
            "method": "hfnet_slam_warmstart",
            "status": "PENDING"
            if bridge_audit.get("state") == "PENDING_MISSING_SEALED_BRIDGE"
            else "FAIL",
            "failure_codes": list(bridge_audit.get("errors") or []),
            "trajectory": None,
            "runtime": None,
        }
    trajectory = canonical_audit.get("trajectory")
    failures: list[str] = []
    if canonical_audit.get("state") != "PASS" or not isinstance(trajectory, Mapping):
        failures.extend(canonical_audit.get("errors") or ["HFNET_CANONICALIZATION_INVALID"])
        trajectory = {}
    if not trajectory.get("valid"):
        failures.append("HFNET_CANONICAL_TRAJECTORY_INVALID")
    if trajectory.get("score_pose_count") != 401:
        failures.append("HFNET_CANONICAL_SCORE_ROW_COUNT_NOT_401")
    if float(trajectory.get("score_temporal_span_fraction") or 0.0) < MIN_SCORE_SPAN_FRACTION:
        failures.append("SCORE_TEMPORAL_SPAN_COVERAGE_LT_70_PERCENT")
    max_gap = trajectory.get("score_max_adjacent_gap_s")
    if not isinstance(max_gap, (int, float)) or max_gap > 0.5:
        failures.append("SCORE_MAX_ADJACENT_OUTPUT_GAP_GT_0_5S")
    manifest = bridge_audit.get("manifest")
    run_result = manifest.get("run_result") if isinstance(manifest, Mapping) else None
    if not isinstance(run_result, Mapping) or (
        run_result.get("score_reset_count") != 0
        or run_result.get("prefix_reset_count") != 22
        or run_result.get("score_pose_count") != 401
    ):
        failures.append("HFNET_RUNTIME_BRIDGE_AUDIT_INVALID")
    return {
        "method": "hfnet_slam_warmstart",
        "status": "PASS" if not failures else "FAIL",
        "failure_codes": list(dict.fromkeys(failures)),
        "trajectory": {key: value for key, value in trajectory.items() if key != "stamps_ns"},
        "timestamp_canonicalization": {
            key: value for key, value in canonical_audit.items()
            if key != "trajectory"
        },
        "runtime": {
            "pre_score_initialized": True,
            "surviving_initialization_source_frame": 2355,
            "score_failure_mentions": 0,
            "score_restart_or_reset_events": 0,
            "prefix_active_map_reset_events": 22,
            "source": "SEALED_RUN_RESULT_AND_BRIDGE_MANIFEST",
        },
    }


def audit_learned_action() -> dict[str, Any]:
    path = ITEM_DIRS["aquafe_build"] / "stats.csv"
    if not path.exists() and not path.is_symlink():
        return {"state": "MISSING", "path": str(path)}
    segments = {
        "full": {"observations": 0, "affected_feature_frames": 0},
        "prefix": {"observations": 0, "affected_feature_frames": 0},
        "score": {"observations": 0, "affected_feature_frames": 0},
    }
    errors: list[str] = []
    rows = 0
    try:
        file_identity = identity(path)
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            required = {"frame_index", "selector_injected_observations"}
            if reader.fieldnames is None or not required.issubset(reader.fieldnames):
                raise EvidenceError("AQUAFE_STATS_REQUIRED_COLUMNS_MISSING")
            for row_number, row in enumerate(reader, 2):
                rows += 1
                try:
                    frame_index = int((row.get("frame_index") or "").strip())
                    raw_count = float(
                        (row.get("selector_injected_observations") or "0").strip()
                    )
                except ValueError as error:
                    raise EvidenceError(
                        f"AQUAFE_STATS_NUMERIC_ERROR:ROW_{row_number}"
                    ) from error
                if frame_index != rows - 1:
                    errors.append(f"FRAME_INDEX_SEQUENCE_ERROR:ROW_{row_number}")
                if (
                    not math.isfinite(raw_count)
                    or raw_count < 0
                    or abs(raw_count - round(raw_count)) > 1e-9
                ):
                    errors.append(f"INJECTED_COUNT_INVALID:ROW_{row_number}")
                    count = 0
                else:
                    count = int(round(raw_count))
                source_index = 2 * frame_index + 1
                for segment in ("full",):
                    segments[segment]["observations"] += count
                    segments[segment]["affected_feature_frames"] += int(count > 0)
                target = "score" if SCORE_SOURCE_RANGE[0] <= source_index <= SCORE_SOURCE_RANGE[1] else "prefix"
                segments[target]["observations"] += count
                segments[target]["affected_feature_frames"] += int(count > 0)
    except (EvidenceError, OSError, UnicodeError) as error:
        return {
            "state": "INVALID",
            "path": str(path),
            "errors": [f"{type(error).__name__}:{error}"],
        }
    if rows != 1400:
        errors.append(f"ROW_COUNT_MISMATCH:{rows}!=1400")
    return {
        "state": "PASS" if not errors else "INVALID",
        "path": str(path),
        "identity": file_identity,
        "method_native_mapping": "source_index=2*frame_index+1",
        "row_count": rows,
        "segments": segments,
        "errors": errors,
        "interpretation": (
            "Score-only action is direct score-frame learned action; prefix-only action can "
            "affect score history but is not direct score-frame action."
        ),
    }


def verify_reference_rows() -> dict[str, Any]:
    raw_identity = exact_identity(RAW_BAG, RAW_BAG_EXPECTED, "RAW_BAG")
    try:
        import rosbag
    except ImportError as error:
        raise EvidenceError("ROSBAG_PYTHON_UNAVAILABLE") from error
    stamps: list[int] = []
    try:
        with rosbag.Bag(str(RAW_BAG)) as bag:
            for _, message, _ in bag.read_messages(topics=["/aqualoc/colmap_gt"]):
                if not hasattr(message, "header"):
                    continue
                stamp = int(message.header.stamp.to_nsec())
                if SCORE_START_NS <= stamp <= SCORE_END_NS:
                    stamps.append(stamp)
    except Exception as error:
        raise EvidenceError(f"REFERENCE_BAG_READ_FAILED:{type(error).__name__}:{error}") from error
    if len(stamps) != REFERENCE_ROWS:
        raise EvidenceError(f"REFERENCE_ROW_COUNT_DRIFT:{len(stamps)}!={REFERENCE_ROWS}")
    if stamps[0] != SCORE_START_NS or stamps[-1] != SCORE_END_NS:
        raise EvidenceError("REFERENCE_SCORE_ENDPOINT_DRIFT")
    if any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise EvidenceError("REFERENCE_TIMESTAMPS_NOT_STRICT")
    return {
        "identity": raw_identity,
        "topic": "/aqualoc/colmap_gt",
        "score_row_count": len(stamps),
        "score_first_timestamp_ns": stamps[0],
        "score_last_timestamp_ns": stamps[-1],
        "fixed_common_coverage_denominator": REFERENCE_ROWS,
    }


def canonical_artifact_payloads(
    logical_common_dir: Path,
    canonical_audit: Mapping[str, Any],
    canonical_payload: bytes,
) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    canonical_path = logical_common_dir / HFNET_CANONICAL_NAME
    canonical_identity = payload_identity(canonical_payload, canonical_path)
    audit_for_manifest = {
        key: value for key, value in canonical_audit.items()
        if key != "trajectory"
    }
    manifest = {
        "schema_version": HFNET_CANONICAL_SCHEMA,
        "status": "PASS_ANALYSIS_ONLY_SOURCE_STAMP_CANONICALIZATION",
        "canonical_output": canonical_identity,
        "audit": audit_for_manifest,
    }
    manifest_payload = (
        json.dumps(
            manifest, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
        ) + "\n"
    ).encode("utf-8")
    manifest_identity = payload_identity(
        manifest_payload, logical_common_dir / HFNET_CANONICAL_MANIFEST_NAME
    )
    return canonical_identity, manifest_payload, manifest_identity


def evaluator_input_manifest(
    reference_audit: Mapping[str, Any],
    canonical_identity: Mapping[str, Any],
    canonical_manifest_identity: Mapping[str, Any],
) -> dict[str, Any]:
    files = {
        "raw_bag": reference_audit["identity"],
        "evaluator": identity(EVALUATOR),
        "evaluator_core": identity(EVALUATOR_CORE),
        "protocol": identity(PROTOCOL),
        "execution_lock": identity(EXECUTION_LOCK),
        "hfnet_sealed_bridge": identity(HFNET_BRIDGE),
        "hfnet_sealed_bridge_manifest": identity(HFNET_BRIDGE_MANIFEST),
        "hfnet_evaluator_canonical_bridge": dict(canonical_identity),
        "hfnet_evaluator_canonical_manifest": dict(canonical_manifest_identity),
    }
    for item_id, receipt_path in RECEIPTS.items():
        files[f"{item_id}_receipt"] = identity(receipt_path)
    for arm in VINS_ARMS:
        files[f"{arm}_trajectory"] = identity(VINS_PATHS[arm].trajectory)
        files[f"{arm}_config"] = identity(VINS_PATHS[arm].config)
    return {
        "schema_version": "aqua-fe-a10-samehistory-evaluator-input-manifest-v1",
        "files": files,
        "score": {
            "source_indices_inclusive": list(SCORE_SOURCE_RANGE),
            "start_ns": SCORE_START_NS,
            "end_ns": SCORE_END_NS,
            "native_reference_rows": REFERENCE_ROWS,
        },
        "protocol": {
            "evaluation_rate_hz": 1.0,
            "nominal_reference_rate_hz": 1.0,
            "nominal_estimate_rate_hz": 10.0,
            "max_reference_gap_s": 2.5,
            "max_estimate_gap_s": 0.25,
            "rpe_delta_s": 1.0,
            "min_ape_poses": FORMAL_APE_MIN_POSES,
            "min_ape_span_s": 10.0,
            "min_common_coverage": 0.70,
            "fixed_native_reference_denominator": REFERENCE_ROWS,
            "minimum_common_rows": MIN_COMMON_ROWS,
            "min_rpe_pairs": MIN_RPE_PAIRS,
            "uniform_grid_count": UNIFORM_1HZ_GRID_SAMPLES,
            "coverage_gate_semantics": (
                "uniform_common_matched_count>=15 AND matched/20>=0.70 AND "
                "conservative_fixed_denominator_index=matched/21>=0.70"
            ),
        },
    }


def verify_pre_evaluator_receipt_bindings(
    receipts: Mapping[str, Mapping[str, Any]], lock_audit: Mapping[str, Any]
) -> None:
    if not identity_claim_matches(lock_audit.get("identity"), identity(EXECUTION_LOCK)):
        raise EvidenceError("PRE_EVALUATOR_EXECUTION_LOCK_CHANGED")
    for item_id, audit in receipts.items():
        if not identity_claim_matches(audit.get("identity"), identity(RECEIPTS[item_id])):
            raise EvidenceError(f"PRE_EVALUATOR_RECEIPT_CHANGED:{item_id}")
        outputs = audit.get("artifact_outputs")
        if not isinstance(outputs, Mapping):
            raise EvidenceError(f"PRE_EVALUATOR_OUTPUT_BINDINGS_MISSING:{item_id}")
        for raw_path, claim in outputs.items():
            if (
                not isinstance(raw_path, str)
                or not isinstance(claim, Mapping)
                or not identity_claim_matches(claim, identity(Path(raw_path)))
            ):
                raise EvidenceError(
                    f"PRE_EVALUATOR_OUTPUT_CHANGED:{item_id}:{raw_path}"
                )


def decimal_seconds(stamp_ns: int) -> str:
    return format(Decimal(stamp_ns) / Decimal("1000000000"), "f")


def build_evaluator_command(output_dir: Path, hfnet_canonical_path: Path) -> list[str]:
    command = [
        sys.executable,
        str(EVALUATOR),
        "--reference-bag",
        str(RAW_BAG),
        "--reference-topic",
        "/aqualoc/colmap_gt",
    ]
    for arm in VINS_ARMS:
        command.extend(
            ["--arm", f"{EVALUATOR_NAMES[arm]}={VINS_PATHS[arm].trajectory}"]
        )
    command.extend(
        [
            "--arm",
            f"{EVALUATOR_NAMES['hfnet_slam_warmstart']}={hfnet_canonical_path}",
        ]
    )
    for arm in VINS_ARMS:
        command.extend(
            ["--arm-config", f"{EVALUATOR_NAMES[arm]}={VINS_PATHS[arm].config}"]
        )
    command.extend(
        [
            "--arm-config",
            f"{EVALUATOR_NAMES['hfnet_slam_warmstart']}="
            f"{VINS_PATHS['vanilla_origin_native_image_context'].config}",
            "--nominal-reference-rate-hz",
            "1.0",
            "--nominal-estimate-rate-hz",
            "10.0",
            "--evaluation-rate-hz",
            "1.0",
            "--max-reference-gap-s",
            "2.5",
            "--max-estimate-gap-s",
            "0.25",
            "--window-start-s",
            decimal_seconds(SCORE_START_NS),
            "--window-end-s",
            decimal_seconds(SCORE_END_NS),
            "--rpe-delta-s",
            "1.0",
            "--min-ape-poses",
            str(FORMAL_APE_MIN_POSES),
            "--min-ape-span-s",
            "10.0",
            "--min-common-coverage",
            "0.70",
            "--min-rpe-pairs",
            str(MIN_RPE_PAIRS),
            "--contrast-name",
            "SAMEHISTORY_SYSTEM_A10_FINALONLINE_V1_SCORE_2400_2800",
            "--output-dir",
            str(output_dir),
        ]
    )
    return command


def verify_common_support_result_manifest(final: Path) -> dict[str, Any]:
    manifest_path = final / "common_support_result_manifest_v1.json"
    manifest = read_json(manifest_path)
    if (
        set(manifest) != {"schema_version", "files"}
        or manifest.get("schema_version")
        != "aqua-fe-a10-common-support-result-manifest-v1"
    ):
        raise EvidenceError("COMMON_SUPPORT_RESULT_MANIFEST_SCHEMA_DRIFT")
    claims = manifest.get("files")
    if not isinstance(claims, Mapping):
        raise EvidenceError("COMMON_SUPPORT_RESULT_MANIFEST_FILES_MISSING")
    actual_names: set[str] = set()
    for entry in final.iterdir():
        if entry.name == manifest_path.name:
            continue
        info = entry.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise EvidenceError(f"COMMON_SUPPORT_UNEXPECTED_NONREGULAR:{entry}")
        actual_names.add(entry.name)
    if actual_names != set(claims):
        raise EvidenceError("COMMON_SUPPORT_RESULT_FILE_SET_DRIFT")
    for name in sorted(actual_names):
        claim = claims.get(name)
        actual = identity(final / name)
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or not isinstance(claim, Mapping)
            or set(claim) != {"size_bytes", "sha256"}
            or any(
                claim.get(key) != actual.get(key)
                for key in ("size_bytes", "sha256")
            )
        ):
            raise EvidenceError(f"COMMON_SUPPORT_RESULT_FILE_IDENTITY_DRIFT:{name}")
    return {
        "identity": identity(manifest_path),
        "files": dict(claims),
    }


def ensure_common_support(
    output_root: Path,
    logical_output_root: Path,
    reference_audit: Mapping[str, Any],
    canonical_audit: Mapping[str, Any],
    canonical_payload: bytes,
    *,
    run_evaluator: bool,
) -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    if sha256(EVALUATOR) != EVALUATOR_EXPECTED_SHA256:
        raise EvidenceError("FROZEN_COMMON_SUPPORT_EVALUATOR_SHA256_DRIFT")
    if sha256(EVALUATOR_CORE) != EVALUATOR_CORE_EXPECTED_SHA256:
        raise EvidenceError("FROZEN_COMMON_SUPPORT_EVALUATOR_CORE_SHA256_DRIFT")
    final = output_root / "common_support"
    logical_final = logical_output_root / "common_support"
    summary_path = final / "common_support_summary.json"
    manifest_path = final / "a10_evaluator_input_manifest_v1.json"
    canonical_identity, canonical_manifest_payload, canonical_manifest_identity = (
        canonical_artifact_payloads(
            logical_final, canonical_audit, canonical_payload
        )
    )
    expected_manifest = evaluator_input_manifest(
        reference_audit, canonical_identity, canonical_manifest_identity
    )
    if summary_path.is_file():
        if not manifest_path.is_file():
            raise EvidenceError("UNATTESTED_EXISTING_COMMON_SUPPORT")
        if read_json(manifest_path) != expected_manifest:
            raise EvidenceError("STALE_COMMON_SUPPORT_INPUT_MANIFEST")
        result_manifest_audit = verify_common_support_result_manifest(final)
        return read_json(summary_path), {
            "state": "READ_EXISTING_COMMON_SUPPORT",
            "summary_path": str(summary_path),
            "input_manifest": expected_manifest,
            "result_manifest_audit": result_manifest_audit,
        }
    if not run_evaluator:
        return None, {
            "state": "READY_BUT_EVALUATOR_DISABLED",
            "summary_path": str(summary_path),
            "input_manifest": expected_manifest,
        }
    if final.exists() or final.is_symlink():
        raise EvidenceError("PARTIAL_COMMON_SUPPORT_DIRECTORY_EXISTS")
    final.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=".a10_common_support.", dir=str(final.parent))
    )
    try:
        actual_canonical_path = staging / HFNET_CANONICAL_NAME
        actual_canonical_path.write_bytes(canonical_payload)
        (staging / HFNET_CANONICAL_MANIFEST_NAME).write_bytes(
            canonical_manifest_payload
        )
        if (
            identity(actual_canonical_path)["sha256"] != canonical_identity["sha256"]
            or identity(staging / HFNET_CANONICAL_MANIFEST_NAME)["sha256"]
            != canonical_manifest_identity["sha256"]
        ):
            raise EvidenceError("HFNET_CANONICAL_ARTIFACT_WRITE_MISMATCH")
        command = build_evaluator_command(staging, actual_canonical_path)
        process = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=180,
        )
        (staging / "evaluator_process_receipt_v1.json").write_text(
            json.dumps(
                {
                    "schema_version": "aqua-fe-a10-common-support-evaluator-process-receipt-v1",
                    "command": command,
                    "raw_return_code": process.returncode,
                    "stdout": process.stdout,
                },
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        if process.returncode != 0 or not (
            staging / "common_support_summary.json"
        ).is_file():
            raise EvidenceError(
                f"COMMON_SUPPORT_EVALUATOR_FAILED_RC_{process.returncode}:"
                f"{process.stdout[-1000:]}"
            )
        (staging / manifest_path.name).write_text(
            json.dumps(
                expected_manifest, indent=2, sort_keys=True, allow_nan=False
            ) + "\n",
            encoding="utf-8",
        )
        result_files: dict[str, Any] = {}
        for path in sorted(staging.iterdir()):
            if path.is_file() and path.name != "common_support_result_manifest_v1.json":
                actual = identity(path)
                result_files[path.name] = {
                    "size_bytes": actual["size_bytes"],
                    "sha256": actual["sha256"],
                }
        result_manifest = {
            "schema_version": "aqua-fe-a10-common-support-result-manifest-v1",
            "files": result_files,
        }
        (staging / "common_support_result_manifest_v1.json").write_text(
            json.dumps(result_manifest, indent=2, sort_keys=True, allow_nan=False)
            + "\n",
            encoding="utf-8",
        )
        staging.rename(final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    result_manifest_audit = verify_common_support_result_manifest(final)
    return read_json(summary_path), {
        "state": "RAN_COMMON_SUPPORT_EVALUATOR",
        "summary_path": str(summary_path),
        "input_manifest": expected_manifest,
        "result_manifest_audit": result_manifest_audit,
    }


def adjudicate_common_support(
    summary: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "formal_ape_gate_open": False,
        "formal_ape_gate_reason": "NATIVE_REFERENCE_ROWS_21_LT_FORMAL_MINIMUM_30",
        "native_reference_rows": REFERENCE_ROWS,
        "formal_ape_minimum_poses": FORMAL_APE_MIN_POSES,
        "formal_winner_permitted": False,
        "significance_test_permitted": False,
        "ranking_permitted": False,
        "cross_window_mean_permitted": False,
        "failure_as_zero_imputation_permitted": False,
        "common_support_available": summary is not None,
        "descriptive_proxy_metrics": None,
    }
    if summary is None:
        result["state"] = "NOT_EVALUATED"
        return result
    if set(summary) != {"protocol", "support", "reference", "arms"}:
        raise EvidenceError("COMMON_SUPPORT_TOP_LEVEL_SCHEMA_INVALID")
    evaluator_protocol = summary.get("protocol")
    support = summary.get("support")
    arms = summary.get("arms")
    if (
        not isinstance(evaluator_protocol, Mapping)
        or not isinstance(support, Mapping)
        or not isinstance(arms, Mapping)
    ):
        raise EvidenceError("COMMON_SUPPORT_SUMMARY_SCHEMA_INVALID")
    exact_protocol_values = {
        "contrast_name": "SAMEHISTORY_SYSTEM_A10_FINALONLINE_V1_SCORE_2400_2800",
        "reference": f"{RAW_BAG}:/aqualoc/colmap_gt",
        "evaluation_rate_hz": 1.0,
        "nominal_reference_rate_hz": 1.0,
        "nominal_estimate_rate_hz": 10.0,
        "max_reference_gap_s": 2.5,
        "max_estimate_gap_s": 0.25,
        "rpe_delta_s": 1.0,
        "body_to_camera_applied": True,
        "rpe_semantics": "aligned_global_frame_positional_delta",
        "reference_time_offset_s": 0.0,
        "arm_time_offsets_s": {
            name: 0.0 for name in EVALUATOR_NAMES.values()
        },
    }
    for key, expected in exact_protocol_values.items():
        if evaluator_protocol.get(key) != expected:
            raise EvidenceError(f"COMMON_SUPPORT_PROTOCOL_DRIFT:{key}")
    for key, expected in {
        "window_start_s": SCORE_START_NS / 1e9,
        "window_end_s": SCORE_END_NS / 1e9,
    }.items():
        actual = finite_number(evaluator_protocol.get(key), f"protocol:{key}")
        if abs(actual - expected) > 1e-9:
            raise EvidenceError(f"COMMON_SUPPORT_PROTOCOL_DRIFT:{key}")

    expected_arms = set(EVALUATOR_NAMES.values())
    if set(arms) != expected_arms:
        raise EvidenceError("COMMON_SUPPORT_ARM_SET_DRIFT")
    if support.get("ape_valid") is not False:
        raise EvidenceError("FORMAL_APE_GATE_UNEXPECTEDLY_OPEN")
    grid_count = exact_integer(support.get("grid_count"), "support:grid_count")
    matched = exact_integer(support.get("matched_count"), "support:matched_count")
    rpe_pairs = exact_integer(support.get("rpe_pairs"), "support:rpe_pairs")
    segment_count = exact_integer(support.get("segment_count"), "support:segment_count")
    if grid_count != UNIFORM_1HZ_GRID_SAMPLES:
        raise EvidenceError(f"UNIFORM_GRID_COUNT_DRIFT:{grid_count}")
    if not 0 <= matched <= grid_count:
        raise EvidenceError("UNIFORM_MATCHED_COUNT_OUT_OF_RANGE")
    if not 0 <= rpe_pairs <= max(0, grid_count - 1):
        raise EvidenceError("UNIFORM_RPE_PAIR_COUNT_OUT_OF_RANGE")
    if not 0 <= segment_count <= matched:
        raise EvidenceError("UNIFORM_SEGMENT_COUNT_OUT_OF_RANGE")
    uniform_coverage = matched / grid_count
    recorded_uniform_coverage = finite_number(
        support.get("common_coverage"), "support:common_coverage"
    )
    if abs(recorded_uniform_coverage - uniform_coverage) > 1e-12:
        raise EvidenceError("UNIFORM_COMMON_COVERAGE_DIVERGES")
    if support.get("rpe_valid") is not (rpe_pairs >= MIN_RPE_PAIRS):
        raise EvidenceError("UNIFORM_RPE_VALID_FLAG_DIVERGES")
    finite_number(support.get("common_span_s"), "support:common_span_s")
    finite_number(support.get("window_duration_s"), "support:window_duration_s")
    conservative_index = matched / REFERENCE_ROWS
    common_ok = (
        matched >= MIN_COMMON_ROWS
        and uniform_coverage >= 0.70
        and conservative_index >= 0.70
    )
    rpe_ok = common_ok and rpe_pairs >= MIN_RPE_PAIRS

    ordered_metrics: dict[str, dict[str, Any]] = {}
    for method in METHOD_ORDER:
        name = EVALUATOR_NAMES[method]
        metrics = arms.get(name)
        if not isinstance(metrics, Mapping):
            raise EvidenceError(f"COMMON_SUPPORT_ARM_SCHEMA_INVALID:{name}")
        if (
            exact_integer(metrics.get("matched_count"), f"arm:{name}:matched_count")
            != matched
            or exact_integer(metrics.get("rpe_pairs"), f"arm:{name}:rpe_pairs")
            != rpe_pairs
        ):
            raise EvidenceError(f"COMMON_SUPPORT_ARM_COUNT_DIVERGES:{name}")
        for key in ("ape_rmse_m", "ape_median_m", "ape_max_m"):
            if matched >= 3:
                finite_number(metrics.get(key), f"arm:{name}:{key}")
            elif key in metrics:
                raise EvidenceError(f"COMMON_SUPPORT_UNSUPPORTED_APE_PRESENT:{name}:{key}")
        for key in ("rpe_rmse_m", "rpe_median_m", "rpe_max_m"):
            if rpe_pairs > 0:
                finite_number(metrics.get(key), f"arm:{name}:{key}")
            elif key in metrics:
                raise EvidenceError(f"COMMON_SUPPORT_UNSUPPORTED_RPE_PRESENT:{name}:{key}")
        ordered_metrics[name] = dict(metrics)
    result.update(
        {
            "state": "DESCRIPTIVE_SUPPORT_PASS" if common_ok else "DESCRIPTIVE_SUPPORT_FAIL",
            "evaluator_support": dict(support),
            "uniform_grid_count": grid_count,
            "uniform_common_matched_count": matched,
            "uniform_common_coverage": uniform_coverage,
            "conservative_fixed_denominator_count": REFERENCE_ROWS,
            "conservative_fixed_denominator_index": conservative_index,
            "minimum_common_rows": MIN_COMMON_ROWS,
            "common_support_gate_pass": common_ok,
            "descriptive_rpe_gate_pass": rpe_ok,
            "uniform_exact_1s_rpe_pairs": rpe_pairs,
            "note": (
                "The numerator is the 1 Hz uniform-grid jointly matched sample count. "
                "matched/20 is uniform-grid coverage; matched/21 is a separately named "
                "conservative fixed-denominator index, never native-row coverage or support."
            ),
        }
    )
    if common_ok:
        result["descriptive_proxy_metrics"] = {
            "label": "DESCRIPTIVE_COLMAP_PROXY_ONLY_FIXED_ORDER_NO_RANKING",
            "arms": {
                name: {
                    "matched_count": metrics.get("matched_count"),
                    "ape_rmse_m_descriptive_only": metrics.get("ape_rmse_m"),
                    "ape_median_m_descriptive_only": metrics.get("ape_median_m"),
                    "ape_max_m_descriptive_only": metrics.get("ape_max_m"),
                    "rpe_pairs": metrics.get("rpe_pairs"),
                    "rpe_rmse_m_descriptive_only": (
                        metrics.get("rpe_rmse_m") if rpe_ok else None
                    ),
                    "rpe_median_m_descriptive_only": (
                        metrics.get("rpe_median_m") if rpe_ok else None
                    ),
                    "rpe_max_m_descriptive_only": (
                        metrics.get("rpe_max_m") if rpe_ok else None
                    ),
                }
                for name, metrics in ordered_metrics.items()
            },
            "rpe_withheld_if_support_below_10_pairs": not rpe_ok,
        }
    return result


def receipt_only_system_row(
    arm: str, receipt: Mapping[str, Any], *, global_reason: str
) -> dict[str, Any]:
    if receipt.get("state") == "PENDING_MISSING_RECEIPT":
        status = "PENDING"
        codes = ["FORMAL_RUN_RECEIPT_MISSING"]
    elif receipt.get("terminal_valid") is not True:
        status = "NOT_ADJUDICATED"
        codes = ["RECEIPT_EVIDENCE_INVALID"]
    elif receipt.get("process_artifact_execution_successful") is not True:
        status = "FAIL"
        codes = list(receipt.get("blocking_reasons") or ["PROCESS_ARTIFACT_EXECUTION_NOT_SUCCESSFUL"])
    elif receipt.get("score_usability_status") == "FAIL":
        status = "FAIL"
        codes = list(
            (receipt.get("score_usability") or {}).get("failure_codes")
            or ["RECEIPT_SCORE_USABILITY_NOT_PASS"]
        )
    else:
        status = "NOT_COMPARED"
        codes = [global_reason]
    return {
        "method": arm,
        "status": status,
        "failure_codes": codes,
        "receipt": receipt,
        "trajectory": None,
    }


def build_bundle(
    output_dir: Path,
    *,
    run_evaluator: bool,
    logical_output_dir: Optional[Path] = None,
) -> dict[str, Any]:
    logical_output = (
        logical_output_dir.absolute()
        if logical_output_dir is not None else output_dir.absolute()
    )
    lock, lock_audit = inspect_lock()
    lock_identity = (
        lock_audit.get("identity") if lock_audit.get("state") == "PASS" else None
    )
    receipts = {
        item_id: audit_receipt(item_id, lock, lock_identity) for item_id in ITEM_ORDER
    }
    missing_receipts = [
        item_id
        for item_id, receipt in receipts.items()
        if receipt["state"] == "PENDING_MISSING_RECEIPT"
    ]
    all_receipts_terminal = all(receipt.get("terminal") is True for receipt in receipts.values())
    all_receipts_terminal_valid = all(
        receipt.get("terminal_valid") is True for receipt in receipts.values()
    )
    all_process_artifact_execution_successful = all(
        receipt.get("process_artifact_execution_successful") is True
        for receipt in receipts.values()
    )
    all_receipts_successful = all(receipt["successful"] for receipt in receipts.values())
    invalid_terminal_receipts = [
        item_id
        for item_id, receipt in receipts.items()
        if receipt["state"] == "TERMINAL_INVALID"
    ]

    bridge_audit = audit_hfnet_bridge()
    canonical_audit, canonical_payload = audit_hfnet_canonicalization(bridge_audit)
    rows: list[dict[str, Any]] = []
    evaluator_audit: dict[str, Any]
    common_summary: Optional[dict[str, Any]] = None
    reference_audit: Optional[dict[str, Any]] = None
    learned_action: dict[str, Any] = {
        "state": "PENDING_RECEIPTS",
        "path": str(ITEM_DIRS["aquafe_build"] / "stats.csv"),
    }

    if missing_receipts:
        analysis_state = "PENDING_REQUIRED_RECEIPTS"
        evaluator_audit = {
            "state": "PENDING_REQUIRED_TERMINAL_INPUTS",
            "missing_receipts": missing_receipts,
        }
        rows = [
            receipt_only_system_row(
                arm, receipts[arm], global_reason="ANOTHER_FROZEN_ITEM_PENDING"
            )
            for arm in VINS_ARMS
        ]
        rows.append(hfnet_usability(bridge_audit, canonical_audit))
    elif not all_receipts_terminal_valid:
        analysis_state = "BLOCKED_INVALID_RECEIPT_EVIDENCE"
        evaluator_audit = {"state": "BLOCKED_INVALID_RECEIPT_EVIDENCE"}
        for arm in VINS_ARMS:
            rows.append(
                {
                    "method": arm,
                    "status": "NOT_ADJUDICATED",
                    "failure_codes": ["RECEIPT_EVIDENCE_INVALID"],
                    "receipt": receipts[arm],
                    "trajectory": None,
                }
            )
        rows.append(hfnet_usability(bridge_audit, canonical_audit))
    elif invalid_terminal_receipts:
        analysis_state = "BLOCKED_INVALID_RECEIPT_EVIDENCE"
        evaluator_audit = {
            "state": "BLOCKED_INVALID_RECEIPT_EVIDENCE",
            "invalid_terminal_receipts": invalid_terminal_receipts,
        }
        for arm in VINS_ARMS:
            rows.append(
                {
                    "method": arm,
                    "status": "NOT_ADJUDICATED",
                    "failure_codes": ["RECEIPT_EVIDENCE_INVALID"],
                    "receipt": receipts[arm],
                    "trajectory": None,
                }
            )
        rows.append(hfnet_usability(bridge_audit, canonical_audit))
    elif not all_process_artifact_execution_successful:
        analysis_state = "TERMINAL_EXECUTION_FAILURE_ACCURACY_NOT_RUN"
        evaluator_audit = {
            "state": "BLOCKED_TERMINAL_EXECUTION_FAILURE",
            "failed_or_invalid_items": [
                item_id
                for item_id, receipt in receipts.items()
                if not receipt["process_artifact_execution_successful"]
            ],
            "failure_values_imputed_as_zero": False,
        }
        rows = [
            receipt_only_system_row(
                arm, receipts[arm], global_reason="ANOTHER_FROZEN_ITEM_FAILED"
            )
            for arm in VINS_ARMS
        ]
        rows.append(hfnet_usability(bridge_audit, canonical_audit))
    else:
        learned_action = audit_learned_action()
        rows = [vins_usability(arm, receipts[arm]) for arm in VINS_ARMS]
        rows.append(hfnet_usability(bridge_audit, canonical_audit))
        all_usable = all(row.get("status") == "PASS" for row in rows)
        if not all_usable:
            if bridge_audit.get("state") == "PENDING_MISSING_SEALED_BRIDGE":
                analysis_state = "PENDING_SEALED_HFNET_BRIDGE"
                evaluator_audit = {"state": "PENDING_SEALED_HFNET_BRIDGE"}
            else:
                analysis_state = "TERMINAL_USABILITY_FAILURE_ACCURACY_NOT_RUN"
                evaluator_audit = {
                    "state": "BLOCKED_SYSTEM_UNUSABLE",
                    "unusable_methods": [
                        row["method"] for row in rows if row.get("status") != "PASS"
                    ],
                    "failure_values_imputed_as_zero": False,
                }
        elif learned_action.get("state") != "PASS":
            analysis_state = "BLOCKED_LEARNED_ACTION_AUDIT_INVALID"
            evaluator_audit = {"state": "BLOCKED_LEARNED_ACTION_AUDIT_INVALID"}
        elif lock is None or lock_audit.get("state") != "PASS":
            analysis_state = "BLOCKED_EXECUTION_LOCK_EVIDENCE_INVALID"
            evaluator_audit = {"state": "BLOCKED_EXECUTION_LOCK_EVIDENCE_INVALID"}
        else:
            try:
                if canonical_payload is None or canonical_audit.get("state") != "PASS":
                    raise EvidenceError("HFNET_CANONICAL_EVALUATOR_INPUT_NOT_AVAILABLE")
                verify_pre_evaluator_receipt_bindings(receipts, lock_audit)
                reference_audit = verify_reference_rows()
                common_summary, evaluator_audit = ensure_common_support(
                    output_dir,
                    logical_output,
                    reference_audit,
                    canonical_audit,
                    canonical_payload,
                    run_evaluator=run_evaluator,
                )
                analysis_state = (
                    "READY_FOR_COMMON_SUPPORT_EVALUATOR"
                    if common_summary is None
                    else "TERMINAL_DESCRIPTIVE_ONLY_FORMAL_APE_CLOSED"
                )
            except EvidenceError as error:
                analysis_state = "BLOCKED_COMMON_SUPPORT_EVIDENCE_ERROR"
                evaluator_audit = {
                    "state": "BLOCKED_COMMON_SUPPORT_EVIDENCE_ERROR",
                    "errors": [str(error)],
                }

    accuracy = adjudicate_common_support(common_summary)
    if common_summary is not None and accuracy.get("common_support_gate_pass") is not True:
        analysis_state = "TERMINAL_COMMON_SUPPORT_FAIL_METRICS_WITHHELD"
    bundle = {
        "schema_version": SCHEMA,
        "analysis_state": analysis_state,
        "question": (
            "A10 source 0..2800 same-history system comparison, scored only on "
            "source 2400..2800."
        ),
        "analysis_only": True,
        "frozen_support": {
            "feed_source_indices_inclusive": list(FEED_SOURCE_RANGE),
            "score_source_indices_inclusive": list(SCORE_SOURCE_RANGE),
            "score_start_ns": SCORE_START_NS,
            "score_end_ns": SCORE_END_NS,
            "score_duration_s": SCORE_DURATION_NS / 1e9,
            "native_reference_rows": REFERENCE_ROWS,
            "uniform_1hz_grid_count": UNIFORM_1HZ_GRID_SAMPLES,
        },
        "frozen_paths": {
            "receipts": {key: str(value) for key, value in RECEIPTS.items()},
            "vins_trajectories": {
                key: str(value.trajectory) for key, value in VINS_PATHS.items()
            },
            "hfnet_bridge": str(HFNET_BRIDGE),
        },
        "protocol": optional_identity(PROTOCOL),
        "execution_lock": lock_audit,
        "receipt_audits": receipts,
        "all_five_receipts_terminal": all_receipts_terminal,
        "all_five_receipts_terminal_valid": all_receipts_terminal_valid,
        "all_five_process_artifact_execution_successful": (
            all_process_artifact_execution_successful
        ),
        "all_five_receipts_successful": all_receipts_successful,
        "hfnet_bridge_audit": bridge_audit,
        "hfnet_timestamp_canonicalization_audit": {
            key: value for key, value in canonical_audit.items()
            if key != "trajectory"
        },
        "reference_audit": reference_audit,
        "learned_action_audit": learned_action,
        "systems": rows,
        "evaluator_audit": evaluator_audit,
        "accuracy": accuracy,
        "interpretation_policy": {
            "formal_ape_gate_open": False,
            "formal_winner_permitted": False,
            "significance_test_permitted": False,
            "ranking_permitted": False,
            "failure_as_zero_imputation_permitted": False,
            "failed_arm_metric_value": None,
            "system_order_is_fixed_not_performance_sorted": list(METHOD_ORDER),
            "cross_system_disclosures": [
                "vanilla is the local quality-capable VINS-origin native-image context, not pristine upstream VINS-Fusion",
                "external KLT and AQUA-FE publish odd source frames at approximately 10 Hz while HFNet sees the 20 Hz camera stream",
                "raw-IMU API support is real but not byte-identical across project and sealed HFNet adapters",
                "HFNet has 22 prefix active-map resets and a surviving initialization at source frame 2355, with zero score reset",
                "HFNet evaluator timestamps are analysis-only source-index canonical spellings audited within 128 ns; sealed pose rows are unchanged",
                "VINS online outputs and HFNet online-final map trajectory semantics differ",
                "the AQUALOC COLMAP trajectory is a same-image proxy rather than sensor-independent ground truth",
            ],
        },
    }
    return clean_json(bundle)


def write_rows_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = [
        "method",
        "status",
        "failure_codes",
        "score_pose_count",
        "score_span_fraction",
        "score_max_gap_s",
        "score_failure_mentions",
        "score_reset_events",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            trajectory = row.get("trajectory")
            runtime = row.get("runtime_log") or row.get("runtime")
            writer.writerow(
                {
                    "method": row.get("method"),
                    "status": row.get("status"),
                    "failure_codes": "|".join(row.get("failure_codes") or []),
                    "score_pose_count": trajectory.get("score_pose_count")
                    if isinstance(trajectory, Mapping)
                    else None,
                    "score_span_fraction": trajectory.get(
                        "score_temporal_span_fraction"
                    )
                    if isinstance(trajectory, Mapping)
                    else None,
                    "score_max_gap_s": trajectory.get("score_max_adjacent_gap_s")
                    if isinstance(trajectory, Mapping)
                    else None,
                    "score_failure_mentions": runtime.get("score_failure_mentions")
                    if isinstance(runtime, Mapping)
                    else None,
                    "score_reset_events": runtime.get(
                        "score_restart_or_reset_events"
                    )
                    if isinstance(runtime, Mapping)
                    else None,
                }
            )


def write_report(path: Path, bundle: Mapping[str, Any]) -> None:
    lines = [
        "# A10 same-history final-online analysis v1",
        "",
        f"Analysis state: `{bundle['analysis_state']}`.",
        "",
        (
            "This is an analysis-only development comparison. The score interval has "
            "21 native COLMAP proxy rows, so the 30-pose formal APE gate is closed. "
            "No winner, significance test, ranking, or failure-as-zero penalty is permitted."
        ),
        "",
        "| System | Usability | score poses | span coverage | max gap (s) | failure codes |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in bundle.get("systems", []):
        trajectory = row.get("trajectory")
        if isinstance(trajectory, Mapping):
            poses = trajectory.get("score_pose_count", "n/a")
            span = trajectory.get("score_temporal_span_fraction")
            gap = trajectory.get("score_max_adjacent_gap_s")
            span_text = f"{span:.3f}" if isinstance(span, (int, float)) else "n/a"
            gap_text = f"{gap:.3f}" if isinstance(gap, (int, float)) else "n/a"
        else:
            poses, span_text, gap_text = "n/a", "n/a", "n/a"
        lines.append(
            f"| `{row.get('method')}` | {row.get('status')} | {poses} | "
            f"{span_text} | {gap_text} | {'; '.join(row.get('failure_codes') or []) or '-'} |"
        )
    accuracy = bundle.get("accuracy") or {}
    lines.extend(
        [
            "",
            "## Accuracy gate",
            "",
            f"State: `{accuracy.get('state')}`.",
            "",
            f"Formal APE gate open: `{accuracy.get('formal_ape_gate_open')}`.",
        ]
    )
    if accuracy.get("common_support_available"):
        lines.extend(
            [
                "",
                (
                    "Uniform 1 Hz grid: "
                    f"count `{accuracy.get('uniform_grid_count')}`, jointly matched "
                    f"`{accuracy.get('uniform_common_matched_count')}`, coverage "
                    f"`{accuracy.get('uniform_common_coverage')}`."
                ),
                "",
                (
                    "Conservative fixed-denominator index: "
                    f"`{accuracy.get('conservative_fixed_denominator_index')}` "
                    f"(matched / {REFERENCE_ROWS}); this index is not native-row "
                    "coverage or native-row support."
                ),
                "",
                (
                    "Uniform exact-1 s RPE pairs: "
                    f"`{accuracy.get('uniform_exact_1s_rpe_pairs')}`; descriptive "
                    f"RPE gate pass: `{accuracy.get('descriptive_rpe_gate_pass')}`."
                ),
            ]
        )
    descriptive = accuracy.get("descriptive_proxy_metrics")
    if isinstance(descriptive, Mapping):
        lines.extend(
            [
                "",
                "Descriptive proxy metrics are retained in the JSON bundle in fixed arm "
                "order. They are deliberately not sorted or converted into a winner.",
            ]
        )
    lines.extend(
        [
            "",
            "## Required disclosures",
            "",
        ]
    )
    for disclosure in bundle["interpretation_policy"]["cross_system_disclosures"]:
        lines.append(f"- {disclosure}")
    canonical = bundle.get("hfnet_timestamp_canonicalization_audit")
    if isinstance(canonical, Mapping):
        lines.extend(
            [
                "",
                "## HFNet timestamp spelling audit",
                "",
                f"State: `{canonical.get('state')}`.",
                "",
                (
                    "Complete sealed-minus-raw delta histogram (ns): `"
                    + json.dumps(
                        canonical.get("complete_delta_histogram_ns"),
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "`."
                ),
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def fsync_tree(root: Path) -> None:
    directories: list[Path] = []
    for current_raw, directory_names, file_names in os.walk(
        root, topdown=True, followlinks=False
    ):
        current = Path(current_raw)
        directories.append(current)
        for name in directory_names:
            path = current / name
            if path.is_symlink() or not path.is_dir():
                raise EvidenceError(f"ANALYSIS_OUTPUT_NONREGULAR_DIRECTORY:{path}")
        for name in file_names:
            path = current / name
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise EvidenceError(f"ANALYSIS_OUTPUT_NONREGULAR_FILE:{path}")
            descriptor = os.open(
                path,
                os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    for directory in reversed(directories):
        fsync_directory(directory)


@contextmanager
def blocked_termination_signals():
    blocked = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def rename_directory_noreplace(source: Path, destination: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise EvidenceError("RENAMEAT2_NOREPLACE_UNAVAILABLE")
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        -100,
        os.fsencode(source),
        -100,
        os.fsencode(destination),
        1,
    )
    if result != 0:
        value = ctypes.get_errno()
        if value == errno.EEXIST:
            raise EvidenceError(f"ANALYSIS_OUTPUT_ALREADY_EXISTS:{destination}")
        raise EvidenceError(
            f"ANALYSIS_OUTPUT_NOREPLACE_RENAME_FAILED:{os.strerror(value)}"
        )


def relative_file_claims(root: Path, *, excluded: set[str]) -> dict[str, Any]:
    claims: dict[str, Any] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise EvidenceError(f"ANALYSIS_OUTPUT_SYMLINK_FORBIDDEN:{path}")
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            raise EvidenceError(f"ANALYSIS_OUTPUT_NONREGULAR_FORBIDDEN:{path}")
        if relative in excluded:
            continue
        actual = identity(path)
        claims[relative] = {
            "size_bytes": actual["size_bytes"],
            "sha256": actual["sha256"],
        }
    return claims


def validate_reused_external_evidence(bundle: Mapping[str, Any]) -> None:
    protocol = bundle.get("protocol")
    if not isinstance(protocol, Mapping) or protocol.get("exists") is not True:
        raise EvidenceError("REUSED_ANALYSIS_PROTOCOL_EVIDENCE_INVALID")
    actual_protocol = identity(PROTOCOL)
    if not identity_claim_matches(protocol, actual_protocol):
        raise EvidenceError("REUSED_ANALYSIS_PROTOCOL_CHANGED")
    lock_audit = bundle.get("execution_lock")
    if not isinstance(lock_audit, Mapping):
        raise EvidenceError("REUSED_ANALYSIS_LOCK_AUDIT_MISSING")
    lock_exists = EXECUTION_LOCK.exists() or EXECUTION_LOCK.is_symlink()
    if lock_audit.get("state") == "PENDING_MISSING_EXECUTION_LOCK":
        if lock_exists:
            raise EvidenceError("REUSED_ANALYSIS_LOCK_STATE_CHANGED")
    else:
        if not lock_exists or not identity_claim_matches(
            lock_audit.get("identity"), identity(EXECUTION_LOCK)
        ):
            raise EvidenceError("REUSED_ANALYSIS_LOCK_CHANGED")
    relevant_identities = lock_audit.get("verified_relevant_identities")
    if isinstance(relevant_identities, Mapping):
        for name, claim in relevant_identities.items():
            if not isinstance(claim, Mapping) or not identity_claim_matches(
                claim, identity(Path(str(claim.get("path", ""))))
            ):
                raise EvidenceError(
                    f"REUSED_ANALYSIS_LOCK_RELEVANT_IDENTITY_CHANGED:{name}"
                )
    receipt_audits = bundle.get("receipt_audits")
    if not isinstance(receipt_audits, Mapping):
        raise EvidenceError("REUSED_ANALYSIS_RECEIPT_AUDITS_MISSING")
    for item_id, receipt_path in RECEIPTS.items():
        audit = receipt_audits.get(item_id)
        if not isinstance(audit, Mapping):
            raise EvidenceError(f"REUSED_ANALYSIS_RECEIPT_AUDIT_MISSING:{item_id}")
        exists = receipt_path.exists() or receipt_path.is_symlink()
        if audit.get("state") == "PENDING_MISSING_RECEIPT":
            if exists:
                raise EvidenceError(f"REUSED_ANALYSIS_RECEIPT_STATE_CHANGED:{item_id}")
        elif not exists or not identity_claim_matches(audit.get("identity"), identity(receipt_path)):
            raise EvidenceError(f"REUSED_ANALYSIS_RECEIPT_CHANGED:{item_id}")
        claim_identity = audit.get("claim_identity")
        if isinstance(claim_identity, Mapping) and not identity_claim_matches(
            claim_identity, identity(ITEM_DIRS[item_id] / CLAIM_NAME)
        ):
            raise EvidenceError(f"REUSED_ANALYSIS_CLAIM_CHANGED:{item_id}")
        process_log_identity = audit.get("process_log_identity")
        if isinstance(process_log_identity, Mapping) and not identity_claim_matches(
            process_log_identity, identity(ITEM_DIRS[item_id] / LOG_NAME)
        ):
            raise EvidenceError(f"REUSED_ANALYSIS_PROCESS_LOG_CHANGED:{item_id}")
        artifact_outputs = audit.get("artifact_outputs")
        if isinstance(artifact_outputs, Mapping):
            for raw_path, claim in artifact_outputs.items():
                if (
                    not isinstance(raw_path, str)
                    or not isinstance(claim, Mapping)
                    or not identity_claim_matches(claim, identity(Path(raw_path)))
                ):
                    raise EvidenceError(
                        f"REUSED_ANALYSIS_ARTIFACT_OUTPUT_CHANGED:{item_id}:{raw_path}"
                    )
    bridge = bundle.get("hfnet_bridge_audit")
    if not isinstance(bridge, Mapping) or not identity_claim_matches(
        bridge.get("identity"), identity(HFNET_BRIDGE)
    ):
        raise EvidenceError("REUSED_ANALYSIS_HFNET_BRIDGE_CHANGED")
    if not identity_claim_matches(
        bridge.get("manifest_identity"), identity(HFNET_BRIDGE_MANIFEST)
    ):
        raise EvidenceError("REUSED_ANALYSIS_HFNET_BRIDGE_MANIFEST_CHANGED")
    run_result_audit = bridge.get("run_result_audit")
    if not isinstance(run_result_audit, Mapping) or not identity_claim_matches(
        run_result_audit.get("identity"), identity(HFNET_RUN_RESULT)
    ):
        raise EvidenceError("REUSED_ANALYSIS_HFNET_RUN_RESULT_CHANGED")
    if not identity_claim_matches(
        bridge.get("score_crop_identity"), identity(HFNET_SCORE_CROP)
    ):
        raise EvidenceError("REUSED_ANALYSIS_HFNET_SCORE_CROP_CHANGED")
    canonical = bundle.get("hfnet_timestamp_canonicalization_audit")
    if not isinstance(canonical, Mapping) or not identity_claim_matches(
        canonical.get("raw_bag"), identity(RAW_BAG)
    ):
        raise EvidenceError("REUSED_ANALYSIS_RAW_BAG_CHANGED")


def build_analysis_output_manifest(
    staging: Path, logical_output: Path, *, run_evaluator: bool
) -> dict[str, Any]:
    return {
        "schema_version": "aqua-fe-a10-analysis-output-manifest-v1",
        "status": "COMPLETE_ATOMIC_ANALYSIS_OUTPUT",
        "logical_output_dir": str(logical_output),
        "evaluator_enabled": run_evaluator,
        "producer_analyzer": identity(Path(__file__)),
        "files": relative_file_claims(
            staging, excluded={"analysis_output_manifest_v1.json"}
        ),
    }


def verify_existing_analysis_output(
    output_dir: Path, *, run_evaluator: bool
) -> dict[str, Any]:
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise EvidenceError(f"EXISTING_ANALYSIS_OUTPUT_NOT_DIRECTORY:{output_dir}")
    manifest_path = output_dir / "analysis_output_manifest_v1.json"
    manifest = read_json(manifest_path)
    if (
        set(manifest)
        != {
            "schema_version",
            "status",
            "logical_output_dir",
            "evaluator_enabled",
            "producer_analyzer",
            "files",
        }
        or
        manifest.get("schema_version") != "aqua-fe-a10-analysis-output-manifest-v1"
        or manifest.get("status") != "COMPLETE_ATOMIC_ANALYSIS_OUTPUT"
        or manifest.get("logical_output_dir") != str(output_dir)
        or manifest.get("evaluator_enabled") is not run_evaluator
        or not isinstance(manifest.get("files"), Mapping)
    ):
        raise EvidenceError("EXISTING_ANALYSIS_OUTPUT_MANIFEST_DRIFT")
    if not identity_claim_matches(
        manifest.get("producer_analyzer"), identity(Path(__file__))
    ):
        raise EvidenceError("EXISTING_ANALYSIS_OUTPUT_PRODUCER_CHANGED")
    actual_claims = relative_file_claims(
        output_dir, excluded={"analysis_output_manifest_v1.json"}
    )
    if actual_claims != manifest["files"]:
        raise EvidenceError("EXISTING_ANALYSIS_OUTPUT_FILE_IDENTITY_DRIFT")
    bundle = read_json(
        output_dir / "samehistory_system_a10_analysis_bundle_v1.json"
    )
    validate_reused_external_evidence(bundle)
    return bundle


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--no-evaluator",
        action="store_true",
        help="audit terminal/usability readiness without invoking the CPU evaluator",
    )
    args = parser.parse_args(argv)
    output_dir = args.output_dir.absolute()
    run_evaluator = not args.no_evaluator
    if output_dir.exists() or output_dir.is_symlink():
        try:
            bundle = verify_existing_analysis_output(
                output_dir, run_evaluator=run_evaluator
            )
        except Exception as error:
            print(f"analysis_error={error}", file=sys.stderr)
            return 2
        bundle_path = output_dir / "samehistory_system_a10_analysis_bundle_v1.json"
        print(f"bundle={bundle_path}")
        print("output_reused=1")
        print(f"analysis_state={bundle['analysis_state']}")
        print(f"formal_ape_gate_open={int(bundle['accuracy']['formal_ape_gate_open'])}")
        print(f"winner_permitted={int(bundle['accuracy']['formal_winner_permitted'])}")
        return 0
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.staging.", dir=str(output_dir.parent))
    )
    try:
        bundle = build_bundle(
            staging,
            run_evaluator=run_evaluator,
            logical_output_dir=output_dir,
        )
        bundle_path_staging = staging / "samehistory_system_a10_analysis_bundle_v1.json"
        bundle_path_staging.write_text(
            json.dumps(
                bundle,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            ) + "\n",
            encoding="utf-8",
        )
        if read_json(bundle_path_staging) != bundle:
            raise EvidenceError("ANALYSIS_BUNDLE_STRICT_READBACK_MISMATCH")
        write_rows_csv(staging / "samehistory_system_a10_rows_v1.csv", bundle["systems"])
        write_report(staging / "samehistory_system_a10_analysis_report_v1.md", bundle)
        manifest = build_analysis_output_manifest(
            staging, output_dir, run_evaluator=run_evaluator
        )
        manifest_path = staging / "analysis_output_manifest_v1.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        if read_json(manifest_path) != manifest:
            raise EvidenceError("ANALYSIS_OUTPUT_MANIFEST_STRICT_READBACK_MISMATCH")
        fsync_tree(staging)
        with blocked_termination_signals():
            rename_directory_noreplace(staging, output_dir)
            fsync_directory(output_dir.parent)
    except Exception as error:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        print(f"analysis_error={error}", file=sys.stderr)
        return 2
    bundle_path = output_dir / "samehistory_system_a10_analysis_bundle_v1.json"
    print(f"bundle={bundle_path}")
    print(f"analysis_state={bundle['analysis_state']}")
    print(f"formal_ape_gate_open={int(bundle['accuracy']['formal_ape_gate_open'])}")
    print(f"winner_permitted={int(bundle['accuracy']['formal_winner_permitted'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
