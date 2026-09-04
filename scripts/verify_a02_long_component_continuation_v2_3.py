#!/usr/bin/env python3
"""Additive v2.3 component-only continuation for A02 4500..6300.

The v1, v2.1, and v2.2 protocols are immutable.  v2.2 completed its fixed
order with a scientific FAIL/no-ranking terminal state.  This verifier only
corrects the const-q audit source partition from ``{1}`` to ``{1, 2}``, gives
the never-started XFeat producer and two component VINS replays new one-shot
paths, and seals component usability.  HFNet is immutable unusable carry-
forward and is never rerun, bridged, evaluated, or ranked here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import audit_quality_partition as quality_auditor
from scripts import verify_a02_long_three_arm_eval_inputs_v1 as v1
from scripts import verify_a02_long_three_arm_eval_inputs_v2 as v2_1
from scripts import verify_a02_long_three_arm_eval_inputs_v2_2 as v2_2


FREEZE_SCHEMA = "aqua-fe-a02-4500-6300-component-only-continuation-freeze-v2-3"
FREEZE_STATUS = "FROZEN_THIRD_REVISED_POST_INCIDENT_COMPONENT_ONLY_CONTINUATION"
INCIDENT_SCHEMA = "aqua-fe-a02-4500-6300-v2-2-fixed-order-terminal-incident-v1"
INCIDENT_STATUS = "V2_2_FIXED_ORDER_COMPLETED_FAIL_NO_RANKING"
TERMINAL_SCHEMA = (
    "aqua-fe-a02-long-component-outcomes-terminal-v2-3-post-incident-continuation"
)
TERMINAL_PASS = "TERMINAL_COMPONENT_ARMS_USABLE_NO_THREE_ARM_RANKING_HFNET_UNUSABLE"
TERMINAL_FAIL = "TERMINAL_COMPONENT_ARM_FAILURE_NO_RANKING_HFNET_UNUSABLE"
SCIENTIFIC_ROLE = (
    "THIRD_REVISED_POST_INCIDENT_DEVELOPMENT_EXPLORATORY_"
    "COMPONENT_OUTCOMES_NOT_CONFIRMATORY"
)
RECEIPT_SCHEMA = "aqua-fe-a02-vins-arm-process-receipt-v2-3"

DEFAULT_FREEZE = ROOT / "papers/a02_4500_6300_component_only_continuation_freeze_v2_3.json"
DEFAULT_INCIDENT = ROOT / "papers/a02_4500_6300_v2_2_terminal_incident_v1.json"
DEFAULT_ADDENDUM = ROOT / "papers/2026-08-12--a02-4500-6300-component-only-continuation-v2-3.md"
DEFAULT_BUILDER = ROOT / "scripts/build_a02_long_component_continuation_freeze_v2_3.py"
DEFAULT_TESTS = ROOT / "scripts/tests/test_verify_a02_long_component_continuation_v2_3.py"
DEFAULT_VERIFIER = Path(__file__).resolve()

CORRECTED_AUDIT = (
    ROOT / "papers/a02_4500_6300_constq_quality_partition_audit_v2_3_post_incident.json"
)
XFEAT_ROOT = (
    ROOT
    / "logs/aqualoc_archaeo_vins/"
    "external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_"
    "xfeatbirth_rawlkcarrier_v1_post_incident_v2_3_r1"
)
XFEAT_BAG = XFEAT_ROOT / "features.bag"
XFEAT_MANIFEST = XFEAT_ROOT / "export_manifest.json"
XFEAT_AUDIT = XFEAT_ROOT / "audit.json"
B1_RUN = (
    ROOT
    / "logs/aqualoc_archaeo_vins/"
    "external_klt_every2_litcmp_a02_4500_6300_preroll_"
    "b1_constq_vins_post_incident_v2_3_r1"
)
XFEAT_RUN = (
    ROOT
    / "logs/aqualoc_archaeo_vins/"
    "external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_"
    "xfeatbirth_rawlkcarrier_v1_vins_post_incident_v2_3_r1"
)
B1_VIO = B1_RUN / "vins_output/vio.csv"
XFEAT_VIO = XFEAT_RUN / "vins_output/vio.csv"
B1_LOG = B1_RUN / "vins.log"
XFEAT_LOG = XFEAT_RUN / "vins.log"
TERMINAL_EVIDENCE = (
    ROOT / "papers/a02_4500_6300_component_outcomes_terminal_v2_3_post_incident.json"
)

# v1's sealed replay provenance passes these exact ports into the arm
# validators.  Reuse is safe because v2.2 has completed and the new attempts
# have disjoint paths/tags; changing them would make valid new runs unverifiable.
B1_PORT = 11531
XFEAT_PORT = 11532
B1_TAG = "litcmp_a02_4500_6300_preroll_b1_constq_vins_post_incident_v2_3_r1"
XFEAT_TAG = (
    "litcmp_a02_4500_6300_preroll_"
    "xfeatbirth_rawlkcarrier_v1_vins_post_incident_v2_3_r1"
)

RESERVED_PATHS = [
    str(CORRECTED_AUDIT),
    str(XFEAT_ROOT),
    str(B1_RUN),
    str(XFEAT_RUN),
    str(TERMINAL_EVIDENCE),
]

EXPECTED_NATIVE_SHA256 = "dbe85f68c91e523f56c7f7488accd216a6b56ffc3949eb9e6a09745fa2e5d6cb"
EXPECTED_CONSTQ_SHA256 = "a91b159c46c51c0d3d7232e86901e86862b4f58fbf9bef58a224f9f8444db523"
EXPECTED_V2_2_FREEZE_SHA256 = "6ff86836f3331fdf8618c82ec9d8cf4efaa383893a14a2e335bed81344c37527"
EXPECTED_V2_2_PRESEAL_SHA256 = "1cff9e454466673902f26f09811ad46a60122b1fe0b174b3b2b2c71af906cd7e"
EXPECTED_HFNET_RESULT_SHA256 = "b7c911ca364a9d9233fa9b7cf0c6f245b83e89b129882628075fd8e759c6cb73"

V2_2_PRESEAL = v2_2.DEFAULT_V2_2_EVIDENCE
HFNET_DRIVER_ROOT = v1.DEFAULT_V4_RESULT.parent
HFNET_RUN_ROOT = v1.DEFAULT_HFNET_RUN_DIR
OLD_B1_SKIP_ROOT = v1.DEFAULT_B1.parents[1]
OLD_XFEAT_SKIP_ROOT = v1.DEFAULT_XFEAT.parents[1]
CONSTQ_ROOT = v1.DEFAULT_B1_CONSTQ_BAG.parent
EMPTY_PYCACHE_PREFIX = Path("/tmp/aqua-fe-a02-long-eval-empty-pycache-v1")

_ORIGINAL_LOAD = v1.load_canonical_json
_ORIGINAL_QUALITY_VALIDATOR = v1.validate_quality_chain
_ORIGINAL_RECEIPT_CONTRACT = v1.vins_process_receipt_contract
_ORIGINAL_RECEIPT_VALIDATOR = v1.validate_vins_process_receipt


class ComponentVerificationError(v1.VerificationError):
    """Protocol-specific fail-closed error."""


def identity(path: Path, label: str) -> dict[str, object]:
    _payload, result = v1.read_regular(path, label)
    return result


def require_identity(claim: object, label: str) -> dict[str, object]:
    if not isinstance(claim, Mapping) or not isinstance(claim.get("path"), str):
        raise ComponentVerificationError(f"{label}_IDENTITY_INVALID")
    actual = identity(Path(str(claim["path"])), label)
    if dict(claim) != actual:
        raise ComponentVerificationError(f"{label}_IDENTITY_MISMATCH")
    return actual


def tree_record(root: Path, label: str) -> dict[str, object]:
    entries = v2_1.inventory_tree(root, label)
    return {
        "entries": entries,
        "root": str(root.resolve(strict=True)),
        "summary": v2_1._inventory_summary(entries),
    }


def old_skip_tree(root: Path, label: str, arm: str) -> dict[str, object]:
    tree = tree_record(root, label)
    regular = [
        entry for entry in tree["entries"] if entry.get("type") == "regular"
    ]
    if (
        len(tree["entries"]) != 2
        or len(regular) != 1
        or regular[0].get("relative_path") != "process_rc_receipt.json"
    ):
        raise ComponentVerificationError(f"{label}_NOT_SINGLETON_RECEIPT_TREE")
    receipt, receipt_identity = _ORIGINAL_LOAD(
        root / "process_rc_receipt.json", f"{label}_RECEIPT"
    )
    expected = v1.build_vins_process_receipt(arm, 125)
    if receipt != expected:
        raise ComponentVerificationError(f"{label}_LEGACY_RC125_RECEIPT_MISMATCH")
    result = dict(tree)
    result["receipt_identity"] = receipt_identity
    result["receipt_record"] = receipt
    result["semantic_interpretation"] = {
        "legacy_attempt_count_field": 1,
        "algorithm_process_start_count": 0,
        "classification": "DEPENDENCY_SKIP_NOT_ALGORITHM_ATTEMPT",
    }
    return result


def _prior_reserved_union(v2_2_freeze: Mapping[str, object]) -> set[str]:
    keys = (
        "legacy_v1_remaining_reserved_paths",
        "v2_1_remaining_reserved_paths",
        "v2_2_remaining_reserved_paths",
    )
    union: set[str] = set()
    for key in keys:
        value = v2_2_freeze.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ComponentVerificationError(f"V2_3_PRIOR_RESERVED_INVALID:{key}")
        union.update(value)
    return union


def prior_present_paths() -> list[str]:
    return sorted(
        {
            str(CONSTQ_ROOT),
            str(OLD_B1_SKIP_ROOT),
            str(OLD_XFEAT_SKIP_ROOT),
            str(v1.DEFAULT_V4_CONTRACT),
            str(HFNET_RUN_ROOT),
            str(HFNET_DRIVER_ROOT),
            str(V2_2_PRESEAL),
        }
    )


def prior_absent_paths(v2_2_freeze: Mapping[str, object]) -> list[str]:
    """Return the frozen semantic absent set, never a live filtered subset."""

    expected = sorted(
        {
            str(v1.DEFAULT_B1_QUALITY_AUDIT),
            str(v1.DEFAULT_XFEAT_BAG.parent),
            str(v1.DEFAULT_HFNET),
            str(v1.DEFAULT_BRIDGE_MANIFEST),
            str(v1.DEFAULT_OUTPUT),
            str(v1.DEFAULT_EVAL_DIR),
            str(v1.DEFAULT_POST_EVAL_OUTPUT),
            str(v2_1.DEFAULT_V2_EVIDENCE),
            str(v2_1.DEFAULT_V2_POST_EVAL_EVIDENCE),
            str(v2_2.DEFAULT_V2_2_POST_EVAL_EVIDENCE),
        }
    )
    union = _prior_reserved_union(v2_2_freeze)
    present = prior_present_paths()
    if set(expected).intersection(present) or set(expected).union(present) != union:
        raise ComponentVerificationError("V2_3_PRIOR_RESERVED_PARTITION_MISMATCH")
    return expected


def require_paths_absent(paths: Sequence[str], label: str) -> None:
    """Fail closed on every frozen path without filtering the claimed set."""

    present = [
        item for item in paths if Path(item).exists() or Path(item).is_symlink()
    ]
    if present:
        raise ComponentVerificationError(f"{label}:{present}")


def current_terminal_carry_forward() -> dict[str, object]:
    run_result, run_result_identity = _ORIGINAL_LOAD(
        v1.DEFAULT_V4_RESULT, "V2_3_HFNET_RUN_RESULT"
    )
    preseal, preseal_identity = _ORIGINAL_LOAD(
        V2_2_PRESEAL, "V2_3_V2_2_PRESEAL"
    )
    if (
        run_result_identity["sha256"] != EXPECTED_HFNET_RESULT_SHA256
        or run_result.get("schema_version") != v1.V4_SCHEMA
        or run_result.get("status") != "HEADLESS_RUN_FAILED_OR_UNUSABLE"
        or run_result.get("return_code") != 1
        or run_result.get("evaluable") is not False
        or run_result.get("execution", {}).get("raw_returncode") != 0
        or run_result.get("gate", {}).get("trajectory", {}).get("pose_count") != 22
        or run_result.get("gate", {}).get("trajectory", {}).get("score_pose_count") != 22
        or run_result.get("gate", {}).get("trajectory", {}).get("score_span_seconds")
        != 1.051619328
    ):
        raise ComponentVerificationError("V2_3_HFNET_TERMINAL_RESULT_MISMATCH")
    if (
        preseal_identity["sha256"] != EXPECTED_V2_2_PRESEAL_SHA256
        or preseal.get("schema_version") != v2_2.PRE_EVAL_SCHEMA_V2_2
        or preseal.get("status") != "FAIL_ONE_OR_MORE_SCIENTIFIC_ARMS"
        or preseal.get("evaluation_contract", {}).get("three_arm_evaluation_eligible")
        is not False
    ):
        raise ComponentVerificationError("V2_3_V2_2_PRESEAL_TERMINAL_MISMATCH")
    return {
        "constq_tree": tree_record(CONSTQ_ROOT, "V2_3_CONSTQ_TREE"),
        "old_b1_skip_tree": old_skip_tree(
            OLD_B1_SKIP_ROOT, "V2_3_OLD_B1_SKIP_TREE", "B1_CONSTQ"
        ),
        "old_xfeat_skip_tree": old_skip_tree(
            OLD_XFEAT_SKIP_ROOT,
            "V2_3_OLD_XFEAT_SKIP_TREE",
            "XFEATBIRTH_RAWLK",
        ),
        "hfnet_contract": identity(v1.DEFAULT_V4_CONTRACT, "V2_3_HFNET_CONTRACT"),
        "hfnet_driver_tree": tree_record(HFNET_DRIVER_ROOT, "V2_3_HFNET_DRIVER_TREE"),
        "hfnet_run_tree": tree_record(HFNET_RUN_ROOT, "V2_3_HFNET_RUN_TREE"),
        "hfnet_run_result": run_result_identity,
        "v2_2_preseal": preseal_identity,
    }


def expected_corrected_audit_claim() -> dict[str, object]:
    return {
        "schema_version": "aqua-fe-quality-partition-audit-v1",
        "contract_pass": True,
        "input_bag": str(v1.DEFAULT_B1_NATIVE_BAG.expanduser().absolute()),
        "input_sha256": EXPECTED_NATIVE_SHA256,
        "output_bag": str(v1.DEFAULT_B1_CONSTQ_BAG.expanduser().absolute()),
        "output_sha256": EXPECTED_CONSTQ_SHA256,
        "feature_topic": "/feature_tracker/feature",
        "source_codes": [1, 2],
        "quality": 1.0,
        "sigma": 1.0,
        "total_messages": 19075,
        "raw_equal_nonfeature_messages": 18175,
        "feature_frames": 900,
        "selected_observations": 315000,
        "changed_observations": 315000,
        "untouched_observations": 0,
    }


def validate_corrected_audit(path: Path = CORRECTED_AUDIT) -> dict[str, object]:
    audit, audit_identity = _ORIGINAL_LOAD(path, "V2_3_CORRECTED_QUALITY_AUDIT")
    if audit != expected_corrected_audit_claim():
        raise ComponentVerificationError("V2_3_CORRECTED_QUALITY_AUDIT_NOT_EXACT")
    return {"status": "PASS_SOURCE_CODES_1_2", "identity": audit_identity}


def probe_native_source_distribution() -> dict[str, object]:
    counts: dict[int, int] = {}
    feature_frames = 0
    with quality_auditor.rosbag.Bag(str(v1.DEFAULT_B1_NATIVE_BAG), "r") as bag:
        for _topic, message, _stamp in bag.read_messages(
            topics=["/feature_tracker/feature"]
        ):
            feature_frames += 1
            channels = quality_auditor.channels(message)
            values = channels.get("source_code")
            if values is None or len(values) != len(message.points):
                raise ComponentVerificationError(
                    "V2_3_NATIVE_SOURCE_CODE_CHANNEL_MISSING_OR_LENGTH_MISMATCH"
                )
            for raw in values:
                code = int(round(raw))
                counts[code] = counts.get(code, 0) + 1
    expected = {1: 310704, 2: 4296}
    if feature_frames != 900 or counts != expected:
        raise ComponentVerificationError(
            f"V2_3_NATIVE_SOURCE_DISTRIBUTION_MISMATCH:{feature_frames}:{counts}"
        )
    return {
        "feature_frames": feature_frames,
        "source_code_counts": {str(key): value for key, value in sorted(counts.items())},
        "total_observations": sum(counts.values()),
    }


def probe_corrected_audit_read_only() -> dict[str, object]:
    before_native = identity(v1.DEFAULT_B1_NATIVE_BAG, "V2_3_PROBE_NATIVE_BEFORE")
    before_constq = identity(v1.DEFAULT_B1_CONSTQ_BAG, "V2_3_PROBE_CONSTQ_BEFORE")
    result = quality_auditor.audit_bags(
        input_bag=v1.DEFAULT_B1_NATIVE_BAG,
        output_bag=v1.DEFAULT_B1_CONSTQ_BAG,
        feature_topic="/feature_tracker/feature",
        source_codes={1, 2},
        quality=1.0,
        min_quality=0.05,
    )
    after_native = identity(v1.DEFAULT_B1_NATIVE_BAG, "V2_3_PROBE_NATIVE_AFTER")
    after_constq = identity(v1.DEFAULT_B1_CONSTQ_BAG, "V2_3_PROBE_CONSTQ_AFTER")
    if before_native != after_native or before_constq != after_constq:
        raise ComponentVerificationError("V2_3_READ_ONLY_AUDIT_CHANGED_FEATURE_BAG")
    if result != expected_corrected_audit_claim():
        raise ComponentVerificationError("V2_3_READ_ONLY_AUDIT_RESULT_MISMATCH")
    return {
        "status": "PASS_READ_ONLY_SOURCE_CODES_1_2",
        "native_feature_bag": after_native,
        "constq_feature_bag": after_constq,
        "selected_observations": 315000,
        "changed_observations": 315000,
        "untouched_observations": 0,
        "native_source_distribution": probe_native_source_distribution(),
    }


def validate_quality_chain_v2_3(
    native_bag: Path, constq_bag: Path, audit_path: Path
) -> dict[str, object]:
    _, native_identity = v1.read_regular(native_bag, "V2_3_B1_NATIVE_FEATURE_BAG")
    _, constq_identity = v1.read_regular(constq_bag, "V2_3_B1_CONSTQ_FEATURE_BAG")
    audit, audit_identity = _ORIGINAL_LOAD(audit_path, "V2_3_B1_CONSTQ_QUALITY_AUDIT")
    expected = expected_corrected_audit_claim()
    if (
        audit != expected
        or audit.get("input_sha256") != native_identity["sha256"]
        or audit.get("output_sha256") != constq_identity["sha256"]
    ):
        raise ComponentVerificationError("V2_3_B1_CONSTQ_QUALITY_AUDIT_MISMATCH")
    return {
        "status": "PASS",
        "native_feature_bag": native_identity,
        "constq_feature_bag": constq_identity,
        "quality_audit": audit_identity,
        "audited_contract": {
            "feature_frames": 900,
            "selected_observations": 315000,
            "changed_observations": 315000,
            "untouched_observations": 0,
            "quality": 1.0,
            "sigma": 1.0,
            "source_codes": [1, 2],
            "nonquality_nonfeature_and_order_equality": True,
        },
    }


def receipt_contract_v2_3(label: str) -> dict[str, object]:
    contracts = {
        "B1_CONSTQ": {
            "run_dir": B1_RUN,
            "feature_bag": v1.DEFAULT_B1_CONSTQ_BAG,
            "port": B1_PORT,
            "tag": B1_TAG,
        },
        "XFEATBIRTH_RAWLK": {
            "run_dir": XFEAT_RUN,
            "feature_bag": XFEAT_BAG,
            "port": XFEAT_PORT,
            "tag": XFEAT_TAG,
        },
    }
    if label not in contracts:
        raise ComponentVerificationError(f"V2_3_UNKNOWN_ARM:{label}")
    return contracts[label]


def build_receipt_v2_3(label: str, return_code: int, started: bool) -> dict[str, object]:
    if isinstance(return_code, bool) or not 0 <= return_code <= 255:
        raise ComponentVerificationError("V2_3_RECEIPT_RETURN_CODE_INVALID")
    contract = receipt_contract_v2_3(label)
    if not started and return_code != 125:
        raise ComponentVerificationError("V2_3_NOT_STARTED_RECEIPT_MUST_BE_RC125")
    status = (
        "PASS_ACTUAL_PROCESS_RC0"
        if started and return_code == 0
        else "FAIL_ACTUAL_PROCESS_NONZERO"
        if started
        else "DEPENDENCY_SKIP_PROCESS_NOT_STARTED"
    )
    return {
        "schema_version": RECEIPT_SCHEMA,
        "status": status,
        "arm": label,
        "return_code": return_code,
        "algorithm_started": started,
        "actual_process_start_count": 1 if started else 0,
        "attempt_count": 1 if started else 0,
        "no_retry": True,
        "run_dir": str(Path(contract["run_dir"]).absolute()),
        "feature_bag": str(Path(contract["feature_bag"]).absolute()),
        "port": contract["port"],
        "tag": contract["tag"],
        "runner": {"path": str(v1.RUNNER), "sha256": v1.RUNNER_SHA256},
        "continuation_generation": "v2.3_component_only",
    }


def validate_receipt_v2_3(run_dir: Path, label: str) -> dict[str, object]:
    receipt, receipt_identity = _ORIGINAL_LOAD(
        run_dir / "process_rc_receipt.json", f"V2_3_{label}_PROCESS_RECEIPT"
    )
    if receipt != build_receipt_v2_3(label, 0, True):
        raise ComponentVerificationError(f"V2_3_{label}_RECEIPT_NOT_ACTUAL_RC0")
    return receipt_identity


def observe_receipt(label: str) -> dict[str, object]:
    contract = receipt_contract_v2_3(label)
    path = Path(contract["run_dir"]) / "process_rc_receipt.json"
    try:
        receipt, receipt_identity = _ORIGINAL_LOAD(path, f"V2_3_{label}_OBSERVED_RECEIPT")
    except (OSError, v1.VerificationError, ValueError) as error:
        return {"status": "MISSING_OR_INVALID", "reason": str(error)}
    return {"status": "OBSERVED", "identity": receipt_identity, "record": receipt}


def injected_v1_arguments(argv: Sequence[str]) -> list[str]:
    fixed = {
        "--b1-quality-audit": CORRECTED_AUDIT,
        "--xfeat-bag": XFEAT_BAG,
        "--xfeat-manifest": XFEAT_MANIFEST,
        "--xfeat-audit": XFEAT_AUDIT,
        "--b1": B1_VIO,
        "--b1-log": B1_LOG,
        "--xfeat": XFEAT_VIO,
        "--xfeat-log": XFEAT_LOG,
        "--evidence": TERMINAL_EVIDENCE,
    }
    for token in argv:
        if token in fixed or any(token.startswith(option + "=") for option in fixed):
            raise ComponentVerificationError(f"V2_3_FIXED_ARGUMENT_CONFLICT:{token}")
    result = list(argv)
    for option, value in fixed.items():
        result.extend([option, str(value)])
    return result


def _assert_v1_immutable() -> None:
    old_freeze, _ = _ORIGINAL_LOAD(v2_1.DEFAULT_OLD_FREEZE, "V2_3_OLD_FREEZE")
    if v1.authoritative_commands() != old_freeze.get("commands"):
        raise ComponentVerificationError("V2_3_V1_AUTHORITATIVE_COMMANDS_CHANGED")
    if (
        v1.DEFAULT_B1_QUALITY_AUDIT != v1.DEFAULT_B1_CONSTQ_BAG.parent / "quality_partition_audit.json"
        or v1.DEFAULT_XFEAT_BAG.parent
        != ROOT
        / "logs/aqualoc_archaeo_vins/"
        "external_xfeat_lk_every2_litcmp_a02_4500_6300_preroll_"
        "xfeatbirth_rawlkcarrier_v1_r1"
    ):
        raise ComponentVerificationError("V2_3_V1_DEFAULTS_CHANGED")


def _build_component_base_record() -> dict[str, object]:
    args = v1.parser().parse_args(injected_v1_arguments(["--action", "check"]))
    prior_loader = v1.load_canonical_json
    prior_quality = v1.validate_quality_chain
    prior_contract = v1.vins_process_receipt_contract
    prior_receipt = v1.validate_vins_process_receipt
    _assert_v1_immutable()
    v1.load_canonical_json = v2_1.load_canonical_json_v2
    v1.validate_quality_chain = validate_quality_chain_v2_3
    v1.vins_process_receipt_contract = receipt_contract_v2_3
    v1.validate_vins_process_receipt = validate_receipt_v2_3
    try:
        _assert_v1_immutable()
        return v1.build_record(args)
    finally:
        v1.load_canonical_json = prior_loader
        v1.validate_quality_chain = prior_quality
        v1.vins_process_receipt_contract = prior_contract
        v1.validate_vins_process_receipt = prior_receipt
        _assert_v1_immutable()


def v2_2_preseal_recomputation() -> dict[str, object]:
    args = v1.parser().parse_args(["--action", "check"])
    prior_loader = v1.load_canonical_json
    v1.load_canonical_json = v2_1.load_canonical_json_v2
    try:
        base = v1.build_record(args)
        binding = v2_2.continuation_binding(
            v2_2.DEFAULT_REVISION_FREEZE, evidence_stage="pre_eval"
        )
        record = v2_2.inject_provenance(base, binding, evidence_stage="pre_eval")
    finally:
        v1.load_canonical_json = prior_loader
    expected_payload = v1.canonical_json(record)
    actual_payload, actual_identity = v1.read_regular(
        V2_2_PRESEAL, "V2_3_RECOMPUTED_V2_2_PRESEAL"
    )
    if actual_payload != expected_payload:
        raise ComponentVerificationError("V2_3_V2_2_PRESEAL_NOT_BYTE_RECOMPUTABLE")
    return {
        "status": "PASS_BYTE_RECOMPUTABLE",
        "identity": actual_identity,
        "v2_2_status": record.get("status"),
    }


def expected_protocol_history(
    incident_v1: Mapping[str, object],
    incident_v2_1: Mapping[str, object],
    incident_v2_2: Mapping[str, object],
) -> list[dict[str, object]]:
    return [
        {
            "protocol": "v1",
            "status": "TERMINATED_AT_COMMAND9_RC42_NOT_RESUMED",
            "incident": dict(incident_v1),
        },
        {
            "protocol": "v2.1",
            "status": "TERMINATED_AT_9R_RC42_NOT_RESUMED",
            "incident": dict(incident_v2_1),
        },
        {
            "protocol": "v2.2",
            "status": "FIXED_ORDER_COMPLETED_FAIL_NO_RANKING_NOT_RESUMED",
            "incident": dict(incident_v2_2),
        },
    ]


def expected_incident_record() -> dict[str, object]:
    v2_2_freeze, v2_2_freeze_identity = _ORIGINAL_LOAD(
        v2_2.DEFAULT_REVISION_FREEZE, "V2_3_INCIDENT_V2_2_FREEZE"
    )
    carry = current_terminal_carry_forward()
    return {
        "schema_version": INCIDENT_SCHEMA,
        "status": INCIDENT_STATUS,
        "scientific_role": "POST_STOP_EXPLORATORY_FAILURE_INCIDENT_NOT_AN_ACCURACY_RESULT",
        "observation_provenance": {
            "captured_from_orchestrator_transcript": True,
            "persistent_raw_stream_artifact": False,
            "root_operator_confirmed_fixed_order_completion": True,
        },
        "v2_2_protocol": {
            "freeze": v2_2_freeze_identity,
            "command_labels": v2_2_freeze["command_labels"],
            "fixed_order_completed": True,
            "must_not_resume_or_retry": True,
            "three_arm_ranking_performed": False,
        },
        "stage_observations": {
            "constq_rewrite": {
                "command_label": "10C2",
                "actual_process_started": True,
                "internal_return_code": 0,
                "output_bag_sha256": EXPECTED_CONSTQ_SHA256,
            },
            "constq_audit": {
                "command_label": "11C2",
                "actual_process_started": True,
                "script_return_code": 1,
                "whole_shell_return_code": 0,
                "audit_output_created": False,
            },
            "constq_gate": {
                "command_label": "12C2",
                "internal_return_code": 1,
                "whole_shell_return_code": 0,
            },
            "xfeat_export": {
                "command_label": "14C2",
                "reported_return_code": 125,
                "algorithm_process_started": False,
            },
            "xfeat_audit": {
                "command_label": "16C2",
                "reported_return_code": 125,
                "algorithm_process_started": False,
            },
            "b1_vins": {
                "command_label": "18C2",
                "reported_return_code": 125,
                "algorithm_process_started": False,
                "receipt": carry["old_b1_skip_tree"]["receipt_identity"],
                "legacy_attempt_count_field": 1,
                "algorithm_process_start_count": 0,
                "semantic_interpretation": "DEPENDENCY_SKIP_NOT_ALGORITHM_ATTEMPT",
            },
            "xfeat_vins": {
                "command_label": "19C2",
                "reported_return_code": 125,
                "algorithm_process_started": False,
                "receipt": carry["old_xfeat_skip_tree"]["receipt_identity"],
                "legacy_attempt_count_field": 1,
                "algorithm_process_start_count": 0,
                "semantic_interpretation": "DEPENDENCY_SKIP_NOT_ALGORITHM_ATTEMPT",
            },
            "hfnet": {
                "command_label": "23C2",
                "actual_process_start_count": 1,
                "raw_process_return_code": 0,
                "wrapper_return_code": 1,
                "evaluable": False,
                "trajectory_pose_count": 22,
                "trajectory_score_span_seconds": 1.051619328,
                "run_result": carry["hfnet_run_result"],
            },
            "bridge": {
                "command_label": "24C2",
                "started": False,
                "output_created": False,
            },
            "preseal": {
                "command_label": "27C2",
                "identity": carry["v2_2_preseal"],
                "status": "FAIL_ONE_OR_MORE_SCIENTIFIC_ARMS",
                "three_arm_evaluation_eligible": False,
            },
            "evaluator": {"started": False, "ranking_created": False},
        },
        "root_cause": {
            "classification": "CONSTQ_AUDITOR_SOURCE_PARTITION_FALSE_NEGATIVE",
            "v2_2_audited_source_codes": [1],
            "correct_source_codes": [1, 2],
            "source_code_1_observations": 310704,
            "source_code_2_observations": 4296,
            "corrected_read_only_probe": expected_corrected_audit_claim(),
            "algorithm_or_feature_bag_modified_by_diagnosis": False,
        },
        "terminal_carry_forward": carry,
        "prior_absent_paths_must_remain_absent": prior_absent_paths(v2_2_freeze),
        "continuation_boundary": {
            "b1_native_and_constq_bags_immutable": True,
            "constq_rewrite_forbidden": True,
            "hfnet_preflight_freeze_run_bridge_evaluator_forbidden": True,
            "old_skip_receipts_are_dependency_skips_not_algorithm_attempts": True,
            "v2_3_is_additive_not_v2_2_resume": True,
        },
    }


def expected_static_paths() -> dict[str, Path]:
    return {
        "incident_v1": v2_1.DEFAULT_INCIDENT,
        "incident_v2_1": v2_2.DEFAULT_INCIDENT_V2_1,
        "incident_v2_2": DEFAULT_INCIDENT,
        "v1_freeze": v2_1.DEFAULT_OLD_FREEZE,
        "v1_verifier": v2_1.V1_VERIFIER,
        "v2_1_freeze": v2_1.DEFAULT_REVISION_FREEZE,
        "v2_1_verifier": v2_1.V2_VERIFIER,
        "v2_2_addendum": v2_2.DEFAULT_ADDENDUM,
        "v2_2_builder": v2_2.DEFAULT_BUILDER,
        "v2_2_freeze": v2_2.DEFAULT_REVISION_FREEZE,
        "v2_2_preseal": V2_2_PRESEAL,
        "v2_2_tests": v2_2.DEFAULT_TESTS,
        "v2_2_verifier": v2_2.V2_2_VERIFIER,
        "v2_3_addendum": DEFAULT_ADDENDUM,
        "v2_3_builder": DEFAULT_BUILDER,
        "v2_3_tests": DEFAULT_TESTS,
        "v2_3_verifier": DEFAULT_VERIFIER,
        "quality_auditor": ROOT / "scripts/audit_quality_partition.py",
    }


def v2_2_freeze_carry_forward() -> object:
    prior, identity_claim = _ORIGINAL_LOAD(
        v2_2.DEFAULT_REVISION_FREEZE, "V2_3_PRIOR_CARRY_FREEZE"
    )
    if identity_claim["sha256"] != EXPECTED_V2_2_FREEZE_SHA256:
        raise ComponentVerificationError("V2_3_PRIOR_CARRY_FREEZE_IDENTITY_MISMATCH")
    return prior.get("carry_forward")


def project_python_prefix() -> str:
    return v1.sealed_evaluation_python_prefix()


def verifier_command(action: str) -> str:
    return (
        f"{project_python_prefix()} scripts/verify_a02_long_component_continuation_v2_3.py "
        f"--revision-freeze {DEFAULT_FREEZE} --action {action}"
    )


def _xfeat_export_invocation() -> str:
    return (
        "test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && "
        "/usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash "
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin "
        "LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 "
        "PYTHONDONTWRITEBYTECODE=1 "
        "PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 "
        "CUDA_VISIBLE_DEVICES=0 "
        f"PYTHONPATH={ROOT}:/home/ma/.local/lib/python3.8/site-packages:/opt/ros/noetic/lib/python3/dist-packages "
        "/usr/bin/python3.8 scripts/export_xfeat_lk_carrier_v1.py "
        f"--source-feature-bag {v1.DEFAULT_B1_CONSTQ_BAG} "
        f"--raw-image-bag {v1.DEFAULT_WINDOW_BAG} "
        f"--camera-yaml {v1.DEFAULT_B1_NATIVE_CAMERA} "
        f"--output-bag {XFEAT_BAG} "
        "--image-topic /camera/image_raw --feature-topic /feature_tracker/feature "
        f"--manifest-json {XFEAT_MANIFEST}"
    )


def _xfeat_audit_invocation() -> str:
    return (
        "test ! -e /tmp/aqua-fe-a02-long-eval-empty-pycache-v1 && "
        "/usr/bin/env -i HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash "
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin "
        "LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 "
        "PYTHONDONTWRITEBYTECODE=1 "
        "PYTHONPYCACHEPREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1 "
        "PYTHONPATH=/opt/ros/noetic/lib/python3/dist-packages "
        f"{v1.XFEAT_AUDIT_PYTHON} scripts/audit_xfeat_lk_carrier_v1.py "
        f"--reference-bag {v1.DEFAULT_B1_CONSTQ_BAG} "
        f"--candidate-bag {XFEAT_BAG} "
        f"--camera-yaml {v1.DEFAULT_B1_NATIVE_CAMERA} "
        "--feature-topic /feature_tracker/feature "
        f"--output-json {XFEAT_AUDIT}"
    )


def _vins_invocation(feature_bag: Path, port: int, tag: str) -> str:
    raw_root = ROOT / "datasets/full_downloads/aqualoc/Archaeological_site_sequences"
    assignments = (
        "HOME=/home/ma", "USER=ma", "LOGNAME=ma", "SHELL=/bin/bash",
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG=C.UTF-8", "LC_ALL=C.UTF-8", "ROS_DISTRO=noetic",
        f"ROS_MASTER_URI=http://localhost:{port}", "PYTHONNOUSERSITE=1",
        "PYTHONHASHSEED=0", "CMAKE_PREFIX_PATH=/home/ma/SLAM/VINS-Fusion-origin/devel",
        "CATKIN_SETUP_UTIL_ARGS='--local --extend'", f"ROOT={ROOT}",
        "VINS_WS=/home/ma/SLAM/VINS-Fusion-origin", f"AQUALOC_ROOT={raw_root}",
        f"RAW_TAR={raw_root / 'archaeo_sequence_2_raw_data.tar.gz'}", "RAW_ROOT=raw_data",
        f"GT_TXT={raw_root / 'archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_02.txt'}",
        f"RAW_BAG={v1.DEFAULT_WINDOW_BAG}", f"FEATURE_BAG_OVERRIDE={feature_bag}",
        f"FRONTEND_CONFIG={ROOT / 'uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml'}",
        "BACKEND_REPLAY_ONLY=0", "RUN_VINS=1", "FORCE_RAW=0", "FORCE_EXPORT=0",
        "EXPORT_FEATURES=0", "VINS_MULTIPLE_THREAD=0",
        "VINS_TD=-0.053694112369382575", "VINS_ESTIMATE_TD=0",
        "VINS_MAX_SOLVER_TIME=0.04", "VINS_MAX_NUM_ITERATIONS=8",
        "AQUALOC_BODY_T_CAM0_MODE=imu_cam", "PLAY_RATE=1.0", "POST_PLAY_SLEEP=8",
        "ROSBAG_PLAY_DELAY=3", "ROSBAG_WAIT_FOR_SUBSCRIBERS=0", "ROSBAG_PLAY_TOPICS=",
        "WAIT_FOR_VINS_SUBSCRIBERS=0", "WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT=20",
        f"PORT={port}", f"TAG={tag}",
    )
    return " ".join((
        "/usr/bin/env", "-i", *assignments, "/bin/bash", "--noprofile", "--norc",
        str(ROOT / "scripts/run_aqualoc_archaeo_vins_eval.sh"),
        "external", "2", "4500", "6300", "klt", "2",
    ))


def expected_commands() -> list[str]:
    prefix = project_python_prefix()
    start = (
        f"{prefix} scripts/build_a02_long_component_continuation_freeze_v2_3.py --action check && "
        f"{verifier_command('check-continuation-start')} || exit 42"
    )
    corrected_audit = (
        f"audit_rc=73; if [ ! -e {CORRECTED_AUDIT} ]; then audit_rc=0; "
        f"{prefix} scripts/audit_quality_partition.py "
        f"--input-bag {v1.DEFAULT_B1_NATIVE_BAG} --output-bag {v1.DEFAULT_B1_CONSTQ_BAG} "
        f"--audit-json {CORRECTED_AUDIT} --feature-topic /feature_tracker/feature "
        "--source-code 1 --source-code 2 --quality 1 --min-quality 0.05 || audit_rc=$?; fi; "
        "printf 'V2_3_CORRECTED_AUDIT_RC=%s\\n' \"$audit_rc\"; exit \"$audit_rc\""
    )
    audit_gate = f"{verifier_command('check-corrected-audit')}"
    static = f"{verifier_command('check-static')} || exit 42"
    xfeat_export = (
        f"xfeat_export_rc=125; if {audit_gate}; then if [ ! -e {XFEAT_ROOT} ]; then "
        f"xfeat_export_rc=0; /usr/bin/mkdir {XFEAT_ROOT} && {_xfeat_export_invocation()} "
        "|| xfeat_export_rc=$?; else xfeat_export_rc=73; fi; fi; "
        "printf 'V2_3_XFEAT_EXPORT_RC=%s\\n' \"$xfeat_export_rc\"; exit \"$xfeat_export_rc\""
    )
    xfeat_audit = (
        f"xfeat_audit_rc=125; if [ -f {XFEAT_BAG} ] && [ -f {XFEAT_MANIFEST} ] "
        f"&& [ ! -e {XFEAT_AUDIT} ]; then xfeat_audit_rc=0; {_xfeat_audit_invocation()} "
        "|| xfeat_audit_rc=$?; fi; "
        "printf 'V2_3_XFEAT_AUDIT_RC=%s\\n' \"$xfeat_audit_rc\"; exit \"$xfeat_audit_rc\""
    )

    def replay(
        *, label: str, variable: str, started: str, feature_bag: Path,
        run_dir: Path, port: int, tag: str, dependency: str
    ) -> str:
        receipt_rc = "b1_receipt_rc" if label == "B1_CONSTQ" else "xfeat_receipt_rc"
        return (
            f"{variable}=125; {started}=0; if {dependency}; then if [ ! -e {run_dir} ]; then "
            f"{started}=1; {variable}=0; {_vins_invocation(feature_bag, port, tag)} "
            f"|| {variable}=$?; else {variable}=73; fi; fi; {receipt_rc}=0; "
            f"{prefix} scripts/verify_a02_long_component_continuation_v2_3.py "
            f"--revision-freeze {DEFAULT_FREEZE} --action seal-arm-rc --arm {label} "
            f"--return-code \"${variable}\" --started \"${started}\" || {receipt_rc}=$?; "
            f"printf 'V2_3_{label}_VINS_RC=%s\\n' \"${variable}\"; "
            f"printf 'V2_3_{label}_RECEIPT_RC=%s\\n' \"${receipt_rc}\"; "
            f"if [ \"${receipt_rc}\" -ne 0 ]; then exit \"${receipt_rc}\"; fi; exit \"${variable}\""
        )

    b1_replay = replay(
        label="B1_CONSTQ", variable="b1_vins_rc", started="b1_started",
        feature_bag=v1.DEFAULT_B1_CONSTQ_BAG, run_dir=B1_RUN,
        port=B1_PORT, tag=B1_TAG, dependency=audit_gate,
    )
    xfeat_replay = replay(
        label="XFEATBIRTH_RAWLK", variable="xfeat_vins_rc", started="xfeat_started",
        feature_bag=XFEAT_BAG, run_dir=XFEAT_RUN, port=XFEAT_PORT, tag=XFEAT_TAG,
        dependency=verifier_command("check-xfeat-input"),
    )
    terminal = (
        f"terminal_seal_rc=0; {verifier_command('seal-terminal')} || terminal_seal_rc=$?; "
        "terminal_check_rc=2; "
        f"if [ -e {TERMINAL_EVIDENCE} ]; then terminal_check_rc=0; "
        f"{verifier_command('check-terminal')} || terminal_check_rc=$?; fi; "
        "printf 'V2_3_TERMINAL_SEAL_RC=%s\\n' \"$terminal_seal_rc\"; "
        "printf 'V2_3_TERMINAL_CHECK_RC=%s\\n' \"$terminal_check_rc\"; "
        "if [ \"$terminal_seal_rc\" -eq 0 ] && [ \"$terminal_check_rc\" -eq 0 ]; then "
        "echo V2_3_COMPONENT_USABILITY_EVIDENCE_SEALED_STATUS_IN_JSON_NO_RANKING; exit 0; "
        "else echo V2_3_COMPONENT_USABILITY_TERMINAL_GATE_FAILED; exit 2; fi"
    )
    commands = [
        start, corrected_audit, audit_gate, static, xfeat_export, static,
        xfeat_audit, b1_replay, xfeat_replay, terminal,
    ]
    joined = "\n".join(commands)
    forbidden = (
        "agent_qi_calibration_rewrite_bag.py",
        "run_a02_b1_klt_nativeq_current_exporter_guarded",
        "run_hfnet_slam_a02_long1801_headless_v4.py",
        "bridge_hfnet_world_body_to_vins_csv_v1.py",
        "evaluate_vins_common_support.py",
        str(v1.DEFAULT_B1_QUALITY_AUDIT),
        str(v1.DEFAULT_XFEAT_BAG.parent),
        str(OLD_B1_SKIP_ROOT),
        str(OLD_XFEAT_SKIP_ROOT),
    )
    if any(token in joined for token in forbidden):
        raise ComponentVerificationError("V2_3_COMMAND_PROTOCOL_FORBIDDEN_TOKEN")
    return commands


def validate_revision(path: Path, *, require_reserved_absent: bool) -> dict[str, object]:
    freeze, freeze_identity = _ORIGINAL_LOAD(path, "V2_3_COMPONENT_FREEZE")
    expected_keys = {
        "schema_version", "status", "working_directory",
        "post_incident_evidence_role", "incident", "protocol_history",
        "prior_v2_2_carry_forward", "v2_2_terminal_carry_forward",
        "prior_present_paths_immutable",
        "prior_absent_paths_must_remain_absent", "reserved_paths_absent_at_freeze",
        "corrected_quality_audit_contract", "narrow_infrastructure_change",
        "component_terminal_contract", "execution_policy", "command_labels",
        "commands", "required_static_identities",
    }
    if (
        set(freeze) != expected_keys
        or
        freeze.get("schema_version") != FREEZE_SCHEMA
        or freeze.get("status") != FREEZE_STATUS
        or freeze.get("working_directory") != str(ROOT)
    ):
        raise ComponentVerificationError("V2_3_FREEZE_SCHEMA_STATUS_CWD_MISMATCH")
    prior = v2_2.validate_revision(
        v2_2.DEFAULT_REVISION_FREEZE, require_remaining_absent=False
    )
    if prior.get("revision_freeze", {}).get("sha256") != EXPECTED_V2_2_FREEZE_SHA256:
        raise ComponentVerificationError("V2_3_V2_2_FREEZE_IDENTITY_MISMATCH")
    static = freeze.get("required_static_identities")
    paths = expected_static_paths()
    if not isinstance(static, Mapping) or set(static) != set(paths):
        raise ComponentVerificationError("V2_3_STATIC_IDENTITY_KEYSET_MISMATCH")
    for label, expected_path in paths.items():
        checked = require_identity(static[label], f"V2_3_STATIC_{label}")
        if checked["path"] != str(expected_path.resolve(strict=True)):
            raise ComponentVerificationError(f"V2_3_STATIC_PATH_MISMATCH:{label}")
    incident, incident_identity = _ORIGINAL_LOAD(DEFAULT_INCIDENT, "V2_3_INCIDENT")
    if incident != expected_incident_record():
        raise ComponentVerificationError("V2_3_INCIDENT_NOT_EXACT_CURRENT_TERMINAL")
    if freeze.get("incident") != incident_identity:
        raise ComponentVerificationError("V2_3_FREEZE_INCIDENT_IDENTITY_MISMATCH")
    history = expected_protocol_history(
        static["incident_v1"], static["incident_v2_1"], static["incident_v2_2"]
    )
    if freeze.get("protocol_history") != history:
        raise ComponentVerificationError("V2_3_PROTOCOL_HISTORY_MISMATCH")
    if freeze.get("prior_v2_2_carry_forward") != v2_2_freeze_carry_forward():
        raise ComponentVerificationError("V2_3_PRIOR_V2_2_CARRY_FORWARD_MISMATCH")
    current_carry = current_terminal_carry_forward()
    if freeze.get("v2_2_terminal_carry_forward") != current_carry:
        raise ComponentVerificationError("V2_3_TERMINAL_CARRY_FORWARD_DRIFT")
    v2_2_freeze, _ = _ORIGINAL_LOAD(v2_2.DEFAULT_REVISION_FREEZE, "V2_3_PRIOR_FREEZE")
    absent = prior_absent_paths(v2_2_freeze)
    if freeze.get("prior_present_paths_immutable") != prior_present_paths():
        raise ComponentVerificationError("V2_3_PRIOR_PRESENT_PATH_SET_MISMATCH")
    if freeze.get("prior_absent_paths_must_remain_absent") != absent:
        raise ComponentVerificationError("V2_3_PRIOR_ABSENT_PATH_SET_MISMATCH")
    require_paths_absent(absent, "V2_3_PRIOR_ABSENT_PATH_APPEARED")
    if freeze.get("reserved_paths_absent_at_freeze") != RESERVED_PATHS:
        raise ComponentVerificationError("V2_3_RESERVED_PATH_SET_MISMATCH")
    if freeze.get("corrected_quality_audit_contract") != expected_corrected_audit_claim():
        raise ComponentVerificationError("V2_3_CORRECTED_AUDIT_FREEZE_CONTRACT_MISMATCH")
    expected_change = {
        "quality_audit_source_codes_before": [1],
        "quality_audit_source_codes_after": [1, 2],
        "constq_rewrite_repeated": False,
        "b1_native_or_constq_bag_modified": False,
        "all_other_component_algorithms_or_parameters_changed": False,
        "hfnet_or_bridge_or_evaluator_executed": False,
    }
    if freeze.get("narrow_infrastructure_change") != expected_change:
        raise ComponentVerificationError("V2_3_NARROW_CHANGE_MISMATCH")
    expected_terminal = {
        "schema_version": TERMINAL_SCHEMA,
        "evidence_path": str(TERMINAL_EVIDENCE),
        "b1_and_xfeat_usability_only": True,
        "component_ranking_performed": False,
        "three_arm_ranking_eligible": False,
        "hfnet_is_immutable_unusable_carry_forward": True,
        "scientific_failure_is_sealed_without_suppressing_later_commands": True,
    }
    if freeze.get("component_terminal_contract") != expected_terminal:
        raise ComponentVerificationError("V2_3_TERMINAL_CONTRACT_MISMATCH")
    if freeze.get("post_incident_evidence_role") != SCIENTIFIC_ROLE:
        raise ComponentVerificationError("V2_3_EVIDENCE_ROLE_MISMATCH")
    if require_reserved_absent:
        require_paths_absent(RESERVED_PATHS, "V2_3_RESERVED_PATH_PRESENT")
    if EMPTY_PYCACHE_PREFIX.exists() or EMPTY_PYCACHE_PREFIX.is_symlink():
        raise ComponentVerificationError("V2_3_PYCACHE_PREFIX_PRESENT")
    if freeze.get("commands") != expected_commands():
        raise ComponentVerificationError("V2_3_COMMAND_PROTOCOL_MISMATCH")
    if freeze.get("command_labels") != [
        "28R3", "29C3", "30C3", "31C3", "32C3",
        "33C3", "34C3", "35C3", "36C3", "37C3",
    ]:
        raise ComponentVerificationError("V2_3_COMMAND_LABELS_MISMATCH")
    policy = freeze.get("execution_policy")
    if policy != {
        "fixed_order": True,
        "formal_commands_executed_by_builder": False,
        "global_start_or_static_failure_stops_protocol": True,
        "scientific_or_dependency_failure_does_not_suppress_later_commands": True,
        "no_retry": True,
        "single_writer_working_directory": str(ROOT),
        "hfnet_bridge_evaluator_forbidden": True,
        "component_ranking_performed": False,
    }:
        raise ComponentVerificationError("V2_3_EXECUTION_POLICY_MISMATCH")
    _assert_v1_immutable()
    result = {
        "status": (
            "PASS_V2_3_COMPONENT_CONTINUATION_START"
            if require_reserved_absent
            else "PASS_V2_3_COMPONENT_CONTINUATION_STATIC"
        ),
        "revision_freeze": freeze_identity,
        "static_identity_count": len(static),
        "reserved_path_count": len(RESERVED_PATHS),
        "v2_2_terminal_carry_forward": current_carry,
    }
    if require_reserved_absent:
        result["corrected_audit_read_only_probe"] = probe_corrected_audit_read_only()
        result["v2_2_preseal_recomputation"] = v2_2_preseal_recomputation()
    return result


def continuation_binding(path: Path) -> dict[str, object]:
    freeze, freeze_identity = _ORIGINAL_LOAD(path, "V2_3_BINDING_FREEZE")
    static = freeze.get("required_static_identities")
    if not isinstance(static, Mapping):
        raise ComponentVerificationError("V2_3_BINDING_STATIC_INVALID")
    active_verifier = identity(DEFAULT_VERIFIER, "V2_3_BINDING_VERIFIER")
    if static.get("v2_3_verifier") != active_verifier:
        raise ComponentVerificationError("V2_3_BINDING_VERIFIER_MISMATCH")
    incident_ids = []
    for label in ("incident_v1", "incident_v2_1", "incident_v2_2"):
        claim = static.get(label)
        incident_ids.append(require_identity(claim, f"V2_3_BINDING_{label}"))
    return {
        "active_continuation_freeze": freeze_identity,
        "active_verifier": active_verifier,
        "role": SCIENTIFIC_ROLE,
        "protocol_history": expected_protocol_history(*incident_ids),
        "source_partition_correction": {
            "only_semantic_delta": "quality_audit_source_codes_[1]_to_[1,2]",
            "constq_rewrite_repeated": False,
            "native_or_constq_bag_modified": False,
        },
        "execution_boundary": {
            "hfnet_immutable_unusable_no_rerun": True,
            "bridge_not_run": True,
            "evaluator_not_run": True,
            "component_ranking_not_performed": True,
            "new_paths_only": True,
            "no_retry": True,
        },
    }


def build_terminal_record(path: Path) -> dict[str, object]:
    validate_revision(path, require_reserved_absent=False)
    base = _build_component_base_record()
    arms = base.get("arms")
    if not isinstance(arms, Mapping) or set(arms) != set(v1.ARM_LABELS):
        raise ComponentVerificationError("V2_3_BASE_ARM_SET_INVALID")
    hfnet = arms.get("HFNET_WHOLE_SYSTEM")
    if not isinstance(hfnet, Mapping) or hfnet.get("status") != "FAIL":
        raise ComponentVerificationError("V2_3_HFNET_MUST_REMAIN_UNUSABLE")
    component_status = {
        label: arms[label].get("status")
        for label in ("B1_CONSTQ", "XFEATBIRTH_RAWLK")
    }
    all_usable = all(value == "PASS" for value in component_status.values())
    carry = current_terminal_carry_forward()
    result = dict(base)
    result["schema_version"] = TERMINAL_SCHEMA
    result["status"] = TERMINAL_PASS if all_usable else TERMINAL_FAIL
    result["scientific_role"] = SCIENTIFIC_ROLE
    result["post_incident_continuation"] = continuation_binding(path)
    result["terminal_outcome"] = {
        "component_arm_status": component_status,
        "component_arms_all_usable": all_usable,
        "component_process_receipts": {
            "B1_CONSTQ": observe_receipt("B1_CONSTQ"),
            "XFEATBIRTH_RAWLK": observe_receipt("XFEATBIRTH_RAWLK"),
        },
        "hfnet_immutable_unusable": {
            "run_result_identity": carry["hfnet_run_result"],
            "raw_process_return_code": 0,
            "wrapper_return_code": 1,
            "evaluable": False,
            "trajectory_pose_count": 22,
            "trajectory_score_span_seconds": 1.051619328,
        },
        "v2_2_preseal_identity": carry["v2_2_preseal"],
        "v2_2_preseal_byte_recomputable": v2_2_preseal_recomputation(),
        "bridge_run": False,
        "evaluator_run": False,
        "component_ranking_performed": False,
        "three_arm_ranking_eligible": False,
        "proxy_reference_is_not_independent_ground_truth": True,
        "terminal_failure_sealed": not all_usable,
    }
    return result


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument(
        "--action",
        choices=(
            "check-continuation-start", "check-static", "check-corrected-audit",
            "check-xfeat-input", "seal-arm-rc", "seal-terminal", "check-terminal",
        ),
        required=True,
    )
    value.add_argument("--revision-freeze", type=Path, default=DEFAULT_FREEZE)
    value.add_argument("--arm", choices=("B1_CONSTQ", "XFEATBIRTH_RAWLK"))
    value.add_argument("--return-code", type=int)
    value.add_argument("--started", type=int, choices=(0, 1))
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.action == "check-continuation-start":
            record = validate_revision(args.revision_freeze, require_reserved_absent=True)
            print(json.dumps(record, sort_keys=True))
            return 0
        validate_revision(args.revision_freeze, require_reserved_absent=False)
        if args.action == "check-static":
            print(json.dumps({"status": "PASS_V2_3_STATIC"}, sort_keys=True))
            return 0
        if args.action == "check-corrected-audit":
            print(json.dumps(validate_corrected_audit(), sort_keys=True))
            return 0
        if args.action == "check-xfeat-input":
            validate_corrected_audit()
            result = v1.validate_xfeat_chain(
                source_bag=v1.DEFAULT_B1_CONSTQ_BAG,
                raw_bag=v1.DEFAULT_WINDOW_BAG,
                camera_yaml=v1.DEFAULT_B1_NATIVE_CAMERA,
                output_bag=XFEAT_BAG,
                manifest_path=XFEAT_MANIFEST,
                audit_path=XFEAT_AUDIT,
            )
            print(json.dumps({"status": "PASS_V2_3_XFEAT_INPUT", "lineage": result}, sort_keys=True))
            return 0
        if args.action == "seal-arm-rc":
            if args.arm is None or args.return_code is None or args.started is None:
                raise ComponentVerificationError("V2_3_SEAL_RECEIPT_ARGUMENTS_MISSING")
            contract = receipt_contract_v2_3(args.arm)
            receipt_path = Path(contract["run_dir"]) / "process_rc_receipt.json"
            if receipt_path.exists() or receipt_path.is_symlink():
                raise ComponentVerificationError("V2_3_PROCESS_RECEIPT_ALREADY_EXISTS")
            record = build_receipt_v2_3(args.arm, args.return_code, bool(args.started))
            payload = v1.canonical_json(record)
            v1.write_exclusive(receipt_path, payload)
            print(json.dumps({
                "status": "SEALED_V2_3_ARM_PROCESS_RECEIPT",
                "evidence": str(receipt_path),
                "evidence_sha256": hashlib.sha256(payload).hexdigest(),
            }, sort_keys=True))
            return 0
        record = build_terminal_record(args.revision_freeze)
        payload = v1.canonical_json(record)
        if args.action == "seal-terminal":
            if TERMINAL_EVIDENCE.exists() or TERMINAL_EVIDENCE.is_symlink():
                raise ComponentVerificationError("V2_3_TERMINAL_EVIDENCE_ALREADY_EXISTS")
            v1.write_exclusive(TERMINAL_EVIDENCE, payload)
            status = "SEALED"
        else:
            existing, _ = v1.read_regular(TERMINAL_EVIDENCE, "V2_3_TERMINAL_EVIDENCE")
            if existing != payload:
                raise ComponentVerificationError("V2_3_TERMINAL_EVIDENCE_DRIFT")
            status = "CHECK_PASS"
        print(json.dumps({
            "status": status,
            "scientific_status": record["status"],
            "evidence": str(TERMINAL_EVIDENCE),
            "evidence_sha256": hashlib.sha256(payload).hexdigest(),
        }, sort_keys=True))
        return 0
    except (v1.VerificationError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"VERIFICATION_BLOCKED:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
