#!/usr/bin/env python3
"""Accuracy controller v2 for cache-adjudicated HFNet runability receipts.

This is a narrow authorization layer over the byte-pinned v1 controller core
and unchanged evaluator.  The v1 outcome-blind seal remains the metric-design
authority.  A separately published delta seal authorizes only the remaining
nine cases, independent cache adjudication, and new v2 output namespaces.
"""

from __future__ import annotations

import argparse
import contextlib
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sys
from typing import Any, Iterator, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = Path(__file__).resolve()
BASE_CONTROLLER = ROOT / "scripts/run_hfnet_v6_samehistory_positive_roster_accuracy_v1.py"
SUPERSESSION_BUILDER_V2 = (
    ROOT / "scripts/build_hfnet_v6_samehistory_positive_accuracy_supersession_v2.py"
)
CACHE_ADJUDICATOR = (
    ROOT / "scripts/adjudicate_hfnet_v6_samehistory_positive_roster_cache_contract_v1.py"
)
ACCURACY_PROTOCOL = (
    ROOT
    / "papers/hfnet_v6_samehistory_positive_accuracy_cache_adjudication_supersession_v2.md"
)
CACHE_CONTRACT_ADDENDUM = (
    ROOT
    / "papers/hfnet_v6_samehistory_positive_roster_cache_contract_prospective_addendum_v1.md"
)
ZERO_KF_WATCHDOG_PROTOCOL = (
    ROOT
    / "papers/hfnet_v6_samehistory_positive_roster_zero_kf_save_hang_watchdog_protocol_v1.md"
)
V2_RUNNER = ROOT / "scripts/run_hfnet_v6_samehistory_positive_roster_v2.py"
V2_POINTER = Path(
    "/mnt/data/AQUA-FE_WS/locks/"
    "hfnet_v6_samehistory_positive_roster_execution_lock_v2.json"
)
DEFAULT_DELTA_SEAL = Path(
    "/mnt/data/AQUA-FE_WS/locks/"
    "hfnet_v6_samehistory_positive_accuracy_supersession_v2.json"
)
RUNTIME_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/"
    "samehistory_old_positive_roster_v2"
)
EXECUTION_LOCK_ROOT = RUNTIME_ROOT / "_accuracy_execution_locks_v2"
ACCURACY_ROOT = RUNTIME_ROOT / "_accuracy_analysis_v2"

SCHEMA_VERSION = "aqua-fe-hfnet-v6-samehistory-positive-roster-accuracy-controller-v2"
CLAIM_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-accuracy-start-once-claim-v2"
TERMINAL_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-accuracy-terminal-receipt-v2"
DELTA_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-accuracy-supersession-v2"
DELTA_STATUS = "SEALED_POST_A05_CACHE_VALIDATOR_INCIDENT_BEFORE_REMAINING_NINE_NO_METRICS"
ADJUDICATION_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-cache-contract-adjudication-v1"
PRESTART_SCHEMA = "aqua-fe-hfnet-v6-samehistory-positive-cache-contract-prestart-v1"
ADJUDICATION_ROLE = "INDEPENDENT_CACHE_VALIDATOR_ADJUDICATION"
ADJUDICATION_PASS = "PASS_CACHE_ONLY_V2_POST_AUDIT_CORRECTED"
WATCHDOG_SCHEMA = "aqua-fe-hfnet-v6-zero-kf-save-hang-watchdog-receipt-v1"
WATCHDOG_PASSIVE_STATUS = "PASSIVE_RUNNER_EXIT_WITHOUT_WATCHDOG_SIGNAL"
WATCHDOG_PROMOTION_CONTRACT = {
    "accuracy_promotable_status": WATCHDOG_PASSIVE_STATUS,
    "pass_requires_runner_reaped": True,
    "pass_requires_zero_signal_attempts": True,
    "pass_requires_zero_signals": True,
    "pass_requires_empty_monitoring_errors": True,
    "raw_runability_receipt_exact_pin_required": True,
    "supervisor_pre_post_exact_code_identity_required": True,
    "runner_claim_chain_exactly_validated_by_adjudicator": True,
    "zero_kf_or_supervision_error_promotable": False,
}

AUTHORIZATION_TOKEN = "RUN_FROZEN_HFNET_V6_SAMEHISTORY_ACCURACY_V2"
AUTHORIZATION_TOKEN_SHA256 = hashlib.sha256(AUTHORIZATION_TOKEN.encode("ascii")).hexdigest()
FREEZE_LOCK_TOKEN = "FREEZE_HFNET_V6_SAMEHISTORY_ACCURACY_LOCK_V2"

BASE_CONTROLLER_EXPECTED = {
    "path": str(BASE_CONTROLLER),
    "size_bytes": 120_822,
    "sha256": "4208597556c62b1023ce564d2ac8065558622193863b942d8a88f6f40b0ff887",
}
BASE_SEAL_EXPECTED = {
    "path": (
        "/mnt/data/AQUA-FE_WS/locks/"
        "hfnet_v6_samehistory_positive_accuracy_prefreeze_seal_v1.json"
    ),
    "size_bytes": 98_877,
    "sha256": "67f2ae286d0e0e3f19a7b490711318e9f7b059c12949e3efe297bbbe5151c6b5",
}
V2_RUNNER_EXPECTED = {
    "path": str(V2_RUNNER),
    "size_bytes": 7_639,
    "sha256": "ec1afff8b1f7a8fdac0e7d395648bd4aa4b47b107bd3c2871a034eb49ba83bbb",
}
V2_POINTER_EXPECTED = {
    "path": str(V2_POINTER),
    "size_bytes": 5_296,
    "sha256": "f9b44e9c126e68d151368c84a562aef5f9b06e1200b6f5dd1b6fe55d33430df1",
}
WATCHDOG_PROTOCOL_EXPECTED = {
    "path": str(ZERO_KF_WATCHDOG_PROTOCOL),
    "size_bytes": 5_967,
    "sha256": "ef328399e1bb23209fd3481426b6d91df6919b0a9dff8685392fd51dc47bf82a",
}
CACHE_ADJUDICATOR_EXPECTED = {
    "path": str(CACHE_ADJUDICATOR),
    "size_bytes": 65_899,
    "sha256": "4ac16863c9ed068351d065724fc3ed4208ee3a7f3cff9d7b35434d5c3d2f3a54",
}
CACHE_CONTRACT_ADDENDUM_EXPECTED = {
    "path": str(CACHE_CONTRACT_ADDENDUM),
    "size_bytes": 5_666,
    "sha256": "3efbf2e0d31548b5c12d9f0ca9f6ff344a82b9453ff4f475a986c6b774ab4dea",
}
REMAINING_CASES = (
    "a07_10800_11200",
    "a08_4500_4660",
    "a09_6000_6200",
    "fjord1_s83_d10",
    "mclab1_s60_d15",
    "cirs_s575_d30",
    "cirs_s900_d30",
    "a02_7600_8000",
    "mclab2_s110_d10",
)

# The delta seal includes this controller's exact identity.  Replacing only
# that field with a sentinel breaks the controller<->seal hash cycle while
# retaining a hash over every other semantic byte.
DELTA_CONTROLLER_SENTINEL = {
    "path": "<NORMALIZED_ACCURACY_CONTROLLER_V2_SELF>",
    "size_bytes": 0,
    "sha256": "0" * 64,
}
DELTA_GLOBAL_LOCK_CONTRACT = {
    "path": str(RUNTIME_ROOT / ".gpu_serial.lock"),
    "mode": "EXCLUSIVE_NONBLOCKING_FLOCK",
    "scope": "DOUBLE_BUILD_COMPARE_THROUGH_HARDLINK_PUBLICATION_OR_DRY_RUN_OUTPUT",
    "held_through_double_build_and_publication": True,
}
DELTA_SEMANTIC_PROJECTION_SHA256 = (
    "72eb51fac12d39c3cd260b651b68bc778092e2edd9188527f77b81ba24c47523"
)


def _load_base_controller() -> Any:
    payload = BASE_CONTROLLER.read_bytes()
    if (
        len(payload) != BASE_CONTROLLER_EXPECTED["size_bytes"]
        or hashlib.sha256(payload).hexdigest() != BASE_CONTROLLER_EXPECTED["sha256"]
    ):
        raise RuntimeError("BASE_CONTROLLER_IDENTITY_MISMATCH")
    specification = importlib.util.spec_from_file_location(
        "_aqua_fe_accuracy_controller_v1_pinned_core", BASE_CONTROLLER
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("BASE_CONTROLLER_IMPORT_SPEC")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


BASE = _load_base_controller()
ControllerError = BASE.ControllerError


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ControllerError(code)


def canonical_json_bytes(value: Any) -> bytes:
    return BASE.canonical_json_bytes(value)


def _contains_plaintext_token(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == "authorization_token":
                return True
            if _contains_plaintext_token(child):
                return True
    elif isinstance(value, list):
        return any(_contains_plaintext_token(child) for child in value)
    elif isinstance(value, str):
        return any(
            token in value
            for token in (AUTHORIZATION_TOKEN, FREEZE_LOCK_TOKEN)
        )
    return False


def delta_semantic_projection_sha256(delta: Mapping[str, Any]) -> str:
    normalized = json.loads(canonical_json_bytes(delta).decode("utf-8"))
    identities = normalized.get("analysis_code_identities")
    require(isinstance(identities, dict), "DELTA_CODE_IDENTITIES")
    require(
        "formal_accuracy_controller_v2" in identities,
        "DELTA_CONTROLLER_V2_IDENTITY_MISSING",
    )
    controller_contract = normalized.get("future_accuracy_controller_contract")
    require(isinstance(controller_contract, dict), "DELTA_CONTROLLER_CONTRACT")
    require(
        controller_contract.get("active_controller")
        == identities["formal_accuracy_controller_v2"],
        "DELTA_CONTROLLER_SELF_REFERENCE_MISMATCH",
    )
    identities["formal_accuracy_controller_v2"] = dict(DELTA_CONTROLLER_SENTINEL)
    controller_contract["active_controller"] = dict(DELTA_CONTROLLER_SENTINEL)
    return hashlib.sha256(canonical_json_bytes(normalized)).hexdigest()


def _identity(value: Any, label: str) -> Mapping[str, Any]:
    return BASE._identity_shape(value, label)


def _verify_delta_file_identity(
    delta: Mapping[str, Any], label: str, key: str
) -> BASE.FileSnapshot:
    identities = delta.get("analysis_code_identities")
    require(isinstance(identities, Mapping), "DELTA_CODE_IDENTITIES")
    expected = _identity(identities.get(key), f"delta_code:{key}")
    snapshot, _payload = BASE.verify_pinned_file(expected, label)
    return snapshot


def _verify_delta_authority(
    delta: Mapping[str, Any],
    key: str,
    expected_path: Path,
    *,
    expected_identity: Mapping[str, Any] | None = None,
) -> BASE.FileSnapshot:
    authorities = delta.get("authorities")
    require(isinstance(authorities, Mapping), "DELTA_AUTHORITIES")
    identity = _identity(authorities.get(key), f"delta_authority:{key}")
    require(identity.get("path") == str(expected_path), f"DELTA_AUTHORITY_PATH:{key}")
    if expected_identity is not None:
        require(dict(identity) == dict(expected_identity), f"DELTA_AUTHORITY_IDENTITY:{key}")
    snapshot, _payload = BASE.verify_pinned_file(identity, f"delta_authority:{key}")
    return snapshot


def validate_delta_seal(
    delta: Mapping[str, Any], snapshot: BASE.FileSnapshot
) -> dict[str, BASE.FileSnapshot]:
    require(snapshot.path == str(DEFAULT_DELTA_SEAL), "DELTA_SEAL_NONCANONICAL_PATH")
    require(delta.get("schema_version") == DELTA_SCHEMA, "DELTA_SEAL_SCHEMA")
    require(delta.get("status") == DELTA_STATUS, "DELTA_SEAL_STATUS")
    require(
        delta_semantic_projection_sha256(delta) == DELTA_SEMANTIC_PROJECTION_SHA256,
        "DELTA_SEAL_SEMANTIC_PROJECTION_MISMATCH",
    )
    require(delta.get("remaining_cases") == list(REMAINING_CASES), "DELTA_REMAINING_CASES")
    require(
        delta.get("parent_accuracy_design_seal") == BASE_SEAL_EXPECTED,
        "DELTA_PARENT_SEAL_IDENTITY",
    )
    BASE.verify_pinned_file(BASE_SEAL_EXPECTED, "delta_parent_v1_seal")
    require(delta.get("parent_design_retained_without_modification") is True, "DELTA_PARENT_NOT_RETAINED")

    snapshots = {
        key: _verify_delta_file_identity(delta, f"delta_code:{key}", key)
        for key in (
            "accuracy_supersession_builder_v2",
            "base_accuracy_controller_core",
            "formal_accuracy_controller_v2",
            "roster_evaluator_core",
            "cache_contract_adjudicator",
            "zero_kf_watchdog",
        )
    }
    require(
        snapshots["base_accuracy_controller_core"].identity == BASE_CONTROLLER_EXPECTED,
        "DELTA_BASE_CONTROLLER_IDENTITY",
    )
    require(
        snapshots["cache_contract_adjudicator"].identity == CACHE_ADJUDICATOR_EXPECTED,
        "DELTA_CACHE_ADJUDICATOR_IDENTITY",
    )
    require(
        snapshots["accuracy_supersession_builder_v2"].path
        == str(SUPERSESSION_BUILDER_V2),
        "DELTA_BUILDER_V2_PATH",
    )
    self_snapshot, _payload = BASE.snapshot_file(CONTROLLER, "controller_v2_self")
    require(
        self_snapshot.identity == snapshots["formal_accuracy_controller_v2"].identity,
        "CONTROLLER_V2_SELF_IDENTITY_MISMATCH",
    )
    authorities = delta.get("authorities")
    require(
        isinstance(authorities, Mapping)
        and set(authorities)
        == {
            "accuracy_cache_adjudication_protocol",
            "cache_contract_governance_addendum",
            "zero_kf_watchdog_protocol",
            "v2_runner",
            "v2_roster_pointer",
        },
        "DELTA_AUTHORITY_SET",
    )
    snapshots.update(
        {
            "accuracy_cache_adjudication_protocol": _verify_delta_authority(
                delta,
                "accuracy_cache_adjudication_protocol",
                ACCURACY_PROTOCOL,
            ),
            "cache_contract_governance_addendum": _verify_delta_authority(
                delta,
                "cache_contract_governance_addendum",
                CACHE_CONTRACT_ADDENDUM,
                expected_identity=CACHE_CONTRACT_ADDENDUM_EXPECTED,
            ),
            "zero_kf_watchdog_protocol": _verify_delta_authority(
                delta,
                "zero_kf_watchdog_protocol",
                ZERO_KF_WATCHDOG_PROTOCOL,
                expected_identity=WATCHDOG_PROTOCOL_EXPECTED,
            ),
            "v2_runner": _verify_delta_authority(
                delta,
                "v2_runner",
                V2_RUNNER,
                expected_identity=V2_RUNNER_EXPECTED,
            ),
            "v2_roster_pointer": _verify_delta_authority(
                delta,
                "v2_roster_pointer",
                V2_POINTER,
                expected_identity=V2_POINTER_EXPECTED,
            ),
        }
    )
    contract = delta.get("cache_adjudication_contract")
    require(isinstance(contract, Mapping), "DELTA_ADJUDICATION_CONTRACT")
    require(
        contract.get("prestart_receipt_schema") == PRESTART_SCHEMA
        and contract.get("terminal_receipt_schema") == ADJUDICATION_SCHEMA
        and contract.get("prestart_receipt_pattern")
        == str(
            RUNTIME_ROOT
            / "_cache_contract_adjudication_v1/{case_id}.prestart.json"
        )
        and contract.get("terminal_receipt_pattern")
        == str(
            RUNTIME_ROOT
            / "_cache_contract_adjudication_v1/{case_id}.runability_adjudication.json"
        )
        and contract.get("receipt_role") == ADJUDICATION_ROLE
        and contract.get("pass_adjudication_status") == ADJUDICATION_PASS
        and contract.get("any_other_failure_can_be_promoted") is False
        and contract.get("accuracy_computed_must_be_false") is True
        and contract.get("replacement_adjudication_permitted") is False,
        "DELTA_ADJUDICATION_CONTRACT_MISMATCH",
    )
    require(
        delta.get("zero_kf_watchdog_contract") == WATCHDOG_PROMOTION_CONTRACT,
        "DELTA_WATCHDOG_PROMOTION_CONTRACT",
    )
    controller_contract = delta.get("future_accuracy_controller_contract")
    require(isinstance(controller_contract, Mapping), "DELTA_CONTROLLER_CONTRACT")
    require(
        controller_contract.get("active_controller")
        == snapshots["formal_accuracy_controller_v2"].identity
        and controller_contract.get("imported_base_controller_core")
        == snapshots["base_accuracy_controller_core"].identity
        and controller_contract.get("unchanged_evaluator")
        == snapshots["roster_evaluator_core"].identity
        and controller_contract.get("authorization_token_sha256")
        == AUTHORIZATION_TOKEN_SHA256
        and controller_contract.get("raw_and_adjudicated_receipts_required") is True
        and controller_contract.get("delta_seal_required_at_freeze_check_and_run") is True
        and controller_contract.get("pre_metric_and_pre_publication_toctou_required") is True
        and controller_contract.get("direct_base_controller_use_on_v2_namespace_authorized")
        is False
        and controller_contract.get("maximum_accuracy_claims_per_case") == 1
        and controller_contract.get("retry_permitted") is False,
        "DELTA_CONTROLLER_CONTRACT_MISMATCH",
    )
    namespaces = delta.get("future_namespaces")
    require(isinstance(namespaces, Mapping), "DELTA_NAMESPACES")
    require(
        namespaces.get("execution_lock_root") == str(EXECUTION_LOCK_ROOT)
        and namespaces.get("accuracy_root") == str(ACCURACY_ROOT)
        and namespaces.get("zero_kf_watchdog_root")
        == str(RUNTIME_ROOT / "_zero_kf_save_hang_watchdog_v1")
        and namespaces.get("zero_kf_watchdog_receipt_schema") == WATCHDOG_SCHEMA
        and namespaces.get("zero_kf_watchdog_receipt_pattern")
        == str(RUNTIME_ROOT / "_zero_kf_save_hang_watchdog_v1/{case_id}.json")
        and namespaces.get("case_execution_lock_pattern")
        == str(EXECUTION_LOCK_ROOT / "{case_id}.json")
        and namespaces.get("case_bridge_receipt_pattern")
        == str(EXECUTION_LOCK_ROOT / "{case_id}.hfnet_timestamp_bridge_receipt.json")
        and namespaces.get("case_claim_pattern")
        == str(ACCURACY_ROOT / "_claims/{case_id}.start_once")
        and namespaces.get("case_output_pattern")
        == str(ACCURACY_ROOT / "{case_id}/attempt_001")
        and namespaces.get("case_terminal_pattern")
        == str(ACCURACY_ROOT / "{case_id}/terminal_receipt.json")
        and namespaces.get("write_once_no_clobber") is True,
        "DELTA_NAMESPACE_MISMATCH",
    )
    a05 = delta.get("a05_terminal_boundary")
    require(
        isinstance(a05, Mapping)
        and a05.get("case_id") == "a05_3300_3700"
        and a05.get("status") == "TERMINAL_FAIL_ACCURACY_NA_NO_RETRY"
        and a05.get("cache_validator_incident_cannot_promote_a05") is True
        and a05.get("accuracy_numeric_authorized") is False
        and "a05_3300_3700" not in delta.get("remaining_cases", []),
        "DELTA_A05_TERMINAL_BOUNDARY",
    )
    publication = delta.get("publication_contract")
    require(isinstance(publication, Mapping), "DELTA_PUBLICATION_CONTRACT")
    require(
        publication.get("global_serial_lock_contract") == DELTA_GLOBAL_LOCK_CONTRACT,
        "DELTA_GLOBAL_LOCK_CONTRACT",
    )
    require(
        publication.get("default_mode") == "DRY_RUN_NO_WRITE"
        and publication.get("token_serialized_into_seal") is False
        and publication.get("replacement_permitted") is False
        and publication.get("double_build_byte_comparison_before_publication") is True,
        "DELTA_PUBLICATION_BOUNDARY",
    )
    require(not _contains_plaintext_token(delta), "PLAINTEXT_AUTHORIZATION_TOKEN_IN_DELTA")
    return snapshots


def read_delta_seal() -> tuple[dict[str, Any], BASE.FileSnapshot, dict[str, BASE.FileSnapshot]]:
    delta, snapshot = BASE.read_canonical_json_path(DEFAULT_DELTA_SEAL, "accuracy_delta_seal")
    code = validate_delta_seal(delta, snapshot)
    return delta, snapshot, code


def _base_seal(delta: Mapping[str, Any]) -> tuple[dict[str, Any], BASE.FileSnapshot]:
    identity = _identity(delta.get("parent_accuracy_design_seal"), "parent_v1_seal")
    seal, snapshot = BASE.read_canonical_json_identity(identity, "parent_v1_seal")
    BASE.verify_prestart_seal(seal, snapshot, require_pristine_destinations=False)
    return seal, snapshot


_ADJUDICATOR_MODULE_CACHE: tuple[dict[str, Any], Any] | None = None


def _load_cache_adjudicator(snapshot: BASE.FileSnapshot) -> Any:
    """Import only the delta-pinned validator implementation."""

    global _ADJUDICATOR_MODULE_CACHE
    require(snapshot.path == str(CACHE_ADJUDICATOR), "ADJUDICATOR_NONCANONICAL_PATH")
    current, _payload = BASE.snapshot_file(CACHE_ADJUDICATOR, "cache_adjudicator_import")
    require(current == snapshot, "ADJUDICATOR_CHANGED_BEFORE_IMPORT")
    if (
        _ADJUDICATOR_MODULE_CACHE is not None
        and _ADJUDICATOR_MODULE_CACHE[0] == snapshot.identity
    ):
        return _ADJUDICATOR_MODULE_CACHE[1]
    module_name = f"_aqua_fe_cache_adjudicator_{snapshot.sha256[:16]}"
    specification = importlib.util.spec_from_file_location(module_name, CACHE_ADJUDICATOR)
    require(
        specification is not None and specification.loader is not None,
        "ADJUDICATOR_IMPORT_SPEC",
    )
    module = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = module
    specification.loader.exec_module(module)
    require(
        getattr(module, "VALIDATOR", None) == CACHE_ADJUDICATOR
        and callable(getattr(module, "validate_post", None)),
        "ADJUDICATOR_API_CONTRACT",
    )
    _ADJUDICATOR_MODULE_CACHE = (dict(snapshot.identity), module)
    return module


def _recompute_and_match_adjudication(
    adjudication: Mapping[str, Any],
    adjudication_snapshot: BASE.FileSnapshot,
    raw_snapshot: BASE.FileSnapshot,
    prestart_snapshot: BASE.FileSnapshot,
    delta_snapshot: BASE.FileSnapshot,
    code: Mapping[str, BASE.FileSnapshot],
    row: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Reject a copied identity field by replaying the exact pinned validator.

    The publication adds only a timestamp and the global-lock evidence.  Every
    scientific and identity-bearing field must equal a fresh read-only
    ``validate_post`` result from the delta-pinned adjudicator bytes.
    """

    case_spec_identity = _identity(row.get("case_spec"), "row_case_spec")
    case_spec_snapshot, _payload = BASE.verify_pinned_file(
        case_spec_identity, "adjudication_case_spec"
    )
    module = _load_cache_adjudicator(code["cache_contract_adjudicator"])
    validate_published = getattr(module, "validate_published_adjudication", None)
    require(callable(validate_published), "ADJUDICATOR_PUBLISHED_VALIDATION_API")
    validation = validate_published(Path(case_spec_snapshot.path))
    require(
        isinstance(validation, Mapping)
        and set(validation)
        == {
            "schema_version",
            "status",
            "case_id",
            "receipt_identity",
            "validator",
            "raw_runability_receipt",
            "prestart_receipt",
            "zero_kf_watchdog_receipt",
            "accuracy_authority_supersession",
            "accuracy_computed",
        }
        and validation.get("status")
        == "PASS_PUBLISHED_ADJUDICATION_EXACTLY_RECOMPUTED"
        and validation.get("case_id") == row.get("case_id")
        and validation.get("receipt_identity") == adjudication_snapshot.identity
        and validation.get("validator") == code["cache_contract_adjudicator"].identity
        and validation.get("raw_runability_receipt") == raw_snapshot.identity
        and validation.get("prestart_receipt") == prestart_snapshot.identity
        and validation.get("accuracy_authority_supersession") == delta_snapshot.identity
        and validation.get("accuracy_computed") is False,
        "ADJUDICATION_PUBLISHED_REPLAY_VALIDATION",
    )
    return validation


def _format_pattern(delta: Mapping[str, Any], section: str, key: str, case_id: str) -> Path:
    value = delta.get(section)
    require(isinstance(value, Mapping), f"DELTA_SECTION:{section}")
    pattern = value.get(key)
    require(isinstance(pattern, str), f"DELTA_PATTERN:{section}:{key}")
    return BASE._canonical_future_path(Path(pattern.format(case_id=case_id)), f"delta:{key}")


def execution_lock_paths(delta: Mapping[str, Any], case_id: str) -> tuple[Path, Path]:
    return (
        _format_pattern(delta, "future_namespaces", "case_execution_lock_pattern", case_id),
        _format_pattern(delta, "future_namespaces", "case_bridge_receipt_pattern", case_id),
    )


def future_publication(delta: Mapping[str, Any], case_id: str) -> dict[str, Any]:
    return {
        "output_dir": str(_format_pattern(delta, "future_namespaces", "case_output_pattern", case_id)),
        "process_claim": str(_format_pattern(delta, "future_namespaces", "case_claim_pattern", case_id)),
        "terminal_receipt": str(_format_pattern(delta, "future_namespaces", "case_terminal_pattern", case_id)),
        "retry_permitted": False,
        "replacement_output_permitted": False,
        "maximum_claims": 1,
    }


@dataclass
class AdjudicationBundle:
    raw: Mapping[str, Any]
    raw_snapshot: BASE.FileSnapshot
    prestart: Mapping[str, Any]
    prestart_snapshot: BASE.FileSnapshot
    adjudication: Mapping[str, Any]
    adjudication_snapshot: BASE.FileSnapshot
    watchdog: Mapping[str, Any]
    watchdog_snapshot: BASE.FileSnapshot
    trajectory_snapshot: BASE.FileSnapshot


def _read_identity_json(value: Any, label: str) -> tuple[dict[str, Any], BASE.FileSnapshot]:
    identity = _identity(value, label)
    return BASE.read_canonical_json_identity(identity, label)


def _validate_raw_cache_only_pass_candidate(
    raw: Mapping[str, Any], case_id: str, delta: Mapping[str, Any]
) -> None:
    contract = delta["cache_adjudication_contract"]
    require(
        raw.get("schema_version")
        == "aqua-fe-hfnet-v6-samehistory-positive-result-v2",
        "RAW_RUNABILITY_SCHEMA",
    )
    require(raw.get("case_id") == case_id, "RAW_RUNABILITY_CASE")
    require(
        raw.get("status") == contract.get("raw_status_required_for_correction"),
        "RAW_RUNABILITY_STATUS_NOT_CORRECTABLE",
    )
    raw_failures = raw.get("failure_codes")
    required_failures = contract.get("raw_failure_code_set_required")
    require(
        isinstance(raw_failures, list)
        and all(isinstance(value, str) for value in raw_failures)
        and len(raw_failures) == len(set(raw_failures))
        and isinstance(required_failures, list)
        and len(raw_failures) == len(required_failures)
        and set(raw_failures) == set(required_failures),
        "RAW_FAILURE_SET_NOT_CACHE_ONLY",
    )
    require(
        raw.get("post_audit_errors") == [contract.get("sole_post_audit_error_required")],
        "RAW_POST_AUDIT_NOT_CACHE_ONLY",
    )
    execution = raw.get("execution")
    require(isinstance(execution, Mapping), "RAW_EXECUTION_MISSING")
    require(
        execution.get("raw_returncode") == 0
        and execution.get("timed_out") is False
        and execution.get("termination") is None
        and execution.get("supervisor_error") is None
        and execution.get("child_reaped_before_post_audit") is True
        and execution.get("popen_invocations") == 1
        and execution.get("retry_performed") is False
        and execution.get("retry_permitted") is False,
        "RAW_EXECUTION_NOT_CLEAN",
    )
    support = raw.get("support")
    require(isinstance(support, Mapping), "RAW_SUPPORT_MISSING")
    trajectory = support.get("trajectory")
    keyframes = support.get("keyframes")
    log = support.get("log")
    require(
        isinstance(trajectory, Mapping)
        and trajectory.get("valid") is True
        and float(trajectory.get("coverage_fraction", 0.0)) >= 0.70
        and float(trajectory.get("longest_contiguous_fraction", 0.0)) >= 0.70,
        "RAW_TRAJECTORY_GATE_FAILED",
    )
    require(
        isinstance(keyframes, Mapping)
        and keyframes.get("valid") is True
        and int(keyframes.get("pose_count", 0)) >= 1,
        "RAW_KEYFRAME_GATE_FAILED",
    )
    require(
        isinstance(log, Mapping)
        and log.get("valid") is True
        and log.get("final_atlas_nonempty") is True
        and int(log.get("initialization_count", 0)) >= 1
        and not log.get("accepted_support_unresolved_reset_events")
        and not log.get("accepted_support_reinitialization_frame_ids"),
        "RAW_LOG_OR_RESET_GATE_FAILED",
    )
    terminal = raw.get("terminal_contract")
    require(
        isinstance(terminal, Mapping)
        and terminal.get("attempt_consumed") is True
        and terminal.get("retry_after_pass_or_fail") is False,
        "RAW_TERMINAL_CONTRACT",
    )
    require(not _contains_plaintext_token(raw), "PLAINTEXT_TOKEN_IN_RAW_RUNABILITY_RECEIPT")


def validate_adjudication_bundle(
    delta: Mapping[str, Any],
    delta_snapshot: BASE.FileSnapshot,
    code: Mapping[str, BASE.FileSnapshot],
    row: Mapping[str, Any],
    case_id: str,
) -> AdjudicationBundle:
    require(case_id in REMAINING_CASES, f"CASE_NOT_IN_REMAINING_NINE:{case_id}")
    raw_path, trajectory_path = BASE._hfnet_terminal_paths(row)
    raw, raw_snapshot = BASE.read_canonical_json_path(raw_path, "raw_runability_receipt")
    _validate_raw_cache_only_pass_candidate(raw, case_id, delta)

    contract = delta["cache_adjudication_contract"]
    pre_path = BASE._canonical_existing_path(
        Path(str(contract["prestart_receipt_pattern"]).format(case_id=case_id)),
        "cache_prestart_receipt",
    )
    adjudication_path = BASE._canonical_existing_path(
        Path(str(contract["terminal_receipt_pattern"]).format(case_id=case_id)),
        "cache_adjudication_receipt",
    )
    prestart, prestart_snapshot = BASE.read_canonical_json_path(
        pre_path, "cache_prestart_receipt"
    )
    adjudication, adjudication_snapshot = BASE.read_canonical_json_path(
        adjudication_path, "cache_adjudication_receipt"
    )
    require(
        prestart.get("schema_version") == PRESTART_SCHEMA
        and prestart.get("status")
        == "FROZEN_PROSPECTIVE_CACHE_SEED_BOUNDARY_NOT_STARTED"
        and prestart.get("case_id") == case_id
        and prestart.get("validator") == code["cache_contract_adjudicator"].identity
        and prestart.get("governance_addendum")
        == code["cache_contract_governance_addendum"].identity
        and prestart.get("zero_kf_watchdog") == code["zero_kf_watchdog"].identity
        and prestart.get("zero_kf_watchdog_protocol")
        == code["zero_kf_watchdog_protocol"].identity
        and prestart.get("v2_runner") == code["v2_runner"].identity
        and prestart.get("accuracy_authority_supersession") == delta_snapshot.identity,
        "CACHE_PRESTART_RECEIPT_CONTRACT",
    )
    require(
        adjudication.get("schema_version") == ADJUDICATION_SCHEMA
        and adjudication.get("status") == "PASS"
        and adjudication.get("role") == ADJUDICATION_ROLE
        and adjudication.get("case_id") == case_id
        and adjudication.get("adjudication_status") == ADJUDICATION_PASS
        and adjudication.get("effective_runability_status") == "PASS"
        and adjudication.get("validator") == code["cache_contract_adjudicator"].identity
        and adjudication.get("failure_codes") == []
        and adjudication.get("raw_runability_receipt") == raw_snapshot.identity
        and adjudication.get("prestart_receipt") == prestart_snapshot.identity
        and adjudication.get("accuracy_authority_supersession") == delta_snapshot.identity
        and adjudication.get("accuracy_computed") is False,
        "CACHE_ADJUDICATION_RECEIPT_CONTRACT",
    )
    require(
        adjudication.get("cache_contract_delta_seal")
        == code["cache_contract_governance_addendum"].identity
        and adjudication.get("execution") == raw.get("execution")
        and adjudication.get("pins", {}).get("validator")
        == code["cache_contract_adjudicator"].identity
        and adjudication.get("pins", {}).get("governance_addendum")
        == code["cache_contract_governance_addendum"].identity
        and adjudication.get("pins", {}).get("accuracy_authority_supersession")
        == delta_snapshot.identity
        and adjudication.get("pins", {}).get("v2_runner") == code["v2_runner"].identity
        and adjudication.get("pins", {}).get("v2_run_result") == raw_snapshot.identity,
        "CACHE_ADJUDICATION_AUTHORITY_PINS",
    )
    replay_validation = _recompute_and_match_adjudication(
        adjudication,
        adjudication_snapshot,
        raw_snapshot,
        prestart_snapshot,
        delta_snapshot,
        code,
        row,
    )
    terminal = adjudication.get("terminal_contract")
    require(
        isinstance(terminal, Mapping)
        and terminal.get("attempt_consumed") is True
        and terminal.get("retry_after_pass_or_fail") is False
        and terminal.get("replacement_adjudication_permitted") is False,
        "CACHE_ADJUDICATION_TERMINAL_CONTRACT",
    )
    trajectory_snapshot, _trajectory_payload = BASE.snapshot_file(
        trajectory_path, "adjudicated_hfnet_trajectory"
    )
    raw_trajectory_identity = raw.get("support", {}).get("trajectory", {}).get("identity")
    adjudicated_trajectory_identity = (
        adjudication.get("support", {}).get("trajectory", {}).get("identity")
    )
    require(
        trajectory_snapshot.identity == raw_trajectory_identity
        and trajectory_snapshot.identity == adjudicated_trajectory_identity
        and trajectory_snapshot.identity == adjudication.get("support_trajectory_identity"),
        "ADJUDICATED_TRAJECTORY_IDENTITY_MISMATCH",
    )
    watchdog_identity = _identity(
        adjudication.get("zero_kf_watchdog_receipt"), "zero_kf_watchdog_receipt"
    )
    watchdog, watchdog_snapshot = BASE.read_canonical_json_identity(
        watchdog_identity, "zero_kf_watchdog_receipt"
    )
    require(
        replay_validation.get("zero_kf_watchdog_receipt") == watchdog_snapshot.identity,
        "ADJUDICATOR_REPLAY_WATCHDOG_IDENTITY",
    )
    namespaces = delta.get("future_namespaces")
    require(isinstance(namespaces, Mapping), "DELTA_NAMESPACES")
    expected_watchdog_path = str(
        Path(str(namespaces["zero_kf_watchdog_receipt_pattern"]).format(case_id=case_id))
    )
    require(
        watchdog_snapshot.path == expected_watchdog_path
        and watchdog.get("schema_version") == WATCHDOG_SCHEMA
        and watchdog.get("status") == WATCHDOG_PASSIVE_STATUS
        and watchdog.get("case_id") == case_id,
        "ZERO_KF_WATCHDOG_RECEIPT_CONTRACT",
    )
    watchdog_execution = watchdog.get("execution")
    require(
        isinstance(watchdog_execution, Mapping)
        and watchdog_execution.get("runner_entry") == code["v2_runner"].path
        and watchdog_execution.get("runner_action") == "run"
        and watchdog_execution.get("case_spec") == row.get("case_spec", {}).get("path")
        and watchdog_execution.get("runner_popen_invocations") == 1
        and watchdog_execution.get("runner_reaped") is True
        and watchdog_execution.get("retry_performed") is False
        and watchdog_execution.get("retry_permitted") is False
        and watchdog_execution.get("hfnet_popen_authority_remains_with_frozen_runner") is True
        and watchdog_execution.get("authorization_token_in_os_argv") is False
        and watchdog_execution.get("authorization_token_in_environment") is False
        and watchdog_execution.get("authorization_token_serialized_in_receipt") is False
        # The supervised v2 CLI returns 2 because its immutable raw receipt is
        # FAIL, while the HFNet child return code inside that receipt is 0.
        and watchdog_execution.get("runner_returncode") == 2,
        "ZERO_KF_WATCHDOG_EXECUTION_NOT_PASSIVE_CLEAN",
    )
    watchdog_action = watchdog.get("watchdog_action")
    require(
        isinstance(watchdog_action, Mapping)
        and watchdog_action.get("sigterm_sent") is False
        and watchdog_action.get("sigterm_sent_at_utc") is None
        and watchdog_action.get("signal_attempt_count") == 0
        and watchdog_action.get("signal_count") == 0
        and watchdog_action.get("signal") is None
        and watchdog_action.get("signal_scope") is None
        and watchdog_action.get("process_group_signaled") is False
        and watchdog_action.get("sigkill_sent") is False
        and watchdog_action.get("other_process_signaled") is False
        and watchdog_action.get("signal_delivery") is None
        and watchdog_action.get("post_signal_identity_state") is None,
        "ZERO_KF_WATCHDOG_SIGNAL_OR_ERROR",
    )
    observations = watchdog.get("observations")
    signature = observations.get("signature_evidence") if isinstance(observations, Mapping) else None
    require(
        isinstance(observations, Mapping)
        and observations.get("monitoring_errors") == []
        and not (isinstance(signature, Mapping) and signature.get("confirmed") is True),
        "ZERO_KF_WATCHDOG_OBSERVATION_NOT_PASSIVE",
    )
    watchdog_pins = watchdog.get("pins")
    require(
        isinstance(watchdog_pins, Mapping)
        and watchdog_pins.get("supervisor_pre") == code["zero_kf_watchdog"].identity
        and watchdog_pins.get("supervisor_post") == code["zero_kf_watchdog"].identity
        and watchdog_pins.get("frozen_runner") == code["v2_runner"].identity
        and watchdog_pins.get("roster_pointer") == code["v2_roster_pointer"].identity
        and watchdog_pins.get("accuracy_prefreeze_seal") == BASE_SEAL_EXPECTED
        and watchdog_pins.get("case_spec") == row.get("case_spec")
        and watchdog_pins.get("prepared_manifest") == row.get("prepared_manifest")
        and watchdog_pins.get("runner_result_at_receipt") == raw_snapshot.identity
        and watchdog_pins.get("stdout_log_at_receipt") == raw.get("pins", {}).get("stdout")
        and watchdog_pins.get("trajectory_at_receipt") == trajectory_snapshot.identity,
        "ZERO_KF_WATCHDOG_PINS",
    )
    watchdog_terminal = watchdog.get("terminal_contract")
    require(
        isinstance(watchdog_terminal, Mapping)
        and watchdog_terminal.get("receipt_path") == expected_watchdog_path
        and watchdog_terminal.get("receipt_outside_attempt_directory") is True
        and watchdog_terminal.get("watchdog_retry_after_receipt") is False
        and watchdog_terminal.get("watchdog_never_fabricates_or_edits_runner_outputs") is True,
        "ZERO_KF_WATCHDOG_TERMINAL_CONTRACT",
    )
    require(not _contains_plaintext_token(prestart), "PLAINTEXT_TOKEN_IN_CACHE_PRESTART_RECEIPT")
    require(not _contains_plaintext_token(adjudication), "PLAINTEXT_TOKEN_IN_ADJUDICATION_RECEIPT")
    require(not _contains_plaintext_token(watchdog), "PLAINTEXT_TOKEN_IN_WATCHDOG_RECEIPT")
    return AdjudicationBundle(
        raw=raw,
        raw_snapshot=raw_snapshot,
        prestart=prestart,
        prestart_snapshot=prestart_snapshot,
        adjudication=adjudication,
        adjudication_snapshot=adjudication_snapshot,
        watchdog=watchdog,
        watchdog_snapshot=watchdog_snapshot,
        trajectory_snapshot=trajectory_snapshot,
    )


def _lock_extension(
    delta_snapshot: BASE.FileSnapshot,
    code: Mapping[str, BASE.FileSnapshot],
    bundle: AdjudicationBundle,
) -> dict[str, Any]:
    return {
        "schema_version": "aqua-fe-hfnet-v6-samehistory-positive-accuracy-lock-extension-v2",
        "status": "EFFECTIVE_RUNABILITY_PASS_FROM_INDEPENDENT_CACHE_ADJUDICATION",
        "accuracy_supersession_seal": delta_snapshot.identity,
        "accuracy_supersession_builder_v2": code[
            "accuracy_supersession_builder_v2"
        ].identity,
        "active_accuracy_controller_v2": code["formal_accuracy_controller_v2"].identity,
        "base_accuracy_controller_core": code["base_accuracy_controller_core"].identity,
        "cache_contract_adjudicator": code["cache_contract_adjudicator"].identity,
        "cache_contract_governance_addendum": code[
            "cache_contract_governance_addendum"
        ].identity,
        "zero_kf_watchdog": code["zero_kf_watchdog"].identity,
        "zero_kf_watchdog_protocol": code["zero_kf_watchdog_protocol"].identity,
        "raw_hfnet_runability_receipt": {
            "identity": bundle.raw_snapshot.identity,
            "status": "FAIL",
        },
        "cache_prestart_receipt": bundle.prestart_snapshot.identity,
        "cache_runability_adjudication_receipt": {
            "identity": bundle.adjudication_snapshot.identity,
            "status": "PASS",
        },
        "zero_kf_watchdog_receipt": bundle.watchdog_snapshot.identity,
        "published_adjudication_semantically_replayed": True,
        "watchdog_passive_zero_signal_contract_verified": True,
        "accuracy_computed_by_adjudicator": False,
        "raw_failure_erased_or_rewritten": False,
    }


def _add_v2_ledger_inputs(
    context: Any,
    delta_snapshot: BASE.FileSnapshot,
    code: Mapping[str, BASE.FileSnapshot],
    bundle: AdjudicationBundle,
    delta: Mapping[str, Any],
) -> None:
    context.ledger.add("accuracy_supersession_v2", delta_snapshot)
    context.ledger.add(
        "accuracy_supersession_builder_v2", code["accuracy_supersession_builder_v2"]
    )
    context.ledger.add("active_accuracy_controller_v2", code["formal_accuracy_controller_v2"])
    context.ledger.add("cache_contract_adjudicator", code["cache_contract_adjudicator"])
    context.ledger.add("zero_kf_watchdog_code", code["zero_kf_watchdog"])
    context.ledger.add("raw_runability_receipt", bundle.raw_snapshot)
    context.ledger.add("cache_prestart_receipt", bundle.prestart_snapshot)
    context.ledger.add("zero_kf_watchdog_receipt", bundle.watchdog_snapshot)
    for key in (
        "accuracy_cache_adjudication_protocol",
        "cache_contract_governance_addendum",
        "zero_kf_watchdog_protocol",
        "v2_runner",
        "v2_roster_pointer",
    ):
        context.ledger.add(f"delta_authority:{key}", code[key])
    BASE._verify_input_aliases(context.ledger)
    context.ledger.verify_all()


def _install_v2_reverification(
    context: Any,
    lock: Mapping[str, Any],
    delta: Mapping[str, Any],
    delta_snapshot: BASE.FileSnapshot,
    code: Mapping[str, BASE.FileSnapshot],
    case_id: str,
) -> None:
    """Make every base-core TOCTOU pass replay the v2 authority chain."""

    original_verify_all = context.ledger.verify_all

    def verify_all_with_v2_replay() -> dict[str, Any]:
        current_delta, current_snapshot, current_code = read_delta_seal()
        require(current_snapshot == delta_snapshot, "DELTA_CHANGED_SINCE_CONTEXT_FREEZE")
        require(current_delta == delta, "DELTA_VALUE_CHANGED_SINCE_CONTEXT_FREEZE")
        for key, snapshot in code.items():
            require(current_code.get(key) == snapshot, f"DELTA_PIN_CHANGED:{key}")
        _validate_lock_extension(
            lock,
            current_delta,
            current_snapshot,
            current_code,
            context.row,
            case_id,
        )
        return original_verify_all()

    context.ledger.verify_all = verify_all_with_v2_replay


def _validate_lock_extension(
    lock: Mapping[str, Any],
    delta: Mapping[str, Any],
    delta_snapshot: BASE.FileSnapshot,
    code: Mapping[str, BASE.FileSnapshot],
    row: Mapping[str, Any],
    case_id: str,
) -> AdjudicationBundle:
    bundle = validate_adjudication_bundle(delta, delta_snapshot, code, row, case_id)
    expected = _lock_extension(delta_snapshot, code, bundle)
    require(lock.get("accuracy_supersession_v2") == expected, "LOCK_V2_EXTENSION_MISMATCH")
    require(
        lock.get("accuracy_supersession_seal") == delta_snapshot.identity,
        "LOCK_DELTA_SEAL_IDENTITY",
    )
    require(
        lock.get("hfnet_runability_receipt")
        == {"identity": bundle.adjudication_snapshot.identity, "status": "PASS"},
        "LOCK_EFFECTIVE_RUNABILITY_RECEIPT",
    )
    return bundle


def freeze_lock(case_id: str, authorization_token: str) -> dict[str, Any]:
    require(secrets.compare_digest(authorization_token, FREEZE_LOCK_TOKEN), "FREEZE_TOKEN_INVALID")
    require(case_id in REMAINING_CASES, f"CASE_NOT_IN_REMAINING_NINE:{case_id}")
    delta, delta_snapshot, code = read_delta_seal()
    seal, seal_snapshot = _base_seal(delta)
    row = BASE._case_row(seal, case_id)
    lock_path, bridge_path = execution_lock_paths(delta, case_id)
    destinations = BASE.require_distinct_canonical_paths(
        {"execution_lock": lock_path, "bridge_receipt": bridge_path}
    )
    for label, path in destinations.items():
        BASE._destination_absent(path, label)
    publications = BASE.require_distinct_canonical_paths(
        {
            key: Path(str(value))
            for key, value in future_publication(delta, case_id).items()
            if key in ("output_dir", "process_claim", "terminal_receipt")
        }
    )
    for label, path in publications.items():
        BASE._destination_absent(path, f"formal_accuracy_v2:{label}")
    bundle = validate_adjudication_bundle(delta, delta_snapshot, code, row, case_id)
    trajectory_payload = Path(bundle.trajectory_snapshot.path).read_bytes()
    headers, headers_identity, headers_snapshot = BASE._score_headers(row)
    serialized, _positions, _quaternions = BASE.parse_ascii_pose_rows(
        trajectory_payload,
        format_name="HFNET_QXYZW_FLOAT_EPOCH",
        label="hfnet_freeze_v2",
        timestamps_only=True,
    )
    mapped, mappings = BASE.bridge_hfnet_timestamps(serialized, headers)
    bridge = BASE.build_bridge_receipt(
        case_id,
        bundle.trajectory_snapshot.identity,
        headers_identity,
        serialized,
        mapped,
        mappings,
    )
    evaluator, evaluator_snapshot = BASE.import_evaluator(
        BASE._seal_code_identity(seal, "roster_evaluator_core")
    )
    base_controller_snapshot, _ = BASE.verify_pinned_file(
        BASE._seal_code_identity(seal, "formal_accuracy_controller"), "base_controller_core"
    )
    ledger = BASE.IdentityLedger()
    for label, snapshot in (
        ("parent_v1_seal", seal_snapshot),
        ("accuracy_supersession_v2", delta_snapshot),
        ("raw_runability_receipt", bundle.raw_snapshot),
        ("cache_prestart_receipt", bundle.prestart_snapshot),
        ("cache_adjudication_receipt", bundle.adjudication_snapshot),
        ("zero_kf_watchdog_receipt", bundle.watchdog_snapshot),
        ("hfnet_trajectory", bundle.trajectory_snapshot),
        ("score_headers", headers_snapshot),
        ("base_controller_core", base_controller_snapshot),
        ("accuracy_supersession_builder_v2", code["accuracy_supersession_builder_v2"]),
        ("active_controller_v2", code["formal_accuracy_controller_v2"]),
        ("evaluator", evaluator_snapshot),
        ("cache_adjudicator", code["cache_contract_adjudicator"]),
        ("zero_kf_watchdog_code", code["zero_kf_watchdog"]),
        ("accuracy_v2_protocol", code["accuracy_cache_adjudication_protocol"]),
        ("cache_contract_governance_addendum", code["cache_contract_governance_addendum"]),
        ("zero_kf_watchdog_protocol", code["zero_kf_watchdog_protocol"]),
        ("v2_runner", code["v2_runner"]),
        ("v2_roster_pointer", code["v2_roster_pointer"]),
    ):
        ledger.add(label, snapshot)
    for name, identity in BASE._historical_identity_entries(row):
        observed, _payload = BASE.verify_pinned_file(identity, f"historical:{name}")
        ledger.add(f"historical:{name}", observed)
    BASE._verify_input_aliases(ledger)

    def revalidate_freeze_inputs() -> None:
        current_delta, current_delta_snapshot, current_code = read_delta_seal()
        require(current_delta_snapshot == delta_snapshot, "DELTA_CHANGED_DURING_LOCK_FREEZE")
        require(current_delta == delta, "DELTA_VALUE_CHANGED_DURING_LOCK_FREEZE")
        require(current_code == code, "DELTA_CODE_CHANGED_DURING_LOCK_FREEZE")
        current_bundle = validate_adjudication_bundle(
            current_delta,
            current_delta_snapshot,
            current_code,
            row,
            case_id,
        )
        require(current_bundle == bundle, "ADJUDICATION_CHANGED_DURING_LOCK_FREEZE")
        ledger.verify_all()

    # Full pinned-adjudicator replay immediately before the first publication.
    revalidate_freeze_inputs()
    BASE._mkdir_plain(bridge_path.parent)
    bridge_snapshot = BASE.atomic_publish_noreplace(bridge_path, canonical_json_bytes(bridge))
    lock = BASE.build_execution_lock(
        seal=seal,
        seal_snapshot=seal_snapshot,
        row=row,
        evaluator=evaluator,
        runability_receipt_identity=bundle.adjudication_snapshot.identity,
        hfnet_trajectory_identity=bundle.trajectory_snapshot.identity,
        bridge_identity=bridge_snapshot.identity,
        score_headers_identity=headers_identity,
    )
    lock["publication"] = future_publication(delta, case_id)
    lock["controller_contract"]["authorization_token_sha256"] = AUTHORIZATION_TOKEN_SHA256
    lock["accuracy_supersession_seal"] = delta_snapshot.identity
    lock["accuracy_supersession_v2"] = _lock_extension(delta_snapshot, code, bundle)
    # Replay once more after bridge publication and immediately before the
    # execution lock becomes the metric-authorization boundary.
    revalidate_freeze_inputs()
    lock_snapshot = BASE.atomic_publish_noreplace(lock_path, canonical_json_bytes(lock))
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_V2_EXECUTION_LOCK_PUBLISHED_PRE_METRIC",
        "case_id": case_id,
        "accuracy_supersession_seal": delta_snapshot.identity,
        "raw_runability_receipt": bundle.raw_snapshot.identity,
        "cache_adjudication_receipt": bundle.adjudication_snapshot.identity,
        "bridge_receipt": bridge_snapshot.identity,
        "execution_lock": lock_snapshot.identity,
        "support_computed": False,
        "ape_computed": False,
        "rpe_computed": False,
        "ranking_computed": False,
    }


@contextlib.contextmanager
def patched_base_runtime(
    delta: Mapping[str, Any],
    delta_snapshot: BASE.FileSnapshot,
    code: Mapping[str, BASE.FileSnapshot],
) -> Iterator[None]:
    originals = {
        "execution_lock_paths": BASE.execution_lock_paths,
        "_future_publication_from_row": BASE._future_publication_from_row,
        "verify_execution_context": BASE.verify_execution_context,
        "AUTHORIZATION_TOKEN": BASE.AUTHORIZATION_TOKEN,
        "AUTHORIZATION_TOKEN_SHA256": BASE.AUTHORIZATION_TOKEN_SHA256,
        "SCHEMA_VERSION": BASE.SCHEMA_VERSION,
        "CLAIM_SCHEMA": BASE.CLAIM_SCHEMA,
        "TERMINAL_SCHEMA": BASE.TERMINAL_SCHEMA,
    }

    def v2_execution_paths(_seal: Mapping[str, Any], case_id: str) -> tuple[Path, Path]:
        return execution_lock_paths(delta, case_id)

    def v2_publication(row: Mapping[str, Any]) -> dict[str, Any]:
        return future_publication(delta, str(row["case_id"]))

    original_verify = originals["verify_execution_context"]

    def enhanced_verify(
        case_id: str,
        lock: Mapping[str, Any],
        lock_snapshot: BASE.FileSnapshot,
        *,
        require_destinations_absent: bool,
    ) -> Any:
        require(case_id in REMAINING_CASES, f"CASE_NOT_IN_REMAINING_NINE:{case_id}")
        context = original_verify(
            case_id,
            lock,
            lock_snapshot,
            require_destinations_absent=require_destinations_absent,
        )
        bundle = _validate_lock_extension(
            lock, delta, delta_snapshot, code, context.row, case_id
        )
        _add_v2_ledger_inputs(context, delta_snapshot, code, bundle, delta)
        _install_v2_reverification(
            context, lock, delta, delta_snapshot, code, case_id
        )
        return context

    BASE.execution_lock_paths = v2_execution_paths
    BASE._future_publication_from_row = v2_publication
    BASE.verify_execution_context = enhanced_verify
    BASE.AUTHORIZATION_TOKEN = AUTHORIZATION_TOKEN
    BASE.AUTHORIZATION_TOKEN_SHA256 = AUTHORIZATION_TOKEN_SHA256
    BASE.SCHEMA_VERSION = SCHEMA_VERSION
    BASE.CLAIM_SCHEMA = CLAIM_SCHEMA
    BASE.TERMINAL_SCHEMA = TERMINAL_SCHEMA
    try:
        yield
    finally:
        for name, value in originals.items():
            setattr(BASE, name, value)


def check_case(case_id: str, execution_lock: Path) -> dict[str, Any]:
    delta, delta_snapshot, code = read_delta_seal()
    expected_lock, _bridge = execution_lock_paths(delta, case_id)
    require(execution_lock == expected_lock, "EXECUTION_LOCK_NONCANONICAL_V2_PATH")
    with patched_base_runtime(delta, delta_snapshot, code):
        result = BASE.check_case(case_id, execution_lock)
    result["schema_version"] = SCHEMA_VERSION
    result["accuracy_supersession_seal"] = delta_snapshot.identity
    result["active_accuracy_controller_v2"] = code["formal_accuracy_controller_v2"].identity
    result["raw_and_adjudicated_receipts_verified"] = True
    return result


def run_case(case_id: str, execution_lock: Path, authorization_token: str) -> dict[str, Any]:
    delta, delta_snapshot, code = read_delta_seal()
    expected_lock, _bridge = execution_lock_paths(delta, case_id)
    require(execution_lock == expected_lock, "EXECUTION_LOCK_NONCANONICAL_V2_PATH")
    with patched_base_runtime(delta, delta_snapshot, code):
        result = BASE.run_case(case_id, execution_lock, authorization_token)
    return {
        **result,
        "accuracy_supersession_seal": delta_snapshot.identity,
        "active_accuracy_controller_v2": code["formal_accuracy_controller_v2"].identity,
        "raw_and_adjudicated_receipts_verified": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze-lock")
    freeze.add_argument("--case-id", required=True, choices=REMAINING_CASES)
    freeze.add_argument("--authorization-token", required=True)
    check = commands.add_parser("check")
    check.add_argument("--case-id", required=True, choices=REMAINING_CASES)
    check.add_argument("--execution-lock", type=Path, required=True)
    run = commands.add_parser("run")
    run.add_argument("--case-id", required=True, choices=REMAINING_CASES)
    run.add_argument("--execution-lock", type=Path, required=True)
    run.add_argument("--authorization-token", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.command == "freeze-lock":
            result = freeze_lock(arguments.case_id, arguments.authorization_token)
        elif arguments.command == "check":
            result = check_case(arguments.case_id, arguments.execution_lock)
        else:
            result = run_case(
                arguments.case_id,
                arguments.execution_lock,
                arguments.authorization_token,
            )
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except BaseException as error:
        code = getattr(error, "code", f"{type(error).__name__}:{error}")
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "BLOCKED_NO_ACCURACY_NO_RANKING",
                    "error": code,
                    "accuracy_numeric_authorized": False,
                    "ranking_authorized": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
