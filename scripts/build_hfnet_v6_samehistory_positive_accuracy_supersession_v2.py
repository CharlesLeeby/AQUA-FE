#!/usr/bin/env python3
"""Build the post-A05, pre-remaining-nine accuracy delta seal.

The outcome-blind v1 seal is an immutable parent.  This builder never rebuilds
or edits it.  The default command is a read-only dry-run; publication requires
an explicit token and uses FUSE-safe hard-link no-replace semantics.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/"
    "samehistory_old_positive_roster_v2"
)
PUBLICATION_PATH = Path(
    "/mnt/data/AQUA-FE_WS/locks/"
    "hfnet_v6_samehistory_positive_accuracy_supersession_v2.json"
)
BASE_SEAL = Path(
    "/mnt/data/AQUA-FE_WS/locks/"
    "hfnet_v6_samehistory_positive_accuracy_prefreeze_seal_v1.json"
)
BASE_CONTROLLER = ROOT / "scripts/run_hfnet_v6_samehistory_positive_roster_accuracy_v1.py"
SUPERSESSION_BUILDER_V2 = Path(__file__).resolve()
CONTROLLER_V2 = ROOT / "scripts/run_hfnet_v6_samehistory_positive_roster_accuracy_v2.py"
EVALUATOR = ROOT / "scripts/evaluate_hfnet_v6_samehistory_positive_roster_common_support_v1.py"
CACHE_ADJUDICATOR = (
    ROOT / "scripts/adjudicate_hfnet_v6_samehistory_positive_roster_cache_contract_v1.py"
)
ZERO_KF_WATCHDOG = (
    ROOT / "scripts/run_hfnet_v6_samehistory_positive_roster_zero_kf_watchdog_v1.py"
)
CACHE_CONTRACT_ADDENDUM = (
    ROOT
    / "papers/hfnet_v6_samehistory_positive_roster_cache_contract_prospective_addendum_v1.md"
)
ZERO_KF_WATCHDOG_PROTOCOL = (
    ROOT
    / "papers/hfnet_v6_samehistory_positive_roster_zero_kf_save_hang_watchdog_protocol_v1.md"
)
PROTOCOL = (
    ROOT
    / "papers/hfnet_v6_samehistory_positive_accuracy_cache_adjudication_supersession_v2.md"
)
V2_RUNNER = ROOT / "scripts/run_hfnet_v6_samehistory_positive_roster_v2.py"
V2_POINTER = Path(
    "/mnt/data/AQUA-FE_WS/locks/hfnet_v6_samehistory_positive_roster_execution_lock_v2.json"
)

SCHEMA_VERSION = "aqua-fe-hfnet-v6-samehistory-positive-accuracy-supersession-v2"
STATUS = "SEALED_POST_A05_CACHE_VALIDATOR_INCIDENT_BEFORE_REMAINING_NINE_NO_METRICS"
PUBLISH_TOKEN = "PUBLISH_HFNET_V6_ACCURACY_SUPERSESSION_V2"
PUBLISH_TOKEN_SHA256 = hashlib.sha256(PUBLISH_TOKEN.encode("ascii")).hexdigest()

BASE_SEAL_EXPECTED = (98_877, "67f2ae286d0e0e3f19a7b490711318e9f7b059c12949e3efe297bbbe5151c6b5")
BASE_CONTROLLER_EXPECTED = (
    120_822,
    "4208597556c62b1023ce564d2ac8065558622193863b942d8a88f6f40b0ff887",
)
EVALUATOR_EXPECTED = (
    109_889,
    "91b0245a4f8cd76b95f3fa2a18bcf67fe1ce9bfe7324d996ca23fb37baedeca5",
)
V2_RUNNER_EXPECTED = (
    7_639,
    "ec1afff8b1f7a8fdac0e7d395648bd4aa4b47b107bd3c2871a034eb49ba83bbb",
)
V2_POINTER_EXPECTED = (
    5_296,
    "f9b44e9c126e68d151368c84a562aef5f9b06e1200b6f5dd1b6fe55d33430df1",
)
ZERO_KF_WATCHDOG_EXPECTED = (
    35_087,
    "a85c6620fb16bb3c2525e654342aa22ab816684030d41bc598ead752fc399b71",
)
CACHE_ADJUDICATOR_EXPECTED = (
    65_899,
    "4ac16863c9ed068351d065724fc3ed4208ee3a7f3cff9d7b35434d5c3d2f3a54",
)
CACHE_CONTRACT_ADDENDUM_EXPECTED = (
    5_666,
    "3efbf2e0d31548b5c12d9f0ca9f6ff344a82b9453ff4f475a986c6b774ab4dea",
)
ZERO_KF_WATCHDOG_PROTOCOL_EXPECTED = (
    5_967,
    "ef328399e1bb23209fd3481426b6d91df6919b0a9dff8685392fd51dc47bf82a",
)

A05 = "a05_3300_3700"
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
EXPECTED_PREPARED: Mapping[str, tuple[int, str]] = {
    "a07_10800_11200": (12_493, "37b83a33fe7de41840aaa755d5dc8b620f9ccac25d2b7fe440ab218fd03f0433"),
    "a08_4500_4660": (12_457, "4a51677efb9847d8d7da1c38618bd17a46456b342d5ee755efb00961d483ab7e"),
    "a09_6000_6200": (12_457, "acbe74bd8860d60fd2f9544741f0550f07309587979e9e455828a4c6aa279628"),
    "fjord1_s83_d10": (12_550, "2f1735cf84e17d47736ec19a4f1b1306c705ea8c9e8ffb6d3857ee49ea9aebf1"),
    "mclab1_s60_d15": (12_552, "5685ceb62aee423adffdbd841ed9680222c39c4d77987030eeb6ffa416e2ff72"),
    "cirs_s575_d30": (12_373, "e6c4ee20c36dc7cb7cf635db69bc841dcce8904b9ff92317e0c7551f1bd4b1e9"),
    "cirs_s900_d30": (12_373, "3ad88677a431928e9c81e9d78bd3a0e63f7564a5bf9aed715ebe2a8f5b50feca"),
    "a02_7600_8000": (12_457, "e6c936e716668c3b0fefff70286fcd221d1cfe56740ad044bebc73557c6337fb"),
    "mclab2_s110_d10": (12_568, "7ac863487757ad92e61d3da299d71730cd15d0befc0706af154cb2f787de742b"),
}

ADJUDICATION_ROOT = RUNTIME_ROOT / "_cache_contract_adjudication_v1"
EXECUTION_LOCK_ROOT = RUNTIME_ROOT / "_accuracy_execution_locks_v2"
ACCURACY_ROOT = RUNTIME_ROOT / "_accuracy_analysis_v2"
WATCHDOG_ROOT = RUNTIME_ROOT / "_zero_kf_save_hang_watchdog_v1"
GLOBAL_SERIAL_LOCK = RUNTIME_ROOT / ".gpu_serial.lock"
SERIALIZED_GLOBAL_LOCK_CONTRACT = {
    "path": str(GLOBAL_SERIAL_LOCK),
    "mode": "EXCLUSIVE_NONBLOCKING_FLOCK",
    "scope": "DOUBLE_BUILD_COMPARE_THROUGH_HARDLINK_PUBLICATION_OR_DRY_RUN_OUTPUT",
    "held_through_double_build_and_publication": True,
}


class BuildError(RuntimeError):
    pass


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_existing(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise BuildError(f"PATH_NOT_ABSOLUTE:{label}")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise BuildError(f"PATH_RESOLVE_FAILED:{label}:{type(error).__name__}") from error
    if resolved != path or path.is_symlink():
        raise BuildError(f"PATH_NOT_CANONICAL_REGULAR:{label}")
    return resolved


def _absent(path: Path, label: str) -> None:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return
    raise BuildError(f"PATH_MUST_BE_ABSENT:{label}")


def file_identity(
    path: Path,
    label: str,
    expected: tuple[int, str] | None = None,
) -> dict[str, Any]:
    canonical = _canonical_existing(path, label)
    metadata = os.lstat(canonical)
    if not stat.S_ISREG(metadata.st_mode):
        raise BuildError(f"NOT_REGULAR_FILE:{label}")
    payload = canonical.read_bytes()
    observed = {
        "path": str(canonical),
        "size_bytes": len(payload),
        "sha256": sha256_bytes(payload),
    }
    if expected is not None and (observed["size_bytes"], observed["sha256"]) != expected:
        raise BuildError(f"IDENTITY_MISMATCH:{label}")
    return observed


def read_canonical_json(
    path: Path, label: str, expected: tuple[int, str] | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    identity = file_identity(path, label, expected)
    payload = path.read_bytes()
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BuildError(f"JSON_INVALID:{label}") from error
    if not isinstance(value, dict) or payload != canonical_json_bytes(value):
        raise BuildError(f"JSON_NOT_CANONICAL_OBJECT:{label}")
    return value, identity


def _a05_boundary() -> dict[str, Any]:
    attempt = RUNTIME_ROOT / A05 / "attempt_001"
    paths = {
        "prepared_manifest": attempt / "prepared_manifest.json",
        "attempt_process_start_claim": attempt / "process_start_claim.json",
        "permanent_process_start_claim": RUNTIME_ROOT / "_case_claims" / f"{A05}.process_start_claim.json",
        "permanent_start_once": RUNTIME_ROOT / "_case_claims" / f"{A05}.start_once",
        "raw_runability_receipt": attempt / "run_result.json",
        "stdout": attempt / "headless.stdout.log",
        "stderr": attempt / "headless.stderr.log",
    }
    expected = {
        "prepared_manifest": (12_457, "aa24be0a28216dcc0ddbf42d445171ba4a266c66950150179db5f400ffcf8e26"),
        "attempt_process_start_claim": (3_266, "754ea40ee10aa154d9c329e0eac6a46d59099e823dd2c733ed359a3d066c9230"),
        "permanent_process_start_claim": (3_266, "754ea40ee10aa154d9c329e0eac6a46d59099e823dd2c733ed359a3d066c9230"),
        "permanent_start_once": (304, "62c1c2401f65c87efb83b77e29edaff12a641e52814e96639814fbfb0866c0cb"),
        "raw_runability_receipt": (6_926, "16de64e13e07b7e8bcf38afddd04348b2d82ce73c5d50e2d2b704f57ee0d1ebe"),
        "stdout": (4_614, "56710e1c5f3f577ffe800334aba3453d1f0e38b6e90566841e00b4b92341e109"),
        "stderr": (5_894, "8829d5558b7b882b91cff0ddeb9eb78425f60b946a1015c39c5e091e4ec55cf3"),
    }
    identities = {
        label: file_identity(path, f"a05:{label}", expected[label])
        for label, path in paths.items()
    }
    receipt, _ = read_canonical_json(
        paths["raw_runability_receipt"], "a05:raw_runability_receipt", expected["raw_runability_receipt"]
    )
    if (
        receipt.get("case_id") != A05
        or receipt.get("status") != "FAIL_SAMEHISTORY_COLDSTART_RUNABILITY"
        or receipt.get("terminal_contract", {}).get("attempt_consumed") is not True
        or receipt.get("terminal_contract", {}).get("retry_after_pass_or_fail") is not False
        or "NO_VALID_KEYFRAME_TRAJECTORY" not in receipt.get("failure_codes", [])
        or "FINAL_ATLAS_EMPTY_OR_UNPARSEABLE" not in receipt.get("failure_codes", [])
    ):
        raise BuildError("A05_TERMINAL_SCIENTIFIC_BOUNDARY_INVALID")
    for trajectory in (
        attempt / "result/trajectory.txt",
        attempt / "result/trajectory_keyframe.txt",
    ):
        _absent(trajectory, f"a05:no_trajectory:{trajectory.name}")
    return {
        "case_id": A05,
        "status": "TERMINAL_FAIL_ACCURACY_NA_NO_RETRY",
        "identities": identities,
        "independent_failure_reasons": [
            "FINAL_ATLAS_ONE_MAP_ZERO_KEYFRAMES",
            "NO_VALID_TRAJECTORY",
            "NO_VALID_KEYFRAME_TRAJECTORY",
            "ACTIVE_MAP_RESET_BOUNDARY_UNRESOLVED",
        ],
        "cache_validator_incident_cannot_promote_a05": True,
        "accuracy_numeric_authorized": False,
    }


def _remaining_case(case_id: str) -> dict[str, Any]:
    attempt = RUNTIME_ROOT / case_id / "attempt_001"
    if attempt.resolve(strict=True) != attempt or attempt.is_symlink():
        raise BuildError(f"ATTEMPT_ROOT_INVALID:{case_id}")
    result_dir = attempt / "result"
    if not result_dir.is_dir() or result_dir.is_symlink() or any(result_dir.iterdir()):
        raise BuildError(f"RESULT_DIRECTORY_NOT_PRISTINE:{case_id}")
    expected_files = {
        "prepared_manifest.json",
        "runtime_config_model_path_only.yaml",
        "run_local_model/HFNet-RT/HF-Net.onnx",
        "run_local_model/HFNet-RT/HF-Net.cache",
    }
    observed_files = {
        path.relative_to(attempt).as_posix() for path in attempt.rglob("*") if path.is_file()
    }
    if observed_files != expected_files:
        raise BuildError(f"PREPARED_FILE_SET_NOT_PRISTINE:{case_id}")
    prepared_path = attempt / "prepared_manifest.json"
    prepared, prepared_identity = read_canonical_json(
        prepared_path, f"remaining:{case_id}:prepared", EXPECTED_PREPARED[case_id]
    )
    if (
        prepared.get("case_id") != case_id
        or prepared.get("status") != "PREPARED_NOT_STARTED"
        or prepared.get("schema_version")
        != "aqua-fe-hfnet-v6-samehistory-positive-prepared-v2"
        or prepared.get("runner")
        != file_identity(V2_RUNNER, "v2_runner", V2_RUNNER_EXPECTED)
    ):
        raise BuildError(f"PREPARED_CONTRACT_INVALID:{case_id}")
    for path in (
        RUNTIME_ROOT / "_case_claims" / f"{case_id}.start_once",
        RUNTIME_ROOT / "_case_claims" / f"{case_id}.process_start_claim.json",
        attempt / "process_start_claim.json",
        attempt / "run_result.json",
        attempt / "headless.stdout.log",
        attempt / "headless.stderr.log",
        ADJUDICATION_ROOT / f"{case_id}.prestart.json",
        ADJUDICATION_ROOT / f"{case_id}.runability_adjudication.json",
        WATCHDOG_ROOT / f"{case_id}.json",
    ):
        _absent(path, f"remaining:{case_id}:{path.name}")
    return {
        "case_id": case_id,
        "status": "PREPARED_NOT_STARTED_ZERO_CLAIMS_RESULTS_LOGS_OR_TRAJECTORIES",
        "prepared_manifest": prepared_identity,
        "case_spec": prepared["case_spec"],
        "local_cache_seed": prepared["derived"]["local_cache"],
        "local_onnx": prepared["derived"]["local_onnx"],
        "runtime_config": prepared["derived"]["runtime_config"],
    }


def _validate_runtime_lock_evidence(lock_evidence: Mapping[str, Any]) -> None:
    if (
        set(lock_evidence) != {"path", "pid", "acquired_at_utc", "mode", "scope"}
        or lock_evidence.get("path") != str(GLOBAL_SERIAL_LOCK)
        or not isinstance(lock_evidence.get("pid"), int)
        or isinstance(lock_evidence.get("pid"), bool)
        or lock_evidence["pid"] <= 0
        or not isinstance(lock_evidence.get("acquired_at_utc"), str)
        or lock_evidence.get("mode") != "EXCLUSIVE_NONBLOCKING_FLOCK"
        or lock_evidence.get("scope")
        != "DOUBLE_BUILD_COMPARE_THROUGH_HARDLINK_PUBLICATION_OR_DRY_RUN_OUTPUT"
    ):
        raise BuildError("RUNTIME_GLOBAL_SERIAL_LOCK_EVIDENCE")


def build_document(lock_evidence: Mapping[str, Any]) -> dict[str, Any]:
    _validate_runtime_lock_evidence(lock_evidence)
    _absent(PUBLICATION_PATH, "delta_seal")
    for path, label in (
        (RUNTIME_ROOT / "_accuracy_execution_locks_v1", "legacy_accuracy_locks"),
        (RUNTIME_ROOT / "_accuracy_analysis_v1", "legacy_accuracy_analysis"),
        (EXECUTION_LOCK_ROOT, "accuracy_locks_v2"),
        (ACCURACY_ROOT, "accuracy_analysis_v2"),
        (ADJUDICATION_ROOT, "cache_adjudication_root"),
        (WATCHDOG_ROOT, "watchdog_root"),
    ):
        _absent(path, label)
    base_seal, base_identity = read_canonical_json(BASE_SEAL, "parent_v1_seal", BASE_SEAL_EXPECTED)
    if (
        base_seal.get("schema_version")
        != "aqua-fe-hfnet-v6-samehistory-positive-accuracy-prefreeze-seal-v1"
        or base_seal.get("status") != "SEALED_OUTCOME_BLIND_BEFORE_ANY_HFNET_START"
        or base_seal.get("case_count") != 10
    ):
        raise BuildError("PARENT_V1_SEAL_CONTRACT_INVALID")
    code = {
        "accuracy_supersession_builder_v2": file_identity(
            SUPERSESSION_BUILDER_V2, "supersession_builder_v2"
        ),
        "base_accuracy_controller_core": file_identity(
            BASE_CONTROLLER, "base_controller", BASE_CONTROLLER_EXPECTED
        ),
        "formal_accuracy_controller_v2": file_identity(CONTROLLER_V2, "controller_v2"),
        "roster_evaluator_core": file_identity(EVALUATOR, "evaluator", EVALUATOR_EXPECTED),
        "cache_contract_adjudicator": file_identity(
            CACHE_ADJUDICATOR,
            "cache_adjudicator",
            CACHE_ADJUDICATOR_EXPECTED,
        ),
        "zero_kf_watchdog": file_identity(
            ZERO_KF_WATCHDOG,
            "zero_kf_watchdog",
            ZERO_KF_WATCHDOG_EXPECTED,
        ),
    }
    remaining = [_remaining_case(case_id) for case_id in REMAINING_CASES]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "reporting_boundary": (
            "post-A05 validator-incident interface freeze before the remaining nine; "
            "no support coordinates, APE, RPE, evo result, winner, or ranking computed"
        ),
        "parent_accuracy_design_seal": base_identity,
        "parent_design_retained_without_modification": True,
        "analysis_code_identities": code,
        "authorities": {
            "accuracy_cache_adjudication_protocol": file_identity(PROTOCOL, "protocol"),
            "cache_contract_governance_addendum": file_identity(
                CACHE_CONTRACT_ADDENDUM,
                "cache_contract_governance_addendum",
                CACHE_CONTRACT_ADDENDUM_EXPECTED,
            ),
            "zero_kf_watchdog_protocol": file_identity(
                ZERO_KF_WATCHDOG_PROTOCOL,
                "zero_kf_watchdog_protocol",
                ZERO_KF_WATCHDOG_PROTOCOL_EXPECTED,
            ),
            "v2_runner": file_identity(V2_RUNNER, "v2_runner", V2_RUNNER_EXPECTED),
            "v2_roster_pointer": file_identity(V2_POINTER, "v2_pointer", V2_POINTER_EXPECTED),
        },
        "a05_terminal_boundary": _a05_boundary(),
        "remaining_cases": list(REMAINING_CASES),
        "remaining_nine_prestart": remaining,
        "cache_adjudication_contract": {
            "prestart_receipt_schema": "aqua-fe-hfnet-v6-samehistory-positive-cache-contract-prestart-v1",
            "terminal_receipt_schema": "aqua-fe-hfnet-v6-samehistory-positive-cache-contract-adjudication-v1",
            "receipt_role": "INDEPENDENT_CACHE_VALIDATOR_ADJUDICATION",
            "prestart_receipt_pattern": str(ADJUDICATION_ROOT / "{case_id}.prestart.json"),
            "terminal_receipt_pattern": str(
                ADJUDICATION_ROOT / "{case_id}.runability_adjudication.json"
            ),
            "effective_status_values": ["PASS", "FAIL"],
            "pass_adjudication_status": "PASS_CACHE_ONLY_V2_POST_AUDIT_CORRECTED",
            "raw_status_required_for_correction": "FAIL_SAMEHISTORY_COLDSTART_RUNABILITY",
            "raw_failure_code_set_required": [
                "FROZEN_CONTRACT_DRIFT",
                "POST_AUDIT_INCOMPLETE",
            ],
            "sole_post_audit_error_required": (
                "FROZEN_CONTRACT_POST_AUDIT:ContractError:"
                "DERIVED_FILE_DRIFT:local_cache"
            ),
            "any_other_failure_can_be_promoted": False,
            "accuracy_computed_must_be_false": True,
            "replacement_adjudication_permitted": False,
        },
        "zero_kf_watchdog_contract": {
            "accuracy_promotable_status": "PASSIVE_RUNNER_EXIT_WITHOUT_WATCHDOG_SIGNAL",
            "pass_requires_runner_reaped": True,
            "pass_requires_zero_signal_attempts": True,
            "pass_requires_zero_signals": True,
            "pass_requires_empty_monitoring_errors": True,
            "raw_runability_receipt_exact_pin_required": True,
            "supervisor_pre_post_exact_code_identity_required": True,
            "runner_claim_chain_exactly_validated_by_adjudicator": True,
            "zero_kf_or_supervision_error_promotable": False,
        },
        "future_accuracy_controller_contract": {
            "active_controller": code["formal_accuracy_controller_v2"],
            "imported_base_controller_core": code["base_accuracy_controller_core"],
            "unchanged_evaluator": code["roster_evaluator_core"],
            "authorization_token_sha256": hashlib.sha256(
                b"RUN_FROZEN_HFNET_V6_SAMEHISTORY_ACCURACY_V2"
            ).hexdigest(),
            "raw_and_adjudicated_receipts_required": True,
            "delta_seal_required_at_freeze_check_and_run": True,
            "pre_metric_and_pre_publication_toctou_required": True,
            "direct_base_controller_use_on_v2_namespace_authorized": False,
            "maximum_accuracy_claims_per_case": 1,
            "retry_permitted": False,
        },
        "future_namespaces": {
            "cache_adjudication_root": str(ADJUDICATION_ROOT),
            "zero_kf_watchdog_root": str(WATCHDOG_ROOT),
            "zero_kf_watchdog_receipt_schema": (
                "aqua-fe-hfnet-v6-zero-kf-save-hang-watchdog-receipt-v1"
            ),
            "zero_kf_watchdog_receipt_pattern": str(WATCHDOG_ROOT / "{case_id}.json"),
            "execution_lock_root": str(EXECUTION_LOCK_ROOT),
            "case_execution_lock_pattern": str(EXECUTION_LOCK_ROOT / "{case_id}.json"),
            "case_bridge_receipt_pattern": str(
                EXECUTION_LOCK_ROOT / "{case_id}.hfnet_timestamp_bridge_receipt.json"
            ),
            "accuracy_root": str(ACCURACY_ROOT),
            "case_claim_pattern": str(ACCURACY_ROOT / "_claims/{case_id}.start_once"),
            "case_output_pattern": str(ACCURACY_ROOT / "{case_id}/attempt_001"),
            "case_terminal_pattern": str(ACCURACY_ROOT / "{case_id}/terminal_receipt.json"),
            "all_destinations_absent_at_seal": True,
            "write_once_no_clobber": True,
        },
        "claims": {
            "a05_accuracy_na_terminal": True,
            "remaining_nine_hfnet_started": False,
            "accuracy_execution_lock_published": False,
            "accuracy_analysis_started": False,
            "accuracy_measured": False,
            "winner_or_ranking_authorized": False,
        },
        "publication_contract": {
            "canonical_path": str(PUBLICATION_PATH),
            "default_mode": "DRY_RUN_NO_WRITE",
            "publish_token_sha256": PUBLISH_TOKEN_SHA256,
            "token_serialized_into_seal": False,
            "commit": "TEMP_O_EXCL_FSYNC_HARDLINK_NOREPLACE_DIRECTORY_FSYNC",
            "replacement_permitted": False,
            "global_serial_lock_contract": dict(SERIALIZED_GLOBAL_LOCK_CONTRACT),
            "double_build_byte_comparison_before_publication": True,
        },
    }


def validate_document(document: Mapping[str, Any]) -> None:
    if document.get("schema_version") != SCHEMA_VERSION or document.get("status") != STATUS:
        raise BuildError("DOCUMENT_SCHEMA_OR_STATUS")
    if document.get("remaining_cases") != list(REMAINING_CASES):
        raise BuildError("DOCUMENT_REMAINING_CASES")
    if document.get("a05_terminal_boundary", {}).get("status") != "TERMINAL_FAIL_ACCURACY_NA_NO_RETRY":
        raise BuildError("DOCUMENT_A05_BOUNDARY")
    code = document.get("analysis_code_identities")
    if not isinstance(code, Mapping) or set(code) != {
        "accuracy_supersession_builder_v2",
        "base_accuracy_controller_core",
        "formal_accuracy_controller_v2",
        "roster_evaluator_core",
        "cache_contract_adjudicator",
        "zero_kf_watchdog",
    }:
        raise BuildError("DOCUMENT_CODE_IDENTITY_SET")
    if document.get("parent_accuracy_design_seal") != file_identity(
        BASE_SEAL, "parent_v1_seal", BASE_SEAL_EXPECTED
    ):
        raise BuildError("DOCUMENT_PARENT_SEAL")
    if document.get("publication_contract", {}).get("token_serialized_into_seal") is not False:
        raise BuildError("DOCUMENT_TOKEN_BOUNDARY")
    lock = document.get("publication_contract", {}).get("global_serial_lock_contract")
    if lock != SERIALIZED_GLOBAL_LOCK_CONTRACT:
        raise BuildError("DOCUMENT_GLOBAL_SERIAL_LOCK_CONTRACT")
    payload = canonical_json_bytes(document)
    for token in (
        PUBLISH_TOKEN,
        "FREEZE_HFNET_V6_SAMEHISTORY_ACCURACY_LOCK_V2",
        "RUN_FROZEN_HFNET_V6_SAMEHISTORY_ACCURACY_V2",
    ):
        if token.encode("ascii") in payload:
            raise BuildError("DOCUMENT_PLAINTEXT_TOKEN")


@contextmanager
def global_serial_lock() -> Any:
    """Share the exact roster lock from pristine audit through publication."""

    try:
        canonical = _canonical_existing(GLOBAL_SERIAL_LOCK, "global_serial_lock")
        descriptor = os.open(
            str(canonical),
            os.O_RDWR
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as error:
        raise BuildError(f"GLOBAL_SERIAL_LOCK_OPEN:{type(error).__name__}") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise BuildError("GLOBAL_SERIAL_LOCK_NOT_REGULAR")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise BuildError("GLOBAL_SERIAL_LOCK_BUSY") from error
        yield {
            "path": str(canonical),
            "pid": os.getpid(),
            "acquired_at_utc": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "mode": "EXCLUSIVE_NONBLOCKING_FLOCK",
            "scope": "DOUBLE_BUILD_COMPARE_THROUGH_HARDLINK_PUBLICATION_OR_DRY_RUN_OUTPUT",
        }
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_noreplace(path: Path, payload: bytes) -> dict[str, Any]:
    _absent(path, "publish_destination")
    parent = path.parent.resolve(strict=True)
    if parent != path.parent or path.parent.is_symlink():
        raise BuildError("PUBLICATION_PARENT_NONCANONICAL")
    temporary = parent / f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(str(temporary), flags, 0o444)
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.link(str(temporary), str(path), follow_symlinks=False)
        _fsync_directory(parent)
    except FileExistsError as error:
        raise BuildError("PUBLICATION_ALREADY_EXISTS") from error
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        _fsync_directory(parent)
    return file_identity(path, "published_delta_seal")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--authorization-token")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(argv)
    try:
        if arguments.authorization_token != PUBLISH_TOKEN:
            if arguments.publish:
                raise BuildError("PUBLISH_AUTHORIZATION_TOKEN_INVALID")
        with global_serial_lock() as lock_evidence:
            first = build_document(lock_evidence)
            validate_document(first)
            second = build_document(lock_evidence)
            validate_document(second)
            payload = canonical_json_bytes(first)
            if canonical_json_bytes(second) != payload:
                raise BuildError("DOUBLE_BUILD_TOCTOU_DRIFT")
            if not arguments.publish:
                sys.stdout.buffer.write(payload)
                return 0
            identity = publish_noreplace(PUBLICATION_PATH, payload)
        print(json.dumps({"status": "PUBLISHED_NO_REPLACE", "identity": identity}, sort_keys=True))
        return 0
    except BuildError as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
