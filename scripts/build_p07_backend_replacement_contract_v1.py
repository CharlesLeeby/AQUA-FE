#!/usr/bin/env python3
"""Freeze the outcome-blind P07 infrastructure-replacement contract.

The contract is intentionally independent of a particular execution lock.  A
future immutable replacement lock binds both this contract and the already
frozen backend execution lock.  Importing this module has no write side effect;
formal generation requires ``--write`` and is no-clobber.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Mapping, Sequence

try:
    from scripts import build_p07_backend_formalization_adoption_v1 as adoption
    from scripts import build_p07_backend_formalization_review_evidence_v1 as review_evidence
    from scripts import build_p07_backend_replay_queue_v1 as queue_builder
    from scripts import p07_g0_publisher_v1 as g0_publisher
    from scripts import p07_g0_governance_v1 as gov
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_backend_formalization_adoption_v1 as adoption  # type: ignore
    import build_p07_backend_formalization_review_evidence_v1 as review_evidence  # type: ignore
    import build_p07_backend_replay_queue_v1 as queue_builder  # type: ignore
    import p07_g0_publisher_v1 as g0_publisher  # type: ignore
    import p07_g0_governance_v1 as gov  # type: ignore


OUTPUT = queue_builder.P07 / "backend_replacement_contract_v1.json"
SCHEMA = "isj-p07-backend-replacement-contract-v1"
STATUS = "FROZEN_READY_FOR_INFRASTRUCTURE_REPLACEMENT_ALLOCATION"
LOCK_SCHEMA = "isj-p07-backend-infrastructure-replacement-lock-v1"
LOCK_STATUS = "FROZEN_PLANNED_INFRASTRUCTURE_REPLACEMENT"
INDEX_SCHEMA = "isj-p07-backend-replacement-allocation-v1"
INDEX_PATH = queue_builder.P07 / "backend_replacement_allocation_v1.csv"
LOCK_DIRECTORY = queue_builder.P07 / "backend_replacements"
GLOBAL_ALLOCATOR_FLOCK = "/tmp/aquafe_p07_backend_replacement_allocator_v1.lock"
SELF_HASH_FIELD = "replacement_contract_hash"
CONTRACT_KEYS = {
    "schema_version",
    "status",
    "frozen_at",
    "formalization_adoption",
    "formalization_review_evidence",
    "eligibility",
    "effective_row_policy",
    "replacement_lock_policy",
    "allocation_index_policy",
    "registry_policy",
    "job_policy",
    "allocator_policy",
    "artifacts",
    "trajectory_outcome_read_at_freeze",
    "outcome_boundary",
    SELF_HASH_FIELD,
}

ALLOWED_EFFECTIVE_ROW_OVERRIDES = (
    "run_id",
    "runner_tag",
    "expected_run_dir",
    "expected_attempt_dir",
)
ALLOWED_INFRASTRUCTURE_FAILURE_CODES = (
    "ROS_MASTER_CONFLICT",
    "FILE_NOT_FOUND",
    "DISK_FULL",
    "PERMISSION_DENIED",
    "HARDWARE_INTERRUPTION",
    "OPERATOR_INTERRUPTION",
    "SUPERVISOR_PROCESS_LOSS",
)
ALLOWED_FAILURE_PHASES = ("PRE_ADAPTER", "ADAPTER_RUNNING", "ADAPTER_RETURNED")

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ReplacementContractError(RuntimeError):
    """The replacement contract is missing, malformed, or drifted."""


def contract_hash(payload: Mapping[str, object]) -> str:
    clone = dict(payload)
    clone.pop(SELF_HASH_FIELD, None)
    return hashlib.sha256(
        queue_builder.canonical_json(clone).encode("utf-8")
    ).hexdigest()


def required_artifact_paths() -> tuple[Path, ...]:
    return (
        queue_builder.ROOT / "scripts/build_p07_backend_replacement_contract_v1.py",
        queue_builder.ROOT / "scripts/allocate_p07_backend_replacement_v1.py",
        queue_builder.ROOT / "scripts/tests/test_p07_backend_replacement_v1.py",
        queue_builder.ROOT / "scripts/run_p07_backend_replay_job_v1.py",
        queue_builder.ROOT / "scripts/p07_backend_replay_common_v1.py",
        queue_builder.ROOT / "scripts/p07_backend_formal_io_v1.py",
        queue_builder.ROOT / "scripts/p07_g0_governance_v1.py",
        queue_builder.ROOT / "scripts/p07_g0_publisher_v1.py",
        queue_builder.ROOT / "scripts/build_p07_backend_formalization_adoption_v1.py",
        queue_builder.ROOT / "scripts/tests/test_p07_backend_formalization_adoption_v1.py",
        queue_builder.ROOT / review_evidence.BUILDER_RELATIVE,
        queue_builder.ROOT / review_evidence.TEST_RELATIVE,
        queue_builder.ROOT / review_evidence.LEAF_TEST_RELATIVE,
        queue_builder.FAILURE_TAXONOMY,
    )


def build_contract_payload(
    *,
    frozen_at: str,
    artifacts: Sequence[Mapping[str, object]],
    formalization_adoption: Mapping[str, object],
    formalization_review_evidence: Mapping[str, object],
) -> dict[str, object]:
    queue_builder.allocation_stamp(frozen_at)
    payload: dict[str, object] = {
        "schema_version": SCHEMA,
        "status": STATUS,
        "frozen_at": frozen_at,
        "formalization_adoption": dict(formalization_adoption),
        "formalization_review_evidence": dict(formalization_review_evidence),
        "eligibility": {
            "failure_class": "INFRASTRUCTURE",
            "original_terminal_status": "FAILED",
            "registry_infrastructure_failure": "true",
            "failure_evidence_infrastructure_failure": True,
            "algorithmic_slot_consumed": False,
            "failure_evidence_sha256_required": True,
            "source_must_be_latest_authorized_attempt": True,
            "unknown_run_in_algorithmic_slot_forbidden": True,
            "completed_or_algorithmic_failure_slot_forbidden": True,
            "failure_evidence_schema": (
                "isj-p07-backend-infrastructure-failure-evidence-v2"
            ),
            "allowed_failure_codes": list(ALLOWED_INFRASTRUCTURE_FAILURE_CODES),
            "allowed_failure_phases": list(ALLOWED_FAILURE_PHASES),
            "phase_evidence_policy": {
                "PRE_ADAPTER": {
                    "adapter_result_required": False,
                    "attempt_intent_required": True,
                    "state_journal_required": True,
                    "replay_boundary_must_be_unreached": True,
                },
                "ADAPTER_RUNNING": {
                    "adapter_result_required": False,
                    "attempt_intent_required": True,
                    "state_journal_required": True,
                    "replay_boundary_must_be_unreached": True,
                },
                "ADAPTER_RETURNED": {
                    "adapter_result_required": True,
                    "attempt_intent_required": True,
                    "state_journal_required": True,
                    "precommit_and_final_output_manifests_required": True,
                },
            },
            "registry_chain": ["PLANNED", "RUNNING", "FAILED"],
            "registry_replay_evaluable": "false",
            "registry_replay_hard_failure": "false",
            "registry_algorithm_hard_failure": "false",
            "slot_consumption_boundary_crossed": False,
            "trajectory_outcome_read": False,
            "evaluation_invoked": False,
            "audit_artifact_created": False,
            "precommit_and_final_output_manifests_required": True,
        },
        "effective_row_policy": {
            "source": (
                "FROZEN_BACKEND_QUEUE_ROW_PLUS_IMMUTABLE_REPLACEMENT_LOCK"
            ),
            "allowed_overrides": list(ALLOWED_EFFECTIVE_ROW_OVERRIDES),
            "all_other_queue_fields_byte_exact": True,
            "runner_tag_suffix": "_attemptNN",
            "run_dir_suffix": "_attemptNN",
            "attempt_dir_suffix": "_attemptNN",
            "minimum_replacement_attempt_number": 2,
        },
        "replacement_lock_policy": {
            "schema_version": LOCK_SCHEMA,
            "status": LOCK_STATUS,
            "directory": queue_builder.display_path(LOCK_DIRECTORY),
            "self_hash_field": "replacement_lock_hash",
            "immutable_no_clobber": True,
            "single_use_via_untouched_planned_e00": True,
            "bind_execution_lock_hash": True,
            "bind_contract_hash": True,
            "bind_original_queue_row_hash": True,
            "bind_failure_evidence_hash": True,
            "bind_registry_planned_event_hash": True,
        },
        "allocation_index_policy": {
            "schema_version": INDEX_SCHEMA,
            "path": queue_builder.display_path(INDEX_PATH),
            "append_only": True,
            "attempt_numbers_strictly_increasing_per_queue_item": True,
            "replacement_lock_sha256_required": True,
            "event_hash_chain_required": True,
            "prior_prefix_snapshot_required": True,
        },
        "registry_policy": {
            "new_run_id_required": True,
            "unique_untouched_planned_e00_required": True,
            "replacement_for_is_immediately_failed_run_id": True,
            "algorithmic_slot_preserved": True,
            "new_run_target_required": True,
            "append_only": True,
        },
        "job_policy": {
            "entrypoint": "scripts/run_p07_backend_replay_job_v1.py",
            "replacement_flag": "--replacement-lock",
            "queue_index_preserved": True,
            "execution_lock_preserved": True,
            "exact_argv_frozen_in_replacement_lock": True,
        },
        "allocator_policy": {
            "global_flock_path": GLOBAL_ALLOCATOR_FLOCK,
            "preflight_is_read_only": True,
            "formal_apply_is_explicit": True,
            "idempotent_crash_recovery_requires_exact_content": True,
        },
        "artifacts": [dict(record) for record in artifacts],
        "trajectory_outcome_read_at_freeze": False,
        "outcome_boundary": (
            "INFRASTRUCTURE_ENVELOPE_ONLY_ALGORITHMIC_SLOT_UNCONSUMED"
        ),
    }
    payload[SELF_HASH_FIELD] = contract_hash(payload)
    return payload


def _validate_record(
    record: Mapping[str, object], *, root: Path, verify_file: bool
) -> Path:
    try:
        raw = str(record["path"])
        digest = str(record["sha256"])
        size = int(record["size_bytes"])
    except (KeyError, TypeError, ValueError) as error:
        raise ReplacementContractError("invalid contract artifact record") from error
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts or size < 0 or not _SHA256_RE.fullmatch(digest):
        raise ReplacementContractError(f"unsafe contract artifact record: {raw!r}")
    resolved = root.joinpath(*path.parts)
    if verify_file:
        try:
            observed = queue_builder.rooted_io.direct_file_record_bound_input_rooted(
                root, resolved, label="replacement contract artifact"
            )
        except (OSError, ValueError, queue_builder.rooted_io.gov.G0GovernanceError) as error:
            raise ReplacementContractError(
                f"missing or unsafe contract artifact: {raw}"
            ) from error
        if observed["size_bytes"] != size or observed["sha256"] != digest:
            raise ReplacementContractError(f"contract artifact drift: {raw}")
    return resolved


def validate_contract_payload(
    payload: Mapping[str, object], *, root: Path, verify_artifacts: bool = True
) -> None:
    if (
        set(payload) != CONTRACT_KEYS
        or payload.get("schema_version") != SCHEMA
        or payload.get("status") != STATUS
        or payload.get(SELF_HASH_FIELD) != contract_hash(payload)
        or payload.get("trajectory_outcome_read_at_freeze") is not False
    ):
        raise ReplacementContractError("replacement contract schema/status/hash mismatch")
    binding = payload.get("formalization_adoption")
    if (
        not isinstance(binding, dict)
        or set(binding) != adoption.ADOPTION_AUTHORITY_BINDING_KEYS
        or binding.get("path") != adoption.OUTPUT_RELATIVE
        or not _SHA256_RE.fullmatch(str(binding.get("sha256", "")))
        or not isinstance(binding.get("size_bytes"), int)
        or int(binding["size_bytes"]) <= 0
        or not _SHA256_RE.fullmatch(
            str(binding.get(adoption.SELF_HASH_FIELD, ""))
        )
    ):
        raise ReplacementContractError("replacement adoption binding shape mismatch")
    if verify_artifacts:
        try:
            adoption.validate_adoption_authority_binding(binding, root=root)
        except adoption.AdoptionError as error:
            raise ReplacementContractError(
                "replacement adoption authority drift"
            ) from error
    evidence_binding = payload.get("formalization_review_evidence")
    if (
        not isinstance(evidence_binding, dict)
        or set(evidence_binding) != review_evidence.AUTHORITY_BINDING_KEYS
        or evidence_binding.get("path") != review_evidence.OUTPUT_RELATIVE
        or not _SHA256_RE.fullmatch(str(evidence_binding.get("sha256", "")))
        or type(evidence_binding.get("size_bytes")) is not int
        or int(evidence_binding["size_bytes"]) <= 0
        or not _SHA256_RE.fullmatch(
            str(evidence_binding.get(review_evidence.SELF_HASH_FIELD, ""))
        )
    ):
        raise ReplacementContractError("replacement review-evidence binding shape mismatch")
    if verify_artifacts:
        try:
            review_evidence.validate_review_evidence_authority_binding(
                evidence_binding, root=root
            )
        except review_evidence.ReviewEvidenceError as error:
            raise ReplacementContractError(
                "replacement review-evidence authority drift"
            ) from error
    eligibility = payload.get("eligibility")
    if not isinstance(eligibility, dict) or any(
        eligibility.get(key) is not True
        for key in (
            "failure_evidence_sha256_required",
            "source_must_be_latest_authorized_attempt",
            "unknown_run_in_algorithmic_slot_forbidden",
            "completed_or_algorithmic_failure_slot_forbidden",
        )
    ):
        raise ReplacementContractError("replacement eligibility is incomplete")
    if (
        eligibility.get("failure_class") != "INFRASTRUCTURE"
        or eligibility.get("original_terminal_status") != "FAILED"
        or eligibility.get("registry_infrastructure_failure") != "true"
        or eligibility.get("failure_evidence_infrastructure_failure") is not True
        or eligibility.get("algorithmic_slot_consumed") is not False
        or eligibility.get("failure_evidence_schema")
        != "isj-p07-backend-infrastructure-failure-evidence-v2"
        or eligibility.get("allowed_failure_codes")
        != list(ALLOWED_INFRASTRUCTURE_FAILURE_CODES)
        or eligibility.get("allowed_failure_phases") != list(ALLOWED_FAILURE_PHASES)
        or eligibility.get("phase_evidence_policy")
        != {
            "PRE_ADAPTER": {
                "adapter_result_required": False,
                "attempt_intent_required": True,
                "state_journal_required": True,
                "replay_boundary_must_be_unreached": True,
            },
            "ADAPTER_RUNNING": {
                "adapter_result_required": False,
                "attempt_intent_required": True,
                "state_journal_required": True,
                "replay_boundary_must_be_unreached": True,
            },
            "ADAPTER_RETURNED": {
                "adapter_result_required": True,
                "attempt_intent_required": True,
                "state_journal_required": True,
                "precommit_and_final_output_manifests_required": True,
            },
        }
        or eligibility.get("registry_chain") != ["PLANNED", "RUNNING", "FAILED"]
        or eligibility.get("registry_replay_evaluable") != "false"
        or eligibility.get("registry_replay_hard_failure") != "false"
        or eligibility.get("registry_algorithm_hard_failure") != "false"
        or eligibility.get("slot_consumption_boundary_crossed") is not False
        or eligibility.get("trajectory_outcome_read") is not False
        or eligibility.get("evaluation_invoked") is not False
        or eligibility.get("audit_artifact_created") is not False
        or eligibility.get("precommit_and_final_output_manifests_required") is not True
    ):
        raise ReplacementContractError("replacement eligibility permits slot consumption")
    row_policy = payload.get("effective_row_policy")
    if (
        not isinstance(row_policy, dict)
        or row_policy.get("allowed_overrides")
        != list(ALLOWED_EFFECTIVE_ROW_OVERRIDES)
        or row_policy.get("all_other_queue_fields_byte_exact") is not True
        or int(row_policy.get("minimum_replacement_attempt_number", 0)) != 2
    ):
        raise ReplacementContractError("effective-row replacement policy drift")
    lock_policy = payload.get("replacement_lock_policy")
    if (
        not isinstance(lock_policy, dict)
        or lock_policy.get("schema_version") != LOCK_SCHEMA
        or lock_policy.get("status") != LOCK_STATUS
        or lock_policy.get("directory") != queue_builder.display_path(LOCK_DIRECTORY)
        or any(
            lock_policy.get(key) is not True
            for key in (
                "immutable_no_clobber",
                "single_use_via_untouched_planned_e00",
                "bind_execution_lock_hash",
                "bind_contract_hash",
                "bind_original_queue_row_hash",
                "bind_failure_evidence_hash",
                "bind_registry_planned_event_hash",
            )
        )
    ):
        raise ReplacementContractError("replacement-lock policy drift")
    index_policy = payload.get("allocation_index_policy")
    if (
        not isinstance(index_policy, dict)
        or index_policy.get("schema_version") != INDEX_SCHEMA
        or index_policy.get("path") != queue_builder.display_path(INDEX_PATH)
        or index_policy.get("append_only") is not True
        or index_policy.get("attempt_numbers_strictly_increasing_per_queue_item")
        is not True
        or index_policy.get("event_hash_chain_required") is not True
        or index_policy.get("prior_prefix_snapshot_required") is not True
    ):
        raise ReplacementContractError("replacement allocation-index policy drift")
    registry = payload.get("registry_policy")
    if not isinstance(registry, dict) or any(
        registry.get(key) is not True
        for key in (
            "new_run_id_required",
            "unique_untouched_planned_e00_required",
            "replacement_for_is_immediately_failed_run_id",
            "algorithmic_slot_preserved",
            "new_run_target_required",
            "append_only",
        )
    ):
        raise ReplacementContractError("replacement registry policy drift")
    job = payload.get("job_policy")
    if (
        not isinstance(job, dict)
        or job.get("entrypoint") != "scripts/run_p07_backend_replay_job_v1.py"
        or job.get("replacement_flag") != "--replacement-lock"
        or job.get("exact_argv_frozen_in_replacement_lock") is not True
    ):
        raise ReplacementContractError("replacement job policy drift")
    records = payload.get("artifacts")
    if not isinstance(records, list):
        raise ReplacementContractError("replacement contract lacks artifacts")
    observed: set[Path] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ReplacementContractError("replacement artifact is not an object")
        path = _validate_record(record, root=root, verify_file=verify_artifacts)
        if path in observed:
            raise ReplacementContractError("duplicate replacement contract artifact")
        observed.add(path)
    required = set(required_artifact_paths())
    if observed != required:
        missing = sorted(queue_builder.display_path(path) for path in required - observed)
        extra = sorted(queue_builder.display_path(path) for path in observed - required)
        raise ReplacementContractError(
            f"replacement contract artifact set mismatch missing={missing} extra={extra}"
        )


def build_live_contract(
    *, frozen_at: str, require_output_absent: bool = True
) -> dict[str, object]:
    if require_output_absent and queue_builder.formal_io.destination_exists(
        queue_builder.ROOT, queue_builder.display_path(OUTPUT)
    ):
        raise FileExistsError(OUTPUT)
    paths = required_artifact_paths()
    try:
        artifacts = [queue_builder.file_record(path).as_dict() for path in paths]
    except (OSError, ValueError, queue_builder.rooted_io.gov.G0GovernanceError) as error:
        raise ReplacementContractError(
            "required replacement artifact is missing or unsafe"
        ) from error
    payload = build_contract_payload(
        frozen_at=frozen_at,
        artifacts=artifacts,
        formalization_adoption=adoption.adoption_authority_binding(
            root=queue_builder.ROOT
        ),
        formalization_review_evidence=(
            review_evidence.review_evidence_authority_binding(
                root=queue_builder.ROOT
            )
        ),
    )
    validate_contract_payload(payload, root=queue_builder.ROOT)
    return payload


def write_no_clobber(path: Path, payload: Mapping[str, object]) -> None:
    frozen_at = payload.get("frozen_at")
    artifacts = payload.get("artifacts")
    adoption_binding = payload.get("formalization_adoption")
    evidence_binding = payload.get("formalization_review_evidence")
    if (
        not isinstance(frozen_at, str)
        or not isinstance(artifacts, list)
        or not isinstance(adoption_binding, Mapping)
        or not isinstance(evidence_binding, Mapping)
    ):
        raise ReplacementContractError(
            "replacement publication payload lacks transactional bindings"
        )

    def validate_fresh_rebuild() -> None:
        rebuilt = build_live_contract(
            frozen_at=frozen_at, require_output_absent=False
        )
        if queue_builder.formal_io.json_bytes(rebuilt) != (
            queue_builder.formal_io.json_bytes(payload)
        ):
            raise ReplacementContractError(
                "replacement publication differs from fresh live rebuild"
            )

    try:
        g0_publisher.publish_json_transactional_rooted(
            queue_builder.ROOT,
            path,
            payload,
            guard_records=[*artifacts, adoption_binding, evidence_binding],
            validate=validate_fresh_rebuild,
        )
    except (queue_builder.formal_io.FormalIOError, gov.G0GovernanceError) as error:
        raise ReplacementContractError(
            "replacement transactional publication failed"
        ) from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--frozen-at", required=True)
    args = parser.parse_args()
    payload = build_live_contract(frozen_at=args.frozen_at)
    if args.preflight_only:
        print(
            json.dumps(
                {
                    "status": "READY",
                    "schema_version": payload["schema_version"],
                    "replacement_contract_hash": payload[SELF_HASH_FIELD],
                    "trajectory_outcome_read_at_freeze": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if not args.write:
        parser.error("refusing formal replacement-contract generation without --write")
    write_no_clobber(OUTPUT, payload)
    print(
        "P07_BACKEND_REPLACEMENT_CONTRACT_FROZEN "
        f"hash={payload[SELF_HASH_FIELD]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
