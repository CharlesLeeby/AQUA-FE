#!/usr/bin/env python3
"""Adopt the unplanned P07 pre-outcome formal batch without authorizing execution.

This is the second layer of the formalization-incident response.  The first
layer records immutable facts.  This layer may only be published after a new
global-stable review and an independent adoption GO are both frozen.  Even a
published adoption record does not authorize B0 materialization, replacement,
G0 evaluation, a backend replay, ROS, or VINS.

The default CLI is read-only.  Publication requires two explicit scope
acknowledgements in addition to ``--write`` and uses the existing hardened
no-clobber publisher.
"""

from __future__ import annotations

import argparse
import ctypes
import csv
import dataclasses
import errno
import hashlib
import io
import json
import os
import re
import secrets
import stat
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Optional, Sequence

try:
    from scripts import build_p07_backend_formalization_incident_v1 as incident
    from scripts import build_p07_backend_legacy_d_compatibility_lock_v1 as legacy
    from scripts import build_p07_backend_replay_queue_v1 as queue
    from scripts import build_p07_evaluator_epoch_ns_correction_lock_v1 as epoch
    from scripts import p07_backend_formal_io_v1 as formal_io
    from scripts import register_p07_backend_allocations_v1 as registration
    from scripts import validate_p07_backend_replay_queue_v1 as queue_validator
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_backend_formalization_incident_v1 as incident  # type: ignore
    import build_p07_backend_legacy_d_compatibility_lock_v1 as legacy  # type: ignore
    import build_p07_backend_replay_queue_v1 as queue  # type: ignore
    import build_p07_evaluator_epoch_ns_correction_lock_v1 as epoch  # type: ignore
    import p07_backend_formal_io_v1 as formal_io  # type: ignore
    import register_p07_backend_allocations_v1 as registration  # type: ignore
    import validate_p07_backend_replay_queue_v1 as queue_validator  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_formalization_adoption_v1.json"
)
GLOBAL_STABLE_REVIEW_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_g0_global_stable_review_v1.json"
)
INDEPENDENT_GO_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_g0_independent_adoption_go_v1.json"
)
EXTERNAL_REVIEW_MANIFEST_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_formalization_external_review_manifest_v1.json"
)
POST_ADOPTION_AUTHORITY_ABSENT_PATHS = tuple(
    dict.fromkeys(
        (
            *incident.DOWNSTREAM_ABSENT_PATHS,
            *incident.EXECUTION_OUTPUT_ROOT_PATHS,
            *incident.REPLACEMENT_OUTPUT_PATHS,
            "papers/ieee_sensors_journal_experiments/p07/"
            "backend_formalization_review_evidence_lock_v1.json",
            "papers/ieee_sensors_journal_experiments/p07/"
            "backend_b0_formalization_adoption_prelock_v1.json",
            "papers/ieee_sensors_journal_experiments/p07/"
            "backend_b0_formalization_adoption_action_intent_v1.json",
            "papers/ieee_sensors_journal_experiments/p07/"
            "backend_b0_formalization_adoption_closeout_v1.json",
        )
    )
)

SCHEMA = "isj-p07-backend-formalization-adoption-v1"
STATUS = "ADOPTED_PREOUTCOME_FORMALS_WITHOUT_EXECUTION_AUTHORITY"
SELF_HASH_FIELD = "formalization_adoption_hash"
GLOBAL_STABLE_SCHEMA = "isj-p07-backend-g0-global-stable-review-v1"
GLOBAL_STABLE_STATUS = "GLOBAL_STABLE_FOR_INDEPENDENT_ADOPTION_REVIEW"
GLOBAL_STABLE_HASH_FIELD = "global_stable_review_hash"
INDEPENDENT_GO_SCHEMA = "isj-p07-backend-g0-independent-adoption-go-v1"
INDEPENDENT_GO_STATUS = (
    "INDEPENDENT_GO_FOR_PREOUTCOME_ADMINISTRATIVE_ADOPTION_ONLY"
)
INDEPENDENT_GO_HASH_FIELD = "independent_adoption_go_hash"
EXTERNAL_REVIEW_MANIFEST_SCHEMA = (
    "isj-p07-backend-formalization-external-review-manifest-v1"
)
EXTERNAL_REVIEW_MANIFEST_STATUS = (
    "FROZEN_EXTERNAL_REVIEW_REQUIREMENTS_NO_EXECUTION_AUTHORITY"
)
EXTERNAL_REVIEW_MANIFEST_HASH_FIELD = "external_review_manifest_hash"
OUTCOME_BOUNDARY = (
    "PREOUTCOME_ADMINISTRATIVE_ADOPTION_ONLY_NO_BACKEND_REPLAY_VINS_APE_RPE"
)
HEX64 = re.compile(r"[0-9a-f]{64}")

GLOBAL_STABLE_KEYS = {
    "schema_version",
    "status",
    "reviewed_at",
    "reviewer_identity",
    "independence_attestation",
    "incident",
    "external_review_manifest",
    "candidate_source_bindings_hash",
    "tests_status",
    "administrative_test_receipt",
    "publication_acknowledgements",
    "formal_write_performed",
    "vins_executed",
    "held_out_trajectory_outcome_read",
    "outcome_boundary",
    GLOBAL_STABLE_HASH_FIELD,
}
INDEPENDENT_GO_KEYS = {
    "schema_version",
    "status",
    "reviewed_at",
    "reviewer_identity",
    "independence_attestation",
    "incident",
    "external_review_manifest",
    "global_stable_review",
    "candidate_source_bindings_hash",
    "administrative_test_receipt",
    "publication_acknowledgements",
    "adoption_scope",
    "execution_authorized",
    "vins_executed",
    "held_out_trajectory_outcome_read",
    "outcome_boundary",
    INDEPENDENT_GO_HASH_FIELD,
}
ADOPTION_KEYS = {
    "schema_version",
    "status",
    "adopted_at",
    "incident",
    "external_review_manifest",
    "global_stable_review",
    "independent_adoption_go",
    "review_chain",
    "live_rebuild",
    "source_bindings",
    "governance_artifacts",
    "adoption_scope",
    "future_binding_policy",
    "authorization",
    "publication_acknowledgements",
    "held_out_trajectory_outcome_read",
    "outcome_boundary",
    SELF_HASH_FIELD,
}
EXTERNAL_REVIEW_MANIFEST_KEYS = {
    "schema_version",
    "status",
    "frozen_at",
    "incident",
    "governance_artifacts",
    "review_protocol",
    "review_scope",
    "reviewer_role_requirements",
    "administrative_test_receipt",
    "publication_acknowledgements",
    "execution_authorized",
    "vins_executed",
    "held_out_trajectory_outcome_read",
    "outcome_boundary",
    EXTERNAL_REVIEW_MANIFEST_HASH_FIELD,
}
ADOPTION_AUTHORITY_BINDING_KEYS = {
    "path",
    "sha256",
    "size_bytes",
    SELF_HASH_FIELD,
}
REVIEWER_IDENTITY_KEYS = {
    "reviewer_id",
    "reviewer_instance",
    "reviewer_role",
}
GLOBAL_REVIEWER_ROLE = "GLOBAL_STABILITY_REVIEWER"
INDEPENDENT_REVIEWER_ROLE = "INDEPENDENT_ADOPTION_REVIEWER"
GLOBAL_INDEPENDENCE_ATTESTATION = {
    "incident_creator_is_reviewer": False,
    "review_performed_without_outcome_access": True,
    "execution_authority_requested": False,
}
INDEPENDENT_INDEPENDENCE_ATTESTATION_KEYS = {
    "global_reviewer_id",
    "global_reviewer_instance",
    "independent_reviewer_is_global_reviewer",
    "incident_creator_is_reviewer",
    "review_performed_without_outcome_access",
    "execution_authority_requested",
}
REVIEW_CHAIN_KEYS = {
    "incident_observed_at",
    "external_manifest_frozen_at",
    "global_stable_reviewed_at",
    "independent_reviewed_at",
    "adopted_at",
    "global_reviewer_identity",
    "independent_reviewer_identity",
    "reviewer_identities_distinct",
    "timestamp_order",
}
INCIDENT_BUILDER_RELATIVE = (
    "scripts/build_p07_backend_formalization_incident_v1.py"
)
INCIDENT_TEST_RELATIVE = (
    "scripts/tests/test_p07_backend_formalization_incident_v1.py"
)
ADOPTION_BUILDER_RELATIVE = "scripts/build_p07_backend_formalization_adoption_v1.py"
ADOPTION_TEST_RELATIVE = "scripts/tests/test_p07_backend_formalization_adoption_v1.py"
REVIEW_EVIDENCE_BUILDER_RELATIVE = (
    "scripts/build_p07_backend_formalization_review_evidence_v1.py"
)
REVIEW_EVIDENCE_TEST_RELATIVE = (
    "scripts/tests/test_p07_backend_formalization_review_evidence_v1.py"
)
REVIEW_EVIDENCE_LEAF_TEST_RELATIVE = (
    "scripts/tests/test_p07_backend_formalization_review_leaf_v1.py"
)
FORMAL_IO_RELATIVE = "scripts/p07_backend_formal_io_v1.py"
EXTERNAL_REVIEW_GOVERNANCE_PATHS = tuple(
    sorted(
        (
            INCIDENT_BUILDER_RELATIVE,
            INCIDENT_TEST_RELATIVE,
            ADOPTION_BUILDER_RELATIVE,
            ADOPTION_TEST_RELATIVE,
            REVIEW_EVIDENCE_BUILDER_RELATIVE,
            REVIEW_EVIDENCE_TEST_RELATIVE,
            REVIEW_EVIDENCE_LEAF_TEST_RELATIVE,
            FORMAL_IO_RELATIVE,
        )
    )
)
ADMINISTRATIVE_TEST_RECEIPT_SCHEMA = (
    "isj-p07-backend-formalization-administrative-test-receipt-v1"
)
ADMINISTRATIVE_TEST_RECEIPT_STATUS = "PASS_OUTCOME_BLIND_ADMINISTRATIVE_TESTS"
ADMINISTRATIVE_TEST_RECEIPT_HASH_FIELD = "administrative_test_receipt_hash"
ADMINISTRATIVE_TEST_RECEIPT_KEYS = {
    "schema_version",
    "status",
    "receipt_role",
    "completed_at",
    "producer_identity",
    "command_argv",
    "python_interpreter",
    "sealed_bootstrap",
    "test_methods",
    "tests_run",
    "return_code",
    "stdout_sha256",
    "stderr_sha256",
    "candidate_source_bindings_hash",
    "formal_write_performed",
    "vins_executed",
    "held_out_trajectory_outcome_read",
    "outcome_boundary",
    ADMINISTRATIVE_TEST_RECEIPT_HASH_FIELD,
}
ADMINISTRATIVE_RECEIPT_ROLES = {
    "EXTERNAL_MANIFEST_PREFLIGHT": "EXTERNAL_MANIFEST_BUILDER",
    "GLOBAL_STABILITY_ADMINISTRATIVE": GLOBAL_REVIEWER_ROLE,
    "INDEPENDENT_ADMINISTRATIVE_REPLAY": INDEPENDENT_REVIEWER_ROLE,
}
ADMINISTRATIVE_TEST_MODULES = (
    "scripts.tests.test_p07_backend_formalization_incident_v1",
    "scripts.tests.test_p07_backend_formalization_adoption_v1",
)
ADMINISTRATIVE_TEST_BOOTSTRAP = (
    "import sys,unittest;"
    "sys.path.insert(0,'/home/ma/AQUA-FE_WS');"
    "unittest.main(module=None,argv=['unittest',*sys.argv[1:]],verbosity=2)"
)
ADMINISTRATIVE_TEST_BOOTSTRAP_BYTES = ADMINISTRATIVE_TEST_BOOTSTRAP.encode("utf-8")
ADMINISTRATIVE_TEST_BOOTSTRAP_RECORD = {
    "sha256": hashlib.sha256(ADMINISTRATIVE_TEST_BOOTSTRAP_BYTES).hexdigest(),
    "size_bytes": len(ADMINISTRATIVE_TEST_BOOTSTRAP_BYTES),
}
ADMINISTRATIVE_PYTHON_INTERPRETER = "/usr/bin/python3.8"
ADMINISTRATIVE_PYTHON_INTERPRETER_RELATIVE = "usr/bin/python3.8"
SEALED_PYTHON_ARGV_TOKEN = "/proc/self/fd/<sealed-python-interpreter>"
SEALED_BOOTSTRAP_ARGV_TOKEN = "/proc/self/fd/<sealed-review-bootstrap>"
ADMINISTRATIVE_TEST_ARGV = (
    SEALED_PYTHON_ARGV_TOKEN,
    "-I",
    SEALED_BOOTSTRAP_ARGV_TOKEN,
    *ADMINISTRATIVE_TEST_MODULES,
)
ADMINISTRATIVE_TEST_METHODS = (
    "scripts.tests.test_p07_backend_formalization_adoption_v1.P07BackendFormalizationAdoptionProductionReadOnlyTests.test_existing_unplanned_batch_rebuilds_byte_exact_without_writing",
    "scripts.tests.test_p07_backend_formalization_adoption_v1.P07BackendFormalizationAdoptionV1Tests.test_adoption_scope_or_authority_tamper_is_rejected_after_rehash",
    "scripts.tests.test_p07_backend_formalization_adoption_v1.P07BackendFormalizationAdoptionV1Tests.test_build_is_administrative_only_and_never_authorizes_execution",
    "scripts.tests.test_p07_backend_formalization_adoption_v1.P07BackendFormalizationAdoptionV1Tests.test_default_cli_reports_blocked_without_incident_and_writes_nothing",
    "scripts.tests.test_p07_backend_formalization_adoption_v1.P07BackendFormalizationAdoptionV1Tests.test_downstream_formal_presence_blocks_adoption",
    "scripts.tests.test_p07_backend_formalization_adoption_v1.P07BackendFormalizationAdoptionV1Tests.test_duplicate_key_and_noncanonical_review_json_fail_closed",
    "scripts.tests.test_p07_backend_formalization_adoption_v1.P07BackendFormalizationAdoptionV1Tests.test_external_manifest_scope_and_bound_code_drift_fail_closed",
    "scripts.tests.test_p07_backend_formalization_adoption_v1.P07BackendFormalizationAdoptionV1Tests.test_historical_validation_allows_later_downstream_but_not_byte_drift",
    "scripts.tests.test_p07_backend_formalization_adoption_v1.P07BackendFormalizationAdoptionV1Tests.test_independent_go_cannot_authorize_execution_even_when_rehashed",
    "scripts.tests.test_p07_backend_formalization_adoption_v1.P07BackendFormalizationAdoptionV1Tests.test_library_publish_api_cannot_bypass_dual_ack",
    "scripts.tests.test_p07_backend_formalization_adoption_v1.P07BackendFormalizationAdoptionV1Tests.test_missing_or_tampered_reviews_fail_closed",
    "scripts.tests.test_p07_backend_formalization_adoption_v1.P07BackendFormalizationAdoptionV1Tests.test_no_clobber_publication_retains_first_adoption",
    "scripts.tests.test_p07_backend_formalization_adoption_v1.P07BackendFormalizationAdoptionV1Tests.test_postlink_drift_rolls_back_only_new_adoption",
    "scripts.tests.test_p07_backend_formalization_adoption_v1.P07BackendFormalizationAdoptionV1Tests.test_prelink_review_and_downstream_drift_leave_no_adoption",
    "scripts.tests.test_p07_backend_formalization_adoption_v1.P07BackendFormalizationAdoptionV1Tests.test_reviewer_identity_independence_and_timestamp_order_fail_closed",
    "scripts.tests.test_p07_backend_formalization_adoption_v1.P07BackendFormalizationAdoptionV1Tests.test_write_requires_both_scope_acknowledgements_before_any_build",
    "scripts.tests.test_p07_backend_formalization_incident_v1.BackendFormalizationIncidentTests.test_broken_symlink_at_every_output_root_or_leaf_fails_closed",
    "scripts.tests.test_p07_backend_formalization_incident_v1.BackendFormalizationIncidentTests.test_default_cli_is_read_only_preview",
    "scripts.tests.test_p07_backend_formalization_incident_v1.BackendFormalizationIncidentTests.test_downstream_presence_fails_closed",
    "scripts.tests.test_p07_backend_formalization_incident_v1.BackendFormalizationIncidentTests.test_exact_preview_and_live_validation",
    "scripts.tests.test_p07_backend_formalization_incident_v1.BackendFormalizationIncidentTests.test_expected_attempt_directory_presence_fails_closed",
    "scripts.tests.test_p07_backend_formalization_incident_v1.BackendFormalizationIncidentTests.test_no_clobber_publication",
    "scripts.tests.test_p07_backend_formalization_incident_v1.BackendFormalizationIncidentTests.test_observation_time_must_not_precede_latest_ctime",
    "scripts.tests.test_p07_backend_formalization_incident_v1.BackendFormalizationIncidentTests.test_orphan_files_under_every_execution_output_root_fail_before_read",
    "scripts.tests.test_p07_backend_formalization_incident_v1.BackendFormalizationIncidentTests.test_payload_tamper_fails_even_with_rehashed_document",
    "scripts.tests.test_p07_backend_formalization_incident_v1.BackendFormalizationIncidentTests.test_post_incident_governance_presence_fails_closed",
    "scripts.tests.test_p07_backend_formalization_incident_v1.BackendFormalizationIncidentTests.test_postlink_competing_winner_is_never_unlinked",
    "scripts.tests.test_p07_backend_formalization_incident_v1.BackendFormalizationIncidentTests.test_postlink_future_output_drift_rolls_back_own_incident",
    "scripts.tests.test_p07_backend_formalization_incident_v1.BackendFormalizationIncidentTests.test_postlink_g0_output_root_drift_rolls_back_own_incident",
    "scripts.tests.test_p07_backend_formalization_incident_v1.BackendFormalizationIncidentTests.test_postlink_present_input_drift_rolls_back_own_incident",
    "scripts.tests.test_p07_backend_formalization_incident_v1.BackendFormalizationIncidentTests.test_prelink_future_output_drift_leaves_no_incident",
    "scripts.tests.test_p07_backend_formalization_incident_v1.BackendFormalizationIncidentTests.test_prelink_orphan_attempt_root_drift_leaves_no_incident",
    "scripts.tests.test_p07_backend_formalization_incident_v1.BackendFormalizationIncidentTests.test_prelink_present_input_drift_leaves_no_incident",
    "scripts.tests.test_p07_backend_formalization_incident_v1.BackendFormalizationIncidentTests.test_present_file_tamper_fails_live_validation",
    "scripts.tests.test_p07_backend_formalization_incident_v1.BackendFormalizationIncidentTests.test_publisher_rejects_nonfresh_rehashed_payload",
    "scripts.tests.test_p07_backend_formalization_incident_v1.BackendFormalizationIncidentTests.test_registry_suffix_drift_fails_closed",
    "scripts.tests.test_p07_backend_formalization_incident_v1.BackendFormalizationIncidentTests.test_replacement_index_and_output_root_presence_fail_before_read",
    "scripts.tests.test_p07_backend_formalization_incident_v1.BackendFormalizationIncidentTests.test_symlinked_output_parent_chain_fails_closed_before_source_read",
)
LIVE_KEYS = {
    "legacy_d",
    "epoch_ns",
    "backend_queue_bundle",
    "queue_validation",
    "registration",
    "all_ten_files_byte_exact",
    "source_artifact_count",
    "source_bindings_hash",
    "source_artifacts",
    "held_out_trajectory_outcome_read",
    "vins_executed",
}
REGISTRATION_EVIDENCE_KEYS = {
    "byte_exact",
    "registry_prefix",
    "registry_suffix_rows",
    "registry_suffix_sha256",
    "intended_registry_rows_sha256",
    "first_registry_event_id",
    "last_registry_event_id",
    "current_registry",
    "planned_e00_exact",
    "backend_output_paths_present",
}


class AdoptionError(RuntimeError):
    """Raised when the unplanned batch is not safe to adopt."""


class RollbackIncomplete(AdoptionError):
    """A failed publication was preserved for separate governed reclamation."""

    def __init__(
        self,
        *,
        retained_path: Path,
        reason: str,
        retained_identity: Optional[Mapping[str, int]] = None,
    ) -> None:
        self.retained_path = Path(os.path.abspath(os.fspath(retained_path)))
        self.reason = reason
        self.retained_identity = (
            dict(retained_identity) if retained_identity is not None else None
        )
        super().__init__(
            "rollback-incomplete: "
            f"reason={reason}; retained_path={os.fspath(self.retained_path)}"
        )


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def json_bytes(payload: Mapping[str, object]) -> bytes:
    return (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")


def document_hash(payload: Mapping[str, object], field: str) -> str:
    clone = dict(payload)
    clone.pop(field, None)
    return hashlib.sha256(canonical_json(clone).encode("utf-8")).hexdigest()


def _timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AdoptionError("timestamp must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise AdoptionError("timestamp must include a timezone")
    return value


def _timestamp_value(value: str) -> datetime:
    _timestamp(value)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _safe_relative(value: str) -> str:
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise AdoptionError(f"unsafe repository-relative path: {value!r}")
    return pure.as_posix()


def _read_direct(root: Path, relative: str, *, label: str) -> tuple[bytes, dict[str, object]]:
    relative = _safe_relative(relative)
    try:
        content, record = queue.rooted_io.read_bytes_and_record_bound_input_rooted(
            root.absolute(), root.absolute().joinpath(*PurePosixPath(relative).parts), label=label
        )
    except Exception as error:
        raise AdoptionError(f"unsafe or missing {label}: {relative}") from error
    exact = {
        "path": relative,
        "sha256": str(record["sha256"]),
        "size_bytes": int(record["size_bytes"]),
    }
    if len(content) != exact["size_bytes"] or hashlib.sha256(content).hexdigest() != exact["sha256"]:
        raise AdoptionError(f"unstable {label}: {relative}")
    return content, exact


def _reject_duplicate_json_pairs(
    pairs: Sequence[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AdoptionError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _json_direct(root: Path, relative: str, *, label: str) -> tuple[dict[str, object], dict[str, object], bytes]:
    content, record = _read_direct(root, relative, label=label)
    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_pairs,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, AdoptionError) as error:
        raise AdoptionError(f"invalid {label} JSON: {relative}") from error
    if not isinstance(value, dict):
        raise AdoptionError(f"{label} is not a JSON object: {relative}")
    if content != json_bytes(value):
        raise AdoptionError(f"{label} JSON is not canonical: {relative}")
    return value, record, content


def _reference(record: Mapping[str, object], self_hash: str, hash_field: str) -> dict[str, object]:
    return {
        "path": str(record["path"]),
        "sha256": str(record["sha256"]),
        "size_bytes": int(record["size_bytes"]),
        hash_field: self_hash,
    }


def _validate_reference(
    value: object,
    *,
    expected_record: Mapping[str, object],
    expected_hash: str,
    hash_field: str,
    label: str,
) -> None:
    expected = _reference(expected_record, expected_hash, hash_field)
    if value != expected:
        raise AdoptionError(f"{label} reference mismatch")


def _validate_reference_shape(
    value: object,
    *,
    expected_path: str,
    hash_field: str,
    label: str,
) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != {"path", "sha256", "size_bytes", hash_field}
        or value.get("path") != expected_path
        or not HEX64.fullmatch(str(value.get("sha256", "")))
        or not isinstance(value.get("size_bytes"), int)
        or int(value["size_bytes"]) <= 0
        or not HEX64.fullmatch(str(value.get(hash_field, "")))
    ):
        raise AdoptionError(f"{label} reference shape mismatch")


def _validate_file_records(records: object, *, label: str) -> list[dict[str, object]]:
    if not isinstance(records, list) or not records:
        raise AdoptionError(f"{label} record list is empty or malformed")
    normalized: list[dict[str, object]] = []
    paths: set[str] = set()
    for item in records:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "sha256", "size_bytes"}
            or not isinstance(item.get("path"), str)
            or not HEX64.fullmatch(str(item.get("sha256", "")))
            or not isinstance(item.get("size_bytes"), int)
            or int(item["size_bytes"]) <= 0
        ):
            raise AdoptionError(f"{label} contains an invalid record")
        path = _safe_relative(str(item["path"]))
        if path in paths:
            raise AdoptionError(f"{label} contains a duplicate path: {path}")
        paths.add(path)
        normalized.append(dict(item))
    if [str(item["path"]) for item in normalized] != sorted(paths):
        raise AdoptionError(f"{label} is not sorted by path")
    return normalized


def _validate_live_shape(live: object) -> dict[str, object]:
    if not isinstance(live, dict) or set(live) != LIVE_KEYS:
        raise AdoptionError("adoption live rebuild key set mismatch")
    legacy_value = live.get("legacy_d")
    epoch_value = live.get("epoch_ns")
    queue_value = live.get("backend_queue_bundle")
    validation_value = live.get("queue_validation")
    registration_value = live.get("registration")
    expected_legacy_paths = [
        "papers/ieee_sensors_journal_experiments/p07/backend_a01_0018_legacy_d_sidecar_v1.json",
        "papers/ieee_sensors_journal_experiments/p07/backend_a02_0005_legacy_d_sidecar_v1.json",
        "papers/ieee_sensors_journal_experiments/p07/backend_legacy_d_resolution_compatibility_lock_v1.json",
    ]
    expected_queue_paths = [
        "papers/ieee_sensors_journal_experiments/p07/backend_replay_queue_v1.csv",
        "papers/ieee_sensors_journal_experiments/p07/backend_run_allocation_v1.csv",
        "papers/ieee_sensors_journal_experiments/p07/backend_queue_lock_v1.json",
    ]
    if (
        not isinstance(legacy_value, dict)
        or set(legacy_value) != {"byte_exact", "paths", "compatibility_lock_hash"}
        or legacy_value.get("byte_exact") is not True
        or legacy_value.get("paths") != expected_legacy_paths
        or not HEX64.fullmatch(str(legacy_value.get("compatibility_lock_hash", "")))
        or not isinstance(epoch_value, dict)
        or set(epoch_value) != {"byte_exact", "path", "epoch_ns_correction_lock_hash"}
        or epoch_value.get("byte_exact") is not True
        or epoch_value.get("path")
        != "papers/ieee_sensors_journal_experiments/p07/evaluator_epoch_ns_correction_lock_v1.json"
        or not HEX64.fullmatch(str(epoch_value.get("epoch_ns_correction_lock_hash", "")))
        or not isinstance(queue_value, dict)
        or set(queue_value)
        != {"byte_exact", "paths", "backend_queue_lock_hash", "backend_replay_jobs"}
        or queue_value.get("byte_exact") is not True
        or queue_value.get("paths") != expected_queue_paths
        or int(queue_value.get("backend_replay_jobs", -1)) != 240
        or not HEX64.fullmatch(str(queue_value.get("backend_queue_lock_hash", "")))
        or not isinstance(validation_value, dict)
        or validation_value
        != {
            "byte_exact": True,
            "path": "papers/ieee_sensors_journal_experiments/p07/backend_queue_validation_v1.json",
            "status": "PASS",
        }
        or not isinstance(registration_value, dict)
        or set(registration_value) != REGISTRATION_EVIDENCE_KEYS
        or registration_value.get("byte_exact") is not True
        or int(registration_value.get("registry_suffix_rows", -1)) != 240
        or registration_value.get("planned_e00_exact") is not True
        or int(registration_value.get("backend_output_paths_present", -1)) != 0
        or not str(registration_value.get("first_registry_event_id", "")).endswith("_e00")
        or not str(registration_value.get("last_registry_event_id", "")).endswith("_e00")
        or not HEX64.fullmatch(str(registration_value.get("registry_suffix_sha256", "")))
        or not HEX64.fullmatch(str(registration_value.get("intended_registry_rows_sha256", "")))
        or live.get("all_ten_files_byte_exact") is not True
        or live.get("held_out_trajectory_outcome_read") is not False
        or live.get("vins_executed") is not False
    ):
        raise AdoptionError("adoption live rebuild semantic shape mismatch")
    source_records = _validate_file_records(
        live.get("source_artifacts"), label="adoption source artifacts"
    )
    if (
        int(live.get("source_artifact_count", -1)) != len(source_records)
        or live.get("source_bindings_hash")
        != hashlib.sha256(canonical_json(source_records).encode("utf-8")).hexdigest()
    ):
        raise AdoptionError("adoption source binding count/hash mismatch")
    for field in ("registry_prefix", "current_registry"):
        record = registration_value.get(field)
        if (
            not isinstance(record, dict)
            or set(record) != {"path", "sha256", "size_bytes"}
            or not HEX64.fullmatch(str(record.get("sha256", "")))
            or not isinstance(record.get("size_bytes"), int)
            or int(record["size_bytes"]) <= 0
        ):
            raise AdoptionError(f"adoption registration {field} malformed")
    if (
        registration_value["registry_prefix"]["path"]
        != "papers/ieee_sensors_journal_experiments/run_registry.csv"
        or registration_value["current_registry"]["path"]
        != registration_value["registry_prefix"]["path"]
        or int(registration_value["current_registry"]["size_bytes"])
        <= int(registration_value["registry_prefix"]["size_bytes"])
    ):
        raise AdoptionError("adoption registry prefix/current record relation mismatch")
    return live


def _source_records_from_formals(root: Path) -> list[dict[str, object]]:
    legacy_payload, _legacy_record, _ = _json_direct(
        root,
        "papers/ieee_sensors_journal_experiments/p07/"
        "backend_legacy_d_resolution_compatibility_lock_v1.json",
        label="legacy-D compatibility lock",
    )
    epoch_payload, _epoch_record, _ = _json_direct(
        root,
        "papers/ieee_sensors_journal_experiments/p07/"
        "evaluator_epoch_ns_correction_lock_v1.json",
        label="epoch-ns correction lock",
    )
    queue_payload, _queue_record, _ = _json_direct(
        root,
        "papers/ieee_sensors_journal_experiments/p07/backend_queue_lock_v1.json",
        label="backend queue lock",
    )
    candidates: list[object] = []
    candidates.extend(legacy_payload.get("artifacts", []))
    candidates.extend(epoch_payload.get("governance_artifacts", []))
    corrected = epoch_payload.get("corrected_implementation_binding")
    if not isinstance(corrected, dict):
        raise AdoptionError("epoch corrected implementation binding missing")
    candidates.extend(corrected.get("files", []))
    candidates.extend(queue_payload.get("artifacts", []))
    observed: dict[str, dict[str, object]] = {}
    for raw in candidates:
        if not isinstance(raw, dict):
            raise AdoptionError("bound artifact record is not an object")
        path = str(raw.get("path", ""))
        if not path.startswith("scripts/"):
            continue
        if set(raw).difference({"path", "sha256", "size_bytes"}):
            # Some scientific records may carry semantic hashes in addition to
            # the common file-record fields.  Only the file identity is folded
            # into this deduplicated source-binding list.
            raw = {key: raw[key] for key in ("path", "sha256", "size_bytes")}
        _content, current = _read_direct(root, path, label="adopted source artifact")
        expected = {
            "path": path,
            "sha256": str(raw.get("sha256", "")),
            "size_bytes": int(raw.get("size_bytes", -1)),
        }
        if current != expected:
            raise AdoptionError(f"bound source artifact drift: {path}")
        previous = observed.get(path)
        if previous is not None and previous != expected:
            raise AdoptionError(f"conflicting bound source records: {path}")
        observed[path] = expected
    if not observed:
        raise AdoptionError("no source artifacts were bound by the unplanned batch")
    return [observed[path] for path in sorted(observed)]


def _frozen_mutable_records(lock: Mapping[str, object]) -> tuple[queue.FileRecord, ...]:
    raw = lock.get("mutable_stream_prefix_snapshots")
    if not isinstance(raw, list) or len(raw) != 2:
        raise AdoptionError("queue lock mutable prefix set mismatch")
    records: list[queue.FileRecord] = []
    paths: set[str] = set()
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "size_bytes"}:
            raise AdoptionError("queue lock mutable prefix record malformed")
        path = str(item["path"])
        if path in paths or not HEX64.fullmatch(str(item["sha256"])):
            raise AdoptionError("queue lock mutable prefix record duplicate/invalid")
        paths.add(path)
        records.append(
            queue.FileRecord(path, str(item["sha256"]), int(item["size_bytes"]))
        )
    expected = {
        queue.display_path(queue.RUN_REGISTRY),
        queue.display_path(queue.ARM_APPLICABILITY),
    }
    if paths != expected:
        raise AdoptionError("queue lock mutable prefix path set mismatch")
    return tuple(records)


def _expected_validation_report(
    *,
    lock: Mapping[str, object],
    queue_content: bytes,
    allocation_content: bytes,
    lock_content: bytes,
) -> dict[str, object]:
    return {
        "schema_version": queue_validator.REPORT_SCHEMA,
        "status": "PASS",
        "backend_queue_lock_hash": lock["backend_queue_lock_hash"],
        "backend_replay_jobs": int(lock["backend_replay_jobs"]),
        "conditional_d_jobs": int(lock["conditional_d_jobs"]),
        "live_rebuild_requested": True,
        "deterministic_live_rebuild": {
            "queue_byte_identical": True,
            "allocation_byte_identical": True,
            "queue_lock_semantic_identical": True,
        },
        "artifacts": {
            "queue_sha256": hashlib.sha256(queue_content).hexdigest(),
            "allocation_sha256": hashlib.sha256(allocation_content).hexdigest(),
            "queue_lock_sha256": hashlib.sha256(lock_content).hexdigest(),
        },
        "issues": [],
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": queue.OUTCOME_BOUNDARY,
    }


def _registration_rebuild(
    root: Path,
    *,
    queue_content: bytes,
    allocation_content: bytes,
    queue_lock: Mapping[str, object],
    queue_record: Mapping[str, object],
    allocation_record: Mapping[str, object],
    queue_lock_record: Mapping[str, object],
    validation_record: Mapping[str, object],
) -> dict[str, object]:
    _queue_fields, queue_rows = queue_validator.parse_csv(queue_content)
    _allocation_fields, allocation_rows = queue_validator.parse_csv(allocation_content)
    split_relative = "papers/ieee_sensors_journal_experiments/p07/split_role_audit_v1.csv"
    split_content, split_record = _read_direct(root, split_relative, label="split role audit")
    _split_fields, split_rows = queue._parse_csv_content(root / split_relative, split_content)
    split_roles = {
        str(row["window_id"]): str(row["corrected_split_role"])
        for row in split_rows
    }
    registry_relative = queue.display_path(queue.RUN_REGISTRY)
    registry_content, registry_record = _read_direct(root, registry_relative, label="canonical run registry")
    registry_fields, registry_rows = registration._parse_csv_content(
        root / registry_relative, registry_content
    )
    intended = registration.build_registry_rows(
        queue_rows,
        allocation_rows,
        registry_fields=registry_fields,
        split_roles=split_roles,
    )
    if len(intended) != 240:
        raise AdoptionError("unplanned registration does not contain exactly 240 rows")
    prefixes = [
        item
        for item in queue_lock.get("mutable_stream_prefix_snapshots", [])
        if isinstance(item, dict) and item.get("path") == registry_relative
    ]
    if len(prefixes) != 1:
        raise AdoptionError("queue lock lacks one canonical registry prefix")
    prefix = prefixes[0]
    size = int(prefix.get("size_bytes", -1))
    if size <= 0 or len(registry_content) < size:
        raise AdoptionError("canonical registry is shorter than frozen prefix")
    prefix_content = registry_content[:size]
    if hashlib.sha256(prefix_content).hexdigest() != prefix.get("sha256"):
        raise AdoptionError("canonical registry frozen prefix drift")
    intended_suffix = registration._row_bytes(registry_fields, intended)
    if registry_content != prefix_content + intended_suffix:
        raise AdoptionError("canonical registry is not exact prefix plus 240 planned rows")
    validation = registration.validate_registered(intended, registry_rows)
    if validation != {
        "intended_backend_runs": 240,
        "unique_untouched_planned_e00": 240,
        "pass": True,
    }:
        raise AdoptionError("canonical registry planned-e00 validation mismatch")
    if any(
        row.get("status") != "PLANNED"
        or row.get("registry_event_id") != f"{row.get('run_id')}_e00"
        or row.get("supersedes_event_id")
        for row in intended
    ):
        raise AdoptionError("canonical registry suffix is not untouched PLANNED e00")
    for row in queue_rows:
        for field in ("expected_run_dir", "expected_attempt_dir"):
            value = _safe_relative(str(row[field]))
            if os.path.lexists(root.joinpath(*PurePosixPath(value).parts)):
                raise AdoptionError(f"backend output path already exists: {value}")

    records = {
        "backend_queue": dict(queue_record),
        "backend_allocation": dict(allocation_record),
        "backend_queue_lock": dict(queue_lock_record),
        "backend_queue_validation": dict(validation_record),
        "split_role_audit": dict(split_record),
    }
    expected_intent = registration.build_registration_intent(
        queue_lock=queue_lock,
        intended=intended,
        registry_prefix=prefix,
        allocated_at=str(allocation_rows[0]["allocated_at"]),
        artifact_records=records,
    )
    intent_relative = "papers/ieee_sensors_journal_experiments/p07/backend_registration_intent_v1.json"
    intent, intent_record, intent_content = _json_direct(root, intent_relative, label="backend registration intent")
    registration.validate_registration_intent(
        intent,
        intended=intended,
        queue_lock=queue_lock,
        expected_artifact_records=records,
    )
    if intent != expected_intent or intent_content != json_bytes(expected_intent):
        raise AdoptionError("backend registration intent deterministic rebuild mismatch")
    expected_report: dict[str, object] = {
        "schema_version": registration.SCHEMA,
        "status": "PASS",
        "recorded_at": allocation_rows[0]["allocated_at"],
        "backend_queue_lock_hash": queue_lock["backend_queue_lock_hash"],
        "registration_intent": {
            "path": intent_relative,
            "sha256": hashlib.sha256(intent_content).hexdigest(),
            "size_bytes": len(intent_content),
            "registration_intent_hash": expected_intent["registration_intent_hash"],
        },
        "registry_rows_appended_this_invocation": 240,
        "registry_rows_reconciled_existing": 0,
        "validation": validation,
        "before_registry_sha256": prefix["sha256"],
        "after_registry_sha256": hashlib.sha256(registry_content).hexdigest(),
        "allocation_sha256": allocation_record["sha256"],
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": queue.OUTCOME_BOUNDARY,
    }
    expected_report["registration_report_hash"] = registration._document_hash(
        expected_report, "registration_report_hash"
    )
    report_relative = "papers/ieee_sensors_journal_experiments/p07/backend_registration_v1.json"
    report, _report_record, report_content = _json_direct(root, report_relative, label="backend registration report")
    if report != expected_report or report_content != json_bytes(expected_report):
        raise AdoptionError("backend registration report deterministic rebuild mismatch")
    return {
        "byte_exact": True,
        "registry_prefix": dict(prefix),
        "registry_suffix_rows": 240,
        "registry_suffix_sha256": hashlib.sha256(intended_suffix).hexdigest(),
        "intended_registry_rows_sha256": expected_intent[
            "intended_registry_rows_sha256"
        ],
        "first_registry_event_id": expected_intent["first_registry_event_id"],
        "last_registry_event_id": expected_intent["last_registry_event_id"],
        "current_registry": dict(registry_record),
        "planned_e00_exact": True,
        "backend_output_paths_present": 0,
    }


def collect_live_rebuild_evidence(*, root: Path = ROOT) -> dict[str, object]:
    """Rebuild all ten files and the registry suffix without writing anything."""

    root = root.absolute()
    if root != queue.ROOT.absolute():
        raise AdoptionError("production live rebuild requires the canonical workspace root")

    legacy_payload = legacy.validate_live_bundle(root=root)
    legacy_outputs = legacy.build_outputs(
        root=root,
        frozen_at=str(legacy_payload["frozen_at"]),
        include_code_records=True,
    )
    legacy_paths: list[str] = []
    for path, expected in legacy_outputs.items():
        relative = path.relative_to(root).as_posix()
        observed, _record = _read_direct(root, relative, label="legacy-D rebuilt artifact")
        if observed != expected:
            raise AdoptionError(f"legacy-D deterministic rebuild mismatch: {relative}")
        legacy_paths.append(relative)

    epoch_relative = "papers/ieee_sensors_journal_experiments/p07/evaluator_epoch_ns_correction_lock_v1.json"
    epoch_payload, _epoch_record, epoch_content = _json_direct(root, epoch_relative, label="epoch-ns correction lock")
    epoch.validate_lock_payload(epoch_payload, root=root, verify_files=True)
    rebuilt_epoch = epoch.build_lock(
        root=root,
        frozen_at=str(epoch_payload["frozen_at"]),
        require_output_absent=False,
    )
    if epoch_content != json_bytes(rebuilt_epoch):
        raise AdoptionError("epoch-ns correction lock deterministic rebuild mismatch")

    queue_relative = queue.display_path(queue.BACKEND_QUEUE)
    allocation_relative = queue.display_path(queue.BACKEND_ALLOCATION)
    lock_relative = queue.display_path(queue.BACKEND_QUEUE_LOCK)
    validation_relative = queue.display_path(queue.BACKEND_QUEUE_VALIDATION)
    queue_content, queue_record = _read_direct(root, queue_relative, label="backend replay queue")
    allocation_content, allocation_record = _read_direct(root, allocation_relative, label="backend allocation")
    lock_payload, lock_record, lock_content = _json_direct(root, lock_relative, label="backend queue lock")
    validation_payload, validation_record, validation_content = _json_direct(
        root, validation_relative, label="backend queue validation"
    )
    _arm_fields, arm_rows, _arm_record = queue.csv_snapshot(queue.ARM_ORDER)
    issues = queue_validator.validate_artifacts(
        queue_content=queue_content,
        allocation_content=allocation_content,
        lock_payload=lock_payload,
        arm_order_rows=arm_rows,
        verify_locked_artifacts=True,
        verify_source_files=True,
        root=root,
    )
    if issues:
        raise AdoptionError(f"backend queue semantic validation failed: {issues}")
    frozen_mutable = _frozen_mutable_records(lock_payload)
    for record in frozen_mutable:
        current, _current_record = _read_direct(root, record.path, label="mutable stream prefix")
        if len(current) < record.size_bytes or hashlib.sha256(current[: record.size_bytes]).hexdigest() != record.sha256:
            raise AdoptionError(f"mutable prefix drift: {record.path}")
    snapshot = queue.collect_live_snapshot()
    snapshot = dataclasses.replace(snapshot, mutable_prefix_records=frozen_mutable)
    rebuilt_queue = queue.build_outputs(
        snapshot, allocated_at=str(lock_payload["frozen_at"])
    )
    actual_by_path = {
        queue.BACKEND_QUEUE: queue_content,
        queue.BACKEND_ALLOCATION: allocation_content,
        queue.BACKEND_QUEUE_LOCK: lock_content,
    }
    if set(rebuilt_queue) != set(actual_by_path):
        raise AdoptionError("backend queue deterministic output set mismatch")
    for path, expected in rebuilt_queue.items():
        if actual_by_path[path] != expected:
            raise AdoptionError(
                f"backend queue deterministic rebuild mismatch: {queue.display_path(path)}"
            )
    expected_validation = _expected_validation_report(
        lock=lock_payload,
        queue_content=queue_content,
        allocation_content=allocation_content,
        lock_content=lock_content,
    )
    if validation_payload != expected_validation or validation_content != json_bytes(expected_validation):
        raise AdoptionError("backend queue validation deterministic rebuild mismatch")

    registration_evidence = _registration_rebuild(
        root,
        queue_content=queue_content,
        allocation_content=allocation_content,
        queue_lock=lock_payload,
        queue_record=queue_record,
        allocation_record=allocation_record,
        queue_lock_record=lock_record,
        validation_record=validation_record,
    )
    sources = _source_records_from_formals(root)
    source_hash = hashlib.sha256(canonical_json(sources).encode("utf-8")).hexdigest()
    return {
        "legacy_d": {
            "byte_exact": True,
            "paths": sorted(legacy_paths),
            "compatibility_lock_hash": legacy_payload["compatibility_lock_hash"],
        },
        "epoch_ns": {
            "byte_exact": True,
            "path": epoch_relative,
            "epoch_ns_correction_lock_hash": epoch_payload[
                "epoch_ns_correction_lock_hash"
            ],
        },
        "backend_queue_bundle": {
            "byte_exact": True,
            "paths": [queue_relative, allocation_relative, lock_relative],
            "backend_queue_lock_hash": lock_payload["backend_queue_lock_hash"],
            "backend_replay_jobs": int(lock_payload["backend_replay_jobs"]),
        },
        "queue_validation": {
            "byte_exact": True,
            "path": validation_relative,
            "status": "PASS",
        },
        "registration": registration_evidence,
        "all_ten_files_byte_exact": True,
        "source_artifact_count": len(sources),
        "source_bindings_hash": source_hash,
        "source_artifacts": sources,
        "held_out_trajectory_outcome_read": False,
        "vins_executed": False,
    }


def _validate_reviewer_identity(
    value: object, *, expected_role: str, label: str
) -> dict[str, str]:
    if (
        not isinstance(value, dict)
        or set(value) != REVIEWER_IDENTITY_KEYS
        or value.get("reviewer_role") != expected_role
    ):
        raise AdoptionError(f"{label} reviewer identity key/role mismatch")
    normalized: dict[str, str] = {}
    for key in REVIEWER_IDENTITY_KEYS:
        raw = value.get(key)
        if (
            not isinstance(raw, str)
            or not raw
            or len(raw) > 160
            or re.fullmatch(r"[A-Za-z0-9._:/@-]+", raw) is None
        ):
            raise AdoptionError(f"{label} reviewer identity field is invalid: {key}")
        normalized[key] = raw
    return normalized


def _reviewer_key(identity: Mapping[str, str]) -> tuple[str, str]:
    return identity["reviewer_id"], identity["reviewer_instance"]


def administrative_test_receipt_hash(payload: Mapping[str, object]) -> str:
    return document_hash(payload, ADMINISTRATIVE_TEST_RECEIPT_HASH_FIELD)


def administrative_python_interpreter_record() -> dict[str, object]:
    """Return the direct, single-link identity of the isolated test interpreter."""

    try:
        content, identity = formal_io.read_direct_bytes(
            Path("/"), ADMINISTRATIVE_PYTHON_INTERPRETER_RELATIVE
        )
    except (OSError, formal_io.FormalIOError) as error:
        raise AdoptionError("administrative Python interpreter is unavailable") from error
    if len(content) != int(identity["size_bytes"]):
        raise AdoptionError("administrative Python interpreter snapshot is unstable")
    return {
        "path": ADMINISTRATIVE_PYTHON_INTERPRETER,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def build_administrative_test_receipt(
    *,
    receipt_role: str,
    completed_at: str,
    producer_identity: Mapping[str, str],
    command_argv: Sequence[str],
    test_methods: Sequence[str],
    tests_run: int,
    return_code: int,
    stdout_sha256: str,
    stderr_sha256: str,
    candidate_source_bindings_hash: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": ADMINISTRATIVE_TEST_RECEIPT_SCHEMA,
        "status": ADMINISTRATIVE_TEST_RECEIPT_STATUS,
        "receipt_role": receipt_role,
        "completed_at": completed_at,
        "producer_identity": dict(producer_identity),
        "command_argv": list(command_argv),
        "python_interpreter": administrative_python_interpreter_record(),
        "sealed_bootstrap": dict(ADMINISTRATIVE_TEST_BOOTSTRAP_RECORD),
        "test_methods": list(test_methods),
        "tests_run": tests_run,
        "return_code": return_code,
        "stdout_sha256": stdout_sha256,
        "stderr_sha256": stderr_sha256,
        "candidate_source_bindings_hash": candidate_source_bindings_hash,
        "formal_write_performed": False,
        "vins_executed": False,
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": OUTCOME_BOUNDARY,
    }
    payload[ADMINISTRATIVE_TEST_RECEIPT_HASH_FIELD] = (
        administrative_test_receipt_hash(payload)
    )
    _validate_administrative_test_receipt(
        payload,
        expected_role=receipt_role,
        expected_source_bindings_hash=candidate_source_bindings_hash,
    )
    return payload


def _validate_administrative_test_receipt(
    payload: object,
    *,
    expected_role: str,
    expected_source_bindings_hash: str,
) -> dict[str, object]:
    producer_role = ADMINISTRATIVE_RECEIPT_ROLES.get(expected_role)
    if producer_role is None:
        raise AdoptionError("unknown administrative test receipt role")
    if (
        not isinstance(payload, dict)
        or set(payload) != ADMINISTRATIVE_TEST_RECEIPT_KEYS
        or payload.get("schema_version") != ADMINISTRATIVE_TEST_RECEIPT_SCHEMA
        or payload.get("status") != ADMINISTRATIVE_TEST_RECEIPT_STATUS
        or payload.get("receipt_role") != expected_role
        or payload.get(ADMINISTRATIVE_TEST_RECEIPT_HASH_FIELD)
        != administrative_test_receipt_hash(payload)
        or type(payload.get("tests_run")) is not int
        or int(payload["tests_run"]) <= 0
        or type(payload.get("return_code")) is not int
        or payload.get("return_code") != 0
        or not HEX64.fullmatch(str(payload.get("stdout_sha256", "")))
        or not HEX64.fullmatch(str(payload.get("stderr_sha256", "")))
        or payload.get("candidate_source_bindings_hash")
        != expected_source_bindings_hash
        or payload.get("formal_write_performed") is not False
        or payload.get("vins_executed") is not False
        or payload.get("held_out_trajectory_outcome_read") is not False
        or payload.get("outcome_boundary") != OUTCOME_BOUNDARY
    ):
        raise AdoptionError("administrative test receipt semantic/hash mismatch")
    _timestamp(str(payload.get("completed_at", "")))
    _validate_reviewer_identity(
        payload.get("producer_identity"),
        expected_role=producer_role,
        label=f"{expected_role} receipt producer",
    )
    argv = payload.get("command_argv")
    methods = payload.get("test_methods")
    interpreter = payload.get("python_interpreter")
    bootstrap = payload.get("sealed_bootstrap")
    if (
        not isinstance(argv, list)
        or argv != list(ADMINISTRATIVE_TEST_ARGV)
        or interpreter != administrative_python_interpreter_record()
        or bootstrap != ADMINISTRATIVE_TEST_BOOTSTRAP_RECORD
        or not isinstance(methods, list)
        or methods != list(ADMINISTRATIVE_TEST_METHODS)
        or int(payload["tests_run"]) != len(ADMINISTRATIVE_TEST_METHODS)
    ):
        raise AdoptionError("administrative test receipt command/method list mismatch")
    return dict(payload)


def _validate_review_order(
    *,
    incident_observed_at: str,
    external_manifest_frozen_at: str,
    global_reviewed_at: str,
    independent_reviewed_at: str,
    adopted_at: str,
) -> None:
    incident_time = _timestamp_value(incident_observed_at)
    manifest_time = _timestamp_value(external_manifest_frozen_at)
    global_time = _timestamp_value(global_reviewed_at)
    independent_time = _timestamp_value(independent_reviewed_at)
    adoption_time = _timestamp_value(adopted_at)
    if not (
        incident_time
        <= manifest_time
        <= global_time
        < independent_time
        <= adoption_time
    ):
        raise AdoptionError(
            "timestamp order must be incident<=manifest<=global<independent<=adopted"
        )


def _review_chain(
    *,
    incident_payload: Mapping[str, object],
    manifest_payload: Mapping[str, object],
    global_payload: Mapping[str, object],
    independent_payload: Mapping[str, object],
    adopted_at: str,
) -> dict[str, object]:
    global_identity = _validate_reviewer_identity(
        global_payload.get("reviewer_identity"),
        expected_role=GLOBAL_REVIEWER_ROLE,
        label="global-stable",
    )
    independent_identity = _validate_reviewer_identity(
        independent_payload.get("reviewer_identity"),
        expected_role=INDEPENDENT_REVIEWER_ROLE,
        label="independent adoption",
    )
    if _reviewer_key(global_identity) == _reviewer_key(independent_identity):
        raise AdoptionError("global and independent reviewer identities are not distinct")
    global_reviewed_at = str(global_payload.get("reviewed_at", ""))
    independent_reviewed_at = str(independent_payload.get("reviewed_at", ""))
    incident_observed_at = str(incident_payload.get("observed_at", ""))
    external_manifest_frozen_at = str(manifest_payload.get("frozen_at", ""))
    _validate_review_order(
        incident_observed_at=incident_observed_at,
        external_manifest_frozen_at=external_manifest_frozen_at,
        global_reviewed_at=global_reviewed_at,
        independent_reviewed_at=independent_reviewed_at,
        adopted_at=adopted_at,
    )
    return {
        "incident_observed_at": incident_observed_at,
        "external_manifest_frozen_at": external_manifest_frozen_at,
        "global_stable_reviewed_at": global_reviewed_at,
        "independent_reviewed_at": independent_reviewed_at,
        "adopted_at": adopted_at,
        "global_reviewer_identity": global_identity,
        "independent_reviewer_identity": independent_identity,
        "reviewer_identities_distinct": True,
        "timestamp_order": "INCIDENT_LE_MANIFEST_LE_GLOBAL_LT_INDEPENDENT_LE_ADOPTED",
    }


def _validate_review_chain_shape(
    value: object, *, adopted_at: str
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != REVIEW_CHAIN_KEYS:
        raise AdoptionError("adoption review-chain key set mismatch")
    global_identity = _validate_reviewer_identity(
        value.get("global_reviewer_identity"),
        expected_role=GLOBAL_REVIEWER_ROLE,
        label="adoption global-stable",
    )
    independent_identity = _validate_reviewer_identity(
        value.get("independent_reviewer_identity"),
        expected_role=INDEPENDENT_REVIEWER_ROLE,
        label="adoption independent",
    )
    if (
        _reviewer_key(global_identity) == _reviewer_key(independent_identity)
        or value.get("reviewer_identities_distinct") is not True
        or value.get("timestamp_order")
        != "INCIDENT_LE_MANIFEST_LE_GLOBAL_LT_INDEPENDENT_LE_ADOPTED"
        or value.get("adopted_at") != adopted_at
    ):
        raise AdoptionError("adoption reviewer independence/order mismatch")
    _validate_review_order(
        incident_observed_at=str(value.get("incident_observed_at", "")),
        external_manifest_frozen_at=str(
            value.get("external_manifest_frozen_at", "")
        ),
        global_reviewed_at=str(value.get("global_stable_reviewed_at", "")),
        independent_reviewed_at=str(value.get("independent_reviewed_at", "")),
        adopted_at=adopted_at,
    )
    return dict(value)


def _validate_external_review_manifest(
    payload: Mapping[str, object],
    *,
    incident_reference: Mapping[str, object],
    root: Path,
    verify_files: bool,
) -> str:
    expected_roles = {
        "required_roles": [GLOBAL_REVIEWER_ROLE, INDEPENDENT_REVIEWER_ROLE],
        "distinct_reviewer_identities_required": True,
        "independent_review_must_bind_global_review": True,
    }
    if (
        set(payload) != EXTERNAL_REVIEW_MANIFEST_KEYS
        or payload.get("schema_version") != EXTERNAL_REVIEW_MANIFEST_SCHEMA
        or payload.get("status") != EXTERNAL_REVIEW_MANIFEST_STATUS
        or payload.get(EXTERNAL_REVIEW_MANIFEST_HASH_FIELD)
        != document_hash(payload, EXTERNAL_REVIEW_MANIFEST_HASH_FIELD)
        or payload.get("incident") != incident_reference
        or payload.get("review_protocol")
        != "TWO_DISTINCT_REVIEWERS_GLOBAL_THEN_INDEPENDENT_BEFORE_ADOPTION"
        or payload.get("review_scope")
        != "PREOUTCOME_BYTE_EXACT_ADMINISTRATIVE_ADOPTION_ONLY"
        or payload.get("reviewer_role_requirements") != expected_roles
        or payload.get("publication_acknowledgements")
        != {
            "external_review_manifest_only": True,
            "no_execution_authority": True,
        }
        or payload.get("execution_authorized") is not False
        or payload.get("vins_executed") is not False
        or payload.get("held_out_trajectory_outcome_read") is not False
        or payload.get("outcome_boundary") != OUTCOME_BOUNDARY
    ):
        raise AdoptionError("external review manifest semantic/hash mismatch")
    _timestamp(str(payload.get("frozen_at", "")))
    records = _validate_file_records(
        payload.get("governance_artifacts"),
        label="external review manifest governance artifacts",
    )
    if [str(record["path"]) for record in records] != list(
        EXTERNAL_REVIEW_GOVERNANCE_PATHS
    ):
        raise AdoptionError("external review manifest governance path set mismatch")
    governance_hash = hashlib.sha256(
        canonical_json(records).encode("utf-8")
    ).hexdigest()
    receipt = _validate_administrative_test_receipt(
        payload.get("administrative_test_receipt"),
        expected_role="EXTERNAL_MANIFEST_PREFLIGHT",
        expected_source_bindings_hash=governance_hash,
    )
    if _timestamp_value(str(receipt["completed_at"])) > _timestamp_value(
        str(payload.get("frozen_at", ""))
    ):
        raise AdoptionError("external manifest predates its administrative tests")
    if verify_files:
        for expected in records:
            _content, observed = _read_direct(
                root,
                str(expected["path"]),
                label="external review manifest governance artifact",
            )
            if observed != expected:
                raise AdoptionError(
                    "external review manifest governance artifact drift: "
                    f"{expected['path']}"
                )
    return str(payload[EXTERNAL_REVIEW_MANIFEST_HASH_FIELD])


def _validate_global_stable_review(
    payload: Mapping[str, object],
    *,
    incident_reference: Mapping[str, object],
    manifest_reference: Mapping[str, object],
    source_bindings_hash: str,
) -> str:
    reviewer_identity = _validate_reviewer_identity(
        payload.get("reviewer_identity"),
        expected_role=GLOBAL_REVIEWER_ROLE,
        label="global-stable",
    )
    if (
        set(payload) != GLOBAL_STABLE_KEYS
        or payload.get("schema_version") != GLOBAL_STABLE_SCHEMA
        or payload.get("status") != GLOBAL_STABLE_STATUS
        or payload.get(GLOBAL_STABLE_HASH_FIELD)
        != document_hash(payload, GLOBAL_STABLE_HASH_FIELD)
        or payload.get("incident") != incident_reference
        or payload.get("external_review_manifest") != manifest_reference
        or payload.get("candidate_source_bindings_hash") != source_bindings_hash
        or payload.get("tests_status") != "PASS"
        or payload.get("independence_attestation")
        != GLOBAL_INDEPENDENCE_ATTESTATION
        or payload.get("publication_acknowledgements")
        != {
            "global_stability_review_only": True,
            "no_execution_authority": True,
        }
        or payload.get("formal_write_performed") is not False
        or payload.get("vins_executed") is not False
        or payload.get("held_out_trajectory_outcome_read") is not False
        or payload.get("outcome_boundary") != OUTCOME_BOUNDARY
    ):
        raise AdoptionError("global-stable review semantic/hash mismatch")
    _timestamp(str(payload.get("reviewed_at", "")))
    receipt = _validate_administrative_test_receipt(
        payload.get("administrative_test_receipt"),
        expected_role="GLOBAL_STABILITY_ADMINISTRATIVE",
        expected_source_bindings_hash=source_bindings_hash,
    )
    if (
        receipt.get("producer_identity") != reviewer_identity
        or _timestamp_value(str(receipt["completed_at"]))
        > _timestamp_value(str(payload["reviewed_at"]))
    ):
        raise AdoptionError("global review administrative receipt mismatch")
    return str(payload[GLOBAL_STABLE_HASH_FIELD])


def _validate_independent_go(
    payload: Mapping[str, object],
    *,
    incident_reference: Mapping[str, object],
    manifest_reference: Mapping[str, object],
    global_reference: Mapping[str, object],
    global_reviewer_identity: Mapping[str, str],
    source_bindings_hash: str,
) -> str:
    independent_identity = _validate_reviewer_identity(
        payload.get("reviewer_identity"),
        expected_role=INDEPENDENT_REVIEWER_ROLE,
        label="independent adoption",
    )
    attestation = payload.get("independence_attestation")
    if (
        not isinstance(attestation, dict)
        or set(attestation) != INDEPENDENT_INDEPENDENCE_ATTESTATION_KEYS
        or attestation
        != {
            "global_reviewer_id": global_reviewer_identity["reviewer_id"],
            "global_reviewer_instance": global_reviewer_identity[
                "reviewer_instance"
            ],
            "independent_reviewer_is_global_reviewer": False,
            "incident_creator_is_reviewer": False,
            "review_performed_without_outcome_access": True,
            "execution_authority_requested": False,
        }
        or _reviewer_key(independent_identity)
        == _reviewer_key(global_reviewer_identity)
    ):
        raise AdoptionError("independent adoption reviewer attestation mismatch")
    if (
        set(payload) != INDEPENDENT_GO_KEYS
        or payload.get("schema_version") != INDEPENDENT_GO_SCHEMA
        or payload.get("status") != INDEPENDENT_GO_STATUS
        or payload.get(INDEPENDENT_GO_HASH_FIELD)
        != document_hash(payload, INDEPENDENT_GO_HASH_FIELD)
        or payload.get("incident") != incident_reference
        or payload.get("external_review_manifest") != manifest_reference
        or payload.get("global_stable_review") != global_reference
        or payload.get("candidate_source_bindings_hash") != source_bindings_hash
        or payload.get("adoption_scope")
        != "ADMINISTRATIVE_ADOPTION_ONLY_NO_EXECUTION"
        or payload.get("publication_acknowledgements")
        != {
            "independent_adoption_review_only": True,
            "no_execution_authority": True,
        }
        or payload.get("execution_authorized") is not False
        or payload.get("vins_executed") is not False
        or payload.get("held_out_trajectory_outcome_read") is not False
        or payload.get("outcome_boundary") != OUTCOME_BOUNDARY
    ):
        raise AdoptionError("independent adoption GO semantic/hash mismatch")
    _timestamp(str(payload.get("reviewed_at", "")))
    receipt = _validate_administrative_test_receipt(
        payload.get("administrative_test_receipt"),
        expected_role="INDEPENDENT_ADMINISTRATIVE_REPLAY",
        expected_source_bindings_hash=source_bindings_hash,
    )
    if (
        receipt.get("producer_identity") != independent_identity
        or _timestamp_value(str(receipt["completed_at"]))
        > _timestamp_value(str(payload["reviewed_at"]))
    ):
        raise AdoptionError("independent review administrative receipt mismatch")
    return str(payload[INDEPENDENT_GO_HASH_FIELD])


def build_adoption(
    *,
    root: Path = ROOT,
    adopted_at: str,
    require_output_absent: bool = True,
    ack_administrative_adoption_only: bool = False,
    ack_no_execution_authority: bool = False,
) -> dict[str, object]:
    root = root.absolute()
    _timestamp(adopted_at)
    incident_relative = incident.OUTPUT_RELATIVE
    incident_payload, incident_record, _incident_content = _json_direct(
        root, incident_relative, label="formalization incident"
    )
    incident_hash = incident.validate_incident(
        incident_payload, root=root, verify_live=False
    )
    incident_reference = _reference(
        incident_record, incident_hash, incident.SELF_HASH_FIELD
    )
    manifest_payload, manifest_record, _manifest_content = _json_direct(
        root,
        EXTERNAL_REVIEW_MANIFEST_RELATIVE,
        label="external review manifest",
    )
    manifest_hash = _validate_external_review_manifest(
        manifest_payload,
        incident_reference=incident_reference,
        root=root,
        verify_files=True,
    )
    manifest_reference = _reference(
        manifest_record,
        manifest_hash,
        EXTERNAL_REVIEW_MANIFEST_HASH_FIELD,
    )
    live = collect_live_rebuild_evidence(root=root)
    if live.get("all_ten_files_byte_exact") is not True:
        raise AdoptionError("ten-file deterministic live rebuild did not pass")
    source_bindings_hash = str(live["source_bindings_hash"])

    global_payload, global_record, _ = _json_direct(
        root, GLOBAL_STABLE_REVIEW_RELATIVE, label="global-stable review"
    )
    global_hash = _validate_global_stable_review(
        global_payload,
        incident_reference=incident_reference,
        manifest_reference=manifest_reference,
        source_bindings_hash=source_bindings_hash,
    )
    global_reference = _reference(
        global_record, global_hash, GLOBAL_STABLE_HASH_FIELD
    )
    global_reviewer_identity = _validate_reviewer_identity(
        global_payload.get("reviewer_identity"),
        expected_role=GLOBAL_REVIEWER_ROLE,
        label="global-stable",
    )
    independent_payload, independent_record, _ = _json_direct(
        root, INDEPENDENT_GO_RELATIVE, label="independent adoption GO"
    )
    independent_hash = _validate_independent_go(
        independent_payload,
        incident_reference=incident_reference,
        manifest_reference=manifest_reference,
        global_reference=global_reference,
        global_reviewer_identity=global_reviewer_identity,
        source_bindings_hash=source_bindings_hash,
    )
    independent_reference = _reference(
        independent_record, independent_hash, INDEPENDENT_GO_HASH_FIELD
    )
    review_chain = _review_chain(
        incident_payload=incident_payload,
        manifest_payload=manifest_payload,
        global_payload=global_payload,
        independent_payload=independent_payload,
        adopted_at=adopted_at,
    )

    governance_artifacts = []
    for relative in (ADOPTION_BUILDER_RELATIVE, ADOPTION_TEST_RELATIVE):
        _content, record = _read_direct(root, relative, label="adoption governance artifact")
        governance_artifacts.append(record)

    for relative in POST_ADOPTION_AUTHORITY_ABSENT_PATHS:
        if formal_io.destination_exists(root, relative):
            raise AdoptionError(f"downstream formal already exists: {relative}")
    if require_output_absent and formal_io.destination_exists(root, OUTPUT_RELATIVE):
        raise FileExistsError(root / OUTPUT_RELATIVE)

    payload: dict[str, object] = {
        "schema_version": SCHEMA,
        "status": STATUS,
        "adopted_at": adopted_at,
        "incident": incident_reference,
        "external_review_manifest": manifest_reference,
        "global_stable_review": global_reference,
        "independent_adoption_go": independent_reference,
        "review_chain": review_chain,
        "live_rebuild": live,
        "source_bindings": {
            "count": live["source_artifact_count"],
            "hash": source_bindings_hash,
            "all_current_hashes_match": True,
        },
        "governance_artifacts": governance_artifacts,
        "adoption_scope": (
            "ADMINISTRATIVELY_ACCEPT_EXISTING_BYTE_EXACT_PREOUTCOME_FORMALS_ONLY"
        ),
        "future_binding_policy": {
            "required_future_formals": [
                "backend_b0_materialization_lock_v1.json",
                "backend_replacement_contract_v1.json",
                "g0_evaluation_lock_v1.json",
                "backend_replay_execution_lock_v1.json",
            ],
            "each_must_bind_adoption_file_sha256_and_hash": True,
            "no_legacy_or_queue_artifact_may_be_overwritten": True,
        },
        "authorization": {
            "b0_materialization_authorized": False,
            "replacement_authorized": False,
            "g0_evaluation_authorized": False,
            "backend_replay_authorized": False,
            "ros_authorized": False,
            "vins_authorized": False,
            "execution_requires_separate_frozen_execution_lock": True,
        },
        "publication_acknowledgements": {
            "administrative_adoption_only": bool(
                ack_administrative_adoption_only
            ),
            "no_execution_authority": bool(ack_no_execution_authority),
        },
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": OUTCOME_BOUNDARY,
    }
    payload[SELF_HASH_FIELD] = document_hash(payload, SELF_HASH_FIELD)
    validate_adoption(payload, root=root, verify_live=False)
    return payload


def validate_adoption(
    payload: Mapping[str, object],
    *,
    root: Path = ROOT,
    verify_live: bool = True,
) -> str:
    if (
        set(payload) != ADOPTION_KEYS
        or payload.get("schema_version") != SCHEMA
        or payload.get("status") != STATUS
        or payload.get(SELF_HASH_FIELD) != document_hash(payload, SELF_HASH_FIELD)
        or payload.get("adoption_scope")
        != "ADMINISTRATIVELY_ACCEPT_EXISTING_BYTE_EXACT_PREOUTCOME_FORMALS_ONLY"
        or payload.get("held_out_trajectory_outcome_read") is not False
        or payload.get("outcome_boundary") != OUTCOME_BOUNDARY
    ):
        raise AdoptionError("adoption schema/status/hash/scope mismatch")
    _timestamp(str(payload.get("adopted_at", "")))
    review_chain = _validate_review_chain_shape(
        payload.get("review_chain"), adopted_at=str(payload.get("adopted_at", ""))
    )
    authorization = payload.get("authorization")
    expected_authorization = {
        "b0_materialization_authorized": False,
        "replacement_authorized": False,
        "g0_evaluation_authorized": False,
        "backend_replay_authorized": False,
        "ros_authorized": False,
        "vins_authorized": False,
        "execution_requires_separate_frozen_execution_lock": True,
    }
    expected_future = {
        "required_future_formals": [
            "backend_b0_materialization_lock_v1.json",
            "backend_replacement_contract_v1.json",
            "g0_evaluation_lock_v1.json",
            "backend_replay_execution_lock_v1.json",
        ],
        "each_must_bind_adoption_file_sha256_and_hash": True,
        "no_legacy_or_queue_artifact_may_be_overwritten": True,
    }
    if authorization != expected_authorization or payload.get("future_binding_policy") != expected_future:
        raise AdoptionError("adoption authorization/future-binding policy mismatch")
    acknowledgements = payload.get("publication_acknowledgements")
    if (
        not isinstance(acknowledgements, dict)
        or set(acknowledgements)
        != {"administrative_adoption_only", "no_execution_authority"}
        or not all(isinstance(value, bool) for value in acknowledgements.values())
    ):
        raise AdoptionError("adoption publication acknowledgement shape mismatch")
    live = _validate_live_shape(payload.get("live_rebuild"))
    sources = payload.get("source_bindings")
    if (
        not isinstance(sources, dict)
        or set(sources) != {"count", "hash", "all_current_hashes_match"}
        or sources.get("all_current_hashes_match") is not True
        or sources.get("hash") != live.get("source_bindings_hash")
        or int(sources.get("count", -1)) != int(live.get("source_artifact_count", -2))
    ):
        raise AdoptionError("adoption live/source evidence mismatch")
    _validate_reference_shape(
        payload.get("incident"),
        expected_path=incident.OUTPUT_RELATIVE,
        hash_field=incident.SELF_HASH_FIELD,
        label="adoption incident",
    )
    _validate_reference_shape(
        payload.get("external_review_manifest"),
        expected_path=EXTERNAL_REVIEW_MANIFEST_RELATIVE,
        hash_field=EXTERNAL_REVIEW_MANIFEST_HASH_FIELD,
        label="adoption external review manifest",
    )
    _validate_reference_shape(
        payload.get("global_stable_review"),
        expected_path=GLOBAL_STABLE_REVIEW_RELATIVE,
        hash_field=GLOBAL_STABLE_HASH_FIELD,
        label="adoption global-stable review",
    )
    _validate_reference_shape(
        payload.get("independent_adoption_go"),
        expected_path=INDEPENDENT_GO_RELATIVE,
        hash_field=INDEPENDENT_GO_HASH_FIELD,
        label="adoption independent GO",
    )
    governance_records = _validate_file_records(
        payload.get("governance_artifacts"), label="adoption governance artifacts"
    )
    if [item["path"] for item in governance_records] != sorted(
        (ADOPTION_BUILDER_RELATIVE, ADOPTION_TEST_RELATIVE)
    ):
        raise AdoptionError("adoption governance artifact path set mismatch")
    if verify_live:
        validate_adoption_historical(payload, root=root)
        root = root.absolute()
        incident_payload, incident_record, _ = _json_direct(
            root, incident.OUTPUT_RELATIVE, label="formalization incident"
        )
        incident_hash = incident.validate_incident(
            incident_payload, root=root, verify_live=False
        )
        incident_reference = _reference(
            incident_record, incident_hash, incident.SELF_HASH_FIELD
        )
        _validate_reference(
            payload.get("incident"),
            expected_record=incident_record,
            expected_hash=incident_hash,
            hash_field=incident.SELF_HASH_FIELD,
            label="adoption incident",
        )
        manifest_payload, manifest_record, _ = _json_direct(
            root,
            EXTERNAL_REVIEW_MANIFEST_RELATIVE,
            label="external review manifest",
        )
        manifest_hash = _validate_external_review_manifest(
            manifest_payload,
            incident_reference=incident_reference,
            root=root,
            verify_files=True,
        )
        manifest_reference = _reference(
            manifest_record,
            manifest_hash,
            EXTERNAL_REVIEW_MANIFEST_HASH_FIELD,
        )
        _validate_reference(
            payload.get("external_review_manifest"),
            expected_record=manifest_record,
            expected_hash=manifest_hash,
            hash_field=EXTERNAL_REVIEW_MANIFEST_HASH_FIELD,
            label="adoption external review manifest",
        )
        observed_live = collect_live_rebuild_evidence(root=root)
        if live != observed_live:
            raise AdoptionError("adoption live rebuild evidence drift")
        for item in governance_records:
            _content, observed = _read_direct(
                root, str(item["path"]), label="adoption governance artifact"
            )
            if observed != item:
                raise AdoptionError(
                    f"adoption governance artifact drift: {item['path']}"
                )
        global_payload, global_record, _ = _json_direct(
            root, GLOBAL_STABLE_REVIEW_RELATIVE, label="global-stable review"
        )
        global_hash = _validate_global_stable_review(
            global_payload,
            incident_reference=incident_reference,
            manifest_reference=manifest_reference,
            source_bindings_hash=str(observed_live["source_bindings_hash"]),
        )
        global_reference = _reference(
            global_record, global_hash, GLOBAL_STABLE_HASH_FIELD
        )
        global_reviewer_identity = _validate_reviewer_identity(
            global_payload.get("reviewer_identity"),
            expected_role=GLOBAL_REVIEWER_ROLE,
            label="global-stable",
        )
        _validate_reference(
            payload.get("global_stable_review"),
            expected_record=global_record,
            expected_hash=global_hash,
            hash_field=GLOBAL_STABLE_HASH_FIELD,
            label="adoption global-stable review",
        )
        independent_payload, independent_record, _ = _json_direct(
            root, INDEPENDENT_GO_RELATIVE, label="independent adoption GO"
        )
        independent_hash = _validate_independent_go(
            independent_payload,
            incident_reference=incident_reference,
            manifest_reference=manifest_reference,
            global_reference=global_reference,
            global_reviewer_identity=global_reviewer_identity,
            source_bindings_hash=str(observed_live["source_bindings_hash"]),
        )
        _validate_reference(
            payload.get("independent_adoption_go"),
            expected_record=independent_record,
            expected_hash=independent_hash,
            hash_field=INDEPENDENT_GO_HASH_FIELD,
            label="adoption independent GO",
        )
        observed_review_chain = _review_chain(
            incident_payload=incident_payload,
            manifest_payload=manifest_payload,
            global_payload=global_payload,
            independent_payload=independent_payload,
            adopted_at=str(payload["adopted_at"]),
        )
        if review_chain != observed_review_chain:
            raise AdoptionError("adoption review-chain live evidence drift")
        for relative in POST_ADOPTION_AUTHORITY_ABSENT_PATHS:
            if formal_io.destination_exists(root, relative):
                raise AdoptionError(f"downstream formal already exists: {relative}")
    return str(payload[SELF_HASH_FIELD])


def validate_adoption_historical(
    payload: Mapping[str, object], *, root: Path = ROOT
) -> str:
    """Verify immutable adopted bytes without requiring pre-adoption live state."""

    root = root.absolute()
    digest = validate_adoption(payload, root=root, verify_live=False)
    if payload.get("publication_acknowledgements") != {
        "administrative_adoption_only": True,
        "no_execution_authority": True,
    }:
        raise AdoptionError("historical adoption lacks both publication acknowledgements")
    incident_payload, incident_record, _ = _json_direct(
        root, incident.OUTPUT_RELATIVE, label="historical formalization incident"
    )
    incident_hash = incident.validate_incident(
        incident_payload, root=root, verify_live=False
    )
    incident_reference = _reference(
        incident_record, incident_hash, incident.SELF_HASH_FIELD
    )
    _validate_reference(
        payload.get("incident"),
        expected_record=incident_record,
        expected_hash=incident_hash,
        hash_field=incident.SELF_HASH_FIELD,
        label="historical adoption incident",
    )

    present = incident_payload.get("present_artifacts")
    if (
        not isinstance(present, list)
        or [item.get("path") for item in present if isinstance(item, dict)]
        != list(incident.PRESENT_PATHS)
    ):
        raise AdoptionError("historical incident ten-file set mismatch")
    for item in present:
        if not isinstance(item, dict):
            raise AdoptionError("historical incident file record malformed")
        relative = str(item.get("path", ""))
        _content, observed = _read_direct(
            root, relative, label="historical adopted formal"
        )
        expected = {
            "path": relative,
            "sha256": item.get("sha256"),
            "size_bytes": item.get("size_bytes"),
        }
        if observed != expected:
            raise AdoptionError(f"historical adopted formal byte drift: {relative}")

    manifest_payload, manifest_record, _ = _json_direct(
        root,
        EXTERNAL_REVIEW_MANIFEST_RELATIVE,
        label="historical external review manifest",
    )
    manifest_hash = _validate_external_review_manifest(
        manifest_payload,
        incident_reference=incident_reference,
        root=root,
        verify_files=True,
    )
    manifest_reference = _reference(
        manifest_record, manifest_hash, EXTERNAL_REVIEW_MANIFEST_HASH_FIELD
    )
    _validate_reference(
        payload.get("external_review_manifest"),
        expected_record=manifest_record,
        expected_hash=manifest_hash,
        hash_field=EXTERNAL_REVIEW_MANIFEST_HASH_FIELD,
        label="historical external review manifest",
    )

    source_hash = str(payload["live_rebuild"]["source_bindings_hash"])
    global_payload, global_record, _ = _json_direct(
        root, GLOBAL_STABLE_REVIEW_RELATIVE, label="historical global-stable review"
    )
    global_hash = _validate_global_stable_review(
        global_payload,
        incident_reference=incident_reference,
        manifest_reference=manifest_reference,
        source_bindings_hash=source_hash,
    )
    global_reference = _reference(
        global_record, global_hash, GLOBAL_STABLE_HASH_FIELD
    )
    _validate_reference(
        payload.get("global_stable_review"),
        expected_record=global_record,
        expected_hash=global_hash,
        hash_field=GLOBAL_STABLE_HASH_FIELD,
        label="historical global-stable review",
    )
    global_identity = _validate_reviewer_identity(
        global_payload.get("reviewer_identity"),
        expected_role=GLOBAL_REVIEWER_ROLE,
        label="historical global-stable",
    )
    independent_payload, independent_record, _ = _json_direct(
        root, INDEPENDENT_GO_RELATIVE, label="historical independent adoption GO"
    )
    independent_hash = _validate_independent_go(
        independent_payload,
        incident_reference=incident_reference,
        manifest_reference=manifest_reference,
        global_reference=global_reference,
        global_reviewer_identity=global_identity,
        source_bindings_hash=source_hash,
    )
    _validate_reference(
        payload.get("independent_adoption_go"),
        expected_record=independent_record,
        expected_hash=independent_hash,
        hash_field=INDEPENDENT_GO_HASH_FIELD,
        label="historical independent adoption GO",
    )
    observed_chain = _review_chain(
        incident_payload=incident_payload,
        manifest_payload=manifest_payload,
        global_payload=global_payload,
        independent_payload=independent_payload,
        adopted_at=str(payload["adopted_at"]),
    )
    if payload.get("review_chain") != observed_chain:
        raise AdoptionError("historical review-chain evidence drift")

    for record in _validate_file_records(
        payload.get("governance_artifacts"),
        label="historical adoption governance artifacts",
    ):
        _content, observed = _read_direct(
            root, str(record["path"]), label="historical adoption governance artifact"
        )
        if observed != record:
            raise AdoptionError(
                f"historical adoption governance drift: {record['path']}"
            )
    for record in _validate_file_records(
        payload["live_rebuild"].get("source_artifacts"),
        label="historical adopted source bindings",
    ):
        _content, observed = _read_direct(
            root, str(record["path"]), label="historical adopted source"
        )
        if observed != record:
            raise AdoptionError(f"historical adopted source drift: {record['path']}")
    return digest


def validate_adoption_live_pre_adoption(
    payload: Mapping[str, object], *, root: Path = ROOT
) -> str:
    """Verify historical bytes plus the still-pristine pre-adoption live state."""

    return validate_adoption(payload, root=root, verify_live=True)


def load_and_validate_historical_adoption(
    root: Path = ROOT,
) -> tuple[dict[str, object], dict[str, object]]:
    """Load the direct canonical adoption and verify immutable historical facts."""

    root = root.absolute()
    payload, record, _content = _json_direct(
        root, OUTPUT_RELATIVE, label="historical formalization adoption"
    )
    validate_adoption_historical(payload, root=root)
    return payload, record


def adoption_authority_binding(root: Path = ROOT) -> dict[str, object]:
    """Return the exact one-way authority record future formals must bind."""

    payload, record = load_and_validate_historical_adoption(root=root)
    return {
        "path": OUTPUT_RELATIVE,
        "sha256": record["sha256"],
        "size_bytes": record["size_bytes"],
        SELF_HASH_FIELD: payload[SELF_HASH_FIELD],
    }


def validate_adoption_authority_binding(
    value: object, *, root: Path = ROOT
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != ADOPTION_AUTHORITY_BINDING_KEYS:
        raise AdoptionError("adoption authority binding key set mismatch")
    expected = adoption_authority_binding(root=root)
    if value != expected:
        raise AdoptionError("adoption authority binding live mismatch")
    return dict(value)


def _publication_guard_paths(
    payload: Mapping[str, object], *, root: Path
) -> list[str]:
    paths = {
        incident.OUTPUT_RELATIVE,
        EXTERNAL_REVIEW_MANIFEST_RELATIVE,
        GLOBAL_STABLE_REVIEW_RELATIVE,
        INDEPENDENT_GO_RELATIVE,
        ADOPTION_BUILDER_RELATIVE,
        ADOPTION_TEST_RELATIVE,
        "papers/ieee_sensors_journal_experiments/p07/split_role_audit_v1.csv",
    }
    paths.update(EXTERNAL_REVIEW_GOVERNANCE_PATHS)
    incident_payload, _incident_record, _ = _json_direct(
        root, incident.OUTPUT_RELATIVE, label="publication incident lease source"
    )
    present = incident_payload.get("present_artifacts")
    if isinstance(present, list):
        for record in present:
            if isinstance(record, dict) and isinstance(record.get("path"), str):
                paths.add(_safe_relative(str(record["path"])))
    registry = incident_payload.get("canonical_run_registry")
    if isinstance(registry, dict):
        full_file = registry.get("full_file")
        if isinstance(full_file, dict) and isinstance(full_file.get("path"), str):
            paths.add(_safe_relative(str(full_file["path"])))

    live = payload.get("live_rebuild")
    if not isinstance(live, dict):
        raise AdoptionError("publication live rebuild evidence is missing")
    source_records = _validate_file_records(
        live.get("source_artifacts"), label="publication source leases"
    )
    paths.update(str(record["path"]) for record in source_records)
    governance_records = _validate_file_records(
        payload.get("governance_artifacts"), label="publication governance leases"
    )
    paths.update(str(record["path"]) for record in governance_records)

    # These direct, outcome-free queue inputs are also retained when present.
    # Synthetic unit roots omit them and substitute a deterministic live-rebuild
    # fixture; the canonical production root contains all of them.
    static_inputs = (
        queue.MANIFEST,
        queue.ARM_ORDER,
        queue.METHOD_LOCK,
        queue.ENVIRONMENT,
        queue.EVALUATOR,
        queue.FAILURE_TAXONOMY,
        queue.FRONTEND_QUEUE,
        queue.FRONTEND_ALLOCATION,
        queue.FRONTEND_QUEUE_LOCK,
        queue.FRONTEND_QUEUE_VALIDATION,
        queue.D_QUEUE,
        queue.RUN_REGISTRY,
        queue.ARM_APPLICABILITY,
        queue.EVALUATOR_CORRECTION_LOCK,
        queue.EVALUATOR_EPOCH_CORRECTION_LOCK,
    )
    canonical_root = queue.ROOT.absolute()
    for absolute in static_inputs:
        relative = absolute.absolute().relative_to(canonical_root).as_posix()
        candidate = root / relative
        if os.path.lexists(candidate):
            paths.add(relative)
    if OUTPUT_RELATIVE in paths:
        raise AdoptionError("adoption output cannot be one of its retained inputs")
    return sorted(paths)


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return left.st_dev == right.st_dev and left.st_ino == right.st_ino


_RENAME_NOREPLACE = 1
_LIBC = ctypes.CDLL(None, use_errno=True)


def _rollback_identity(info: os.stat_result) -> dict[str, int]:
    return {
        "device": int(info.st_dev),
        "inode": int(info.st_ino),
        "mode": int(info.st_mode),
        "size_bytes": int(info.st_size),
        "nlink": int(info.st_nlink),
        "mtime_ns": int(info.st_mtime_ns),
        "ctime_ns": int(info.st_ctime_ns),
    }


def _capture_final_retained_identity(
    *, parent_fd: int, parent_path: Path, retained_path: Path
) -> dict[str, int]:
    """Capture one no-follow FD/lexical view after publication cleanup."""

    expected_parent = parent_path.absolute()
    retained = Path(os.path.abspath(os.fspath(retained_path)))
    if retained.parent != expected_parent or retained.name in {"", ".", ".."}:
        raise AdoptionError("retained rollback path escaped its anchored parent")

    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = -1
    try:
        descriptor = os.open(retained.name, flags, dir_fd=parent_fd)
        opened_before = os.fstat(descriptor)
        reachable = os.stat(
            retained.name, dir_fd=parent_fd, follow_symlinks=False
        )
        opened_after = os.fstat(descriptor)
        identities = (
            _rollback_identity(opened_before),
            _rollback_identity(reachable),
            _rollback_identity(opened_after),
        )
        if not (
            _same_inode(opened_before, reachable)
            and _same_inode(opened_after, reachable)
            and identities[0] == identities[1] == identities[2]
        ):
            raise AdoptionError("retained rollback final identity drift")
        return identities[1]
    except OSError as error:
        raise AdoptionError("cannot capture retained rollback final identity") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _finalize_pending_rollback_identity(
    rollback: RollbackIncomplete,
    *,
    parent_fd: int,
    parent_path: Path,
) -> None:
    """Refresh a pending structured rollback without replacing that exception."""

    try:
        rollback.retained_identity = _capture_final_retained_identity(
            parent_fd=parent_fd,
            parent_path=parent_path,
            retained_path=rollback.retained_path,
        )
    except AdoptionError:
        rollback.reason = (
            f"{rollback.reason}_FINAL_IDENTITY_UNAVAILABLE_NO_AUTOMATIC_RECLAIM"
        )
        rollback.retained_identity = None
        rollback.args = (
            "rollback-incomplete: "
            f"reason={rollback.reason}; retained_path={os.fspath(rollback.retained_path)}",
        )


def _rename_noreplace_at(
    parent_fd: int, source_name: str, destination_name: str
) -> None:
    renameat2 = getattr(_LIBC, "renameat2", None)
    if renameat2 is None:
        raise AdoptionError("renameat2(RENAME_NOREPLACE) is unavailable")
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    if renameat2(
        parent_fd,
        os.fsencode(source_name),
        parent_fd,
        os.fsencode(destination_name),
        _RENAME_NOREPLACE,
    ) != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number), destination_name)


def _preserved_rollback_paths(
    *, parent_fd: int, name: str, parent_path: Path
) -> list[Path]:
    prefix = f".{name}.aqua-fe-preserved-rollback-"
    try:
        names = os.listdir(parent_fd)
    except OSError as error:
        raise AdoptionError("cannot inspect preserved rollback artifacts") from error
    return sorted(
        (parent_path / entry).absolute()
        for entry in names
        if isinstance(entry, str) and entry.startswith(prefix)
    )


def _assert_no_preserved_rollback(
    *, parent_fd: int, name: str, parent_path: Path
) -> None:
    preserved = _preserved_rollback_paths(
        parent_fd=parent_fd, name=name, parent_path=parent_path
    )
    if preserved:
        raise RollbackIncomplete(
            retained_path=preserved[0],
            reason="PRESERVED_ROLLBACK_REQUIRES_SEPARATE_GOVERNANCE",
        )


def _preserve_own_destination_rollback(
    *,
    parent_fd: int,
    name: str,
    parent_path: Path,
    staged: os.stat_result,
    retained_fd: int,
) -> None:
    """Preserve a failed canonical publication without name-based deletion."""

    canonical_path = (parent_path / name).absolute()
    try:
        retained = os.fstat(retained_fd)
        if not stat.S_ISREG(retained.st_mode) or not _same_inode(retained, staged):
            raise RollbackIncomplete(
                retained_path=canonical_path,
                reason="RETAINED_STAGED_DESCRIPTOR_IDENTITY_DRIFT",
            )
        os.fsync(retained_fd)
    except RollbackIncomplete:
        raise
    except OSError as error:
        raise RollbackIncomplete(
            retained_path=canonical_path,
            reason="RETAINED_STAGED_DESCRIPTOR_UNAVAILABLE",
        ) from error

    try:
        observed = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError as error:
        raise RollbackIncomplete(
            retained_path=canonical_path,
            reason="CANONICAL_DESTINATION_MISSING_NO_AUTOMATIC_RECLAIM",
        ) from error
    if not _same_inode(observed, staged):
        raise RollbackIncomplete(
            retained_path=canonical_path,
            reason="UNKNOWN_CANONICAL_WINNER_RETAINED",
            retained_identity=_rollback_identity(observed),
        )

    preserved_name: Optional[str] = None
    for _attempt in range(32):
        candidate = (
            f".{name}.aqua-fe-preserved-rollback-"
            f"{os.getpid()}-{secrets.token_hex(16)}"
        )
        try:
            _rename_noreplace_at(parent_fd, name, candidate)
        except FileNotFoundError as error:
            raise RollbackIncomplete(
                retained_path=canonical_path,
                reason="CANONICAL_DESTINATION_DISAPPEARED_BEFORE_PRESERVATION",
            ) from error
        except OSError as error:
            if error.errno == errno.EEXIST:
                continue
            raise RollbackIncomplete(
                retained_path=canonical_path,
                reason="ROLLBACK_PRESERVATION_RENAME_FAILED",
                retained_identity=_rollback_identity(observed),
            ) from error
        preserved_name = candidate
        break
    if preserved_name is None:
        raise RollbackIncomplete(
            retained_path=canonical_path,
            reason="ROLLBACK_PRESERVATION_NAME_COLLISIONS",
            retained_identity=_rollback_identity(observed),
        )

    preserved_path = (parent_path / preserved_name).absolute()
    try:
        formal_io._fsync_directory(parent_fd)
    except OSError as error:
        raise RollbackIncomplete(
            retained_path=preserved_path,
            reason="PRESERVED_ROLLBACK_DIRECTORY_FSYNC_FAILED",
            retained_identity=_rollback_identity(staged),
        ) from error
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(preserved_name, flags, dir_fd=parent_fd)
        moved = os.fstat(descriptor)
        if not _same_inode(moved, staged):
            raise RollbackIncomplete(
                retained_path=preserved_path,
                reason="UNKNOWN_MOVED_INODE_PRESERVED",
                retained_identity=_rollback_identity(moved),
            )
        os.fsync(descriptor)
    except RollbackIncomplete:
        raise
    except OSError as error:
        raise RollbackIncomplete(
            retained_path=preserved_path,
            reason="PRESERVED_ROLLBACK_DESCRIPTOR_UNAVAILABLE",
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    raise RollbackIncomplete(
        retained_path=preserved_path,
        reason="OWN_PUBLICATION_PRESERVED_NO_AUTOMATIC_RECLAIM",
        retained_identity=_rollback_identity(staged),
    )


def publish_adoption_no_clobber(
    payload: Mapping[str, object],
    *,
    root: Path = ROOT,
    ack_administrative_adoption_only: bool,
    ack_no_execution_authority: bool,
    _pre_link_test_hook: Optional[Callable[[], None]] = None,
    _post_link_test_hook: Optional[Callable[[], None]] = None,
) -> dict[str, object]:
    """Commit the adoption last under retained inputs with safe own-inode rollback."""

    root = root.absolute()
    if not ack_administrative_adoption_only or not ack_no_execution_authority:
        raise AdoptionError(
            "publication API requires both administrative-only/no-execution acknowledgements"
        )
    if payload.get("publication_acknowledgements") != {
        "administrative_adoption_only": True,
        "no_execution_authority": True,
    }:
        raise AdoptionError("publication payload does not record both acknowledgements")
    content = json_bytes(payload)
    paths = _publication_guard_paths(payload, root=root)
    expected_inputs: dict[str, bytes] = {}
    for relative in paths:
        try:
            expected_inputs[relative] = formal_io.read_direct_bytes(root, relative)[0]
        except (OSError, formal_io.FormalIOError) as error:
            raise AdoptionError(
                f"cannot retain adoption publication input: {relative}"
            ) from error

    with formal_io.global_formal_lock():
        if formal_io.destination_exists(root, OUTPUT_RELATIVE):
            raise FileExistsError(OUTPUT_RELATIVE)
        with ExitStack() as stack:
            leases = [
                stack.enter_context(
                    formal_io._retained_exact_leaf(
                        root, relative, expected_inputs[relative]
                    )
                )
                for relative in paths
            ]

            def validate_same_snapshot() -> None:
                for lease in leases:
                    formal_io._validate_retained_exact_leaf(lease)
                validate_adoption(payload, root=root, verify_live=True)
                for lease in leases:
                    formal_io._validate_retained_exact_leaf(lease)

            validate_same_snapshot()
            with formal_io._parent_dirfd(root, OUTPUT_RELATIVE) as (parent_fd, name):
                parent_path = (root / OUTPUT_RELATIVE).parent.absolute()
                _assert_no_preserved_rollback(
                    parent_fd=parent_fd, name=name, parent_path=parent_path
                )
                try:
                    os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise FileExistsError(OUTPUT_RELATIVE)

                temporary = (
                    f".{name}.partial.{os.getpid()}.{secrets.token_hex(12)}"
                )
                staged_fd = -1
                staged: Optional[os.stat_result] = None
                linked = False
                temporary_present = False
                pending_rollback: Optional[RollbackIncomplete] = None
                try:
                    flags = (
                        os.O_WRONLY
                        | os.O_CREAT
                        | os.O_EXCL
                        | os.O_CLOEXEC
                        | os.O_NOFOLLOW
                    )
                    staged_fd = os.open(temporary, flags, 0o600, dir_fd=parent_fd)
                    temporary_present = True
                    formal_io._write_all(staged_fd, content)
                    os.fsync(staged_fd)
                    staged = os.fstat(staged_fd)
                    if (
                        not stat.S_ISREG(staged.st_mode)
                        or staged.st_size != len(content)
                        or staged.st_nlink != 1
                    ):
                        raise AdoptionError("staged adoption identity/size mismatch")

                    if _pre_link_test_hook is not None:
                        _pre_link_test_hook()
                    validate_same_snapshot()
                    _assert_no_preserved_rollback(
                        parent_fd=parent_fd, name=name, parent_path=parent_path
                    )
                    try:
                        os.link(
                            temporary,
                            name,
                            src_dir_fd=parent_fd,
                            dst_dir_fd=parent_fd,
                            follow_symlinks=False,
                        )
                    except FileExistsError:
                        # A winner linked first.  It is never inspected, removed,
                        # or treated as a resumable adoption by this invocation.
                        raise FileExistsError(OUTPUT_RELATIVE)
                    linked = True
                    formal_io._fsync_directory(parent_fd)

                    os.unlink(temporary, dir_fd=parent_fd)
                    temporary_present = False
                    formal_io._fsync_directory(parent_fd)
                    if _post_link_test_hook is not None:
                        _post_link_test_hook()
                    validate_same_snapshot()

                    reachable = os.stat(
                        name, dir_fd=parent_fd, follow_symlinks=False
                    )
                    observed, opened = formal_io._read_direct_at(parent_fd, name)
                    if (
                        staged is None
                        or not _same_inode(reachable, staged)
                        or not _same_inode(opened, staged)
                        or reachable.st_nlink != 1
                        or opened.st_nlink != 1
                        or observed != content
                    ):
                        raise AdoptionError("published adoption identity/bytes drift")
                except BaseException as transaction_error:
                    if linked and staged is not None:
                        try:
                            _preserve_own_destination_rollback(
                                parent_fd=parent_fd,
                                name=name,
                                parent_path=parent_path,
                                staged=staged,
                                retained_fd=staged_fd,
                            )
                        except RollbackIncomplete as rollback_error:
                            pending_rollback = rollback_error
                            raise rollback_error from transaction_error
                    raise
                finally:
                    if staged_fd >= 0:
                        os.close(staged_fd)
                    if temporary_present:
                        try:
                            os.unlink(temporary, dir_fd=parent_fd)
                        except FileNotFoundError:
                            pass
                        try:
                            formal_io._fsync_directory(parent_fd)
                        except OSError:
                            if pending_rollback is None:
                                raise
                    if pending_rollback is not None:
                        _finalize_pending_rollback_identity(
                            pending_rollback,
                            parent_fd=parent_fd,
                            parent_path=parent_path,
                        )

                if staged is None or not linked:
                    raise AdoptionError("adoption was not linked")
                return {
                    "path": OUTPUT_RELATIVE,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                    "device": staged.st_dev,
                    "inode": staged.st_ino,
                    "resumed_exact_existing": False,
                }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--adopted-at", required=True)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--validate-existing", action="store_true")
    parser.add_argument("--validate-existing-live-pre-adoption", action="store_true")
    parser.add_argument("--ack-administrative-adoption-only", action="store_true")
    parser.add_argument("--ack-no-execution-authority", action="store_true")
    args = parser.parse_args()
    root = args.root.absolute()
    if args.validate_existing or args.validate_existing_live_pre_adoption:
        if args.write or (
            args.validate_existing and args.validate_existing_live_pre_adoption
        ):
            parser.error("existing-validation modes and --write are mutually exclusive")
        payload, _record, _content = _json_direct(
            root, OUTPUT_RELATIVE, label="formalization adoption"
        )
        if args.validate_existing_live_pre_adoption:
            digest = validate_adoption_live_pre_adoption(payload, root=root)
            mode = "VALIDATE_EXISTING_LIVE_PRE_ADOPTION"
        else:
            digest = validate_adoption_historical(payload, root=root)
            mode = "VALIDATE_EXISTING_HISTORICAL"
        print(json.dumps({"mode": mode, SELF_HASH_FIELD: digest}, indent=2, sort_keys=True))
        return 0
    if args.write and (
        not args.ack_administrative_adoption_only
        or not args.ack_no_execution_authority
    ):
        parser.error(
            "--write requires both administrative-only and no-execution acknowledgements"
        )
    try:
        payload = build_adoption(
            root=root,
            adopted_at=args.adopted_at,
            require_output_absent=True,
            ack_administrative_adoption_only=(
                args.ack_administrative_adoption_only
            ),
            ack_no_execution_authority=args.ack_no_execution_authority,
        )
    except AdoptionError as error:
        print(
            json.dumps(
                {
                    "mode": "READ_ONLY_BLOCKED" if not args.write else "FORMAL_WRITE_BLOCKED",
                    "path": OUTPUT_RELATIVE,
                    "status": "BLOCKED_AWAITING_EXACT_INCIDENT_AND_TWO_REVIEWS",
                    "reason": str(error),
                    "backend_replay_authorized": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    if args.write:
        publish_adoption_no_clobber(
            payload,
            root=root,
            ack_administrative_adoption_only=(
                args.ack_administrative_adoption_only
            ),
            ack_no_execution_authority=args.ack_no_execution_authority,
        )
        observed, _record, _content = _json_direct(
            root, OUTPUT_RELATIVE, label="published formalization adoption"
        )
        if observed != payload:
            raise AdoptionError("published adoption bytes changed after no-clobber commit")
    print(
        json.dumps(
            {
                "mode": "FORMAL_NO_CLOBBER_WRITE" if args.write else "READ_ONLY_PREVIEW",
                "path": OUTPUT_RELATIVE,
                "status": payload["status"],
                SELF_HASH_FIELD: payload[SELF_HASH_FIELD],
                "backend_replay_authorized": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
