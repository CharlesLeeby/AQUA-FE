#!/usr/bin/python3
"""Fail-closed schedule state for fair-stability runtime-exclusive v10."""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timedelta
from pathlib import Path
import re
from typing import Any, Mapping

from fair_stability_runtime_resource_monitor_v10 import (
    PRESTART_RESOURCE_GATE_FIELDS,
    PRESTART_RESOURCE_GATE_SCHEMA,
    prestart_resource_gate_contract_valid,
)


SCHEDULE_SHA256 = "8fdb07f404bc4a24a3866dc1acd6cf8a20b9c960b84d6a9e430299852bc655e8"
EXPERIMENT_ID = "fair-stability-positive-roster-openloop-runtimeexcl-v10"
V9_NON_IMPORT_CLAIM_KEYS = frozenset(
    {
        "v9_results_imported",
        "v9_runtime_namespace_read",
        "v9_attempts_reused",
        "v9_cache_reused",
    }
)


def valid_v9_non_import_claims(value: object) -> bool:
    return bool(
        isinstance(value, Mapping)
        and all(value.get(key) is False for key in V9_NON_IMPORT_CLAIM_KEYS)
    )


ROS_PYTHONPATH = "/opt/ros/noetic/lib/python3/dist-packages"
FIXED_SERVICE_ENVIRONMENT = {
    "HOME": "/home/ma",
    "USER": "ma",
    "LOGNAME": "ma",
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "PYTHONPATH": ROS_PYTHONPATH,
    "PYTHONNOUSERSITE": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
}
CONTROL_PLANE_ENVIRONMENT = {
    "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
    "XDG_RUNTIME_DIR": "/run/user/1000",
}
TERMINAL_STATUSES = {"SUCCESS", "PARTIAL_NON_SUCCESS", "ALGORITHM_FAILURE"}
CONTROLLER_DISPATCH_EXECUTION_SCHEMA = (
    "aqua-fe-fair-stability-controller-dispatch-execution-v10"
)
NO_START_PROVENANCE_SCHEMA = (
    "aqua-fe-fair-stability-systemd-no-start-provenance-v10"
)
NO_START_OUTCOMES = {
    "RESOURCE_BLOCKED_NO_START",
    "PRESTART_DISPATCH_BLOCKED_NO_ESTIMATOR_START",
}
TERMINAL_SYSTEMD_OUTCOME = "TERMINAL_RESULT_PENDING_SYSTEMD_ADOPTION"
PIPELINE_SYSTEMD_OUTCOME = (
    "PIPELINE_INVALID_FAIL_STOP_MANUAL_REVIEW_ZERO_RETRY"
)
SYSTEMD_ADOPTION_CLAIM_SCHEMA = (
    "aqua-fe-fair-stability-systemd-adoption-claim-v10"
)
SYSTEMD_ADOPTION_SCHEMA = "aqua-fe-fair-stability-systemd-adoption-v10"
RESUBMIT_AUTHORIZATION_SCHEMA = (
    "aqua-fe-fair-stability-systemd-resubmit-authorization-v10"
)
RESUBMIT_AUTHORIZATION_CONSUMPTION_SCHEMA = (
    "aqua-fe-fair-stability-systemd-resubmit-authorization-consumption-v10"
)
RESUBMIT_AUTHORIZATION_CONSUMPTION_FIELDS = frozenset(
    {
        "schema_version",
        "experiment_id",
        "consumed_at_utc",
        "resubmit_authorization",
        "prior_submission_directory",
        "prior_submission_index",
        "prior_submission_claim",
        "new_submission_directory",
        "new_submission_index",
        "new_submission_claim",
        "new_unit",
        "planned_ordinal",
        "attempt_index",
        "attempt_root",
    }
)
RESUBMIT_AUTHORIZATION_FIELDS = frozenset(
    {
        "schema_version",
        "experiment_id",
        "authorized_at_utc",
        "authorization_command",
        "planned_ordinal",
        "attempt_index",
        "attempt_root",
        "prior_submission_index",
        "authorized_submission_index",
        "prior_unit",
        "prior_invocation_id",
        "prior_submission_claim",
        "prior_systemd_start_receipt",
        "prior_systemd_adoption_receipt",
        "ordinal_state_authorized",
        "stopped_unit_observation_before_reset",
        "stopped_unit_contract_before_reset",
        "reset_failed",
        "stopped_unit_observation_after_reset",
        "stopped_unit_contract_after_reset",
        "resource_check",
    }
)
RESUBMIT_RESET_FIELDS = frozenset(
    {
        "sequence_index",
        "started_at_utc",
        "completed_at_utc",
        "argv",
        "control_plane_environment",
        "returncode",
        "stdout",
        "stderr",
    }
)
RESUBMIT_RESOURCE_CHECK_FIELDS = frozenset(
    {
        "sequence_index",
        "started_at_utc",
        "completed_at_utc",
        "argv",
        "environment",
        "returncode",
        "stdout",
        "stderr",
        "ready",
        "resource_gate",
        "runner_result",
    }
)
MAX_REPLACEMENT_ATTEMPTS_PER_CELL = 0
MAX_ATTEMPTS_PER_CELL = 1 + MAX_REPLACEMENT_ATTEMPTS_PER_CELL
AUTOMATIC_RETRY_PIPELINE_FAILURES = frozenset()
ALL_ARMS = {
    "learned_klt_vins", "pure_klt_vins", "hfnet_openloop_675", "hfnet_openloop_350"
}
PIPELINE_EVIDENCE_NAMES = (
    "attempt_manifest.json", "ordinal_dispatch_claim.json", "start_claim.json",
    "run_result.json", "launch_receipt.json", "child_start_receipt.txt",
    "child_lifecycle.txt", "headless.stdout.log", "headless.stderr.log",
    "supervisor.stdout.log", "supervisor.stderr.log", "vins.log",
    "runtime_resource_monitor.json",
    "zero_kf_post_shutdown_watchdog.json",
)


class OrdinalError(RuntimeError):
    pass


def valid_ready_prestart_resource_gate_v10(value: object) -> bool:
    """Recognize the complete, internally consistent v10 ready gate."""
    return prestart_resource_gate_contract_valid(
        value, expected_ready=True
    )


def valid_prestart_resource_gate_v10(
    value: object,
    *,
    expected_ready: bool,
    expected_port: object,
) -> bool:
    """Shared strict gate entry point for controller and receipt validators."""

    return prestart_resource_gate_contract_valid(
        value,
        expected_ready=expected_ready,
        expected_port=expected_port,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise OrdinalError(f"IDENTITY_FILE_INVALID:{path}")
    return {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)}


def identity_matches(record: object, path: Path) -> bool:
    """Require the complete recorded identity, including its fixed path."""
    return isinstance(record, Mapping) and strict_json_equal(record, identity(path))


def parse_key_value_receipt_evidence(path: Path) -> tuple[dict[str, str], list[str]]:
    """Re-read a runner key/value receipt using the frozen VINS parser rules."""
    values: dict[str, str] = {}
    errors: list[str] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if "=" not in line:
            errors.append(f"ROW_{line_number}_FORMAT")
            continue
        key, value = line.split("=", 1)
        if key in values:
            errors.append(f"ROW_{line_number}_DUPLICATE_KEY")
            continue
        values[key] = value
    return values, errors


def control_boundary(experiment_root: Path) -> dict[str, dict[str, object]]:
    """Bind receipts and dispatches to this controller and this frozen control set."""
    common = Path(__file__).resolve()
    controller = common.parent / "run_fair_stability_next_v10.py"
    supervisor = common.parent / "run_fair_stability_systemd_supervisor_v10.py"
    freeze_path = (
        experiment_root / "vins_dev_nativeq_schedfix_runtimeexcl_v10" / "backend_freeze.json"
    )
    require_no_symlink_components(freeze_path, experiment_root)
    freeze_identity = identity(freeze_path)
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    if freeze.get("status") != "FROZEN_BEFORE_NEW_VINS_REPLAY":
        raise OrdinalError("CONTROL_FREEZE_STATUS_INVALID")
    claims = freeze.get("claims")
    if not isinstance(claims, Mapping) or any(
        claims.get(f"v{version}_results_imported") is not False
        for version in range(1, 10)
    ) or not valid_v9_non_import_claims(claims):
        raise OrdinalError("CONTROL_FREEZE_PRIOR_RESULTS_IMPORT_CLAIM_INVALID")
    controls = freeze.get("controls")
    if not isinstance(controls, Mapping):
        raise OrdinalError("CONTROL_FREEZE_CONTROLS_MISSING")
    for path in (common, controller, supervisor):
        if not identity_matches(controls.get(path.name), path):
            raise OrdinalError(f"CONTROL_FREEZE_IDENTITY_DRIFT:{path.name}")
    return {
        "common": identity(common),
        "controller": identity(controller),
        "supervisor": identity(supervisor),
        "control_freeze": freeze_identity,
        "attempt_matrix_freeze": identity(experiment_root / "attempt_matrix_freeze_v10.json"),
    }


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def strict_json_equal(observed: object, expected: object) -> bool:
    """Compare both JSON values and JSON scalar types (so true is not 1)."""
    try:
        return canonical_json(observed) == canonical_json(expected)
    except (TypeError, ValueError):
        return False


SYSTEMD_CHAIN_FILES = {
    "submission_claim": (
        "submission_claim.json",
        "aqua-fe-fair-stability-systemd-submission-v10",
    ),
    "submission_receipt": (
        "submission_receipt.json",
        "aqua-fe-fair-stability-systemd-submit-receipt-v10",
    ),
    "systemd_start_receipt": (
        "systemd_start_receipt.json",
        "aqua-fe-fair-stability-systemd-start-receipt-v10",
    ),
    "systemd_execution_receipt": (
        "systemd_execution_receipt.json",
        "aqua-fe-fair-stability-systemd-execution-v10",
    ),
    "systemd_terminal_receipt": (
        "systemd_terminal_receipt.json",
        "aqua-fe-fair-stability-systemd-terminal-v10",
    ),
}


def validate_attempt_start_systemd_binding(
    experiment_root: Path,
    start_path: Path,
    expected_systemd_start_receipt: object,
) -> dict[str, Any]:
    """Bind an attempt's algorithm start claim to the same adopted service start."""
    start = json.loads(start_path.read_text(encoding="utf-8"))
    if not isinstance(start, dict):
        raise OrdinalError(f"ATTEMPT_SYSTEMD_START_CHAIN_MISMATCH:{start_path}")
    recorded = start.get("systemd_start_receipt")
    if (
        not isinstance(recorded, Mapping)
        or not strict_json_equal(recorded, expected_systemd_start_receipt)
    ):
        raise OrdinalError(f"ATTEMPT_SYSTEMD_START_CHAIN_MISMATCH:{start_path}")
    receipt_path = Path(str(recorded.get("path", "")))
    require_no_symlink_components(receipt_path, experiment_root)
    try:
        receipt_path.relative_to(experiment_root / "systemd_supervision")
    except ValueError as error:
        raise OrdinalError(
            f"ATTEMPT_SYSTEMD_START_OUTSIDE_SUPERVISION_ROOT:{receipt_path}"
        ) from error
    if not identity_matches(recorded, receipt_path):
        raise OrdinalError(f"ATTEMPT_SYSTEMD_START_IDENTITY_DRIFT:{receipt_path}")
    value = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or value.get("schema_version")
        != "aqua-fe-fair-stability-systemd-start-receipt-v10"
        or value.get("experiment_id") != EXPERIMENT_ID
    ):
        raise OrdinalError(f"ATTEMPT_SYSTEMD_START_HEADER_INVALID:{receipt_path}")
    return value


def _validate_pipeline_adjudication_submission(
    experiment_root: Path,
    submission_directory: Path,
    claim: Mapping[str, Any],
    execution: Mapping[str, Any],
    controller_result: Mapping[str, Any],
    attempt_root_path: Path,
    result: Mapping[str, Any],
) -> None:
    """V10 has one attempt per coordinate; pipeline adjudication is disabled."""
    raise OrdinalError(
        "PIPELINE_ADJUDICATION_DISABLED_ZERO_REPLACEMENT_V10:"
        f"{submission_directory}"
    )

    # Retained below as unreachable historical validation logic so older v10
    # receipts remain diagnosable, but no such transition can be accepted.
    pre_state = claim.get("ordinal_state_before_submit")
    execution_state = execution.get("ordinal_state_after_controller")
    next_value = controller_result.get("next")
    if (
        not isinstance(pre_state, Mapping)
        or pre_state.get("state") != "PIPELINE_INVALID_UNADJUDICATED"
        or pre_state.get("attempt_root") != str(attempt_root_path)
        or not strict_json_equal(pre_state.get("result"), result)
        or result.get("status") != "PIPELINE_INVALID"
        or execution.get("controller_returncode") != 0
        or controller_result.get("outcome")
        != "PIPELINE_INVALID_ADJUDICATED_REPLENISHMENT_PREPARED"
        or "dispatch_execution" in controller_result
        or "runner_returncode" in controller_result
        or not isinstance(next_value, Mapping)
        or next_value.get("state") != "READY"
        or not strict_json_equal(execution_state, next_value)
        or type(pre_state.get("attempt_index")) is not int
        or next_value.get("attempt_index") != int(pre_state["attempt_index"]) + 1
    ):
        raise OrdinalError(
            f"SYSTEMD_CHAIN_PIPELINE_ADJUDICATION_TRANSITION_INVALID:"
            f"{submission_directory}"
        )

    invalid_path = attempt_root_path / "pipeline_invalid_receipt.json"
    require_no_symlink_components(invalid_path, experiment_root)
    if invalid_path.is_symlink() or not invalid_path.is_file():
        raise OrdinalError(
            f"SYSTEMD_CHAIN_PIPELINE_ADJUDICATION_RECEIPT_MISSING:{invalid_path}"
        )
    try:
        invalid = json.loads(invalid_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OrdinalError(
            f"SYSTEMD_CHAIN_PIPELINE_ADJUDICATION_RECEIPT_INVALID:{invalid_path}"
        ) from error
    if (
        not isinstance(invalid, dict)
        or invalid.get("schema_version")
        != "aqua-fe-fair-stability-pipeline-invalid-adjudication-v10"
        or invalid.get("experiment_id") != EXPERIMENT_ID
        or invalid.get("accepted_as_external_pipeline_fault") is not True
        or not identity_matches(invalid.get("run_result"), attempt_root_path / "run_result.json")
        or not strict_json_equal(controller_result.get("invalid_receipt"), invalid)
    ):
        raise OrdinalError(
            f"SYSTEMD_CHAIN_PIPELINE_ADJUDICATION_RECEIPT_DRIFT:{invalid_path}"
        )

    prior_adoption_record = invalid.get("systemd_adoption_receipt")
    if not isinstance(prior_adoption_record, Mapping):
        raise OrdinalError(
            f"SYSTEMD_CHAIN_PRIOR_ADOPTION_IDENTITY_MISSING:{invalid_path}"
        )
    prior_adoption_path = Path(str(prior_adoption_record.get("path", "")))
    require_no_symlink_components(prior_adoption_path, experiment_root)
    try:
        prior_adoption_path.relative_to(
            experiment_root / "systemd_supervision"
        )
    except ValueError as error:
        raise OrdinalError(
            f"SYSTEMD_CHAIN_PRIOR_ADOPTION_OUTSIDE_ROOT:{prior_adoption_path}"
        ) from error
    if (
        prior_adoption_path.parent == submission_directory
        or not identity_matches(prior_adoption_record, prior_adoption_path)
    ):
        raise OrdinalError(
            f"SYSTEMD_CHAIN_PRIOR_ADOPTION_IDENTITY_DRIFT:{prior_adoption_path}"
        )
    try:
        prior_adoption = json.loads(
            prior_adoption_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        raise OrdinalError(
            f"SYSTEMD_CHAIN_PRIOR_ADOPTION_INVALID:{prior_adoption_path}"
        ) from error
    if not isinstance(prior_adoption, dict):
        raise OrdinalError(
            f"SYSTEMD_CHAIN_PRIOR_ADOPTION_OBJECT_REQUIRED:{prior_adoption_path}"
        )
    prior_records = {
        key: prior_adoption.get(key) for key in SYSTEMD_CHAIN_FILES
    }
    prior_claim_path = prior_adoption_path.parent / "submission_claim.json"
    if not identity_matches(
        prior_records.get("submission_claim"), prior_claim_path
    ):
        raise OrdinalError(
            f"SYSTEMD_CHAIN_PRIOR_SUBMISSION_CLAIM_DRIFT:{prior_claim_path}"
        )
    try:
        prior_claim_preview = json.loads(
            prior_claim_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        raise OrdinalError(
            f"SYSTEMD_CHAIN_PRIOR_SUBMISSION_CLAIM_INVALID:{prior_claim_path}"
        ) from error
    prior_pre_state = (
        prior_claim_preview.get("ordinal_state_before_submit")
        if isinstance(prior_claim_preview, Mapping)
        else None
    )
    if (
        not isinstance(prior_pre_state, Mapping)
        or prior_pre_state.get("state") not in {"READY", "NEEDS_PREPARATION"}
        or prior_claim_preview.get("attempt_root") != str(attempt_root_path)
    ):
        raise OrdinalError(
            f"SYSTEMD_CHAIN_PRIOR_SUBMISSION_NOT_ORIGINAL_DISPATCH:"
            f"{prior_claim_path}"
        )
    prior_chain = validate_systemd_chain(
        experiment_root, prior_records, prior_adoption_path.parent
    )
    prior_execution = prior_chain["systemd_execution_receipt"]
    prior_controller_result = prior_execution.get("controller_result")
    prior_claim = prior_chain["submission_claim"]
    prior_adoption_claim_record = prior_adoption.get(
        "systemd_adoption_claim"
    )
    if not isinstance(prior_adoption_claim_record, Mapping):
        raise OrdinalError(
            f"SYSTEMD_CHAIN_PRIOR_ADOPTION_CLAIM_MISSING:{prior_adoption_path}"
        )
    prior_adoption_claim_path = Path(
        str(prior_adoption_claim_record.get("path", ""))
    )
    require_no_symlink_components(prior_adoption_claim_path, experiment_root)
    if (
        prior_adoption_claim_path.parent != prior_adoption_path.parent
        or not identity_matches(
            prior_adoption_claim_record, prior_adoption_claim_path
        )
    ):
        raise OrdinalError(
            f"SYSTEMD_CHAIN_PRIOR_ADOPTION_CLAIM_DRIFT:"
            f"{prior_adoption_claim_path}"
        )
    try:
        prior_adoption_claim = json.loads(
            prior_adoption_claim_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        raise OrdinalError(
            f"SYSTEMD_CHAIN_PRIOR_ADOPTION_CLAIM_INVALID:"
            f"{prior_adoption_claim_path}"
        ) from error
    start_path = attempt_root_path / "start_claim.json"
    if (
        not isinstance(prior_controller_result, Mapping)
        or prior_controller_result.get("outcome")
        != "PIPELINE_INVALID_REQUIRES_ADJUDICATION"
        or prior_execution.get("controller_returncode") != 0
        or prior_adoption.get("schema_version")
        != "aqua-fe-fair-stability-systemd-adoption-v10"
        or prior_adoption.get("experiment_id") != EXPERIMENT_ID
        or prior_adoption.get("ordinal_terminal_receipt") is not None
        or prior_adoption.get("unit") != prior_claim.get("unit")
        or prior_adoption.get("controller_returncode") != 0
        or prior_adoption.get("controller_outcome")
        != "PIPELINE_INVALID_REQUIRES_ADJUDICATION"
        or not isinstance(prior_adoption_claim, dict)
        or prior_adoption_claim.get("schema_version")
        != "aqua-fe-fair-stability-systemd-adoption-claim-v10"
        or prior_adoption_claim.get("experiment_id") != EXPERIMENT_ID
        or prior_adoption_claim.get("controller_returncode") != 0
        or prior_adoption_claim.get("controller_outcome")
        != "PIPELINE_INVALID_REQUIRES_ADJUDICATION"
        or any(
            not strict_json_equal(prior_adoption.get(key), record)
            or not strict_json_equal(prior_adoption_claim.get(key), record)
            for key, record in prior_records.items()
        )
    ):
        raise OrdinalError(
            f"SYSTEMD_CHAIN_PRIOR_PIPELINE_ADOPTION_DRIFT:{prior_adoption_path}"
        )
    validate_attempt_start_systemd_binding(
        experiment_root,
        start_path,
        prior_adoption.get("systemd_start_receipt"),
    )


def _validate_recorded_absence(
    record: object,
    expected_path: Path,
    label: str,
) -> None:
    expected = {
        "path": str(expected_path),
        "exists": False,
        "lexists": False,
        "is_regular_file": False,
        "is_symlink": False,
    }
    if not strict_json_equal(record, expected):
        raise OrdinalError(f"SYSTEMD_NO_START_ABSENCE_DRIFT:{label}")


_SYSTEMD_UNIT_COORDINATE = re.compile(
    r"aqua-fe-fair-stability-v10-o(?P<ordinal>[0-9]{3})-"
    r"a(?P<attempt>[0-9]{3})-s(?P<submission>[0-9]{3})-"
    r"(?P<nonce>[a-z0-9]+)\.service"
)
_RESUBMIT_AUTHORIZATION_CONSUMPTION_NAME = re.compile(
    r"resubmit_authorization_consumption_for_submission_([0-9]{3})\.json"
)


def resubmit_authorization_consumption_path(
    prior_directory: Path, new_submission_index: int
) -> Path:
    return (
        prior_directory
        / (
            "resubmit_authorization_consumption_for_submission_"
            f"{new_submission_index:03d}.json"
        )
    )


def _load_systemd_json(
    experiment_root: Path,
    path: Path,
    schema: str,
) -> dict[str, Any]:
    require_no_symlink_components(path, experiment_root)
    if path.is_symlink() or not path.is_file():
        raise OrdinalError(f"SYSTEMD_JSON_REGULAR_FILE_REQUIRED:{path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OrdinalError(f"SYSTEMD_JSON_INVALID:{path}") from error
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != schema
        or value.get("experiment_id") != EXPERIMENT_ID
    ):
        raise OrdinalError(f"SYSTEMD_JSON_SCHEMA_INVALID:{path}")
    return value


def _utc_evidence_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.utcoffset().total_seconds() != 0
    ):
        return None
    return parsed


def validate_resubmit_authorization_consumption(
    experiment_root: Path,
    prior_directory: Path,
    new_directory: Path,
    new_submission_index: int,
) -> dict[str, Any]:
    """Bind one durable authorization consumption to its exact new claim."""

    if type(new_submission_index) is not int or new_submission_index < 2:
        raise OrdinalError("SYSTEMD_RESUBMIT_CONSUMPTION_INDEX_INVALID")
    expected_new_directory = (
        prior_directory.parent / f"submission_{new_submission_index:03d}"
    )
    prior_claim_path = prior_directory / "submission_claim.json"
    new_claim_path = new_directory / "submission_claim.json"
    authorization_path = (
        prior_directory
        / (
            "resubmit_authorization_for_submission_"
            f"{new_submission_index:03d}.json"
        )
    )
    consumption_path = resubmit_authorization_consumption_path(
        prior_directory, new_submission_index
    )
    prior_claim = _load_systemd_json(
        experiment_root,
        prior_claim_path,
        SYSTEMD_CHAIN_FILES["submission_claim"][1],
    )
    new_claim = _load_systemd_json(
        experiment_root,
        new_claim_path,
        SYSTEMD_CHAIN_FILES["submission_claim"][1],
    )
    authorization = _load_systemd_json(
        experiment_root,
        authorization_path,
        RESUBMIT_AUTHORIZATION_SCHEMA,
    )
    consumption = _load_systemd_json(
        experiment_root,
        consumption_path,
        RESUBMIT_AUTHORIZATION_CONSUMPTION_SCHEMA,
    )
    try:
        consumption_bytes = consumption_path.read_bytes()
    except OSError as error:
        raise OrdinalError(
            f"SYSTEMD_RESUBMIT_CONSUMPTION_READ_FAILED:{consumption_path}"
        ) from error
    if consumption_bytes != canonical_json(consumption):
        raise OrdinalError(
            f"SYSTEMD_RESUBMIT_CONSUMPTION_CANONICAL_BYTES_INVALID:"
            f"{consumption_path}"
        )
    authorized_at = _utc_evidence_datetime(
        authorization.get("authorized_at_utc")
    )
    claim_created_at = _utc_evidence_datetime(new_claim.get("created_at_utc"))
    consumed_at = _utc_evidence_datetime(consumption.get("consumed_at_utc"))
    unit = new_claim.get("unit")
    unit_match = (
        _SYSTEMD_UNIT_COORDINATE.fullmatch(unit)
        if isinstance(unit, str)
        else None
    )
    if (
        new_directory != expected_new_directory
        or set(consumption) != RESUBMIT_AUTHORIZATION_CONSUMPTION_FIELDS
        or set(authorization) != RESUBMIT_AUTHORIZATION_FIELDS
        or authorized_at is None
        or claim_created_at is None
        or consumed_at is None
        or consumed_at < authorized_at
        or consumed_at < claim_created_at
        or consumption.get("prior_submission_directory")
        != str(prior_directory)
        or type(consumption.get("prior_submission_index")) is not int
        or consumption.get("prior_submission_index")
        != new_submission_index - 1
        or not identity_matches(
            consumption.get("prior_submission_claim"), prior_claim_path
        )
        or consumption.get("new_submission_directory") != str(new_directory)
        or type(consumption.get("new_submission_index")) is not int
        or consumption.get("new_submission_index") != new_submission_index
        or not identity_matches(
            consumption.get("new_submission_claim"), new_claim_path
        )
        or not identity_matches(
            consumption.get("resubmit_authorization"), authorization_path
        )
        or consumption.get("new_unit") != unit
        or type(consumption.get("planned_ordinal")) is not int
        or consumption.get("planned_ordinal")
        != new_claim.get("planned_ordinal")
        or consumption.get("planned_ordinal")
        != prior_claim.get("planned_ordinal")
        or consumption.get("planned_ordinal")
        != authorization.get("planned_ordinal")
        or type(consumption.get("attempt_index")) is not int
        or consumption.get("attempt_index") != 1
        or consumption.get("attempt_index") != new_claim.get("attempt_index")
        or consumption.get("attempt_index")
        != prior_claim.get("attempt_index")
        or consumption.get("attempt_index")
        != authorization.get("attempt_index")
        or consumption.get("attempt_root") != new_claim.get("attempt_root")
        or consumption.get("attempt_root") != prior_claim.get("attempt_root")
        or consumption.get("attempt_root")
        != authorization.get("attempt_root")
        or prior_claim.get("submission_index") != new_submission_index - 1
        or new_claim.get("submission_index") != new_submission_index
        or new_claim.get("submission_directory") != str(new_directory)
        or authorization.get("prior_submission_index")
        != new_submission_index - 1
        or authorization.get("authorized_submission_index")
        != new_submission_index
        or not identity_matches(
            authorization.get("prior_submission_claim"), prior_claim_path
        )
        or not identity_matches(
            new_claim.get("resubmit_authorization"), authorization_path
        )
        or not strict_json_equal(
            new_claim.get("ordinal_state_before_submit"),
            authorization.get("ordinal_state_authorized"),
        )
        or unit_match is None
        or int(unit_match.group("ordinal"))
        != consumption.get("planned_ordinal")
        or int(unit_match.group("attempt"))
        != consumption.get("attempt_index")
        or int(unit_match.group("submission")) != new_submission_index
    ):
        raise OrdinalError(
            f"SYSTEMD_RESUBMIT_CONSUMPTION_BINDING_INVALID:"
            f"{consumption_path}"
        )
    return consumption


def _systemd_duration_microseconds(value: object) -> int | None:
    match = re.fullmatch(
        r"([0-9]+(?:\.[0-9]+)?)(us|ms|s|min|h)", str(value)
    )
    if match is None:
        return None
    factors = {
        "us": 1,
        "ms": 1_000,
        "s": 1_000_000,
        "min": 60_000_000,
        "h": 3_600_000_000,
    }
    return int(float(match.group(1)) * factors[match.group(2)])


def _recorded_stopped_unit_contract(
    unit: str,
    observation: object,
    invocation_id: str,
    *,
    after_reset: bool,
) -> dict[str, object] | None:
    if not isinstance(observation, Mapping):
        return None
    properties = observation.get("properties")
    if (
        type(observation.get("returncode")) is not int
        or observation.get("returncode") != 0
        or not isinstance(properties, Mapping)
        or _utc_evidence_datetime(observation.get("queried_at_utc")) is None
    ):
        return None
    try:
        main_pid = int(str(properties.get("MainPID", "0")) or "0")
    except ValueError:
        return None
    if (
        after_reset
        and properties.get("Id") == unit
        and properties.get("LoadState") in {"not-found", "unloaded"}
        and properties.get("ActiveState") in {"inactive", None, ""}
        and main_pid == 0
        and str(properties.get("InvocationID", "")) == ""
    ):
        return {
            "unit": unit,
            "unloaded_after_reset": True,
            "main_pid": 0,
            "properties": dict(properties),
        }
    expected = {
        "Id": unit,
        "LoadState": "loaded",
        "Type": "exec",
        "KillMode": "control-group",
        "SendSIGKILL": "yes",
        "NRestarts": "0",
        "Transient": "yes",
        "RemainAfterExit": "no",
        "Restart": "no",
        "UMask": "0077",
    }
    if (
        any(properties.get(key) != expected_value for key, expected_value in expected.items())
        or _systemd_duration_microseconds(properties.get("RuntimeMaxUSec"))
        != 2400 * 1_000_000
        or _systemd_duration_microseconds(properties.get("TimeoutStopUSec"))
        != 120 * 1_000_000
        or str(properties.get("KillSignal", "")) not in {"15", "SIGTERM"}
        or str(properties.get("InvocationID", "")) != invocation_id
        or main_pid != 0
        or properties.get("ActiveState")
        not in ({"inactive"} if after_reset else {"inactive", "failed"})
    ):
        return None
    return {
        "unit": unit,
        "invocation_id": invocation_id,
        "main_pid": 0,
        "control_group": str(properties.get("ControlGroup", "")),
        "properties": dict(properties),
    }


def _runner_check_argv_from_authorized_state(
    state: object,
) -> list[str] | None:
    if not isinstance(state, Mapping):
        return None
    cell = state.get("cell")
    attempt_index = state.get("attempt_index")
    if (
        not isinstance(cell, Mapping)
        or type(attempt_index) is not int
        or not isinstance(cell.get("case_id"), str)
        or type(cell.get("repeat")) is not int
        or not isinstance(cell.get("arm"), str)
    ):
        return None
    common = [
        "--case",
        str(cell["case_id"]),
        "--repeat",
        str(cell["repeat"]),
        "--attempt-index",
        str(attempt_index),
    ]
    scripts = Path(__file__).resolve().parent
    arm = str(cell["arm"])
    if arm.startswith("hfnet_openloop_"):
        return [
            "/usr/bin/python3",
            str(scripts / "run_fair_stability_hfnet_openloop_v10.py"),
            "check",
            *common,
            "--budget",
            arm.rsplit("_", 1)[1],
        ]
    return [
        "/usr/bin/python3",
        str(scripts / "run_fair_stability_vins_replay_v10.py"),
        "check",
        *common,
        "--arm",
        arm,
    ]


def _validate_resubmit_authorization_evidence(
    experiment_root: Path,
    authorization_path: Path,
    authorization: Mapping[str, Any],
    prior_directory: Path,
    prior_claim: Mapping[str, Any],
    state: object,
    authorized_submission_index: int,
) -> None:
    """Revalidate all immutable evidence that could create start authority."""

    reset = authorization.get("reset_failed")
    resource = authorization.get("resource_check")
    if (
        set(authorization) != RESUBMIT_AUTHORIZATION_FIELDS
        or not isinstance(reset, Mapping)
        or set(reset) != RESUBMIT_RESET_FIELDS
        or not isinstance(resource, Mapping)
        or set(resource) != RESUBMIT_RESOURCE_CHECK_FIELDS
    ):
        raise OrdinalError(
            f"SYSTEMD_RESUBMIT_AUTHORIZATION_EVIDENCE_INVALID:"
            f"{authorization_path}"
        )
    prior_start_path = prior_directory / "systemd_start_receipt.json"
    prior_adoption_path = prior_directory / "systemd_adoption_receipt.json"
    prior_start = _load_systemd_json(
        experiment_root,
        prior_start_path,
        SYSTEMD_CHAIN_FILES["systemd_start_receipt"][1],
    )
    prior_adoption = _load_systemd_json(
        experiment_root, prior_adoption_path, SYSTEMD_ADOPTION_SCHEMA
    )
    unit = prior_claim.get("unit")
    invocation_id = prior_start.get("invocation_id")
    before = authorization.get("stopped_unit_observation_before_reset")
    after = authorization.get("stopped_unit_observation_after_reset")
    expected_before = (
        _recorded_stopped_unit_contract(
            str(unit), before, str(invocation_id), after_reset=False
        )
        if isinstance(unit, str) and isinstance(invocation_id, str)
        else None
    )
    expected_after = (
        _recorded_stopped_unit_contract(
            str(unit), after, str(invocation_id), after_reset=True
        )
        if isinstance(unit, str) and isinstance(invocation_id, str)
        else None
    )
    reset_stdout = (
        prior_directory
        / f"resubmit_{authorized_submission_index:03d}_reset.stdout.log"
    )
    reset_stderr = (
        prior_directory
        / f"resubmit_{authorized_submission_index:03d}_reset.stderr.log"
    )
    check_stdout = (
        prior_directory
        / f"resubmit_{authorized_submission_index:03d}_check.stdout.log"
    )
    check_stderr = (
        prior_directory
        / f"resubmit_{authorized_submission_index:03d}_check.stderr.log"
    )
    try:
        runner_result = json.loads(check_stdout.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OrdinalError(
            f"SYSTEMD_RESUBMIT_CHECK_STDOUT_INVALID:{check_stdout}"
        ) from error
    state_attempt_root = (
        state.get("attempt_root") if isinstance(state, Mapping) else None
    )
    attempt_manifest_path = (
        Path(state_attempt_root) / "attempt_manifest.json"
        if isinstance(state_attempt_root, str)
        else Path("")
    )
    try:
        require_no_symlink_components(attempt_manifest_path, experiment_root)
        if (
            not isinstance(state_attempt_root, str)
            or attempt_manifest_path.is_symlink()
            or not attempt_manifest_path.is_file()
        ):
            raise OrdinalError("SYSTEMD_RESUBMIT_ATTEMPT_MANIFEST_INVALID")
        attempt_manifest = json.loads(
            attempt_manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        raise OrdinalError(
            f"SYSTEMD_RESUBMIT_ATTEMPT_MANIFEST_INVALID:"
            f"{attempt_manifest_path}"
        ) from error
    state_cell = state.get("cell") if isinstance(state, Mapping) else None
    arm = state_cell.get("arm") if isinstance(state_cell, Mapping) else None
    expected_port = (
        None
        if isinstance(arm, str) and arm.startswith("hfnet_openloop_")
        else attempt_manifest.get("port")
        if isinstance(attempt_manifest, Mapping)
        else None
    )
    gate = resource.get("resource_gate")
    timestamps = [
        before.get("queried_at_utc") if isinstance(before, Mapping) else None,
        reset.get("started_at_utc"),
        reset.get("completed_at_utc"),
        after.get("queried_at_utc") if isinstance(after, Mapping) else None,
        resource.get("started_at_utc"),
        gate.get("checked_at_utc") if isinstance(gate, Mapping) else None,
        resource.get("completed_at_utc"),
        authorization.get("authorized_at_utc"),
    ]
    parsed_times = [_utc_evidence_datetime(value) for value in timestamps]
    expected_command = [
        "/usr/bin/python3",
        str(
            Path(__file__).resolve().parent
            / "run_fair_stability_systemd_supervisor_v10.py"
        ),
        "authorize-resubmit",
        "--submission-dir",
        str(prior_directory),
    ]
    if (
        any(value is None for value in parsed_times)
        or parsed_times != sorted(parsed_times)  # type: ignore[arg-type]
        or not re.fullmatch(r"[0-9a-f]{32}", str(invocation_id))
        or authorization.get("prior_invocation_id") != invocation_id
        or not strict_json_equal(
            authorization.get("authorization_command"), expected_command
        )
        or prior_adoption.get("controller_outcome") not in NO_START_OUTCOMES
        or type(prior_adoption.get("controller_returncode")) is not int
        or prior_adoption.get("controller_returncode") != 75
        or prior_adoption.get("ordinal_terminal_receipt") is not None
        or expected_before is None
        or expected_after is None
        or not strict_json_equal(
            authorization.get("stopped_unit_contract_before_reset"),
            expected_before,
        )
        or not strict_json_equal(
            authorization.get("stopped_unit_contract_after_reset"),
            expected_after,
        )
        or type(reset.get("sequence_index")) is not int
        or reset.get("sequence_index") != 1
        or reset.get("argv")
        != ["/usr/bin/systemctl", "--user", "reset-failed", unit]
        or not strict_json_equal(
            reset.get("control_plane_environment"),
            CONTROL_PLANE_ENVIRONMENT,
        )
        or type(reset.get("returncode")) is not int
        or reset.get("returncode") != 0
        or not identity_matches(reset.get("stdout"), reset_stdout)
        or not identity_matches(reset.get("stderr"), reset_stderr)
        or type(resource.get("sequence_index")) is not int
        or resource.get("sequence_index") != 2
        or not strict_json_equal(
            resource.get("argv"), _runner_check_argv_from_authorized_state(state)
        )
        or not strict_json_equal(
            resource.get("environment"), FIXED_SERVICE_ENVIRONMENT
        )
        or type(resource.get("returncode")) is not int
        or resource.get("returncode") != 0
        or resource.get("ready") is not True
        or not identity_matches(resource.get("stdout"), check_stdout)
        or not identity_matches(resource.get("stderr"), check_stderr)
        or not isinstance(runner_result, Mapping)
        or set(runner_result) != {"attempt", "resource_gate", "ready"}
        or not isinstance(attempt_manifest, Mapping)
        or not strict_json_equal(runner_result.get("attempt"), attempt_manifest)
        or not isinstance(arm, str)
        or (
            not arm.startswith("hfnet_openloop_")
            and type(expected_port) is not int
        )
        or (
            isinstance(gate, Mapping)
            and gate.get("port") != expected_port
        )
        or runner_result.get("ready") is not True
        or not strict_json_equal(resource.get("runner_result"), runner_result)
        or not strict_json_equal(runner_result.get("resource_gate"), gate)
        or not valid_ready_prestart_resource_gate_v10(gate)
    ):
        raise OrdinalError(
            f"SYSTEMD_RESUBMIT_AUTHORIZATION_EVIDENCE_INVALID:"
            f"{authorization_path}"
        )


def _validated_submission_sequence(
    experiment_root: Path,
    submission_directory: Path,
    anchor_claim: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Validate every accepted submission for one immutable coordinate.

    A no-start submission and a later result share an attempt directory, so
    directory order is part of the evidence.  The directory name, claim
    index, unit encoding, planned coordinate, and accepted receipt must all
    agree, with no gaps or cross-coordinate entries.
    """
    supervision_root = experiment_root / "systemd_supervision"
    ordinal = anchor_claim.get("planned_ordinal")
    attempt_index = anchor_claim.get("attempt_index")
    attempt_root_value = anchor_claim.get("attempt_root")
    if (
        type(ordinal) is not int
        or ordinal <= 0
        or type(attempt_index) is not int
        or attempt_index <= 0
        or not isinstance(attempt_root_value, str)
        or not attempt_root_value
    ):
        raise OrdinalError(
            f"SYSTEMD_SUBMISSION_COORDINATE_INVALID:{submission_directory}"
        )
    ordinal_root = supervision_root / f"ordinal_{ordinal:03d}"
    if submission_directory.parent != ordinal_root:
        raise OrdinalError(
            f"SYSTEMD_SUBMISSION_ORDINAL_ROOT_DRIFT:{submission_directory}"
        )
    require_no_symlink_components(ordinal_root, experiment_root)
    if ordinal_root.is_symlink() or not ordinal_root.is_dir():
        raise OrdinalError(f"SYSTEMD_ORDINAL_ROOT_INVALID:{ordinal_root}")
    entries = sorted(ordinal_root.iterdir(), key=lambda path: path.name)
    directories: list[Path] = []
    for entry in entries:
        match = re.fullmatch(r"submission_([0-9]{3})", entry.name)
        if (
            match is None
            or entry.is_symlink()
            or not entry.is_dir()
        ):
            raise OrdinalError(f"SYSTEMD_SUBMISSION_DIRECTORY_INVALID:{entry}")
        directories.append(entry)
    expected_names = [
        f"submission_{index:03d}"
        for index in range(1, len(directories) + 1)
    ]
    if [path.name for path in directories] != expected_names:
        raise OrdinalError(
            f"SYSTEMD_SUBMISSION_INDEX_SEQUENCE_INVALID:{ordinal_root}"
        )
    for index, directory in enumerate(directories, 1):
        observed_consumptions: list[int] = []
        for candidate in directory.iterdir():
            if not candidate.name.startswith(
                "resubmit_authorization_consumption_for_submission_"
            ):
                continue
            match = _RESUBMIT_AUTHORIZATION_CONSUMPTION_NAME.fullmatch(
                candidate.name
            )
            if (
                match is None
                or candidate.is_symlink()
                or not candidate.is_file()
            ):
                raise OrdinalError(
                    f"SYSTEMD_RESUBMIT_CONSUMPTION_FILE_INVALID:{candidate}"
                )
            require_no_symlink_components(candidate, experiment_root)
            observed_consumptions.append(int(match.group(1)))
        expected_consumptions = (
            [index + 1] if index < len(directories) else []
        )
        if sorted(observed_consumptions) != expected_consumptions:
            raise OrdinalError(
                f"SYSTEMD_RESUBMIT_CONSUMPTION_SEQUENCE_INVALID:"
                f"{directory}:{sorted(observed_consumptions)}:"
                f"{expected_consumptions}"
            )
    validated: list[dict[str, Any]] = []
    for index, directory in enumerate(directories, 1):
        claim_path = directory / "submission_claim.json"
        receipt_path = directory / "submission_receipt.json"
        claim = _load_systemd_json(
            experiment_root,
            claim_path,
            SYSTEMD_CHAIN_FILES["submission_claim"][1],
        )
        receipt = _load_systemd_json(
            experiment_root,
            receipt_path,
            SYSTEMD_CHAIN_FILES["submission_receipt"][1],
        )
        unit = claim.get("unit")
        unit_match = (
            _SYSTEMD_UNIT_COORDINATE.fullmatch(unit)
            if isinstance(unit, str)
            else None
        )
        if (
            type(claim.get("submission_index")) is not int
            or claim.get("submission_index") != index
            or claim.get("submission_directory") != str(directory)
            or type(claim.get("planned_ordinal")) is not int
            or claim.get("planned_ordinal") != ordinal
            or type(claim.get("attempt_index")) is not int
            or claim.get("attempt_index") != attempt_index
            or claim.get("attempt_root") != attempt_root_value
            or unit_match is None
            or int(unit_match.group("ordinal")) != ordinal
            or int(unit_match.group("attempt")) != attempt_index
            or int(unit_match.group("submission")) != index
            or receipt.get("unit") != unit
            or receipt.get("accepted") is not True
            or not identity_matches(
                receipt.get("submission_claim"), claim_path
            )
        ):
            raise OrdinalError(
                f"SYSTEMD_SUBMISSION_INDEX_OR_COORDINATE_DRIFT:{directory}"
            )
        authorization_record = claim.get("resubmit_authorization")
        if "resubmit_authorization" not in claim:
            raise OrdinalError(
                f"SYSTEMD_RESUBMIT_AUTHORIZATION_FIELD_MISSING:{directory}"
            )
        if index == 1:
            if authorization_record is not None:
                raise OrdinalError(
                    f"SYSTEMD_FIRST_SUBMISSION_AUTHORIZATION_FORBIDDEN:"
                    f"{directory}"
                )
        else:
            prior_directory = directories[index - 2]
            authorization_path = (
                prior_directory
                / f"resubmit_authorization_for_submission_{index:03d}.json"
            )
            if not identity_matches(
                authorization_record, authorization_path
            ):
                raise OrdinalError(
                    f"SYSTEMD_RESUBMIT_AUTHORIZATION_IDENTITY_INVALID:"
                    f"{directory}"
                )
            authorization = _load_systemd_json(
                experiment_root,
                authorization_path,
                RESUBMIT_AUTHORIZATION_SCHEMA,
            )
            prior_claim_path = prior_directory / "submission_claim.json"
            prior_start_path = (
                prior_directory / "systemd_start_receipt.json"
            )
            prior_adoption_path = (
                prior_directory / "systemd_adoption_receipt.json"
            )
            reset = authorization.get("reset_failed")
            resource = authorization.get("resource_check")
            state = authorization.get("ordinal_state_authorized")
            gate = (
                resource.get("resource_gate")
                if isinstance(resource, Mapping)
                else None
            )
            expected_authorization_command = [
                "/usr/bin/python3",
                str(
                    Path(__file__).resolve().parent
                    / "run_fair_stability_systemd_supervisor_v10.py"
                ),
                "authorize-resubmit",
                "--submission-dir",
                str(prior_directory),
            ]
            if (
                type(authorization.get("planned_ordinal")) is not int
                or authorization.get("planned_ordinal") != ordinal
                or type(authorization.get("attempt_index")) is not int
                or authorization.get("attempt_index") != attempt_index
                or authorization.get("attempt_root") != attempt_root_value
                or type(authorization.get("prior_submission_index")) is not int
                or authorization.get("prior_submission_index") != index - 1
                or type(authorization.get("authorized_submission_index")) is not int
                or authorization.get("authorized_submission_index") != index
                or authorization.get("prior_unit")
                != validated[-1]["claim"].get("unit")
                or not identity_matches(
                    authorization.get("prior_submission_claim"),
                    prior_claim_path,
                )
                or not identity_matches(
                    authorization.get("prior_systemd_start_receipt"),
                    prior_start_path,
                )
                or not identity_matches(
                    authorization.get("prior_systemd_adoption_receipt"),
                    prior_adoption_path,
                )
                or not strict_json_equal(
                    authorization.get("authorization_command"),
                    expected_authorization_command,
                )
                or not isinstance(state, Mapping)
                or state.get("state") != "READY"
                or state.get("attempt_root") != attempt_root_value
                or state.get("attempt_index") != attempt_index
                or not strict_json_equal(
                    claim.get("ordinal_state_before_submit"), state
                )
                or not isinstance(reset, Mapping)
                or type(reset.get("sequence_index")) is not int
                or reset.get("sequence_index") != 1
                or reset.get("argv")
                != [
                    "/usr/bin/systemctl",
                    "--user",
                    "reset-failed",
                    validated[-1]["claim"].get("unit"),
                ]
                or not strict_json_equal(
                    reset.get("control_plane_environment"),
                    CONTROL_PLANE_ENVIRONMENT,
                )
                or type(reset.get("returncode")) is not int
                or reset.get("returncode") != 0
                or not identity_matches(
                    reset.get("stdout"),
                    prior_directory
                    / f"resubmit_{index:03d}_reset.stdout.log",
                )
                or not identity_matches(
                    reset.get("stderr"),
                    prior_directory
                    / f"resubmit_{index:03d}_reset.stderr.log",
                )
                or not isinstance(resource, Mapping)
                or type(resource.get("sequence_index")) is not int
                or resource.get("sequence_index") != 2
                or not strict_json_equal(
                    resource.get("environment"), FIXED_SERVICE_ENVIRONMENT
                )
                or type(resource.get("returncode")) is not int
                or resource.get("returncode") != 0
                or resource.get("ready") is not True
                or not valid_ready_prestart_resource_gate_v10(gate)
                or not identity_matches(
                    resource.get("stdout"),
                    prior_directory
                    / f"resubmit_{index:03d}_check.stdout.log",
                )
                or not identity_matches(
                    resource.get("stderr"),
                    prior_directory
                    / f"resubmit_{index:03d}_check.stderr.log",
                )
            ):
                raise OrdinalError(
                    f"SYSTEMD_RESUBMIT_AUTHORIZATION_BINDING_INVALID:"
                    f"{authorization_path}"
                )
            _validate_resubmit_authorization_evidence(
                experiment_root,
                authorization_path,
                authorization,
                prior_directory,
                validated[-1]["claim"],
                state,
                index,
            )
            validate_resubmit_authorization_consumption(
                experiment_root,
                prior_directory,
                directory,
                index,
            )
        validated.append(
            {
                "directory": directory,
                "index": index,
                "claim": claim,
                "receipt": receipt,
            }
        )
    if submission_directory not in directories:
        raise OrdinalError(
            f"SYSTEMD_SUBMISSION_NOT_IN_CONTINUOUS_SEQUENCE:"
            f"{submission_directory}"
        )
    return validated


def _path_is_absent(path: Path) -> bool:
    return not any(
        (
            path.exists(),
            os.path.lexists(path),
            path.is_file(),
            path.is_symlink(),
        )
    )


def _expected_terminal_followup_state(
    experiment_root: Path,
    claim: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute the exact global state exposed after terminal adoption."""

    ordinal = claim.get("planned_ordinal")
    submitted = claim.get("ordinal_state_before_submit")
    submitted_cell = (
        submitted.get("cell") if isinstance(submitted, Mapping) else None
    )
    if type(ordinal) is not int:
        raise OrdinalError("SYSTEMD_TERMINAL_FOLLOWUP_ORDINAL_INVALID")
    schedule = load_schedule(experiment_root)
    if (
        ordinal < 1
        or ordinal > len(schedule)
        or not isinstance(submitted_cell, Mapping)
        or not strict_json_equal(submitted_cell, schedule[ordinal - 1])
    ):
        raise OrdinalError("SYSTEMD_TERMINAL_FOLLOWUP_COORDINATE_DRIFT")
    if ordinal == len(schedule):
        return {"state": "COMPLETE", "completed": len(schedule)}
    next_ordinal = ordinal + 1
    next_ordinal_root = (
        experiment_root
        / "systemd_supervision"
        / f"ordinal_{next_ordinal:03d}"
    )
    if next_ordinal_root.exists() or next_ordinal_root.is_symlink():
        require_no_symlink_components(next_ordinal_root, experiment_root)
        if next_ordinal_root.is_symlink() or not next_ordinal_root.is_dir():
            raise OrdinalError(
                "SYSTEMD_TERMINAL_FOLLOWUP_SUBMISSION_ROOT_INVALID"
            )
        first_directory = next_ordinal_root / "submission_001"
        first_claim = _load_systemd_json(
            experiment_root,
            first_directory / "submission_claim.json",
            SYSTEMD_CHAIN_FILES["submission_claim"][1],
        )
        _validated_submission_sequence(
            experiment_root, first_directory, first_claim
        )
        followup = first_claim.get("ordinal_state_before_submit")
    else:
        followup = inspect_cell(experiment_root, schedule[ordinal])
    if (
        not isinstance(followup, Mapping)
        or followup.get("state") not in {"READY", "NEEDS_PREPARATION"}
        or not strict_json_equal(followup.get("cell"), schedule[ordinal])
        or type(followup.get("attempt_index")) is not int
        or followup.get("attempt_index") != 1
        or bool(followup.get("invalid_chain"))
    ):
        raise OrdinalError("SYSTEMD_TERMINAL_FOLLOWUP_STATE_INVALID")
    return followup


def validate_finalized_systemd_adoption(
    experiment_root: Path,
    submission_directory: Path,
    *,
    _validate_submission_history: bool = True,
) -> dict[str, Any]:
    """Validate a finalized adoption with outcome-specific closure."""
    final_path = submission_directory / "systemd_adoption_receipt.json"
    adoption_claim_path = submission_directory / "systemd_adoption_claim.json"
    final = _load_systemd_json(
        experiment_root, final_path, SYSTEMD_ADOPTION_SCHEMA
    )
    adoption_claim = _load_systemd_json(
        experiment_root,
        adoption_claim_path,
        SYSTEMD_ADOPTION_CLAIM_SCHEMA,
    )
    records = {key: final.get(key) for key in SYSTEMD_CHAIN_FILES}
    chain = validate_systemd_chain(
        experiment_root,
        records,
        submission_directory,
        _validate_submission_history=_validate_submission_history,
    )
    claim = chain["submission_claim"]
    execution = chain["systemd_execution_receipt"]
    controller_result = execution.get("controller_result")
    if not isinstance(controller_result, Mapping):
        raise OrdinalError(
            f"SYSTEMD_FINAL_ADOPTION_CONTROLLER_RESULT_INVALID:{final_path}"
        )
    outcome = controller_result.get("outcome")
    returncode = execution.get("controller_returncode")
    before = adoption_claim.get("ordinal_state_before_adoption")
    after = final.get("ordinal_state_before_final_adoption_receipt")
    expected_adoption_claim_fields = {
        "schema_version",
        "experiment_id",
        "created_at_utc",
        "unit",
        "planned_ordinal",
        "attempt_index",
        "attempt_root",
        "ordinal_state_before_adoption",
        *SYSTEMD_CHAIN_FILES.keys(),
        "controller_returncode",
        "controller_outcome",
        "timeout_or_signal_observed",
        "estimator_retry_authorized",
    }
    expected_final_fields = {
        "schema_version",
        "experiment_id",
        "adopted_at_utc",
        "unit",
        *SYSTEMD_CHAIN_FILES.keys(),
        "systemd_adoption_claim",
        "ordinal_terminal_receipt",
        "controller_returncode",
        "controller_outcome",
        "ordinal_state_before_final_adoption_receipt",
        "estimator_retry_authorized",
        "next_submission_requires_new_submit",
    }
    created_at = _utc_evidence_datetime(
        adoption_claim.get("created_at_utc")
    )
    adopted_at = _utc_evidence_datetime(final.get("adopted_at_utc"))
    if (
        set(adoption_claim) != expected_adoption_claim_fields
        or set(final) != expected_final_fields
        or created_at is None
        or adopted_at is None
        or adopted_at < created_at
        or adoption_claim.get("timeout_or_signal_observed") is not False
        or adoption_claim.get("estimator_retry_authorized") is not False
        or final.get("estimator_retry_authorized") is not False
        or final.get("next_submission_requires_new_submit")
        is not (outcome in NO_START_OUTCOMES)
        or final.get("unit") != claim.get("unit")
        or adoption_claim.get("unit") != claim.get("unit")
        or adoption_claim.get("planned_ordinal")
        != claim.get("planned_ordinal")
        or adoption_claim.get("attempt_index") != claim.get("attempt_index")
        or adoption_claim.get("attempt_root") != claim.get("attempt_root")
        or not identity_matches(
            final.get("systemd_adoption_claim"), adoption_claim_path
        )
        or any(
            not strict_json_equal(final.get(key), record)
            or not strict_json_equal(adoption_claim.get(key), record)
            for key, record in records.items()
        )
        or final.get("controller_outcome") != outcome
        or adoption_claim.get("controller_outcome") != outcome
        or type(final.get("controller_returncode")) is not int
        or final.get("controller_returncode") != returncode
        or type(adoption_claim.get("controller_returncode")) is not int
        or adoption_claim.get("controller_returncode") != returncode
        or not isinstance(before, Mapping)
        or not strict_json_equal(
            before, execution.get("ordinal_state_after_controller")
        )
        or before.get("attempt_root") != claim.get("attempt_root")
        or before.get("attempt_index") != claim.get("attempt_index")
        or not isinstance(after, Mapping)
    ):
        raise OrdinalError(
            f"SYSTEMD_FINAL_ADOPTION_BINDING_INVALID:{final_path}"
        )

    ordinal_record = final.get("ordinal_terminal_receipt")
    if outcome == TERMINAL_SYSTEMD_OUTCOME:
        expected_followup = _expected_terminal_followup_state(
            experiment_root, claim
        )
        if (
            type(returncode) is not int
            or returncode != 0
            or before.get("state") != "TERMINAL_UNADOPTED"
            or not strict_json_equal(after, expected_followup)
            or not isinstance(ordinal_record, Mapping)
        ):
            raise OrdinalError(
                f"SYSTEMD_TERMINAL_ADOPTION_CLOSURE_INVALID:{final_path}"
            )
        ordinal_path = Path(str(ordinal_record.get("path", "")))
        expected_ordinal_path = (
            experiment_root
            / "ordinal_receipts"
            / f"ordinal_{int(claim['planned_ordinal']):03d}_terminal.json"
        )
        require_no_symlink_components(ordinal_path, experiment_root)
        try:
            ordinal_path.relative_to(experiment_root / "ordinal_receipts")
        except ValueError as error:
            raise OrdinalError(
                f"SYSTEMD_ORDINAL_TERMINAL_OUTSIDE_ROOT:{ordinal_path}"
            ) from error
        if (
            ordinal_path != expected_ordinal_path
            or not identity_matches(ordinal_record, ordinal_path)
        ):
            raise OrdinalError(
                f"SYSTEMD_ORDINAL_TERMINAL_IDENTITY_DRIFT:{ordinal_path}"
            )
        try:
            ordinal = json.loads(ordinal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise OrdinalError(
                f"SYSTEMD_ORDINAL_TERMINAL_JSON_INVALID:{ordinal_path}"
            ) from error
        if (
            not isinstance(ordinal, Mapping)
            or ordinal.get("schema_version")
            != "aqua-fe-fair-stability-ordinal-terminal-v10"
            or ordinal.get("experiment_id") != EXPERIMENT_ID
            or ordinal.get("planned_ordinal")
            != claim.get("planned_ordinal")
            or ordinal.get("accepted_attempt_index")
            != claim.get("attempt_index")
            or not identity_matches(
                ordinal.get("run_result"),
                Path(str(claim.get("attempt_root"))) / "run_result.json",
            )
            or not identity_matches(
                ordinal.get("systemd_adoption_claim"), adoption_claim_path
            )
        ):
            raise OrdinalError(
                f"SYSTEMD_ORDINAL_TERMINAL_REVERSE_BINDING_INVALID:"
                f"{ordinal_path}"
            )
    elif outcome in NO_START_OUTCOMES:
        if (
            type(returncode) is not int
            or returncode != 75
            or before.get("state") != "READY"
            or after.get("state") != "READY"
            or after.get("attempt_root") != claim.get("attempt_root")
            or after.get("attempt_index") != claim.get("attempt_index")
            or not strict_json_equal(before, after)
            or ordinal_record is not None
        ):
            raise OrdinalError(
                f"SYSTEMD_NO_START_ADOPTION_CLOSURE_INVALID:{final_path}"
            )
    elif outcome == PIPELINE_SYSTEMD_OUTCOME:
        if (
            type(returncode) is not int
            or returncode != 0
            or before.get("state")
            != "PIPELINE_INVALID_FAIL_STOP_ZERO_RETRY"
            or after.get("state")
            != "PIPELINE_INVALID_FAIL_STOP_ZERO_RETRY"
            or after.get("attempt_root") != claim.get("attempt_root")
            or after.get("attempt_index") != claim.get("attempt_index")
            or not strict_json_equal(before, after)
            or ordinal_record is not None
        ):
            raise OrdinalError(
                f"SYSTEMD_PIPELINE_ADOPTION_CLOSURE_INVALID:{final_path}"
            )
    else:
        raise OrdinalError(
            f"SYSTEMD_FINAL_ADOPTION_OUTCOME_INVALID:{final_path}:{outcome}"
        )
    return {
        "receipt": final,
        "adoption_claim": adoption_claim,
        "chain": chain,
    }


def _validate_other_finalized_submissions(
    experiment_root: Path,
    submission_directory: Path,
    sequence: list[dict[str, Any]],
) -> None:
    """Require every other accepted submission to have a closed outcome.

    Local validation disables sequence/history recursion but still re-reads
    the complete five-receipt chain and outcome-specific final adoption.  Any
    submission followed by another must be a finalized no-start, because only
    that outcome authorizes another same-coordinate submission.
    """
    for entry in sequence:
        directory = entry["directory"]
        if directory == submission_directory:
            continue
        finalized = validate_finalized_systemd_adoption(
            experiment_root,
            directory,
            _validate_submission_history=False,
        )
        chain = finalized["chain"]
        execution = chain["systemd_execution_receipt"]
        controller_result = execution.get("controller_result")
        outcome = (
            controller_result.get("outcome")
            if isinstance(controller_result, Mapping)
            else None
        )
        if outcome in NO_START_OUTCOMES:
            _validate_no_start_dispatch_artifact_attribution(
                experiment_root,
                directory,
                chain["submission_claim"],
                sequence,
                int(entry["index"]),
            )
        if entry["index"] < len(sequence) and outcome not in NO_START_OUTCOMES:
            raise OrdinalError(
                f"SYSTEMD_INTERMEDIATE_SUBMISSION_NOT_NO_START:"
                f"{directory}:{outcome}"
            )


def _validate_no_start_current_or_history(
    experiment_root: Path,
    submission_directory: Path,
    claim: Mapping[str, Any],
) -> None:
    """Keep current absence live; attribute later shared artifacts exactly."""
    sequence = _validated_submission_sequence(
        experiment_root, submission_directory, claim
    )
    current_index = next(
        entry["index"]
        for entry in sequence
        if entry["directory"] == submission_directory
    )
    later = [entry for entry in sequence if entry["index"] > current_index]
    attempt_root_path = Path(str(claim["attempt_root"]))
    _validate_no_start_dispatch_artifact_attribution(
        experiment_root,
        submission_directory,
        claim,
        sequence,
        current_index,
    )
    start_path = attempt_root_path / "start_claim.json"
    result_path = attempt_root_path / "run_result.json"
    start_absent = _path_is_absent(start_path)
    result_absent = _path_is_absent(result_path)
    if not later:
        if not start_absent or not result_absent:
            raise OrdinalError(
                f"SYSTEMD_NO_START_CURRENT_ABSENCE_VIOLATED:"
                f"{submission_directory}"
            )
        return
    if start_absent and result_absent:
        return
    if start_absent != result_absent:
        raise OrdinalError(
            f"SYSTEMD_NO_START_LATER_ARTIFACT_PAIR_INVALID:"
            f"{submission_directory}"
        )
    latest = later[-1]
    finalized = validate_finalized_systemd_adoption(
        experiment_root, latest["directory"]
    )
    latest_chain = finalized["chain"]
    latest_execution = latest_chain["systemd_execution_receipt"]
    latest_controller_result = latest_execution.get("controller_result")
    if (
        not isinstance(latest_controller_result, Mapping)
        or latest_controller_result.get("outcome")
        not in {TERMINAL_SYSTEMD_OUTCOME, PIPELINE_SYSTEMD_OUTCOME}
        or latest_execution.get("controller_returncode") != 0
    ):
        raise OrdinalError(
            f"SYSTEMD_NO_START_LATER_RESULT_SUBMISSION_INVALID:"
            f"{latest['directory']}"
        )
    validate_attempt_start_systemd_binding(
        experiment_root,
        start_path,
        identity(latest["directory"] / "systemd_start_receipt.json"),
    )
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OrdinalError(
            f"SYSTEMD_NO_START_LATER_RESULT_INVALID:{result_path}"
        ) from error
    if not isinstance(result, Mapping):
        raise OrdinalError(
            f"SYSTEMD_NO_START_LATER_RESULT_INVALID:{result_path}"
        )
    dispatch = validate_controller_dispatch_execution_for_result(
        experiment_root, attempt_root_path, result
    )
    if not strict_json_equal(
        latest_controller_result.get("dispatch_execution"),
        dispatch["identity"],
    ):
        raise OrdinalError(
            f"SYSTEMD_NO_START_LATER_RESULT_ATTRIBUTION_INVALID:"
            f"{latest['directory']}"
        )


_CONTROLLER_DISPATCH_EXECUTION_NAME = re.compile(
    r"controller_dispatch_execution_([0-9]{3})\.json"
)
_CONTROLLER_DISPATCH_STDOUT_NAME = re.compile(
    r"controller_dispatch_([0-9]{3})\.stdout\.log"
)
_CONTROLLER_DISPATCH_STDERR_NAME = re.compile(
    r"controller_dispatch_([0-9]{3})\.stderr\.log"
)
_NO_START_RUNTIME_EVIDENCE_NAMES = frozenset(PIPELINE_EVIDENCE_NAMES) - {
    "attempt_manifest.json",
    "ordinal_dispatch_claim.json",
    "start_claim.json",
    "run_result.json",
}


def _validate_no_start_dispatch_artifact_attribution(
    experiment_root: Path,
    submission_directory: Path,
    claim: Mapping[str, Any],
    sequence: list[dict[str, Any]],
    current_index: int,
) -> None:
    """Attribute every shared dispatch/runtime artifact to accepted work.

    A current resource-blocked submission has no dispatch authority at all;
    a current pre-start failure owns exactly its recorded dispatch.  Once the
    submission becomes historical, additional artifacts are accepted only
    when each one is owned, in order, by a continuous strictly later accepted
    submission for the same coordinate.  This prevents an orphan claim or
    runner log from being reused as authority for a resubmission.
    """

    root = Path(str(claim.get("attempt_root", "")))
    require_no_symlink_components(root, experiment_root)
    if root.is_symlink() or not root.is_dir():
        raise OrdinalError(
            f"SYSTEMD_NO_START_ATTEMPT_ROOT_INVALID:{submission_directory}"
        )
    execution_paths: list[Path] = []
    stdout_paths: list[Path] = []
    stderr_paths: list[Path] = []
    for candidate in root.iterdir():
        name = candidate.name
        execution_match = _CONTROLLER_DISPATCH_EXECUTION_NAME.fullmatch(name)
        stdout_match = _CONTROLLER_DISPATCH_STDOUT_NAME.fullmatch(name)
        stderr_match = _CONTROLLER_DISPATCH_STDERR_NAME.fullmatch(name)
        if execution_match:
            execution_paths.append(candidate)
        elif stdout_match:
            stdout_paths.append(candidate)
        elif stderr_match:
            stderr_paths.append(candidate)
        elif name.startswith("controller_dispatch_"):
            raise OrdinalError(
                f"SYSTEMD_NO_START_DISPATCH_ARTIFACT_NAME_INVALID:{candidate}"
            )
    for candidate in (*execution_paths, *stdout_paths, *stderr_paths):
        require_no_symlink_components(candidate, experiment_root)
        if candidate.is_symlink() or not candidate.is_file():
            raise OrdinalError(
                f"SYSTEMD_NO_START_DISPATCH_ARTIFACT_FILE_INVALID:{candidate}"
            )
    execution_paths.sort(key=lambda path: path.name)
    stdout_paths.sort(key=lambda path: path.name)
    stderr_paths.sort(key=lambda path: path.name)
    expected_execution_names = [
        f"controller_dispatch_execution_{index:03d}.json"
        for index in range(1, len(execution_paths) + 1)
    ]
    expected_stdout_names = [
        f"controller_dispatch_{index:03d}.stdout.log"
        for index in range(1, len(execution_paths) + 1)
    ]
    expected_stderr_names = [
        f"controller_dispatch_{index:03d}.stderr.log"
        for index in range(1, len(execution_paths) + 1)
    ]
    if (
        [path.name for path in execution_paths] != expected_execution_names
        or [path.name for path in stdout_paths] != expected_stdout_names
        or [path.name for path in stderr_paths] != expected_stderr_names
    ):
        raise OrdinalError(
            f"SYSTEMD_NO_START_DISPATCH_ARTIFACT_SEQUENCE_INVALID:{root}"
        )

    dispatch_claim_path = root / "ordinal_dispatch_claim.json"
    loaded_dispatches: list[dict[str, Any]] = []
    controller_path = (
        Path(__file__).resolve().parent / "run_fair_stability_next_v10.py"
    )
    for index, execution_path in enumerate(execution_paths, 1):
        try:
            value = json.loads(execution_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise OrdinalError(
                f"SYSTEMD_NO_START_DISPATCH_JSON_INVALID:{execution_path}"
            ) from error
        if (
            not isinstance(value, dict)
            or value.get("schema_version")
            != CONTROLLER_DISPATCH_EXECUTION_SCHEMA
            or value.get("experiment_id") != EXPERIMENT_ID
            or type(value.get("dispatch_index")) is not int
            or value.get("dispatch_index") != index
            or not identity_matches(
                value.get("dispatch_claim"), dispatch_claim_path
            )
            or not identity_matches(value.get("controller"), controller_path)
            or not identity_matches(value.get("stdout"), stdout_paths[index - 1])
            or not identity_matches(value.get("stderr"), stderr_paths[index - 1])
        ):
            raise OrdinalError(
                f"SYSTEMD_NO_START_DISPATCH_ARTIFACT_BINDING_INVALID:"
                f"{execution_path}"
            )
        loaded_dispatches.append(value)

    expected_dispatch_records: list[object] = []
    result_owner_directories: list[Path] = []
    for entry in sequence:
        directory = entry["directory"]
        execution_path = directory / "systemd_execution_receipt.json"
        systemd_execution = _load_systemd_json(
            experiment_root,
            execution_path,
            SYSTEMD_CHAIN_FILES["systemd_execution_receipt"][1],
        )
        controller_result = systemd_execution.get("controller_result")
        if not isinstance(controller_result, Mapping):
            raise OrdinalError(
                f"SYSTEMD_NO_START_LATER_CONTROLLER_RESULT_INVALID:{directory}"
            )
        outcome = controller_result.get("outcome")
        dispatch_record = controller_result.get("dispatch_execution")
        if outcome == "RESOURCE_BLOCKED_NO_START":
            if "dispatch_execution" in controller_result:
                raise OrdinalError(
                    f"SYSTEMD_NO_START_RESOURCE_DISPATCH_FORBIDDEN:{directory}"
                )
            continue
        if outcome not in {
            "PRESTART_DISPATCH_BLOCKED_NO_ESTIMATOR_START",
            TERMINAL_SYSTEMD_OUTCOME,
            PIPELINE_SYSTEMD_OUTCOME,
        } or not isinstance(dispatch_record, Mapping):
            raise OrdinalError(
                f"SYSTEMD_NO_START_DISPATCH_OWNER_INVALID:{directory}:{outcome}"
            )
        expected_dispatch_records.append(dispatch_record)
        if (
            entry["index"] >= current_index
            and outcome in {TERMINAL_SYSTEMD_OUTCOME, PIPELINE_SYSTEMD_OUTCOME}
        ):
            result_owner_directories.append(directory)
    observed_dispatch_records = [identity(path) for path in execution_paths]
    if not strict_json_equal(
        expected_dispatch_records, observed_dispatch_records
    ):
        raise OrdinalError(
            f"SYSTEMD_NO_START_DISPATCH_ATTRIBUTION_INVALID:"
            f"{submission_directory}"
        )
    if execution_paths:
        require_no_symlink_components(dispatch_claim_path, experiment_root)
        if dispatch_claim_path.is_symlink() or not dispatch_claim_path.is_file():
            raise OrdinalError(
                f"SYSTEMD_NO_START_DISPATCH_CLAIM_INVALID:{dispatch_claim_path}"
            )
    elif not _path_is_absent(dispatch_claim_path):
        raise OrdinalError(
            f"SYSTEMD_NO_START_ORPHAN_DISPATCH_CLAIM:{dispatch_claim_path}"
        )
    if len(result_owner_directories) > 1:
        raise OrdinalError(
            f"SYSTEMD_NO_START_MULTIPLE_RESULT_OWNERS:{submission_directory}"
        )
    runtime_paths: list[Path] = []
    for name in sorted(_NO_START_RUNTIME_EVIDENCE_NAMES):
        path = root / name
        if _path_is_absent(path):
            continue
        require_no_symlink_components(path, experiment_root)
        if path.is_symlink() or not path.is_file():
            raise OrdinalError(
                f"SYSTEMD_NO_START_RUNTIME_EVIDENCE_INVALID:{path}"
            )
        runtime_paths.append(path)
    if runtime_paths and not result_owner_directories:
        raise OrdinalError(
            f"SYSTEMD_NO_START_ORPHAN_RUNTIME_EVIDENCE:"
            f"{submission_directory}:{runtime_paths}"
        )


def _validate_no_start_dispatch_execution(
    experiment_root: Path,
    root: Path,
    record: object,
) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise OrdinalError("SYSTEMD_NO_START_DISPATCH_IDENTITY_MISSING")
    path = Path(str(record.get("path", "")))
    require_no_symlink_components(path, experiment_root)
    if path.parent != root or not re.fullmatch(
        r"controller_dispatch_execution_[0-9]{3}\.json", path.name
    ):
        raise OrdinalError(f"SYSTEMD_NO_START_DISPATCH_PATH_INVALID:{path}")
    if not identity_matches(record, path):
        raise OrdinalError(f"SYSTEMD_NO_START_DISPATCH_IDENTITY_DRIFT:{path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OrdinalError(
            f"SYSTEMD_NO_START_DISPATCH_JSON_INVALID:{path}"
        ) from error
    dispatch_index = int(path.stem.rsplit("_", 1)[-1])
    controller_path = (
        Path(__file__).resolve().parent / "run_fair_stability_next_v10.py"
    )
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != CONTROLLER_DISPATCH_EXECUTION_SCHEMA
        or value.get("experiment_id") != EXPERIMENT_ID
        or type(value.get("dispatch_index")) is not int
        or value.get("dispatch_index") != dispatch_index
        or type(value.get("returncode")) is not int
        or not identity_matches(
            value.get("dispatch_claim"), root / "ordinal_dispatch_claim.json"
        )
        or not identity_matches(value.get("controller"), controller_path)
        or value.get("run_result") is not None
        or any(
            value.get(key) is not None
            for key in (
                "run_result_status",
                "expected_runner_returncode_from_result_status",
                "runner_result_returncode_binding_valid",
                "run_result_parse_error",
            )
        )
    ):
        raise OrdinalError(
            f"SYSTEMD_NO_START_DISPATCH_RECEIPT_INVALID:{path}"
        )
    return {"path": str(path), "identity": identity(path), "receipt": value}


def _validate_no_start_provenance(
    experiment_root: Path,
    submission_directory: Path,
    records: Mapping[str, object],
    claim: Mapping[str, Any],
    execution: Mapping[str, Any],
    controller_result: Mapping[str, Any],
) -> None:
    outcome = controller_result.get("outcome")
    provenance = execution.get("no_start_provenance")
    attempt_root_value = claim.get("attempt_root")
    if not isinstance(attempt_root_value, str) or not attempt_root_value:
        raise OrdinalError("SYSTEMD_NO_START_ATTEMPT_ROOT_INVALID")
    root = Path(attempt_root_value)
    require_no_symlink_components(root, experiment_root)
    pre_state = claim.get("ordinal_state_before_submit")
    post_state = execution.get("ordinal_state_after_controller")
    expected_provenance_fields = {
        "schema_version",
        "experiment_id",
        "recorded_at_utc",
        "unit",
        "submission_claim",
        "systemd_start_receipt",
        "attempt_root",
        "ordinal_state_before_controller",
        "ordinal_state_after_controller",
        "controller_outcome",
        "controller_returncode",
        "estimator_start_claim_observation",
        "estimator_run_result_observation",
        "estimator_start_authority_present",
        "dispatch_execution",
        "resource_gate",
        "resource_check_returncode",
        "resource_check_ready",
    }
    if (
        not isinstance(provenance, Mapping)
        or set(provenance) != expected_provenance_fields
        or provenance.get("schema_version") != NO_START_PROVENANCE_SCHEMA
        or provenance.get("experiment_id") != EXPERIMENT_ID
        or provenance.get("unit") != claim.get("unit")
        or not valid_utc_receipt_timestamp(provenance.get("recorded_at_utc"))
        or not strict_json_equal(
            provenance.get("submission_claim"), records["submission_claim"]
        )
        or not strict_json_equal(
            provenance.get("systemd_start_receipt"),
            records["systemd_start_receipt"],
        )
        or provenance.get("attempt_root") != str(root)
        or not strict_json_equal(
            provenance.get("ordinal_state_before_controller"), pre_state
        )
        or not strict_json_equal(
            provenance.get("ordinal_state_after_controller"), post_state
        )
        or provenance.get("controller_outcome") != outcome
        or type(provenance.get("controller_returncode")) is not int
        or provenance.get("controller_returncode") != 75
        or type(execution.get("controller_returncode")) is not int
        or execution.get("controller_returncode") != 75
        or provenance.get("estimator_start_authority_present") is not False
        or not isinstance(pre_state, Mapping)
        or pre_state.get("state") not in {"READY", "NEEDS_PREPARATION"}
        or pre_state.get("attempt_root") != str(root)
        or pre_state.get("attempt_index") != claim.get("attempt_index")
        or not isinstance(post_state, Mapping)
        or post_state.get("state") != "READY"
        or post_state.get("attempt_root") != str(root)
        or post_state.get("attempt_index") != claim.get("attempt_index")
    ):
        raise OrdinalError(
            f"SYSTEMD_NO_START_PROVENANCE_INVALID:{submission_directory}"
        )
    _validate_recorded_absence(
        provenance.get("estimator_start_claim_observation"),
        root / "start_claim.json",
        "start_claim",
    )
    _validate_recorded_absence(
        provenance.get("estimator_run_result_observation"),
        root / "run_result.json",
        "run_result",
    )
    if outcome == "RESOURCE_BLOCKED_NO_START":
        resource_gate = controller_result.get("resource_gate")
        manifest_path = root / "attempt_manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise OrdinalError(
                f"SYSTEMD_NO_START_ATTEMPT_MANIFEST_INVALID:{manifest_path}"
            ) from error
        cell = pre_state.get("cell") if isinstance(pre_state, Mapping) else None
        arm = cell.get("arm") if isinstance(cell, Mapping) else None
        expected_port = (
            None
            if isinstance(arm, str) and arm.startswith("hfnet_openloop_")
            else manifest.get("port")
            if isinstance(manifest, Mapping)
            else None
        )
        if (
            set(controller_result)
            != {
                "outcome",
                "next",
                "resource_gate",
                "runner_returncode",
                "systemd_authority",
            }
            or
            not isinstance(manifest, Mapping)
            or manifest.get("experiment_id") != EXPERIMENT_ID
            or not isinstance(arm, str)
            or (
                not arm.startswith("hfnet_openloop_")
                and type(expected_port) is not int
            )
            or not valid_prestart_resource_gate_v10(
                resource_gate,
                expected_ready=False,
                expected_port=expected_port,
            )
            or type(controller_result.get("runner_returncode")) is not int
            or controller_result.get("runner_returncode") != 2
            or "dispatch_execution" in controller_result
            or provenance.get("dispatch_execution") is not None
            or not strict_json_equal(
                provenance.get("resource_gate"), resource_gate
            )
            or provenance.get("resource_check_ready") is not False
            or type(provenance.get("resource_check_returncode")) is not int
            or provenance.get("resource_check_returncode") != 2
            or not strict_json_equal(controller_result.get("next"), post_state)
        ):
            raise OrdinalError(
                f"SYSTEMD_NO_START_RESOURCE_BRANCH_INVALID:{submission_directory}"
            )
        return
    if outcome != "PRESTART_DISPATCH_BLOCKED_NO_ESTIMATOR_START":
        raise OrdinalError(
            f"SYSTEMD_NO_START_OUTCOME_INVALID:{submission_directory}"
        )
    dispatch_record = controller_result.get("dispatch_execution")
    dispatch = _validate_no_start_dispatch_execution(
        experiment_root, root, dispatch_record
    )
    if (
        set(controller_result)
        != {
            "outcome",
            "dispatch_execution",
            "runner_stderr_tail",
            "systemd_authority",
        }
        or not strict_json_equal(provenance.get("dispatch_execution"), dispatch["identity"])
        or provenance.get("resource_gate") is not None
        or provenance.get("resource_check_ready") is not None
        or provenance.get("resource_check_returncode") is not None
    ):
        raise OrdinalError(
            f"SYSTEMD_NO_START_PRESTART_BRANCH_INVALID:{submission_directory}"
        )


def validate_systemd_chain(
    experiment_root: Path,
    records: Mapping[str, object],
    submission_directory: Path,
    *,
    _validate_submission_history: bool = True,
) -> dict[str, dict[str, Any]]:
    """Re-read and bind every immutable systemd receipt, not only its digest copy."""
    require_no_symlink_components(submission_directory, experiment_root)
    supervision_root = experiment_root / "systemd_supervision"
    try:
        submission_directory.relative_to(supervision_root)
    except ValueError as error:
        raise OrdinalError(
            f"SYSTEMD_CHAIN_OUTSIDE_SUPERVISION_ROOT:{submission_directory}"
        ) from error
    loaded: dict[str, dict[str, Any]] = {}
    for key, (filename, schema) in SYSTEMD_CHAIN_FILES.items():
        path = submission_directory / filename
        record = records.get(key)
        if not isinstance(record, Mapping) or not identity_matches(record, path):
            raise OrdinalError(f"SYSTEMD_CHAIN_IDENTITY_DRIFT:{key}:{path}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != schema
            or value.get("experiment_id") != EXPERIMENT_ID
        ):
            raise OrdinalError(f"SYSTEMD_CHAIN_SCHEMA_DRIFT:{key}:{path}")
        loaded[key] = value

    claim = loaded["submission_claim"]
    submit = loaded["submission_receipt"]
    start = loaded["systemd_start_receipt"]
    execution = loaded["systemd_execution_receipt"]
    terminal = loaded["systemd_terminal_receipt"]
    unit = claim.get("unit")
    if (
        not isinstance(unit, str)
        or not unit
        or any(value.get("unit") != unit for value in (submit, start, execution, terminal))
        or claim.get("submission_directory") != str(submission_directory)
        or submit.get("accepted") is not True
        or not strict_json_equal(submit.get("submission_claim"), records["submission_claim"])
        or not strict_json_equal(start.get("submission_claim"), records["submission_claim"])
        or not strict_json_equal(start.get("submission_receipt"), records["submission_receipt"])
        or not strict_json_equal(
            execution.get("systemd_start_receipt"), records["systemd_start_receipt"]
        )
        or any(
            not strict_json_equal(terminal.get(key), record)
            for key, record in records.items()
            if key != "systemd_terminal_receipt"
        )
    ):
        raise OrdinalError(f"SYSTEMD_CHAIN_EMBEDDED_BINDING_DRIFT:{submission_directory}")
    submission_sequence: list[dict[str, Any]] = []
    if _validate_submission_history:
        submission_sequence = _validated_submission_sequence(
            experiment_root, submission_directory, claim
        )
        _validate_other_finalized_submissions(
            experiment_root,
            submission_directory,
            submission_sequence,
        )

    expected_setenv = [
        f"--setenv={key}={value}" for key, value in FIXED_SERVICE_ENVIRONMENT.items()
    ]
    recorded_argv = claim.get("systemd_run_argv")
    recorded_contract = claim.get("systemd_contract")
    recorded_environment = (
        recorded_contract.get("minimum_fixed_environment")
        if isinstance(recorded_contract, Mapping)
        else None
    )
    recorded_control_environment = claim.get("control_plane_environment")
    submit_systemd_run = submit.get("systemd_run")
    if (
        not strict_json_equal(recorded_environment, FIXED_SERVICE_ENVIRONMENT)
        or not strict_json_equal(start.get("fixed_service_environment"), FIXED_SERVICE_ENVIRONMENT)
        or not strict_json_equal(
            recorded_control_environment, CONTROL_PLANE_ENVIRONMENT
        )
        or not isinstance(submit_systemd_run, Mapping)
        or not strict_json_equal(
            submit_systemd_run.get("control_plane_environment"),
            CONTROL_PLANE_ENVIRONMENT,
        )
        or not isinstance(recorded_argv, list)
        or [
            value for value in recorded_argv
            if isinstance(value, str) and value.startswith("--setenv=")
        ] != expected_setenv
    ):
        raise OrdinalError(
            f"SYSTEMD_CHAIN_FIXED_ENVIRONMENT_INVALID:{submission_directory}"
        )

    invocation_ids = {
        str(start.get("invocation_id", "")),
        str(execution.get("invocation_id", "")),
        str(terminal.get("invocation_id_environment", "")),
    }
    observed_tuple = terminal.get("observed_tuple")
    controller_result = execution.get("controller_result")
    authority = (
        controller_result.get("systemd_authority")
        if isinstance(controller_result, Mapping)
        else None
    )
    code_numbers = {"exited": "1", "killed": "2", "dumped": "3"}
    exit_code = str(terminal.get("exit_code_environment", ""))
    exit_status = str(terminal.get("exit_status_environment", ""))
    controller_returncode = execution.get("controller_returncode")
    if (
        len(invocation_ids) != 1
        or not re.fullmatch(r"[0-9a-f]{32}", next(iter(invocation_ids)))
        or not isinstance(observed_tuple, Mapping)
        or observed_tuple.get("Result")
        != terminal.get("service_result_environment")
        or str(observed_tuple.get("ExecMainCode")) != code_numbers.get(exit_code)
        or str(observed_tuple.get("ExecMainStatus")) != exit_status
        or exit_code != "exited"
        or not exit_status.isdigit()
        or type(controller_returncode) is not int
        or int(exit_status) != controller_returncode
        or (
            controller_returncode == 0
            and terminal.get("service_result_environment") != "success"
        )
        or (
            controller_returncode != 0
            and terminal.get("service_result_environment") != "exit-code"
        )
        or terminal.get("service_result_environment") == "timeout"
    ):
        raise OrdinalError(f"SYSTEMD_CHAIN_TERMINAL_TUPLE_INVALID:{submission_directory}")
    if (
        not isinstance(authority, Mapping)
        or authority.get("path")
        != str(submission_directory / "systemd_start_receipt.json")
        or not strict_json_equal(
            authority.get("identity"), records["systemd_start_receipt"]
        )
        or not strict_json_equal(authority.get("receipt"), start)
    ):
        raise OrdinalError(
            f"SYSTEMD_CHAIN_CONTROLLER_AUTHORITY_INVALID:{submission_directory}"
        )

    outcome = controller_result.get("outcome")
    if outcome in NO_START_OUTCOMES:
        _validate_no_start_provenance(
            experiment_root,
            submission_directory,
            records,
            claim,
            execution,
            controller_result,
        )
        if _validate_submission_history:
            _validate_no_start_current_or_history(
                experiment_root, submission_directory, claim
            )
        return loaded
    if (
        "no_start_provenance" not in execution
        or execution.get("no_start_provenance") is not None
    ):
        raise OrdinalError(
            f"SYSTEMD_NO_START_PROVENANCE_FOR_NON_NO_START_OUTCOME:"
            f"{submission_directory}"
        )

    # Every adoptable non-no-start outcome is a result-producing outcome.  It
    # must bind this submission's start receipt, the latest inner runner exit,
    # and the exact state transition published by the controller.
    attempt_root_value = claim.get("attempt_root")
    if not isinstance(attempt_root_value, str) or not attempt_root_value:
        raise OrdinalError(
            f"SYSTEMD_CHAIN_ATTEMPT_ROOT_INVALID:{submission_directory}"
        )
    claimed_attempt_root = Path(attempt_root_value)
    require_no_symlink_components(claimed_attempt_root, experiment_root)
    result_path = claimed_attempt_root / "run_result.json"
    if result_path.is_symlink() or (
        result_path.exists() and not result_path.is_file()
    ):
        raise OrdinalError(
            f"SYSTEMD_CHAIN_RUN_RESULT_PATH_INVALID:{result_path}"
        )
    if not result_path.is_file() or result_path.is_symlink():
        raise OrdinalError(
            f"SYSTEMD_CHAIN_RESULT_REQUIRED_FOR_OUTCOME:"
            f"{submission_directory}:{outcome}"
        )
    dispatch_record = controller_result.get("dispatch_execution")
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OrdinalError(
            f"SYSTEMD_CHAIN_RUN_RESULT_JSON_INVALID:{result_path}"
        ) from error
    if not isinstance(result, dict):
        raise OrdinalError(
            f"SYSTEMD_CHAIN_RUN_RESULT_OBJECT_REQUIRED:{result_path}"
        )
    pre_state = claim.get("ordinal_state_before_submit")
    if (
        isinstance(pre_state, Mapping)
        and pre_state.get("state") == "PIPELINE_INVALID_UNADJUDICATED"
    ):
        _validate_pipeline_adjudication_submission(
            experiment_root,
            submission_directory,
            claim,
            execution,
            controller_result,
            claimed_attempt_root,
            result,
        )
    if not isinstance(dispatch_record, Mapping):
        raise OrdinalError(
            f"SYSTEMD_CHAIN_RESULT_DISPATCH_REQUIRED:"
            f"{submission_directory}"
        )
    dispatch = validate_controller_dispatch_execution_for_result(
        experiment_root, claimed_attempt_root, result
    )
    if not strict_json_equal(dispatch_record, dispatch["identity"]):
        raise OrdinalError(
            f"SYSTEMD_CHAIN_RESULT_DISPATCH_IDENTITY_MISMATCH:"
            f"{submission_directory}"
        )
    expected_outcome = (
        TERMINAL_SYSTEMD_OUTCOME
        if result.get("status") in TERMINAL_STATUSES
        else PIPELINE_SYSTEMD_OUTCOME
        if result.get("status") == "PIPELINE_INVALID"
        else None
    )
    expected_post_state = (
        "TERMINAL_UNADOPTED"
        if expected_outcome == TERMINAL_SYSTEMD_OUTCOME
        else "PIPELINE_INVALID_FAIL_STOP_ZERO_RETRY"
        if expected_outcome == PIPELINE_SYSTEMD_OUTCOME
        else None
    )
    dispatch_receipt = dispatch["receipt"]
    post_state = execution.get("ordinal_state_after_controller")
    result_state = controller_result.get("state")
    start_path = claimed_attempt_root / "start_claim.json"
    if (
        not isinstance(pre_state, Mapping)
        or pre_state.get("state") not in {"READY", "NEEDS_PREPARATION"}
        or pre_state.get("attempt_root") != str(claimed_attempt_root)
        or pre_state.get("attempt_index") != claim.get("attempt_index")
        or expected_outcome is None
        or expected_post_state is None
        or execution.get("controller_returncode") != 0
        or controller_result.get("outcome") != expected_outcome
        or not isinstance(result_state, Mapping)
        or result_state.get("state") != expected_post_state
        or result_state.get("attempt_root") != str(claimed_attempt_root)
        or result_state.get("attempt_index") != claim.get("attempt_index")
        or not strict_json_equal(result_state.get("result"), result)
        or not strict_json_equal(post_state, result_state)
        or not strict_json_equal(
            controller_result.get("dispatch_execution"), dispatch["identity"]
        )
        or controller_result.get("runner_returncode")
        != dispatch_receipt.get("returncode")
    ):
        raise OrdinalError(
            f"SYSTEMD_CHAIN_INNER_RUNNER_EXIT_BINDING_INVALID:"
            f"{submission_directory}"
        )
    validate_attempt_start_systemd_binding(
        experiment_root, start_path, records["systemd_start_receipt"]
    )
    return loaded


def valid_utc_receipt_timestamp(value: object) -> bool:
    """Accept only an explicit, parseable UTC timestamp for immutable receipts."""
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)


def require_no_symlink_components(path: Path, experiment_root: Path) -> None:
    """Reject directory redirection anywhere below the fixed experiment root."""
    anchor = Path(os.path.abspath(experiment_root))
    target = Path(os.path.abspath(path))
    try:
        relative = target.relative_to(anchor)
    except ValueError as error:
        raise OrdinalError(f"PATH_OUTSIDE_EXPERIMENT_ROOT:{target}") from error
    candidate = anchor
    if candidate.is_symlink():
        raise OrdinalError(f"SYMLINK_PATH_COMPONENT:{candidate}")
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise OrdinalError(f"SYMLINK_PATH_COMPONENT:{candidate}")


def load_schedule(experiment_root: Path) -> list[dict[str, Any]]:
    path = experiment_root / "planned_schedule.json"
    require_no_symlink_components(path, experiment_root)
    observed = identity(path)
    if observed["sha256"] != SCHEDULE_SHA256:
        raise OrdinalError("SCHEDULE_IDENTITY_MISMATCH")
    parent = json.loads((experiment_root / "experiment_manifest.json").read_text(encoding="utf-8"))
    if parent.get("experiment_id") != EXPERIMENT_ID:
        raise OrdinalError("PARENT_EXPERIMENT_ID_MISMATCH")
    parent_claims = parent.get("claims")
    if not isinstance(parent_claims, Mapping) or any(
        parent_claims.get(f"v{version}_results_imported") is not False
        for version in range(1, 10)
    ) or not valid_v9_non_import_claims(parent_claims):
        raise OrdinalError("PARENT_PRIOR_RESULTS_IMPORT_CLAIM_INVALID")
    parent_schedule = parent.get("planned_schedule", {})
    if (
        parent_schedule.get("sha256"), parent_schedule.get("size_bytes")
    ) != (observed["sha256"], observed["size_bytes"]):
        raise OrdinalError("PARENT_SCHEDULE_PIN_MISMATCH")
    schedule = json.loads(path.read_text(encoding="utf-8"))
    if len(schedule) != 120:
        raise OrdinalError("SCHEDULE_LENGTH_MISMATCH")
    coordinates: set[tuple[str, str, int]] = set()
    for expected_ordinal, cell in enumerate(schedule, 1):
        coordinate = (str(cell.get("case_id")), str(cell.get("arm")), int(cell.get("repeat", -1)))
        if cell.get("ordinal") != expected_ordinal or coordinate in coordinates:
            raise OrdinalError("SCHEDULE_ORDINAL_OR_COORDINATE_INVALID")
        if coordinate[1] not in ALL_ARMS or coordinate[2] not in (1, 2, 3):
            raise OrdinalError("SCHEDULE_CELL_INVALID")
        coordinates.add(coordinate)
    return schedule


def load_attempt_matrix(experiment_root: Path) -> dict[str, Any]:
    """Verify the immutable 120-attempt v10 matrix without freezing later retries."""
    path = experiment_root / "attempt_matrix_freeze_v10.json"
    require_no_symlink_components(path, experiment_root)
    if path.is_symlink() or not path.is_file():
        raise OrdinalError("ATTEMPT_MATRIX_FREEZE_MISSING_OR_INVALID")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        value.get("schema_version")
        != "aqua-fe-fair-stability-attempt-matrix-freeze-v10"
        or value.get("experiment_id") != EXPERIMENT_ID
        or value.get("status") != "FROZEN_BEFORE_ANY_V10_ESTIMATOR_START"
    ):
        raise OrdinalError("ATTEMPT_MATRIX_FREEZE_HEADER_INVALID")
    expected_replacement_policy = {
        "automatic_retry_pipeline_failure_codes": sorted(
            AUTOMATIC_RETRY_PIPELINE_FAILURES
        ),
        "maximum_replacement_attempts_per_planned_cell": MAX_REPLACEMENT_ATTEMPTS_PER_CELL,
        "maximum_total_attempts_per_planned_cell": MAX_ATTEMPTS_PER_CELL,
        "same_pipeline_failure_code_may_repeat": False,
    }
    if not strict_json_equal(
        value.get("replacement_policy"), expected_replacement_policy
    ):
        raise OrdinalError("ATTEMPT_MATRIX_REPLACEMENT_POLICY_INVALID")
    expected_claims = {
        "attempt_count": 120,
        "v1_results_imported": False,
        "v2_results_imported": False,
        "v3_results_imported": False,
        "v4_results_imported": False,
        "v5_results_imported": False,
        "v6_results_imported": False,
        "v7_results_imported": False,
        "v8_results_imported": False,
        "v9_results_imported": False,
        "v9_runtime_namespace_read": False,
        "v9_attempts_reused": False,
        "v9_cache_reused": False,
        "dispatch_claim_count": 0,
        "start_claim_count": 0,
        "run_result_count": 0,
        "terminal_receipt_count": 0,
    }
    if not strict_json_equal(value.get("claims"), expected_claims):
        raise OrdinalError("ATTEMPT_MATRIX_CLAIMS_INVALID")
    for key, candidate in (
        ("experiment_manifest", experiment_root / "experiment_manifest.json"),
        ("planned_schedule", experiment_root / "planned_schedule.json"),
        (
            "backend_freeze",
            experiment_root
            / "vins_dev_nativeq_schedfix_runtimeexcl_v10"
            / "backend_freeze.json",
        ),
    ):
        if not identity_matches(value.get(key), candidate):
            raise OrdinalError(f"ATTEMPT_MATRIX_PARENT_DRIFT:{key}")
    schedule = load_schedule(experiment_root)
    rows = value.get("attempts")
    if not isinstance(rows, list) or len(rows) != 120:
        raise OrdinalError("ATTEMPT_MATRIX_LENGTH_MISMATCH")
    for cell, row in zip(schedule, rows):
        if not isinstance(row, Mapping):
            raise OrdinalError("ATTEMPT_MATRIX_ROW_INVALID")
        expected_root = attempt_root(experiment_root, cell, 1)
        expected_manifest = expected_root / "attempt_manifest.json"
        if not strict_json_equal(
            [
                row.get("ordinal"), row.get("case_id"), row.get("arm"),
                row.get("repeat"), row.get("attempt_index"),
                row.get("attempt_root"), row.get("maximum_replacement_attempts"),
                row.get("maximum_total_attempts"),
            ],
            [
                int(cell["ordinal"]), str(cell["case_id"]), str(cell["arm"]),
                int(cell["repeat"]), 1, str(expected_root),
                MAX_REPLACEMENT_ATTEMPTS_PER_CELL, MAX_ATTEMPTS_PER_CELL,
            ],
        ) or not identity_matches(row.get("attempt_manifest"), expected_manifest):
            raise OrdinalError(f"ATTEMPT_MATRIX_ROW_DRIFT:{cell['ordinal']}")
    return value


def attempt_root(experiment_root: Path, cell: Mapping[str, Any], attempt_index: int) -> Path:
    case_id, arm, repeat = str(cell["case_id"]), str(cell["arm"]), int(cell["repeat"])
    if arm.startswith("hfnet_openloop_"):
        base = experiment_root / arm / case_id / f"repeat_{repeat:03d}"
    else:
        base = (
            experiment_root / "vins_dev_nativeq_schedfix_runtimeexcl_v10" / "attempts"
            / case_id / arm / f"repeat_{repeat:03d}"
        )
    if attempt_index != 1:
        raise OrdinalError("ATTEMPT_INDEX_INVALID")
    return base


def _coordinate_matches(value: Mapping[str, Any], cell: Mapping[str, Any], attempt_index: int) -> bool:
    observed_arm = value.get("arm")
    if observed_arm is None and value.get("budget") is not None:
        if type(value.get("budget")) is not int:
            return False
        observed_arm = f"hfnet_openloop_{value['budget']}"
    return strict_json_equal(
        [
            value.get("case_id"), observed_arm, value.get("repeat"),
            value.get("attempt_index"),
        ],
        [str(cell["case_id"]), str(cell["arm"]), int(cell["repeat"]), attempt_index],
    )


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    candidate = float(value)
    return candidate if math.isfinite(candidate) else None


def _nonnegative_count(mapping: Mapping[str, Any], key: str) -> int | None:
    value = mapping.get(key, 0)
    return value if type(value) is int and value >= 0 else None


def _vins_lifecycle_semantics(
    value: Mapping[str, Any], timed_out: bool
) -> tuple[list[str], list[str]] | None:
    """Independently replay the VINS start/lifecycle split."""
    pipeline: list[str] = []
    algorithm: list[str] = []
    start = value.get("child_start")
    lifecycle = value.get("child_lifecycle")
    tag = value.get("tag")
    if not isinstance(start, Mapping) or not isinstance(lifecycle, Mapping):
        return None
    start_values = start.get("values")
    if not isinstance(start_values, Mapping) or start_values.get("tag") != tag:
        pipeline.append("ATTEMPT_TAG_BINDING_UNPROVEN")
    if timed_out:
        return pipeline, algorithm
    lifecycle_values = lifecycle.get("values")
    if (
        not isinstance(lifecycle_values, Mapping)
        or lifecycle_values.get("tag") != tag
    ):
        if "ATTEMPT_TAG_BINDING_UNPROVEN" not in pipeline:
            pipeline.append("ATTEMPT_TAG_BINDING_UNPROVEN")
    if lifecycle.get("valid") is True:
        if (
            not isinstance(lifecycle_values, Mapping)
            or lifecycle_values.get("output_nonempty") != "1"
        ):
            pipeline.append("SUPERVISED_SHUTDOWN_CONTRACT_UNPROVEN")
        return pipeline, algorithm
    if not isinstance(lifecycle_values, Mapping):
        pipeline.append("SUPERVISED_SHUTDOWN_CONTRACT_UNPROVEN")
        return pipeline, algorithm
    early_exit = lifecycle_values.get("vins_early_exit") == "1"
    rosbag_nonzero = lifecycle_values.get("rosbag_returncode") not in (None, "0")
    output_empty = lifecycle_values.get("output_nonempty") == "0"
    if early_exit:
        algorithm.append("ESTIMATOR_EXITED_BEFORE_BAG_END")
    if rosbag_nonzero:
        pipeline.append("ROSBAG_PLAY_NONZERO")
    errors = lifecycle.get("errors")
    if (
        not isinstance(errors, list)
        or any(not isinstance(error, str) for error in errors)
    ):
        pipeline.append("SUPERVISED_SHUTDOWN_CONTRACT_UNPROVEN")
        return pipeline, algorithm
    allowed_value_mismatch_keys: set[str] = set()
    allowed_end_identity_keys: set[str] = set()
    if output_empty:
        allowed_value_mismatch_keys.add("output_nonempty")
    if rosbag_nonzero:
        allowed_value_mismatch_keys.add("rosbag_returncode")
    if early_exit:
        allowed_value_mismatch_keys.update(
            {
                "bag_end_vins_alive", "output_nonempty", "vins_signal_sent",
                "vins_wait_returncode", "vins_early_exit",
                "bag_end_vins_identity_match",
            }
        )
        allowed_end_identity_keys.update(
            {
                "bag_end_vins_start_ticks", "bag_end_vins_pgid",
                "bag_end_vins_executable",
            }
        )

    def expected_consequence(error: str) -> bool:
        if error.startswith("VALUE_MISMATCH:"):
            parts = error.split(":", 2)
            return len(parts) >= 2 and parts[1] in allowed_value_mismatch_keys
        if error.startswith("END_IDENTITY_MISMATCH:"):
            return error.split(":", 1)[1] in allowed_end_identity_keys
        return False

    remaining = [error for error in errors if not expected_consequence(error)]
    if remaining or not (early_exit or rosbag_nonzero or output_empty):
        pipeline.append("SUPERVISED_SHUTDOWN_CONTRACT_UNPROVEN")
    return list(dict.fromkeys(pipeline)), algorithm


def _required_result_pipeline_codes(value: Mapping[str, Any]) -> list[str] | None:
    execution = value.get("execution")
    if not isinstance(execution, Mapping):
        return None
    timed_out = execution.get("timed_out")
    if type(timed_out) is not bool:
        return None
    required: list[str] = []
    popen_count = (
        execution.get("supervisor_popen_invocations")
        if "supervisor_popen_invocations" in execution
        else execution.get("popen_invocations")
    )
    if (
        type(popen_count) is not int
        or popen_count != 1
        or execution.get("supervisor_error") is not None
        or execution.get("child_reaped") is not True
    ):
        required.append("SUPERVISOR_LAUNCH_OR_REAP_FAILED")
    residuals = execution.get("residual_attempt_processes", [])
    if not isinstance(residuals, list):
        return None
    if (
        execution.get("supervised_process_group_empty_after_wait") is not True
        or residuals
    ):
        required.append("SUPERVISED_SHUTDOWN_CONTRACT_UNPROVEN")
    arm = value.get("arm")
    if arm in {"learned_klt_vins", "pure_klt_vins"}:
        start = value.get("child_start")
        lifecycle = value.get("child_lifecycle")
        trajectory = value.get("trajectory")
        if not all(
            isinstance(candidate, Mapping)
            for candidate in (start, lifecycle, trajectory)
        ):
            return None
        if start.get("valid") is not True:
            required.append("ESTIMATOR_START_IDENTITY_UNPROVEN")
        lifecycle_semantics = _vins_lifecycle_semantics(value, timed_out)
        if lifecycle_semantics is None:
            return None
        required.extend(lifecycle_semantics[0])
        lifecycle_values = lifecycle.get("values")
        trajectory_nonempty = trajectory.get("file_nonempty")
        if type(trajectory_nonempty) is not bool:
            return None
        if not timed_out and isinstance(lifecycle_values, Mapping):
            lifecycle_nonempty = lifecycle_values.get("output_nonempty")
            if lifecycle_nonempty in {"0", "1"} and (
                (lifecycle_nonempty == "1") is not trajectory_nonempty
            ):
                required.append("SUPERVISED_SHUTDOWN_CONTRACT_UNPROVEN")
        raw_returncode = execution.get("raw_returncode")
        if (
            raw_returncode != 0
            and not timed_out
            and lifecycle.get("valid") is True
        ):
            required.append("WRAPPER_NONZERO_DESPITE_VALID_LIFECYCLE")
    elif isinstance(arm, str) and arm.startswith("hfnet_openloop_"):
        launch = value.get("launch_receipt")
        watchdog = value.get("zero_kf_post_shutdown_watchdog_decision")
        support = value.get("support")
        if (
            not isinstance(launch, Mapping)
            or not isinstance(watchdog, Mapping)
            or not isinstance(support, Mapping)
            or not isinstance(support.get("log"), Mapping)
        ):
            return None
        if launch.get("valid") is not True:
            required.append("ESTIMATOR_START_IDENTITY_UNPROVEN")
        if watchdog.get("monitor_proven") is not True:
            required.append("ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN")
        log = support["log"]
        environment_events = log.get("environment_failure_events", [])
        if not isinstance(environment_events, list):
            return None
        if (
            execution.get("raw_returncode") not in (None, 0)
            and not timed_out
            and watchdog.get("sigterm_sent") is not True
            and environment_events
        ):
            required.append("GPU_DRIVER_OR_RUNTIME_LOAD_FAILURE")
    else:
        return None
    return list(dict.fromkeys(required))


def _result_algorithm_semantics(
    value: Mapping[str, Any],
) -> tuple[list[str], bool] | None:
    """Independently replay each runner's ordered algorithm decision rules."""

    execution = value.get("execution")
    if not isinstance(execution, Mapping):
        return None
    timed_out = execution.get("timed_out")
    raw_returncode = execution.get("raw_returncode")
    if type(timed_out) is not bool or type(raw_returncode) not in (int, type(None)):
        return None
    arm = value.get("arm")
    if not isinstance(arm, str):
        budget = value.get("budget")
        if type(budget) is int:
            arm = f"hfnet_openloop_{budget}"
    expected: list[str] = []

    if arm in {"learned_klt_vins", "pure_klt_vins"}:
        trajectory = value.get("trajectory")
        log = value.get("log")
        lifecycle = value.get("child_lifecycle")
        if not all(isinstance(item, Mapping) for item in (trajectory, log, lifecycle)):
            return None
        lifecycle_semantics = _vins_lifecycle_semantics(value, timed_out)
        if lifecycle_semantics is None:
            return None
        if timed_out:
            expected.append("ESTIMATOR_OR_REPLAY_TIMEOUT")
        expected.extend(lifecycle_semantics[1])
        if trajectory.get("valid") is not True:
            expected.append("TRAJECTORY_INVALID")
        if type(trajectory.get("file_nonempty")) is not bool:
            return None
        pose_count = _nonnegative_count(trajectory, "pose_count")
        if pose_count is None or (
            trajectory.get("valid") is True
            and (trajectory.get("file_nonempty") is not True or pose_count < 1)
        ):
            return None
        coverage = _finite_number(trajectory.get("coverage_fraction", 0.0))
        contiguous = _finite_number(
            trajectory.get("longest_contiguous_fraction", 0.0)
        )
        if (
            coverage is None
            or contiguous is None
            or not 0.0 <= coverage <= 1.0
            or not 0.0 <= contiguous <= coverage
        ):
            return None
        if coverage < 0.50 or contiguous < 0.50:
            expected.append("TRAJECTORY_COVERAGE_BELOW_50_PERCENT")
        elif coverage < 0.70 or contiguous < 0.70:
            expected.append("PARTIAL_TRAJECTORY_COVERAGE_BELOW_70_PERCENT")
        if log.get("valid") is not True:
            expected.append("VINS_LOG_MISSING_OR_INVALID")
        initialization_count = _nonnegative_count(log, "initialization_count")
        init_parse_count = _nonnegative_count(log, "initialization_time_parse_count")
        init_latency = value.get("initialization_latency_seconds")
        if (
            initialization_count is None
            or init_parse_count is None
            or (init_latency is not None and _finite_number(init_latency) is None)
        ):
            return None
        if "initialization_latency_seconds" in log and not strict_json_equal(
            log.get("initialization_latency_seconds"), init_latency
        ):
            return None
        if initialization_count == 0 or init_latency is None:
            expected.append("NO_PROVEN_SUCCESSFUL_INITIALIZATION")
        elif float(init_latency) < 0:
            expected.append("NEGATIVE_INITIALIZATION_LATENCY")
        elif float(init_latency) > 10.0:
            expected.append("INITIALIZATION_AFTER_10_SECONDS")
        if init_parse_count != initialization_count:
            expected.append("INITIALIZATION_SIM_TIME_UNPARSEABLE")
        count_keys = (
            "reinitialization_in_support_count",
            "reinitialization_unresolved_postinit_count",
            "failure_detection_count",
            "nonfinite_log_event_count",
            "reboot_or_reset_in_support_count",
            "reboot_or_reset_unresolved_postinit_count",
            "solver_risk_in_support_count",
            "solver_risk_unresolved_postinit_count",
            "reinitialization_count",
            "solver_risk_count",
            "reboot_or_reset_count",
        )
        counts = {key: _nonnegative_count(log, key) for key in count_keys}
        if any(candidate is None for candidate in counts.values()):
            return None
        if counts["reinitialization_in_support_count"] or counts[
            "reinitialization_unresolved_postinit_count"
        ]:
            expected.append("REINITIALIZATION_WITHIN_OR_UNRESOLVED_SUPPORT")
        if counts["failure_detection_count"]:
            expected.append("FAILURE_DETECTION_EVENT")
        if counts["nonfinite_log_event_count"]:
            expected.append("NONFINITE_EVENT_IN_ESTIMATOR_LOG")
        if counts["reboot_or_reset_in_support_count"] or counts[
            "reboot_or_reset_unresolved_postinit_count"
        ]:
            expected.append(
                "RESET_OR_RESTART_WITHIN_OR_UNRESOLVED_AFTER_INITIALIZATION"
            )
        if counts["solver_risk_in_support_count"] or counts[
            "solver_risk_unresolved_postinit_count"
        ]:
            expected.append(
                "SOLVER_RISK_WITHIN_OR_UNRESOLVED_AFTER_INITIALIZATION"
            )
        clean_base = bool(
            initialization_count == 1
            and counts["reinitialization_count"] == 0
            and counts["solver_risk_count"] == 0
            and counts["reboot_or_reset_count"] == 0
            and counts["failure_detection_count"] == 0
            and counts["nonfinite_log_event_count"] == 0
        )
        return expected, clean_base

    if isinstance(arm, str) and arm.startswith("hfnet_openloop_"):
        support = value.get("support")
        watchdog = value.get("zero_kf_post_shutdown_watchdog_decision")
        if not isinstance(support, Mapping) or not isinstance(watchdog, Mapping):
            return None
        trajectory = support.get("trajectory")
        keyframes = support.get("keyframes")
        log = support.get("log")
        events = support.get("events")
        if not all(
            isinstance(item, Mapping)
            for item in (trajectory, keyframes, log, events)
        ):
            return None
        watchdog_sent = watchdog.get("sigterm_sent")
        if type(watchdog_sent) is not bool:
            return None
        if watchdog_sent:
            expected.append("CONFIRMED_ZERO_KF_POST_SHUTDOWN_SAVE_HANG")
        if timed_out:
            expected.append("ESTIMATOR_TIMEOUT")
        environment_events = log.get("environment_failure_events", [])
        if not isinstance(environment_events, list):
            return None
        if (
            raw_returncode not in (None, 0)
            and not timed_out
            and not watchdog_sent
            and not environment_events
        ):
            expected.append("ESTIMATOR_NONZERO_EXIT")
        if trajectory.get("valid") is not True:
            expected.append("TRAJECTORY_INVALID")
        trajectory_pose_count = _nonnegative_count(trajectory, "pose_count")
        if trajectory_pose_count is None or (
            trajectory.get("valid") is True and trajectory_pose_count < 1
        ):
            return None
        coverage = _finite_number(trajectory.get("coverage_fraction", 0.0))
        contiguous = _finite_number(
            trajectory.get("longest_contiguous_fraction", 0.0)
        )
        if (
            coverage is None
            or contiguous is None
            or not 0.0 <= coverage <= 1.0
            or not 0.0 <= contiguous <= coverage
        ):
            return None
        if coverage < 0.50 or contiguous < 0.50:
            expected.append("TRAJECTORY_COVERAGE_BELOW_50_PERCENT")
        elif coverage < 0.70 or contiguous < 0.70:
            expected.append("PARTIAL_TRAJECTORY_COVERAGE_BELOW_70_PERCENT")
        keyframe_count = _nonnegative_count(keyframes, "pose_count")
        if keyframe_count is None:
            return None
        if keyframes.get("valid") is not True or keyframe_count < 1:
            expected.append("NO_VALID_KEYFRAME_TRAJECTORY")
        if log.get("valid") is not True or log.get("final_atlas_nonempty") is not True:
            expected.append("FINAL_ATLAS_EMPTY_OR_UNPARSEABLE")
        init_latency = value.get("initialization_latency_seconds")
        if init_latency is None:
            expected.append("NO_SUCCESSFUL_INITIALIZATION")
        else:
            numeric_latency = _finite_number(init_latency)
            if numeric_latency is None or numeric_latency < 0:
                return None
            if numeric_latency > 10.0:
                expected.append("INITIALIZATION_AFTER_10_SECONDS")
        for key in (
            "unresolved_resets", "unresolved_solver_risks",
            "support_reinitializations",
        ):
            if not isinstance(events.get(key), list):
                return None
        if events["unresolved_resets"]:
            expected.append("ACTIVE_MAP_RESET_BOUNDARY_UNRESOLVED")
        if events["unresolved_solver_risks"]:
            expected.append("SOLVER_OR_TRACKING_RISK_BOUNDARY_UNRESOLVED")
        if events["support_reinitializations"]:
            expected.append("REINITIALIZATION_WITHIN_ACCEPTED_SUPPORT")
        loop_count = _nonnegative_count(log, "loop_event_text_count")
        reset_count = _nonnegative_count(log, "active_map_reset_count")
        risk_count = _nonnegative_count(log, "solver_risk_count")
        reinit_count = _nonnegative_count(log, "reinitialization_count")
        init_ids = log.get("init_frame_ids")
        if (
            loop_count is None
            or reset_count is None
            or risk_count is None
            or reinit_count is None
            or not isinstance(init_ids, list)
            or any(type(candidate) is not int or candidate < 0 for candidate in init_ids)
        ):
            return None
        if loop_count:
            expected.append("LOOP_EVENT_OBSERVED_DESPITE_OPEN_LOOP_CONFIG")
        clean_base = bool(
            reset_count == 0
            and risk_count == 0
            and reinit_count == 0
            and len(init_ids) == 1
        )
        return expected, clean_base
    return None


def result_contract_valid(value: Mapping[str, Any]) -> bool:
    """Verify status and clean success from parsed estimator evidence."""
    lists: list[list[str]] = []
    for key in (
        "failure_codes",
        "pipeline_failure_codes",
        "algorithm_failure_codes",
    ):
        candidate = value.get(key)
        if (
            not isinstance(candidate, list)
            or any(not isinstance(code, str) or not code for code in candidate)
            or len(candidate) != len(set(candidate))
        ):
            return False
        lists.append(candidate)
    failures, pipeline, algorithm = lists
    if failures != pipeline + algorithm or set(pipeline).intersection(algorithm):
        return False
    execution = value.get("execution")
    semantics = _result_algorithm_semantics(value)
    required_pipeline = _required_result_pipeline_codes(value)
    if (
        not isinstance(execution, Mapping)
        or execution.get("postprocess_signals_deferred") != []
        or semantics is None
        or required_pipeline is None
    ):
        return False
    expected_algorithm, clean_base = semantics
    if algorithm != expected_algorithm:
        return False
    if any(code not in pipeline for code in required_pipeline):
        return False
    if pipeline:
        expected_status = "PIPELINE_INVALID"
    elif not algorithm:
        expected_status = "SUCCESS"
    elif algorithm == ["PARTIAL_TRAJECTORY_COVERAGE_BELOW_70_PERCENT"]:
        expected_status = "PARTIAL_NON_SUCCESS"
    else:
        expected_status = "ALGORITHM_FAILURE"
    clean_success = value.get("clean_success")
    popen_count = (
        execution.get("supervisor_popen_invocations")
        if "supervisor_popen_invocations" in execution
        else execution.get("popen_invocations")
    )
    terminal_execution_clean = bool(
        execution.get("supervisor_error") is None
        and execution.get("child_reaped") is True
        and execution.get("supervised_process_group_empty_after_wait") is True
        and type(popen_count) is int
        and popen_count == 1
        and not execution.get("residual_attempt_processes", [])
    )
    if not pipeline and not terminal_execution_clean:
        return False
    if expected_status in {"SUCCESS", "PARTIAL_NON_SUCCESS"} and (
        execution.get("timed_out") is not False
        or execution.get("raw_returncode") != 0
    ):
        return False
    expected_clean = expected_status == "SUCCESS" and clean_base
    return (
        value.get("status") == expected_status
        and type(clean_success) is bool
        and clean_success is expected_clean
    )


def _semantic_artifact_state(path: Path) -> dict[str, object]:
    absolute = Path(os.path.abspath(path))
    require_no_symlink_components(absolute, Path(absolute.anchor))
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise OrdinalError(f"SEMANTIC_ARTIFACT_NONREGULAR:{path}")
    if not path.is_file():
        return {"path": str(path), "state": "ABSENT"}
    observed = identity(path)
    return {"state": "FILE", **observed}


def require_semantic_artifact_snapshot(
    snapshot: Mapping[str, Any],
) -> None:
    """Require every raw result-bearing artifact to retain the pinned state."""
    if not isinstance(snapshot, Mapping) or not snapshot:
        raise OrdinalError("SEMANTIC_ARTIFACT_SNAPSHOT_INVALID")
    for label, recorded in snapshot.items():
        if (
            not isinstance(label, str)
            or not label
            or not isinstance(recorded, Mapping)
            or not isinstance(recorded.get("path"), str)
            or recorded.get("state") not in {"FILE", "ABSENT"}
            or not strict_json_equal(
                recorded, _semantic_artifact_state(Path(recorded["path"]))
            )
        ):
            raise OrdinalError(f"SEMANTIC_ARTIFACT_SNAPSHOT_DRIFT:{label}")


def validate_result_semantic_evidence(
    root: Path,
    result: Mapping[str, Any],
    cell: Mapping[str, Any],
    attempt_index: int,
) -> dict[str, object]:
    """Reparse raw trajectories/logs and bind every stability fact to bytes."""
    if not _coordinate_matches(result, cell, attempt_index):
        raise OrdinalError(f"SEMANTIC_RESULT_COORDINATE_DRIFT:{root}")
    arm = str(cell["arm"])
    if arm in {"learned_klt_vins", "pure_klt_vins"}:
        if len(root.parents) < 5:
            raise OrdinalError(f"SEMANTIC_ATTEMPT_LAYOUT_INVALID:{root}")
        experiment_root = root.parents[4]
        selected_expected = (
            experiment_root / "input_freeze" / str(cell["case_id"])
            / "cam0_times_vins_matched.txt"
        )
    elif arm.startswith("hfnet_openloop_"):
        if len(root.parents) < 3:
            raise OrdinalError(f"SEMANTIC_ATTEMPT_LAYOUT_INVALID:{root}")
        experiment_root = root.parents[2]
        selected_expected = root / "cam0_times_vins_matched.txt"
    else:
        raise OrdinalError(f"SEMANTIC_ARM_INVALID:{arm}")
    if Path(os.path.abspath(root)) != Path(
        os.path.abspath(attempt_root(experiment_root, cell, attempt_index))
    ):
        raise OrdinalError(f"SEMANTIC_ATTEMPT_LAYOUT_INVALID:{root}")
    require_no_symlink_components(root, experiment_root)
    manifest_path = root / "attempt_manifest.json"
    require_no_symlink_components(manifest_path, root)
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise OrdinalError(f"SEMANTIC_ATTEMPT_MANIFEST_INVALID:{manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OrdinalError(
            f"SEMANTIC_ATTEMPT_MANIFEST_UNREADABLE:{manifest_path}"
        ) from error
    selected_record = manifest.get("selected_times") if isinstance(manifest, Mapping) else None
    if (
        not isinstance(selected_record, Mapping)
        or not isinstance(selected_record.get("path"), str)
    ):
        raise OrdinalError(f"SEMANTIC_SELECTED_TIMES_RECORD_INVALID:{manifest_path}")
    selected_path = Path(selected_record["path"])
    if Path(os.path.abspath(selected_path)) != Path(os.path.abspath(selected_expected)):
        raise OrdinalError(
            f"SEMANTIC_SELECTED_TIMES_PATH_INVALID:{selected_path}"
        )
    require_no_symlink_components(selected_path, experiment_root)
    try:
        selected_identity_matches = identity_matches(selected_record, selected_path)
    except OrdinalError as error:
        raise OrdinalError(
            f"SEMANTIC_SELECTED_TIMES_IDENTITY_DRIFT:{selected_path}"
        ) from error
    if not selected_identity_matches:
        raise OrdinalError(
            f"SEMANTIC_SELECTED_TIMES_IDENTITY_DRIFT:{selected_path}"
        )
    paths: dict[str, Path] = {
        "attempt_manifest": manifest_path,
        "selected_times": selected_path,
    }
    if arm in {"learned_klt_vins", "pure_klt_vins"}:
        paths.update(
            {
                "trajectory": root / "vins_output/vio.csv",
                "estimator_log": root / "vins.log",
                "child_start": root / "child_start_receipt.txt",
                "child_lifecycle": root / "child_lifecycle.txt",
                "supervisor_stdout": root / "supervisor.stdout.log",
                "supervisor_stderr": root / "supervisor.stderr.log",
            }
        )
    elif arm.startswith("hfnet_openloop_"):
        paths.update(
            {
                "trajectory": root / "result/trajectory.txt",
                "keyframe_trajectory": root / "result/trajectory_keyframe.txt",
                "estimator_stdout": root / "headless.stdout.log",
                "estimator_stderr": root / "headless.stderr.log",
                "launch_receipt": root / "launch_receipt.json",
                "zero_kf_watchdog": root / "zero_kf_post_shutdown_watchdog.json",
            }
        )
    for label, path in paths.items():
        if label != "selected_times":
            require_no_symlink_components(path, root)
    initial_snapshot = {
        label: _semantic_artifact_state(path) for label, path in paths.items()
    }
    try:
        if arm in {"learned_klt_vins", "pure_klt_vins"}:
            from run_fair_stability_vins_replay_v10 import (
                parse_child_lifecycle,
                parse_vins_log,
                parse_vio,
                read_ns_lines,
            )

            stamps = read_ns_lines(selected_path)
            trajectory = parse_vio(paths["trajectory"], stamps)
            support_indices = trajectory.get(
                "longest_contiguous_relative_indices_inclusive"
            )
            support_seconds: tuple[float, float] | None = None
            if (
                isinstance(support_indices, list)
                and len(support_indices) == 2
                and all(type(candidate) is int for candidate in support_indices)
            ):
                support_seconds = (
                    stamps[support_indices[0]] / 1e9,
                    stamps[support_indices[1]] / 1e9,
                )
            log = parse_vins_log(paths["estimator_log"], stamps[0], support_seconds)
            lifecycle = parse_child_lifecycle(
                paths["child_lifecycle"], result.get("child_start", {})
            )
            if (
                not strict_json_equal(trajectory, result.get("trajectory"))
                or not strict_json_equal(log, result.get("log"))
                or not strict_json_equal(lifecycle, result.get("child_lifecycle"))
                or not strict_json_equal(
                    log.get("initialization_latency_seconds"),
                    result.get("initialization_latency_seconds"),
                )
            ):
                raise OrdinalError(f"SEMANTIC_VINS_REPARSE_DRIFT:{root}")
        else:
            from run_fair_stability_hfnet_openloop_v10 import (
                accepted_events,
                parse_log,
                parse_trajectory,
                read_ns_lines,
            )

            stamps = read_ns_lines(selected_path)
            trajectory = parse_trajectory(paths["trajectory"], stamps)
            keyframes = parse_trajectory(paths["keyframe_trajectory"], stamps)
            log = parse_log(
                paths["estimator_stdout"], paths["estimator_stderr"], len(stamps)
            )
            events = accepted_events(log, trajectory)
            init_ids = [
                int(candidate)
                for candidate in log.get("init_frame_ids", [])
                if 0 <= int(candidate) < len(stamps)
            ]
            init_latency = (
                (stamps[init_ids[0]] - stamps[0]) / 1e9 if init_ids else None
            )
            expected_support = {
                "trajectory": trajectory,
                "keyframes": keyframes,
                "log": log,
                "events": events,
            }
            if (
                not strict_json_equal(expected_support, result.get("support"))
                or not strict_json_equal(
                    init_latency, result.get("initialization_latency_seconds")
                )
            ):
                raise OrdinalError(f"SEMANTIC_HFNET_REPARSE_DRIFT:{root}")
    except OrdinalError:
        raise
    except BaseException as error:
        raise OrdinalError(
            f"SEMANTIC_RAW_EVIDENCE_UNREADABLE:{root}:{type(error).__name__}:{error}"
        ) from error
    final_snapshot = {
        label: _semantic_artifact_state(path) for label, path in paths.items()
    }
    if not strict_json_equal(initial_snapshot, final_snapshot):
        raise OrdinalError(f"SEMANTIC_ARTIFACT_CHANGED_DURING_REPARSE:{root}")
    return final_snapshot


def validate_runtime_resource_monitor_evidence(
    root: Path,
    result: Mapping[str, Any],
    cell: Mapping[str, Any],
    attempt_index: int,
) -> dict[str, object]:
    """Validate the frozen monitor receipt before classifying an attempt.

    Runner summaries are not trusted.  GPU classifications are replayed from
    the complete recorded query stdout.  Proc samples deliberately retain a
    selective projection (owned, supervised-group, and forbidden processes),
    not every /proc row, so the controller verifies that frozen trusted
    producer's shape, ownership lineage, partition, error, and count-lower-bound
    consistency; it cannot independently prove that the historical /proc
    enumeration omitted no unrelated row.  Any unproven monitor condition is a
    fail-stop pipeline result, and v10 has no replacement attempts.
    """

    path = root / "runtime_resource_monitor.json"
    try:
        if path.is_symlink() or not path.is_file():
            raise OrdinalError(f"IDENTITY_FILE_INVALID:{path}")
        raw_receipt = path.read_bytes()
        current_identity = {
            "path": str(path),
            "size_bytes": len(raw_receipt),
            "sha256": hashlib.sha256(raw_receipt).hexdigest(),
        }
        if not strict_json_equal(current_identity, identity(path)):
            raise OrdinalError(
                f"RUNTIME_RESOURCE_MONITOR_CHANGED_DURING_READ:{path}"
            )
        value = json.loads(raw_receipt.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, OrdinalError) as error:
        raise OrdinalError(
            f"RUNTIME_RESOURCE_MONITOR_UNREADABLE:{path}:{type(error).__name__}"
        ) from error
    if not isinstance(value, Mapping):
        raise OrdinalError(f"RUNTIME_RESOURCE_MONITOR_NOT_OBJECT:{path}")
    bound_vins_manifest_identity: dict[str, object] | None = None

    def finish_validation() -> dict[str, object]:
        try:
            final_identity = identity(path)
        except (OSError, OrdinalError) as error:
            raise OrdinalError(
                f"RUNTIME_RESOURCE_MONITOR_CHANGED_DURING_VALIDATION:{path}"
            ) from error
        if not strict_json_equal(final_identity, current_identity):
            raise OrdinalError(
                f"RUNTIME_RESOURCE_MONITOR_CHANGED_DURING_VALIDATION:{path}"
            )
        if (
            bound_vins_manifest_identity is not None
            and not strict_json_equal(
                bound_vins_manifest_identity,
                identity(root / "attempt_manifest.json"),
            )
        ):
            raise OrdinalError(
                "RUNTIME_RESOURCE_MONITOR_VINS_MANIFEST_CHANGED_DURING_VALIDATION:"
                f"{root / 'attempt_manifest.json'}"
            )
        return current_identity

    execution = result.get("execution")
    integrity = result.get("integrity")
    pipeline_codes = result.get("pipeline_failure_codes")
    hfnet_arm = str(cell["arm"]).startswith("hfnet_openloop_")
    if (
        not isinstance(execution, Mapping)
        or not isinstance(integrity, Mapping)
        or not isinstance(pipeline_codes, list)
    ):
        raise OrdinalError(f"RUNTIME_RESOURCE_MONITOR_RESULT_SHAPE_INVALID:{root}")
    execution_errors = execution.get("runtime_resource_monitor_errors")
    if (
        not isinstance(execution_errors, list)
        or any(not isinstance(error, str) or not error for error in execution_errors)
    ):
        raise OrdinalError(f"RUNTIME_RESOURCE_MONITOR_EXECUTION_ERRORS_INVALID:{root}")

    expected_pid: int | None = None
    expected_start_ticks: int | None = None
    expected_pgid: int | None = None
    vins_child_start: Mapping[str, Any] | None = None
    vins_child_values: Mapping[str, Any] | None = None
    vins_child_path = root / "child_start_receipt.txt"
    vins_child_present = False
    if hfnet_arm:
        decision = result.get("runtime_resource_monitor_decision")
        recorded_identity = result.get("runtime_resource_monitor")
        pins = (recorded_identity, integrity.get("runtime_resource_monitor"))
        launch_path = root / "launch_receipt.json"
        if launch_path.is_file() and not launch_path.is_symlink():
            try:
                launch = json.loads(launch_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise OrdinalError(
                    f"RUNTIME_RESOURCE_MONITOR_LAUNCH_UNREADABLE:{launch_path}"
                ) from error
            if isinstance(launch, Mapping):
                pid = launch.get("pid")
                ticks = launch.get("start_ticks")
                pgid = launch.get("pgid")
                if type(pid) is int and pid > 0:
                    expected_pid = pid
                if type(ticks) is int and ticks > 0:
                    expected_start_ticks = ticks
                if type(pgid) is int and pgid > 0:
                    expected_pgid = pgid
        if not isinstance(decision, Mapping) or set(decision) != {
            "intrusion_detected", "monitor_proven", "pipeline_failure_reasons"
        }:
            raise OrdinalError(f"RUNTIME_RESOURCE_MONITOR_DECISION_INVALID:{root}")
    else:
        summary = result.get("runtime_resource_monitor")
        if not isinstance(summary, Mapping) or set(summary) != {
            "identity", "intrusion_detected", "monitor_proven",
            "pipeline_failure_reasons",
        }:
            raise OrdinalError(f"RUNTIME_RESOURCE_MONITOR_SUMMARY_INVALID:{root}")
        decision = summary
        pins = (
            summary.get("identity"),
            execution.get("runtime_resource_monitor"),
            integrity.get("runtime_resource_monitor"),
        )
        child_start = result.get("child_start")
        if (
            not isinstance(child_start, Mapping)
            or set(child_start) != {"valid", "errors", "values", "identity"}
            or type(child_start.get("valid")) is not bool
            or not isinstance(child_start.get("errors"), list)
            or any(
                not isinstance(error, str) or not error
                for error in child_start.get("errors", [])
            )
            or not isinstance(child_start.get("values"), Mapping)
            or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in child_start.get("values", {}).items()
            )
        ):
            raise OrdinalError(
                f"RUNTIME_RESOURCE_MONITOR_CHILD_START_RESULT_INVALID:{root}"
            )
        vins_child_start = child_start
        vins_child_values = child_start["values"]
        vins_child_value_keys = {
            "schema_version", "experiment_id", "tag", "wrapper_pid",
            "wrapper_start_ticks", "wrapper_pgid", "roscore_pid",
            "roscore_start_ticks", "roscore_executable", "roscore_command",
            "roscore_pgid", "vins_pid", "vins_start_ticks",
            "vins_pgid_start", "vins_executable_expected",
            "vins_executable_observed", "vins_command_observed",
            "source_camera_config", "runtime_camera_config",
            "runtime_camera_config_size_bytes", "runtime_camera_config_sha256",
            "runtime_camera_config_matches_source", "ros_master_uri",
        }
        if vins_child_path.is_symlink() or (
            vins_child_path.exists() and not vins_child_path.is_file()
        ):
            raise OrdinalError(
                f"RUNTIME_RESOURCE_MONITOR_CHILD_START_NONREGULAR:{vins_child_path}"
            )
        vins_child_present = vins_child_path.is_file()
        if vins_child_present:
            try:
                parsed_values, parsed_errors = parse_key_value_receipt_evidence(
                    vins_child_path
                )
                manifest_path = root / "attempt_manifest.json"
                if manifest_path.is_symlink() or not manifest_path.is_file():
                    raise OrdinalError(
                        f"RUNTIME_RESOURCE_MONITOR_VINS_MANIFEST_INVALID:{manifest_path}"
                    )
                raw_manifest = manifest_path.read_bytes()
                bound_vins_manifest_identity = {
                    "path": str(manifest_path),
                    "size_bytes": len(raw_manifest),
                    "sha256": hashlib.sha256(raw_manifest).hexdigest(),
                }
                if not strict_json_equal(
                    bound_vins_manifest_identity, identity(manifest_path)
                ):
                    raise OrdinalError(
                        "RUNTIME_RESOURCE_MONITOR_VINS_MANIFEST_CHANGED_DURING_READ:"
                        f"{manifest_path}"
                    )
                vins_manifest = json.loads(raw_manifest.decode("utf-8"))
            except (OSError, UnicodeError) as error:
                raise OrdinalError(
                    "RUNTIME_RESOURCE_MONITOR_CHILD_START_UNREADABLE:"
                    f"{vins_child_path}:{type(error).__name__}"
                ) from error
            except json.JSONDecodeError as error:
                raise OrdinalError(
                    "RUNTIME_RESOURCE_MONITOR_VINS_MANIFEST_UNREADABLE:"
                    f"{manifest_path}:{type(error).__name__}"
                ) from error
            source_camera = (
                vins_manifest.get("source_camera_config")
                if isinstance(vins_manifest, Mapping)
                else None
            )
            roscore_launch = (
                vins_manifest.get("roscore_launch_control")
                if isinstance(vins_manifest, Mapping)
                else None
            )
            if (
                not isinstance(vins_manifest, Mapping)
                or not isinstance(source_camera, Mapping)
                or not isinstance(source_camera.get("path"), str)
                or type(source_camera.get("size_bytes")) is not int
                or source_camera.get("size_bytes") < 0
                or not isinstance(source_camera.get("sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", source_camera["sha256"])
                is None
                or not isinstance(vins_manifest.get("tag"), str)
                or not vins_manifest.get("tag")
                or type(vins_manifest.get("port")) is not int
                or not 1 <= vins_manifest["port"] <= 65535
                or not isinstance(roscore_launch, Mapping)
                or set(roscore_launch) != {
                    "command_interpreter", "resolved_interpreter", "script"
                }
                or roscore_launch.get("command_interpreter") != "/usr/bin/python3"
                or not isinstance(roscore_launch.get("resolved_interpreter"), Mapping)
                or not isinstance(roscore_launch.get("script"), Mapping)
            ):
                raise OrdinalError(
                    f"RUNTIME_RESOURCE_MONITOR_VINS_MANIFEST_SHAPE_INVALID:{manifest_path}"
                )
            try:
                parsed_wrapper_pid = int(parsed_values.get("wrapper_pid", ""))
            except ValueError:
                parsed_wrapper_pid = -1
            expected_executable = (
                "/mnt/data/AQUA-FE_WS/tmp/mimir_current_schedfix_ws/"
                "devel/lib/vins/vins_node"
            )
            expected_config = str(root / "vins_runtime_config.yaml")
            expected_camera = str(
                root / Path(str(source_camera["path"])).name
            )
            expected_child_values = {
                "schema_version": "aqua-fe-fair-stability-vins-child-start-v10",
                "experiment_id": EXPERIMENT_ID,
                "vins_executable_expected": expected_executable,
                "vins_executable_observed": expected_executable,
                "vins_pgid_start": str(parsed_wrapper_pid),
                "roscore_pgid": str(parsed_wrapper_pid),
                "wrapper_pid": str(parsed_wrapper_pid),
                "wrapper_pgid": str(parsed_wrapper_pid),
                "source_camera_config": str(source_camera["path"]),
                "runtime_camera_config": expected_camera,
                "runtime_camera_config_size_bytes": str(
                    source_camera["size_bytes"]
                ),
                "runtime_camera_config_sha256": str(source_camera["sha256"]),
                "runtime_camera_config_matches_source": "1",
            }
            recomputed_child_errors = list(parsed_errors)
            for key, expected_value in expected_child_values.items():
                if parsed_values.get(key) != expected_value:
                    recomputed_child_errors.append(
                        "VALUE_MISMATCH:"
                        f"{key}:{parsed_values.get(key)}:{expected_value}"
                    )
            for key in (
                "wrapper_start_ticks", "roscore_pid", "roscore_start_ticks",
                "vins_pid", "vins_start_ticks",
            ):
                if (
                    not parsed_values.get(key, "").isdigit()
                    or int(parsed_values[key]) <= 0
                ):
                    recomputed_child_errors.append(
                        f"INVALID_POSITIVE_INTEGER:{key}:{parsed_values.get(key)}"
                    )
            parsed_pids: list[int] = []
            for key in ("wrapper_pid", "roscore_pid", "vins_pid"):
                try:
                    parsed_pids.append(int(parsed_values.get(key, "")))
                except ValueError:
                    parsed_pids.append(-1)
            if len(set(parsed_pids)) != 3 or any(pid <= 0 for pid in parsed_pids):
                recomputed_child_errors.append("CHILD_PROCESS_PIDS_NOT_DISTINCT")
            expected_roscore_interpreter = Path(
                str(roscore_launch["resolved_interpreter"].get("path", ""))
            )
            expected_roscore_script = Path(
                str(roscore_launch["script"].get("path", ""))
            )
            if (
                not identity_matches(
                    roscore_launch["resolved_interpreter"],
                    expected_roscore_interpreter,
                )
                or not identity_matches(
                    roscore_launch["script"], expected_roscore_script
                )
                or expected_roscore_script
                != Path("/opt/ros/noetic/bin/roscore")
                or expected_roscore_interpreter
                != Path("/usr/bin/python3").resolve(strict=True)
            ):
                recomputed_child_errors.append("ROSCORE_LAUNCH_CONTROL_DRIFT")
            expected_roscore_executable = str(expected_roscore_interpreter)
            if parsed_values.get("roscore_executable") != expected_roscore_executable:
                recomputed_child_errors.append("ROSCORE_EXECUTABLE_INVALID")
            if parsed_values.get("roscore_command", "").split() != [
                "/usr/bin/python3",
                str(expected_roscore_script),
                "-p",
                str(vins_manifest["port"]),
            ]:
                recomputed_child_errors.append("ROSCORE_COMMAND_MISMATCH")
            observed_command = parsed_values.get(
                "vins_command_observed", ""
            ).split()
            if observed_command != [expected_executable, expected_config]:
                recomputed_child_errors.append("VINS_COMMAND_MISMATCH")
            if (
                not identity_matches(child_start.get("identity"), vins_child_path)
                or not strict_json_equal(vins_child_values, parsed_values)
                or not strict_json_equal(
                    child_start.get("errors"), recomputed_child_errors
                )
                or child_start.get("valid") is not (not recomputed_child_errors)
                or set(parsed_values) != vins_child_value_keys
                or parsed_values.get("schema_version")
                != "aqua-fe-fair-stability-vins-child-start-v10"
                or parsed_values.get("experiment_id") != EXPERIMENT_ID
                or parsed_values.get("tag") != vins_manifest.get("tag")
                or parsed_values.get("ros_master_uri")
                != f"http://localhost:{vins_manifest['port']}"
            ):
                raise OrdinalError(
                    "RUNTIME_RESOURCE_MONITOR_CHILD_START_EVIDENCE_DRIFT:"
                    f"{vins_child_path}"
                )
        elif (
            child_start.get("identity") is not None
            or child_start.get("valid") is not False
            or child_start.get("values") != {}
            or not any(
                str(error).startswith("MISSING:child_start_receipt.txt")
                for error in child_start.get("errors", [])
            )
        ):
            raise OrdinalError(
                f"RUNTIME_RESOURCE_MONITOR_CHILD_START_MISSING_DRIFT:{vins_child_path}"
            )
        child_values = vins_child_values
        if isinstance(child_values, Mapping):
            try:
                pid = int(str(child_values.get("wrapper_pid", "")))
                ticks = int(str(child_values.get("wrapper_start_ticks", "")))
                pgid = int(str(child_values.get("wrapper_pgid", "")))
            except ValueError:
                pid = ticks = pgid = -1
            if pid > 0:
                expected_pid = pid
            if ticks > 0:
                expected_start_ticks = ticks
            if pgid > 0:
                expected_pgid = pgid

    if any(not strict_json_equal(pin, current_identity) for pin in pins):
        raise OrdinalError(f"RUNTIME_RESOURCE_MONITOR_IDENTITY_DRIFT:{path}")

    reasons = value.get("pipeline_failure_reasons")
    intrusion = value.get("intrusion_detected")
    proven = value.get("monitor_proven")
    if (
        type(intrusion) is not bool
        or type(proven) is not bool
        or not isinstance(reasons, list)
        or any(not isinstance(reason, str) or not reason for reason in reasons)
        or len(reasons) != len(set(reasons))
    ):
        raise OrdinalError(f"RUNTIME_RESOURCE_MONITOR_CLASSIFICATION_INVALID:{path}")
    expected_decision = {
        "intrusion_detected": intrusion,
        "monitor_proven": proven,
        "pipeline_failure_reasons": reasons,
    }
    decision_projection = (
        {
            "intrusion_detected": decision.get("intrusion_detected"),
            "monitor_proven": decision.get("monitor_proven"),
            "pipeline_failure_reasons": decision.get(
                "pipeline_failure_reasons"
            ),
        }
        if isinstance(decision, Mapping)
        else None
    )
    if not strict_json_equal(decision_projection, expected_decision):
        raise OrdinalError(f"RUNTIME_RESOURCE_MONITOR_RESULT_DECISION_DRIFT:{path}")

    runtime_code_expected = (not proven) or bool(execution_errors)
    if (
        ("MIDRUN_EXTERNAL_RESOURCE_INTRUSION" in pipeline_codes) is not intrusion
        or ("RUNTIME_RESOURCE_MONITOR_UNPROVEN" in pipeline_codes)
        is not runtime_code_expected
    ):
        raise OrdinalError(f"RUNTIME_RESOURCE_MONITOR_RESULT_CODE_DRIFT:{path}")
    if (
        not hfnet_arm
        and proven
        and not runtime_code_expected
        and (
            not vins_child_present
            or vins_child_start is None
            or vins_child_start.get("valid") is not True
            or vins_child_start.get("errors") != []
            or expected_pid is None
            or expected_start_ticks is None
            or expected_pgid is None
        )
    ):
        raise OrdinalError(
            f"RUNTIME_RESOURCE_MONITOR_CHILD_START_REQUIRED_INVALID:{vins_child_path}"
        )

    fallback_keys = {
        "schema_version", "experiment_id", "finalized_at_utc",
        "supervised_pid", "intrusion_detected", "monitor_proven",
        "monitor_errors", "pipeline_failure_reasons", "all_intrusions",
        "fallback_receipt",
    }
    if value.get("fallback_receipt") is True:
        monitor_errors = value.get("monitor_errors")
        supervised_pid = value.get("supervised_pid")
        if (
            set(value) != fallback_keys
            or value.get("schema_version")
            != "aqua-fe-fair-stability-runtime-resource-monitor-v10"
            or value.get("experiment_id") != EXPERIMENT_ID
            or not valid_utc_receipt_timestamp(value.get("finalized_at_utc"))
            or intrusion is not False
            or proven is not False
            or reasons != ["RUNTIME_RESOURCE_MONITOR_UNPROVEN"]
            or value.get("all_intrusions") != []
            or not isinstance(monitor_errors, list)
            or not monitor_errors
            or any(not isinstance(error, str) or not error for error in monitor_errors)
            or type(supervised_pid) not in (int, type(None))
            or (type(supervised_pid) is int and supervised_pid <= 0)
            or (
                expected_pid is not None
                and supervised_pid is not None
                and supervised_pid != expected_pid
            )
            or result.get("status") != "PIPELINE_INVALID"
        ):
            raise OrdinalError(f"RUNTIME_RESOURCE_MONITOR_FALLBACK_INVALID:{path}")
        return finish_validation()

    full_keys = {
        "schema_version", "experiment_id", "created_at_utc", "coverage",
        "supervised_process", "sampling_contract", "probe_errors",
        "pre_samples", "post_samples", "samples", "observed_intrusions",
        "cleanup_actions", "intrusion_detected", "monitor_proven",
        "pipeline_valid", "pipeline_failure_reasons",
        "required_attempt_classification",
        "runtime_measurements_eligible_for_performance_claims",
    }
    if (
        set(value) != full_keys
        or value.get("schema_version")
        != "aqua-fe-fair-stability-runtime-resource-monitor-v10"
        or value.get("experiment_id") != EXPERIMENT_ID
        or not valid_utc_receipt_timestamp(value.get("created_at_utc"))
    ):
        raise OrdinalError(f"RUNTIME_RESOURCE_MONITOR_FULL_HEADER_INVALID:{path}")

    coverage = value.get("coverage")
    supervised = value.get("supervised_process")
    sampling = value.get("sampling_contract")
    samples = value.get("samples")
    pre_samples = value.get("pre_samples")
    post_samples = value.get("post_samples")
    observed_intrusions = value.get("observed_intrusions")
    probe_errors = value.get("probe_errors")
    cleanup_actions = value.get("cleanup_actions")
    coverage_keys = {
        "started_at_utc", "start_monotonic_ns", "start_semantics",
        "ended_at_utc", "end_monotonic_ns", "end_semantics",
        "duration_seconds", "process_group_empty",
    }
    supervised_keys = {
        "pid", "leader_identity", "leader_process_record_at_monitor_start",
        "pgid", "supervisor_pid", "returncode",
        "known_owned_identity_history", "ownership_discovery_history",
        "active_owned_identities_at_finalize",
    }
    if (
        not isinstance(coverage, Mapping)
        or set(coverage) != coverage_keys
        or not isinstance(supervised, Mapping)
        or set(supervised) != supervised_keys
        or not isinstance(sampling, Mapping)
        or set(sampling) != {"proc", "gpu"}
        or not isinstance(samples, Mapping)
        or set(samples) != {"proc", "gpu"}
        or not isinstance(pre_samples, Mapping)
        or set(pre_samples) != {"proc", "gpu"}
        or not isinstance(post_samples, Mapping)
        or set(post_samples) != {"proc", "gpu"}
        or not isinstance(observed_intrusions, Mapping)
        or set(observed_intrusions) != {
            "proc_occurrences", "gpu_occurrences", "stale_owned_gpu_rows",
            "external_gpu_todesk_exemption",
        }
        or not isinstance(probe_errors, list)
        or any(not isinstance(error, str) or not error for error in probe_errors)
        or probe_errors != sorted(set(probe_errors))
        or not isinstance(cleanup_actions, list)
        or any(not isinstance(action, Mapping) for action in cleanup_actions)
    ):
        raise OrdinalError(f"RUNTIME_RESOURCE_MONITOR_FULL_SHAPE_INVALID:{path}")

    known_owned_records = supervised.get("known_owned_identity_history")
    ownership_discovery_records = supervised.get("ownership_discovery_history")
    active_owned_records = supervised.get("active_owned_identities_at_finalize")
    if (
        not isinstance(known_owned_records, list)
        or not isinstance(ownership_discovery_records, list)
        or not isinstance(active_owned_records, list)
        or any(
            not isinstance(record, Mapping)
            or set(record) != {"pid", "start_ticks"}
            or type(record.get("pid")) is not int
            or record.get("pid") <= 0
            or type(record.get("start_ticks")) is not int
            or record.get("start_ticks") <= 0
            for record in known_owned_records + active_owned_records
        )
    ):
        raise OrdinalError(f"RUNTIME_RESOURCE_MONITOR_OWNERSHIP_SHAPE_INVALID:{path}")
    known_owned_pairs = [
        (record["pid"], record["start_ticks"])
        for record in known_owned_records
    ]
    active_owned_pairs = [
        (record["pid"], record["start_ticks"])
        for record in active_owned_records
    ]
    if (
        known_owned_pairs != sorted(set(known_owned_pairs))
        or active_owned_pairs != sorted(set(active_owned_pairs))
        or not set(active_owned_pairs).issubset(set(known_owned_pairs))
    ):
        raise OrdinalError(f"RUNTIME_RESOURCE_MONITOR_OWNERSHIP_DRIFT:{path}")
    known_owned_pair_set = set(known_owned_pairs)
    known_owned_pids = {pid for pid, _ticks in known_owned_pairs}
    if not hfnet_arm and vins_child_start is not None and vins_child_start.get("valid") is True:
        try:
            child_identity_pairs = {
                (
                    int(str(vins_child_values[f"{label}_pid"])),
                    int(str(vins_child_values[f"{label}_start_ticks"])),
                )
                for label in ("wrapper", "roscore", "vins")
            }
        except (KeyError, TypeError, ValueError) as error:
            raise OrdinalError(
                f"RUNTIME_RESOURCE_MONITOR_CHILD_OWNERSHIP_INVALID:{path}"
            ) from error
        if (
            len(child_identity_pairs) != 3
            or not child_identity_pairs.issubset(known_owned_pair_set)
        ):
            raise OrdinalError(
                f"RUNTIME_RESOURCE_MONITOR_CHILD_OWNERSHIP_DRIFT:{path}"
            )

    start_ns = coverage.get("start_monotonic_ns")
    end_ns = coverage.get("end_monotonic_ns")
    duration = coverage.get("duration_seconds")
    group_empty = coverage.get("process_group_empty")
    if (
        type(start_ns) is not int
        or start_ns <= 0
        or type(end_ns) is not int
        or end_ns < start_ns
        or type(duration) is not float
        or duration != (end_ns - start_ns) / 1e9
        or type(group_empty) is not bool
        or not valid_utc_receipt_timestamp(coverage.get("started_at_utc"))
        or not valid_utc_receipt_timestamp(coverage.get("ended_at_utc"))
        or coverage.get("start_semantics")
        != "RuntimeResourceMonitor constructed immediately after supervised Popen"
        or coverage.get("end_semantics")
        != (
            "supervised process group and known owned descendants empty and all probe reservations settled"
            if group_empty
            else "forced monitor finalization before clean coverage closure was proven"
        )
        or (
            not runtime_code_expected
            and group_empty
            is not execution.get("supervised_process_group_empty_after_wait")
        )
    ):
        raise OrdinalError(f"RUNTIME_RESOURCE_MONITOR_COVERAGE_INVALID:{path}")

    replayed_owned_pairs: list[tuple[int, int]] = []
    ownership_discovery_times: dict[tuple[int, int], int] = {}
    previous_discovery_ns: int | None = None
    for index, event in enumerate(ownership_discovery_records):
        if (
            not isinstance(event, Mapping)
            or set(event) != {
                "sequence", "observed_monotonic_ns", "source",
                "identity", "parent_identity",
            }
            or type(event.get("sequence")) is not int
            or event.get("sequence") != index
            or type(event.get("observed_monotonic_ns")) is not int
            or not start_ns <= event.get("observed_monotonic_ns") <= end_ns
            or not isinstance(event.get("identity"), Mapping)
            or set(event["identity"]) != {"pid", "start_ticks"}
            or type(event["identity"].get("pid")) is not int
            or event["identity"]["pid"] <= 0
            or type(event["identity"].get("start_ticks")) is not int
            or event["identity"]["start_ticks"] <= 0
        ):
            raise OrdinalError(
                f"RUNTIME_RESOURCE_MONITOR_OWNERSHIP_DISCOVERY_INVALID:{path}:{index}"
            )
        identity_pair = (
            event["identity"]["pid"], event["identity"]["start_ticks"]
        )
        observed_discovery_ns = int(event["observed_monotonic_ns"])
        if (
            previous_discovery_ns is not None
            and observed_discovery_ns < previous_discovery_ns
        ):
            raise OrdinalError(
                f"RUNTIME_RESOURCE_MONITOR_OWNERSHIP_TIME_DRIFT:{path}:{index}"
            )
        if identity_pair in replayed_owned_pairs:
            raise OrdinalError(
                f"RUNTIME_RESOURCE_MONITOR_OWNERSHIP_DISCOVERY_DUPLICATE:{path}:{index}"
            )
        parent = event.get("parent_identity")
        if index == 0:
            if (
                event.get("source") != "LEADER_AT_MONITOR_START"
                or event.get("observed_monotonic_ns") != start_ns
                or parent is not None
                or not strict_json_equal(event.get("identity"), supervised.get("leader_identity"))
            ):
                raise OrdinalError(
                    f"RUNTIME_RESOURCE_MONITOR_OWNERSHIP_LEADER_DRIFT:{path}"
                )
        else:
            if (
                event.get("source") not in {
                    "EXACT_LIVE_PARENT_RECHECK",
                    "STABLE_SCAN_CHILD_EXITED_AFTER_PARENT_RECHECK",
                }
                or not isinstance(parent, Mapping)
                or set(parent) != {"pid", "start_ticks"}
                or type(parent.get("pid")) is not int
                or type(parent.get("start_ticks")) is not int
                or (parent["pid"], parent["start_ticks"])
                not in replayed_owned_pairs
                or observed_discovery_ns
                < ownership_discovery_times[(parent["pid"], parent["start_ticks"])]
                or parent["pid"] == identity_pair[0]
            ):
                raise OrdinalError(
                    f"RUNTIME_RESOURCE_MONITOR_OWNERSHIP_PARENT_DRIFT:{path}:{index}"
                )
        replayed_owned_pairs.append(identity_pair)
        ownership_discovery_times[identity_pair] = observed_discovery_ns
        previous_discovery_ns = observed_discovery_ns
    if (
        sorted(replayed_owned_pairs) != known_owned_pairs
        or bool(replayed_owned_pairs) is not isinstance(
            supervised.get("leader_identity"), Mapping
        )
    ):
        raise OrdinalError(
            f"RUNTIME_RESOURCE_MONITOR_OWNERSHIP_REPLAY_DRIFT:{path}"
        )

    try:
        from fair_stability_runtime_resource_monitor_v10 import (
            GPU_MAX_START_GAP_SECONDS,
            GPU_TARGET_INTERVAL_SECONDS,
            PROC_MAX_START_GAP_SECONDS,
            PROC_TARGET_INTERVAL_SECONDS,
            _is_forbidden_process,
            _parse_gpu_applications,
            _sampling_gap_report,
        )
    except ImportError as error:  # pragma: no cover - frozen environment gate
        raise OrdinalError("RUNTIME_RESOURCE_MONITOR_CONTROL_IMPORT_FAILED") from error

    identity_row_keys = {"pid", "start_ticks"}
    offender_keys = {
        "pid", "start_ticks", "ppid", "pgid", "executable", "comm",
        "command", "cmdline_sha256", "read_errors",
    }
    gpu_application_keys = {
        "pid", "process_name", "used_memory_mib", "raw", "parse_errors",
    }

    def valid_identity_row(candidate: object) -> bool:
        return bool(
            isinstance(candidate, Mapping)
            and set(candidate) == identity_row_keys
            and type(candidate.get("pid")) is int
            and int(candidate["pid"]) > 0
            and type(candidate.get("start_ticks")) is int
            and int(candidate["start_ticks"]) > 0
        )

    def valid_offender(candidate: object) -> bool:
        if not isinstance(candidate, Mapping) or set(candidate) != offender_keys:
            return False
        executable = candidate.get("executable")
        comm = candidate.get("comm")
        read_errors = candidate.get("read_errors")
        return bool(
            type(candidate.get("pid")) is int
            and int(candidate["pid"]) > 0
            and type(candidate.get("start_ticks")) is int
            and int(candidate["start_ticks"]) > 0
            and type(candidate.get("ppid")) is int
            and int(candidate["ppid"]) >= 0
            and type(candidate.get("pgid")) is int
            and int(candidate["pgid"]) > 0
            and (executable is None or isinstance(executable, str))
            and (comm is None or isinstance(comm, str))
            and isinstance(candidate.get("command"), str)
            and isinstance(candidate.get("cmdline_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", candidate["cmdline_sha256"])
            is not None
            and isinstance(read_errors, list)
            and all(isinstance(error, str) and error for error in read_errors)
        )

    def valid_gpu_application(candidate: object) -> bool:
        if not isinstance(candidate, Mapping) or set(candidate) != gpu_application_keys:
            return False
        pid_candidate = candidate.get("pid")
        parse_errors = candidate.get("parse_errors")
        structurally_valid = bool(
            type(pid_candidate) in (int, type(None))
            and (pid_candidate is None or pid_candidate > 0)
            and (
                candidate.get("process_name") is None
                or isinstance(candidate.get("process_name"), str)
            )
            and (
                candidate.get("used_memory_mib") is None
                or isinstance(candidate.get("used_memory_mib"), str)
            )
            and isinstance(candidate.get("raw"), str)
            and isinstance(parse_errors, list)
            and all(isinstance(error, str) and error for error in parse_errors)
        )
        if not structurally_valid:
            return False
        try:
            reparsed = _parse_gpu_applications(str(candidate["raw"]))
        except (TypeError, ValueError):
            return False
        return strict_json_equal(reparsed, [dict(candidate)])

    def valid_gpu_classified(candidate: object, category: str) -> bool:
        if not isinstance(candidate, Mapping):
            return False
        base = {key: candidate.get(key) for key in gpu_application_keys}
        if not valid_gpu_application(base):
            return False
        base_keys = gpu_application_keys | {"classification"}
        read_errors = candidate.get("proc_identity_read_errors", [])
        if (
            not isinstance(read_errors, list)
            or any(not isinstance(error, str) or not error for error in read_errors)
        ):
            return False
        classification = candidate.get("classification")
        if category == "external":
            if classification == "EXTERNAL_GPU_PROCESS_EXACT_IDENTITY_NOT_OWNED":
                return bool(
                    set(candidate) == base_keys | {"process"}
                    and valid_offender(candidate.get("process"))
                    and candidate["process"].get("pid") == candidate.get("pid")
                    and (
                        candidate["process"].get("pid"),
                        candidate["process"].get("start_ticks"),
                    )
                    not in known_owned_pair_set
                )
            errors_present = "proc_identity_read_errors" in candidate
            return bool(
                classification
                == "EXTERNAL_GPU_PROCESS_PROC_IDENTITY_UNPROVEN"
                and set(candidate)
                in (
                    base_keys,
                    base_keys | {"proc_identity_read_errors"},
                )
                and (not errors_present or bool(read_errors))
                and (
                    candidate.get("pid") is None
                    or errors_present
                    or candidate.get("pid") not in known_owned_pids
                )
            )
        if category == "current":
            return bool(
                classification == "CURRENT_EXACT_KNOWN_OWNED_GPU_PROCESS"
                and set(candidate) == base_keys | {"process"}
                and valid_offender(candidate.get("process"))
                and candidate["process"].get("pid") == candidate.get("pid")
                and (
                    candidate["process"].get("pid"),
                    candidate["process"].get("start_ticks"),
                )
                in known_owned_pair_set
            )
        known_ticks = candidate.get("known_owned_start_ticks_for_pid")
        return bool(
            classification == "STALE_OWNED_GPU_ROW_PROC_ABSENT"
            and set(candidate) == base_keys | {"known_owned_start_ticks_for_pid"}
            and isinstance(known_ticks, list)
            and bool(known_ticks)
            and all(type(tick) is int and tick > 0 for tick in known_ticks)
            and known_ticks == sorted(set(known_ticks))
            and type(candidate.get("pid")) is int
            and known_ticks
            == sorted(
                ticks
                for pid, ticks in known_owned_pair_set
                if pid == candidate.get("pid")
            )
        )

    def valid_gpu_partition(sample: Mapping[str, Any]) -> bool:
        compute = sample.get("compute_applications", [])
        external = sample.get("external_compute_applications", [])
        stale = sample.get("stale_owned_gpu_rows", [])
        current = sample.get("current_owned_gpu_rows", [])
        if any(
            not isinstance(rows, list)
            for rows in (compute, external, stale, current)
        ):
            return False

        def base_signature(candidate: Mapping[str, Any]) -> bytes:
            return canonical_json(
                {key: candidate.get(key) for key in gpu_application_keys}
            )

        observed_partition = sorted(
            base_signature(candidate)
            for candidate in external + stale + current
            if isinstance(candidate, Mapping)
        )
        expected_partition = sorted(
            base_signature(candidate)
            for candidate in compute
            if isinstance(candidate, Mapping)
        )
        expected_discovered = [
            {
                "pid": candidate["process"]["pid"],
                "start_ticks": candidate["process"]["start_ticks"],
            }
            for candidate in current
            if isinstance(candidate, Mapping)
            and isinstance(candidate.get("process"), Mapping)
        ]
        return bool(
            len(expected_partition) == len(compute)
            and len(observed_partition) == len(external + stale + current)
            and expected_partition == observed_partition
            and strict_json_equal(
                sample.get("discovered_owned_identities"), expected_discovered
            )
        )

    def valid_proc_sample(sample: Mapping[str, Any]) -> bool:
        if set(sample) != proc_sample_keys:
            return False
        errors = sample.get("probe_errors")
        owned = sample.get("owned_identities")
        group = sample.get("process_group_members")
        external = sample.get("external_conflicting_processes")
        process_count = sample.get("process_count")
        if (
            not isinstance(errors, list)
            or not isinstance(owned, list)
            or not isinstance(group, list)
            or not isinstance(external, list)
            or sample.get("supervised_pgid") != supervised.get("pgid")
        ):
            return False
        exception_errors = [
            error for error in errors
            if isinstance(error, str) and error.startswith("PROC_PROBE_EXCEPTION:")
        ]
        if process_count is None:
            return bool(
                len(errors) == 1
                and len(exception_errors) == 1
                and owned == []
                and group == []
                and external == []
            )
        if (
            type(process_count) is not int
            or process_count < 0
            or exception_errors
            or any(not valid_identity_row(candidate) for candidate in owned)
            or [
                (candidate["pid"], candidate["start_ticks"])
                for candidate in owned
            ]
            != sorted({
                (candidate["pid"], candidate["start_ticks"])
                for candidate in owned
            })
            or any(
                (candidate["pid"], candidate["start_ticks"])
                not in known_owned_pair_set
                for candidate in owned
            )
            or any(not valid_identity_row(candidate) for candidate in group)
            or [
                (candidate["pid"], candidate["start_ticks"])
                for candidate in group
            ]
            != sorted({
                (candidate["pid"], candidate["start_ticks"])
                for candidate in group
            })
            or any(not valid_offender(candidate) for candidate in external)
            or any(not _is_forbidden_process(candidate) for candidate in external)
            or any(
                (candidate["pid"], candidate["start_ticks"])
                in known_owned_pair_set
                for candidate in external
            )
            or any(
                candidate["pid"] == supervised.get("supervisor_pid")
                for candidate in external
            )
            or [
                (candidate["pid"], candidate["start_ticks"])
                for candidate in external
            ]
            != sorted({
                (candidate["pid"], candidate["start_ticks"])
                for candidate in external
            })
        ):
            return False
        owned_pairs = {
            (candidate["pid"], candidate["start_ticks"])
            for candidate in owned
        }
        group_pairs = [
            (candidate["pid"], candidate["start_ticks"])
            for candidate in group
        ]
        expected_group_errors = [
            f"UNOWNED_PROCESS_IN_SUPERVISED_GROUP:{pid}:{start_ticks}"
            for pid, start_ticks in group_pairs
            if (pid, start_ticks) not in known_owned_pair_set
        ]
        observed_group_errors = [
            error for error in errors
            if isinstance(error, str)
            and error.startswith("UNOWNED_PROCESS_IN_SUPERVISED_GROUP:")
        ]
        if observed_group_errors != expected_group_errors:
            return False
        identity_ticks_by_pid: dict[int, set[int]] = {}
        for pid, start_ticks in (
            list(owned_pairs)
            + group_pairs
            + [
                (candidate["pid"], candidate["start_ticks"])
                for candidate in external
            ]
        ):
            identity_ticks_by_pid.setdefault(pid, set()).add(start_ticks)
        if any(len(ticks) != 1 for ticks in identity_ticks_by_pid.values()):
            return False
        represented_pids = {
            candidate["pid"] for candidate in owned
        } | {candidate["pid"] for candidate in group} | {
            candidate["pid"] for candidate in external
        }
        return process_count >= len(represented_pids)

    def valid_gpu_probe_errors(sample: Mapping[str, Any]) -> bool:
        errors = sample.get("probe_errors")
        if not isinstance(errors, list):
            return False
        probe_exceptions = [
            error for error in errors
            if isinstance(error, str) and error.startswith("GPU_PROBE_EXCEPTION:")
        ]
        if probe_exceptions:
            return bool(
                len(errors) == 1
                and len(probe_exceptions) == 1
                and sample.get("query_returncode") is None
                and sample.get("query_stdout") == ""
                and sample.get("query_stderr") == ""
                and sample.get("query_error") is None
                and sample.get("compute_applications") == []
                and sample.get("external_compute_applications") == []
                and sample.get("stale_owned_gpu_rows") == []
                and sample.get("current_owned_gpu_rows") == []
                and sample.get("discovered_owned_identities") == []
            )
        expected: list[str] = []
        query_returncode = sample.get("query_returncode")
        if type(query_returncode) is int:
            expected_query_error = (
                None
                if query_returncode == 0
                else f"GPU_COMPUTE_QUERY_RETURN_CODE:{query_returncode}"
            )
            if sample.get("query_error") != expected_query_error:
                return False
            if expected_query_error is not None:
                expected.append(expected_query_error)
        elif query_returncode is None:
            query_error = sample.get("query_error")
            if not isinstance(query_error, str) or not (
                query_error == "GPU_COMPUTE_QUERY_TIMEOUT"
                or query_error.startswith("GPU_COMPUTE_QUERY_EXCEPTION:")
            ):
                return False
            if query_error.startswith("GPU_COMPUTE_QUERY_EXCEPTION:") and (
                sample.get("query_stdout") != ""
                or sample.get("query_stderr") != ""
                or sample.get("compute_applications") != []
                or sample.get("external_compute_applications") != []
                or sample.get("stale_owned_gpu_rows") != []
                or sample.get("current_owned_gpu_rows") != []
                or sample.get("discovered_owned_identities") != []
            ):
                return False
            expected.append(query_error)
        else:
            return False
        expected.extend(
            str(error)
            for row in sample.get("compute_applications", [])
            for error in row.get("parse_errors", [])
        )
        expected.extend(
            str(error)
            for category in (
                "external_compute_applications",
                "stale_owned_gpu_rows",
                "current_owned_gpu_rows",
            )
            for row in sample.get(category, [])
            for error in row.get("proc_identity_read_errors", [])
        )
        return errors == expected

    def valid_gpu_sample(sample: Mapping[str, Any]) -> bool:
        return bool(
            set(sample) == gpu_sample_keys
            and type(sample.get("query_returncode")) in (int, type(None))
            and not isinstance(sample.get("query_returncode"), bool)
            and isinstance(sample.get("query_stdout"), str)
            and isinstance(sample.get("query_stderr"), str)
            and (
                sample.get("query_error") is None
                or isinstance(sample.get("query_error"), str)
            )
            and isinstance(sample.get("compute_applications"), list)
            and strict_json_equal(
                sample.get("compute_applications"),
                _parse_gpu_applications(sample.get("query_stdout", "")),
            )
            and all(
                valid_gpu_application(candidate)
                for candidate in sample.get("compute_applications", [])
            )
            and isinstance(sample.get("external_compute_applications"), list)
            and isinstance(sample.get("stale_owned_gpu_rows"), list)
            and isinstance(sample.get("current_owned_gpu_rows"), list)
            and isinstance(sample.get("discovered_owned_identities"), list)
            and all(
                valid_gpu_classified(candidate, "external")
                for candidate in sample.get("external_compute_applications", [])
            )
            and all(
                valid_gpu_classified(candidate, "stale")
                for candidate in sample.get("stale_owned_gpu_rows", [])
            )
            and all(
                valid_gpu_classified(candidate, "current")
                for candidate in sample.get("current_owned_gpu_rows", [])
            )
            and all(
                valid_identity_row(candidate)
                for candidate in sample.get("discovered_owned_identities", [])
            )
            and valid_gpu_partition(sample)
            and valid_gpu_probe_errors(sample)
            and sample.get("external_gpu_todesk_exemption") is False
        )

    proc_sample_keys = {
        "sequence", "probe_started_at_utc", "probe_started_monotonic_ns",
        "probe_finished_monotonic_ns", "duration_seconds", "process_count",
        "owned_identities", "supervised_pgid", "process_group_members",
        "external_conflicting_processes", "probe_errors",
    }
    gpu_sample_keys = {
        "sequence", "probe_started_at_utc", "probe_started_monotonic_ns",
        "probe_finished_monotonic_ns", "duration_seconds", "query_returncode",
        "query_stdout", "query_stderr", "query_error",
        "compute_applications", "external_compute_applications",
        "stale_owned_gpu_rows", "current_owned_gpu_rows",
        "discovered_owned_identities", "external_gpu_todesk_exemption",
        "probe_errors",
    }
    sample_errors: list[str] = []
    for stream in ("proc", "gpu"):
        rows = samples.get(stream)
        if not isinstance(rows, list):
            raise OrdinalError(f"RUNTIME_RESOURCE_MONITOR_SAMPLES_INVALID:{path}:{stream}")
        for index, row in enumerate(rows):
            if (
                not isinstance(row, Mapping)
                or type(row.get("sequence")) is not int
                or row.get("sequence") != index
                or not valid_utc_receipt_timestamp(row.get("probe_started_at_utc"))
                or type(row.get("probe_started_monotonic_ns")) is not int
                or row.get("probe_started_monotonic_ns") <= 0
                or type(row.get("probe_finished_monotonic_ns")) is not int
                or not start_ns
                <= row.get("probe_started_monotonic_ns")
                <= row.get("probe_finished_monotonic_ns")
                <= end_ns
                or type(row.get("duration_seconds")) is not float
                or row.get("duration_seconds")
                != (
                    row.get("probe_finished_monotonic_ns")
                    - row.get("probe_started_monotonic_ns")
                ) / 1e9
                or not isinstance(row.get("probe_errors"), list)
                or any(
                    not isinstance(error, str) or not error
                    for error in row.get("probe_errors", [])
                )
                or (
                    stream == "proc"
                    and not valid_proc_sample(row)
                )
                or (
                    stream == "gpu"
                    and not valid_gpu_sample(row)
                )
            ):
                raise OrdinalError(
                    f"RUNTIME_RESOURCE_MONITOR_SAMPLE_ROW_INVALID:{path}:{stream}:{index}"
                )
            sample_errors.extend(str(error) for error in row.get("probe_errors", []))
        expected_sampling = _sampling_gap_report(
            rows,
            start_ns,
            end_ns,
            (
                PROC_TARGET_INTERVAL_SECONDS
                if stream == "proc"
                else GPU_TARGET_INTERVAL_SECONDS
            ),
            (
                PROC_MAX_START_GAP_SECONDS
                if stream == "proc"
                else GPU_MAX_START_GAP_SECONDS
            ),
        )
        if not strict_json_equal(sampling.get(stream), expected_sampling):
            raise OrdinalError(
                f"RUNTIME_RESOURCE_MONITOR_SAMPLING_RECOMPUTE_DRIFT:{path}:{stream}"
            )
        expected_pre = rows[0] if rows else None
        expected_post = rows[-1] if rows else None
        if (
            not strict_json_equal(pre_samples.get(stream), expected_pre)
            or not strict_json_equal(post_samples.get(stream), expected_post)
        ):
            raise OrdinalError(
                f"RUNTIME_RESOURCE_MONITOR_PRE_POST_DRIFT:{path}:{stream}"
            )
    if any(error not in probe_errors for error in sample_errors):
        raise OrdinalError(f"RUNTIME_RESOURCE_MONITOR_PROBE_ERROR_DRIFT:{path}")

    proc_occurrences = [
        dict(row)
        for sample in samples["proc"]
        for row in sample.get("external_conflicting_processes", [])
        if isinstance(row, Mapping)
    ]
    gpu_occurrences = [
        dict(row)
        for sample in samples["gpu"]
        for row in sample.get("external_compute_applications", [])
        if isinstance(row, Mapping)
    ]
    stale_rows = [
        dict(row)
        for sample in samples["gpu"]
        for row in sample.get("stale_owned_gpu_rows", [])
        if isinstance(row, Mapping)
    ]
    if (
        not strict_json_equal(
            observed_intrusions,
            {
                "proc_occurrences": proc_occurrences,
                "gpu_occurrences": gpu_occurrences,
                "stale_owned_gpu_rows": stale_rows,
                "external_gpu_todesk_exemption": False,
            },
        )
        or intrusion is not bool(proc_occurrences or gpu_occurrences)
    ):
        raise OrdinalError(f"RUNTIME_RESOURCE_MONITOR_INTRUSION_RECOMPUTE_DRIFT:{path}")

    recomputed_proven = bool(
        group_empty
        and not probe_errors
        and sampling["proc"].get("proven") is True
        and sampling["gpu"].get("proven") is True
    )
    expected_reasons: list[str] = []
    if intrusion:
        expected_reasons.append("MIDRUN_EXTERNAL_RESOURCE_INTRUSION")
    if not recomputed_proven:
        expected_reasons.append("RUNTIME_RESOURCE_MONITOR_UNPROVEN")
    if (
        proven is not recomputed_proven
        or reasons != expected_reasons
        or value.get("pipeline_valid") is not (not expected_reasons)
        or value.get("required_attempt_classification")
        != ("PIPELINE_INVALID" if expected_reasons else "NO_RESOURCE_MONITOR_INVALIDATION")
        or value.get("runtime_measurements_eligible_for_performance_claims") is not False
    ):
        raise OrdinalError(f"RUNTIME_RESOURCE_MONITOR_DECISION_RECOMPUTE_DRIFT:{path}")

    pid = supervised.get("pid")
    leader_identity = supervised.get("leader_identity")
    pgid = supervised.get("pgid")
    returncode = supervised.get("returncode")
    known_owned = supervised.get("known_owned_identity_history")
    active_owned = supervised.get("active_owned_identities_at_finalize")
    known_pairs = [
        (record.get("pid"), record.get("start_ticks"))
        for record in known_owned
        if isinstance(record, Mapping)
    ] if isinstance(known_owned, list) else []
    active_pairs = [
        (record.get("pid"), record.get("start_ticks"))
        for record in active_owned
        if isinstance(record, Mapping)
    ] if isinstance(active_owned, list) else []
    if (
        type(pid) is not int
        or pid <= 0
        or type(supervised.get("supervisor_pid")) is not int
        or supervised.get("supervisor_pid") <= 0
        or type(returncode) not in (int, type(None))
        or type(execution.get("raw_returncode")) not in (int, type(None))
        or not strict_json_equal(returncode, execution.get("raw_returncode"))
        or not isinstance(known_owned, list)
        or not isinstance(active_owned, list)
        or any(
            not isinstance(record, Mapping)
            or set(record) != {"pid", "start_ticks"}
            or type(record.get("pid")) is not int
            or record.get("pid") <= 0
            or type(record.get("start_ticks")) is not int
            or record.get("start_ticks") <= 0
            for record in known_owned + active_owned
        )
        or known_pairs != sorted(set(known_pairs))
        or active_pairs != sorted(set(active_pairs))
        or not set(active_pairs).issubset(set(known_pairs))
        or group_empty and active_owned != []
    ):
        raise OrdinalError(f"RUNTIME_RESOURCE_MONITOR_PROCESS_SHAPE_INVALID:{path}")
    if expected_pid is not None and pid != expected_pid:
        raise OrdinalError(f"RUNTIME_RESOURCE_MONITOR_PID_DRIFT:{path}")
    if proven:
        leader_record = supervised.get("leader_process_record_at_monitor_start")
        if (
            expected_pid is None
            or expected_start_ticks is None
            or expected_pgid is None
            or not strict_json_equal(
                leader_identity,
                {"pid": expected_pid, "start_ticks": expected_start_ticks},
            )
            or pgid != expected_pgid
            or expected_pgid != expected_pid
            or not valid_offender(leader_record)
            or leader_record.get("read_errors") != []
            or leader_record.get("pid") != expected_pid
            or leader_record.get("start_ticks") != expected_start_ticks
            or leader_record.get("pgid") != expected_pgid
            or leader_record.get("ppid") != supervised.get("supervisor_pid")
            or {"pid": expected_pid, "start_ticks": expected_start_ticks}
            not in known_owned
        ):
            raise OrdinalError(f"RUNTIME_RESOURCE_MONITOR_PROCESS_BINDING_DRIFT:{path}")
    return finish_validation()


def expected_runner_returncode_for_status(status: object) -> int | None:
    """Map an immutable result status to the runner process exit contract."""
    if status == "SUCCESS":
        return 0
    if status in TERMINAL_STATUSES or status == "PIPELINE_INVALID":
        return 3
    return None


def validate_controller_dispatch_execution_for_result(
    experiment_root: Path,
    root: Path,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind a published result to the one runner exit that produced it.

    Pre-start dispatches may leave earlier execution receipts without a
    result.  Exactly one (the latest) receipt must bind the immutable result,
    its status, and the status-derived runner return code.  This closes the
    interval between exclusive result publication and actual runner exit.
    """
    require_no_symlink_components(root, experiment_root)
    candidates = sorted(root.glob("controller_dispatch_execution_*.json"))
    if not candidates:
        raise OrdinalError(f"CONTROLLER_DISPATCH_EXECUTION_MISSING:{root}")
    expected_names = [
        f"controller_dispatch_execution_{index:03d}.json"
        for index in range(1, len(candidates) + 1)
    ]
    if [path.name for path in candidates] != expected_names:
        raise OrdinalError(f"CONTROLLER_DISPATCH_EXECUTION_SEQUENCE_INVALID:{root}")

    result_path = root / "run_result.json"
    dispatch_claim_path = root / "ordinal_dispatch_claim.json"
    controller_path = Path(__file__).resolve().parent / "run_fair_stability_next_v10.py"
    bound: list[tuple[Path, dict[str, Any]]] = []
    for index, path in enumerate(candidates, 1):
        require_no_symlink_components(path, experiment_root)
        if path.is_symlink() or not path.is_file():
            raise OrdinalError(f"CONTROLLER_DISPATCH_EXECUTION_FILE_INVALID:{path}")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise OrdinalError(
                f"CONTROLLER_DISPATCH_EXECUTION_JSON_INVALID:{path}"
            ) from error
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != CONTROLLER_DISPATCH_EXECUTION_SCHEMA
            or value.get("experiment_id") != EXPERIMENT_ID
            or value.get("dispatch_index") != index
            or not identity_matches(value.get("dispatch_claim"), dispatch_claim_path)
            or not identity_matches(value.get("controller"), controller_path)
        ):
            raise OrdinalError(
                f"CONTROLLER_DISPATCH_EXECUTION_HEADER_OR_CONTROL_DRIFT:{path}"
            )
        recorded_result = value.get("run_result")
        if recorded_result is None:
            if any(
                value.get(key) is not None
                for key in (
                    "run_result_status",
                    "expected_runner_returncode_from_result_status",
                    "runner_result_returncode_binding_valid",
                    "run_result_parse_error",
                )
            ):
                raise OrdinalError(
                    f"CONTROLLER_DISPATCH_EXECUTION_EMPTY_RESULT_FIELDS_INVALID:{path}"
                )
            continue
        if path != candidates[-1]:
            raise OrdinalError(
                f"CONTROLLER_DISPATCH_RESULT_NOT_LATEST_EXECUTION:{path}"
            )
        expected_returncode = expected_runner_returncode_for_status(
            result.get("status")
        )
        actual_returncode = value.get("returncode")
        if (
            expected_returncode is None
            or not identity_matches(recorded_result, result_path)
            or value.get("run_result_status") != result.get("status")
            or value.get("expected_runner_returncode_from_result_status")
            != expected_returncode
            or type(actual_returncode) is not int
            or actual_returncode != expected_returncode
            or value.get("runner_result_returncode_binding_valid") is not True
            or value.get("run_result_parse_error") is not None
        ):
            raise OrdinalError(
                f"CONTROLLER_DISPATCH_RUNNER_RESULT_EXIT_BINDING_INVALID:{path}"
            )
        bound.append((path, value))
    if len(bound) != 1:
        raise OrdinalError(
            f"CONTROLLER_DISPATCH_RESULT_BINDING_COUNT_INVALID:{root}:{len(bound)}"
        )
    path, value = bound[0]
    return {"path": str(path), "identity": identity(path), "receipt": value}


def _read_hfnet_watchdog_snapshot(
    path: Path,
    root: Path,
    recorded: object,
) -> tuple[object, dict[str, object]]:
    """Read, hash, size, and parse one immutable watchdog byte snapshot."""

    try:
        require_no_symlink_components(path, root)
        if path.is_symlink() or not path.is_file():
            raise OrdinalError(f"IDENTITY_FILE_INVALID:{path}")
        raw_watchdog = path.read_bytes()
    except (OSError, OrdinalError) as error:
        raise OrdinalError(
            f"HFNET_ZERO_KF_WATCHDOG_IDENTITY_DRIFT:{path}"
        ) from error
    validated_watchdog_identity = {
        "path": str(path),
        "size_bytes": len(raw_watchdog),
        "sha256": hashlib.sha256(raw_watchdog).hexdigest(),
    }
    if (
        not isinstance(recorded, Mapping)
        or not strict_json_equal(recorded, validated_watchdog_identity)
    ):
        raise OrdinalError(f"HFNET_ZERO_KF_WATCHDOG_IDENTITY_DRIFT:{path}")
    try:
        value = json.loads(raw_watchdog.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise OrdinalError(
            f"HFNET_ZERO_KF_WATCHDOG_UNREADABLE:{path}:{type(error).__name__}"
        ) from error
    return value, validated_watchdog_identity


def _require_hfnet_watchdog_snapshot_unchanged(
    path: Path,
    root: Path,
    validated_watchdog_identity: Mapping[str, object],
) -> None:
    """Recheck path components and the complete watchdog identity at the end."""

    try:
        require_no_symlink_components(path, root)
        final_watchdog_identity = identity(path)
    except (OSError, OrdinalError) as error:
        raise OrdinalError(
            f"HFNET_ZERO_KF_WATCHDOG_CHANGED_DURING_VALIDATION:{path}"
        ) from error
    if not strict_json_equal(
        final_watchdog_identity, validated_watchdog_identity
    ):
        raise OrdinalError(
            f"HFNET_ZERO_KF_WATCHDOG_CHANGED_DURING_VALIDATION:{path}"
        )


def validate_hfnet_watchdog_evidence(
    root: Path,
    manifest: Mapping[str, Any],
    result: Mapping[str, Any],
    cell: Mapping[str, Any],
    attempt_index: int,
) -> None:
    path = root / "zero_kf_post_shutdown_watchdog.json"
    value, validated_watchdog_identity = _read_hfnet_watchdog_snapshot(
        path,
        root,
        result.get("zero_kf_post_shutdown_watchdog"),
    )
    if not isinstance(value, Mapping):
        raise OrdinalError(f"HFNET_ZERO_KF_WATCHDOG_NOT_OBJECT:{path}")
    arm = str(cell["arm"])
    arm_prefix = "hfnet_openloop_"
    try:
        budget = int(arm[len(arm_prefix) :]) if arm.startswith(arm_prefix) else -1
    except ValueError as error:
        raise OrdinalError(f"HFNET_ZERO_KF_WATCHDOG_ARM_INVALID:{arm}") from error
    if arm not in {"hfnet_openloop_675", "hfnet_openloop_350"}:
        raise OrdinalError(f"HFNET_ZERO_KF_WATCHDOG_ARM_INVALID:{arm}")
    pins = value.get("pins")
    fixed_contract = manifest.get("zero_kf_post_shutdown_watchdog")
    expected_contract = {
        "enabled": True,
        "fixed_grace_seconds": 30.0,
        "target_poll_interval_seconds": 0.20,
        "maximum_poll_interval_seconds": 0.25,
        "maximum_final_gate_duration_seconds": 0.25,
        "signal": "SIGTERM",
        "signal_scope": "EXACT_REVALIDATED_PROCESS_GROUP",
        "signal_attempt_limit": 1,
        "sigkill_authorized_by_watchdog": False,
        "estimator_total_timeout_seconds": 1800,
        "applies_to_all_hfnet_budgets_windows_and_repeats": True,
    }
    expected_pins = {
        "attempt_manifest": root / "attempt_manifest.json",
        "start_claim": root / "start_claim.json",
        "launch_receipt": root / "launch_receipt.json",
        "stdout": root / "headless.stdout.log",
        "runtime_resource_monitor": root / "runtime_resource_monitor.json",
    }
    if (
        value.get("schema_version")
        != "aqua-fe-fair-stability-hfnet-zero-kf-post-shutdown-watchdog-v10"
        or value.get("experiment_id") != EXPERIMENT_ID
        or not valid_utc_receipt_timestamp(value.get("finalized_at_utc"))
        or not strict_json_equal(
            {
                "case_id": value.get("case_id"),
                "budget": value.get("budget"),
                "arm": value.get("arm"),
                "repeat": value.get("repeat"),
                "attempt_index": value.get("attempt_index"),
                "attempt_root": value.get("attempt_root"),
            },
            {
                "case_id": str(cell["case_id"]),
                "budget": budget,
                "arm": arm,
                "repeat": int(cell["repeat"]),
                "attempt_index": attempt_index,
                "attempt_root": str(root),
            },
        )
        or not strict_json_equal(
            value.get("fixed_contract"),
            fixed_contract,
        )
        or not isinstance(fixed_contract, Mapping)
        or not strict_json_equal(fixed_contract, expected_contract)
        or not isinstance(pins, Mapping)
        or any(
            not identity_matches(pins.get(label), candidate)
            for label, candidate in expected_pins.items()
        )
        or value.get("retry_permitted") is not False
        or value.get("sigkill_sent_by_watchdog") is not False
    ):
        raise OrdinalError(f"HFNET_ZERO_KF_WATCHDOG_CONTRACT_DRIFT:{path}")
    launch_contract = manifest.get("launch")
    launch_path = root / "launch_receipt.json"
    launch_receipt = json.loads(launch_path.read_text(encoding="utf-8"))
    expected_argv = (
        launch_contract.get("argv")
        if isinstance(launch_contract, Mapping)
        else None
    )
    expected_executable = (
        str(expected_argv[0])
        if isinstance(expected_argv, list) and expected_argv
        else None
    )
    expected_cmdline_sha256 = (
        hashlib.sha256(
            b"\0".join(os.fsencode(value) for value in expected_argv) + b"\0"
        ).hexdigest()
        if isinstance(expected_argv, list)
        and expected_argv
        and all(isinstance(value, str) for value in expected_argv)
        else None
    )
    launch_pid = launch_receipt.get("pid") if isinstance(launch_receipt, Mapping) else None
    launch_start_ticks = (
        launch_receipt.get("start_ticks")
        if isinstance(launch_receipt, Mapping)
        else None
    )
    if (
        not isinstance(launch_receipt, Mapping)
        or launch_receipt.get("schema_version")
        != "aqua-fe-fair-stability-hfnet-launch-receipt-v10"
        or launch_receipt.get("experiment_id") != EXPERIMENT_ID
        or launch_receipt.get("valid") is not True
        or launch_receipt.get("errors") != []
        or type(launch_pid) is not int
        or int(launch_pid) <= 0
        or type(launch_start_ticks) is not int
        or int(launch_start_ticks) <= 0
        or launch_receipt.get("pgid") != launch_pid
        or launch_receipt.get("session") != launch_pid
        or not isinstance(expected_argv, list)
        or not expected_argv
        or any(not isinstance(value, str) or not value for value in expected_argv)
        or launch_receipt.get("executable") != expected_executable
        or not strict_json_equal(launch_receipt.get("argv"), expected_argv)
        or launch_receipt.get("expected_executable") != expected_executable
        or not strict_json_equal(
            launch_receipt.get("expected_argv"), expected_argv
        )
    ):
        raise OrdinalError(f"HFNET_ZERO_KF_WATCHDOG_LAUNCH_DRIFT:{path}")
    pipeline_codes = result.get("pipeline_failure_codes", [])
    algorithm_codes = result.get("algorithm_failure_codes", [])
    proven = value.get("monitor_proven") is True
    sent = value.get("sigterm_sent") is True
    watchdog_errors = value.get("monitoring_errors")
    unproven_code = "ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN"
    algorithm_code = "CONFIRMED_ZERO_KF_POST_SHUTDOWN_SAVE_HANG"
    action = value.get("watchdog_action")
    outcome = value.get("outcome")
    final_gate_adjudication = value.get("final_signal_gate_adjudication")
    outcome_final_gate_adjudication = (
        outcome.get("final_signal_gate_adjudication")
        if isinstance(outcome, Mapping)
        else object()
    )
    final_gate_signature = (
        outcome.get("final_signal_gate_signature")
        if isinstance(outcome, Mapping)
        else object()
    )
    final_gate_signature_completed = (
        outcome.get("final_signal_gate_signature_completed_monotonic")
        if isinstance(outcome, Mapping)
        else object()
    )
    passive_exit = (
        outcome.get("passive_exit_adjudication")
        if isinstance(outcome, Mapping)
        else None
    )
    watchdog_child_returncode = value.get("final_child_returncode")
    outcome_child_returncode = (
        outcome.get("final_child_returncode")
        if isinstance(outcome, Mapping)
        else object()
    )
    final_outputs = value.get("final_outputs")
    decision = result.get("zero_kf_post_shutdown_watchdog_decision")
    outcome_errors = (
        outcome.get("monitoring_errors") if isinstance(outcome, Mapping) else None
    )
    signal_attempted = (
        outcome.get("signal_attempted") if isinstance(outcome, Mapping) else None
    )
    maximum_gap = (
        outcome.get("maximum_observed_poll_interval_seconds")
        if isinstance(outcome, Mapping)
        else None
    )
    continuous_seconds = (
        outcome.get("signature_continuous_seconds_at_end")
        if isinstance(outcome, Mapping)
        else None
    )
    pre_candidate_gap_count = (
        outcome.get("pre_candidate_gap_count")
        if isinstance(outcome, Mapping)
        else None
    )
    maximum_pre_candidate_gap = (
        outcome.get("maximum_pre_candidate_gap_seconds")
        if isinstance(outcome, Mapping)
        else None
    )
    confirmation_gap_reset_count = (
        outcome.get("confirmation_gap_reset_count")
        if isinstance(outcome, Mapping)
        else None
    )
    maximum_confirmation_gap = (
        outcome.get("maximum_confirmation_gap_seconds")
        if isinstance(outcome, Mapping)
        else None
    )
    confirmation_candidate_count = (
        outcome.get("confirmation_candidate_count")
        if isinstance(outcome, Mapping)
        else None
    )
    phase_gap_events = (
        outcome.get("phase_gap_events")
        if isinstance(outcome, Mapping)
        else None
    )
    current_trajectory_absent = not (
        (root / "result/trajectory.txt").exists()
        or (root / "result/trajectory.txt").is_symlink()
    )
    current_keyframe_absent = not (
        (root / "result/trajectory_keyframe.txt").exists()
        or (root / "result/trajectory_keyframe.txt").is_symlink()
    )
    numeric_outcome_valid = all(
        type(number) in (int, float)
        and math.isfinite(float(number))
        and float(number) >= 0.0
        for number in (maximum_gap, continuous_seconds)
    )
    runtime_receipt_path = root / "runtime_resource_monitor.json"
    runtime_receipt = json.loads(
        runtime_receipt_path.read_text(encoding="utf-8")
    )
    execution = result.get("execution")
    runtime_supervised = (
        runtime_receipt.get("supervised_process")
        if isinstance(runtime_receipt, Mapping)
        else None
    )
    runtime_coverage = (
        runtime_receipt.get("coverage")
        if isinstance(runtime_receipt, Mapping)
        else None
    )
    runtime_decision = result.get("runtime_resource_monitor_decision")
    runtime_reasons = (
        runtime_receipt.get("pipeline_failure_reasons")
        if isinstance(runtime_receipt, Mapping)
        else None
    )
    expected_runtime_reasons = []
    if isinstance(runtime_receipt, Mapping):
        if runtime_receipt.get("intrusion_detected") is True:
            expected_runtime_reasons.append("MIDRUN_EXTERNAL_RESOURCE_INTRUSION")
        if runtime_receipt.get("monitor_proven") is not True:
            expected_runtime_reasons.append("RUNTIME_RESOURCE_MONITOR_UNPROVEN")
    cleanup_actions = (
        runtime_receipt.get("cleanup_actions", [])
        if isinstance(runtime_receipt, Mapping)
        else None
    )
    watchdog_cleanup_actions = (
        [
            candidate
            for candidate in cleanup_actions
            if isinstance(candidate, Mapping)
            and candidate.get("label")
            == "confirmed_zero_kf_post_shutdown_watchdog"
        ]
        if isinstance(cleanup_actions, list)
        else None
    )
    natural_reaped_without_watchdog_signal = bool(
        proven
        and not sent
        and isinstance(execution, Mapping)
        and type(execution.get("raw_returncode")) is int
        and execution.get("child_reaped") is True
        and execution.get("timed_out") is False
    )

    proof_keys = {
        "observed_at_utc", "observed_monotonic_ns", "proven", "errors",
        "leader_pid", "leader_start_ticks", "expected_executable",
        "expected_argv", "pgid", "session", "members",
    }
    member_keys = {
        "pid", "start_ticks", "pgid", "session", "state", "executable",
        "cmdline_sha256",
    }
    stable_member_keys = (
        "pid", "start_ticks", "pgid", "session", "executable",
        "cmdline_sha256",
    )
    live_states = {"R", "S", "D", "T", "t", "K", "W", "P", "I"}

    def proof_monotonic_ns(proof: object) -> int | None:
        if not isinstance(proof, Mapping):
            return None
        observed = proof.get("observed_monotonic_ns")
        return int(observed) if type(observed) is int and observed > 0 else None

    def stable_member_projection(proof: object) -> list[dict[str, object]] | None:
        if not isinstance(proof, Mapping) or not isinstance(proof.get("members"), list):
            return None
        rows: list[dict[str, object]] = []
        for member in proof["members"]:
            if not isinstance(member, Mapping):
                return None
            rows.append({key: member.get(key) for key in stable_member_keys})
        return rows

    def proof_header_valid(proof: object) -> bool:
        return bool(
            isinstance(proof, Mapping)
            and set(proof) == proof_keys
            and valid_utc_receipt_timestamp(proof.get("observed_at_utc"))
            and proof_monotonic_ns(proof) is not None
            and proof.get("leader_pid") == launch_pid
            and proof.get("leader_start_ticks") == launch_start_ticks
            and proof.get("pgid") == launch_pid
            and proof.get("session") == launch_pid
            and proof.get("expected_executable") == expected_executable
            and strict_json_equal(proof.get("expected_argv"), expected_argv)
        )

    def valid_group_proof(proof: object) -> bool:
        if (
            not proof_header_valid(proof)
            or not isinstance(proof, Mapping)
            or proof.get("proven") is not True
            or proof.get("errors") != []
            or not isinstance(proof.get("members"), list)
            or not proof["members"]
        ):
            return False
        normalized: list[tuple[int, int]] = []
        observed_pids: set[int] = set()
        leader_members = 0
        for member in proof["members"]:
            if (
                not isinstance(member, Mapping)
                or set(member) != member_keys
                or type(member.get("pid")) is not int
                or int(member.get("pid", 0)) <= 0
                or type(member.get("start_ticks")) is not int
                or int(member.get("start_ticks", 0)) <= 0
                or member.get("pgid") != launch_pid
                or member.get("session") != launch_pid
                or member.get("state") not in live_states
                or not isinstance(member.get("executable"), str)
                or not member.get("executable")
                or not isinstance(member.get("cmdline_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", member["cmdline_sha256"])
                is None
            ):
                return False
            pair = (int(member["pid"]), int(member["start_ticks"]))
            if pair in normalized or pair[0] in observed_pids:
                return False
            normalized.append(pair)
            observed_pids.add(pair[0])
            if pair == (launch_pid, launch_start_ticks):
                if (
                    member.get("executable") != expected_executable
                    or member.get("cmdline_sha256") != expected_cmdline_sha256
                ):
                    return False
                leader_members += 1
        return leader_members == 1 and normalized == sorted(normalized)

    def valid_terminal_transition_proof(proof: object) -> bool:
        if (
            not proof_header_valid(proof)
            or not isinstance(proof, Mapping)
            or proof.get("proven") is not False
            or not isinstance(proof.get("members"), list)
        ):
            return False
        errors = proof.get("errors")
        members = proof["members"]
        if errors in (
            ["EXACT_GROUP_LEADER_COUNT:0"],
            ["EXACT_GROUP_LEADER_DISAPPEARED_DURING_RECHECK"],
        ):
            return members == []
        if (
            errors != ["EXACT_GROUP_LEADER_IDENTITY_OR_ARGV_MISMATCH"]
            or len(members) != 1
            or not isinstance(members[0], Mapping)
        ):
            return False
        member = members[0]
        return bool(
            set(member) == member_keys
            and member.get("pid") == launch_pid
            and member.get("start_ticks") == launch_start_ticks
            and member.get("pgid") == launch_pid
            and member.get("session") == launch_pid
            and isinstance(member.get("state"), str)
            and bool(member.get("state"))
            and member.get("executable") is None
            and member.get("cmdline_sha256") == hashlib.sha256(b"").hexdigest()
        )

    final_gate_timing_keys = {
        "deadline_monotonic",
        "final_gate_started_monotonic",
        "maximum_final_gate_duration_seconds",
        "pre_signal_monotonic",
        "final_gate_elapsed_seconds",
    }

    def finite_seconds(candidate: object) -> float | None:
        if type(candidate) not in (int, float):
            return None
        numeric = float(candidate)
        return numeric if math.isfinite(numeric) else None

    def failed_group_proof_valid(proof: object) -> bool:
        if (
            not proof_header_valid(proof)
            or not isinstance(proof, Mapping)
            or proof.get("proven") is not False
            or not isinstance(proof.get("errors"), list)
            or not proof["errors"]
            or any(not isinstance(error, str) or not error for error in proof["errors"])
            or not isinstance(proof.get("members"), list)
        ):
            return False
        observed_pids: set[int] = set()
        for member in proof["members"]:
            if (
                not isinstance(member, Mapping)
                or set(member) != member_keys
                or type(member.get("pid")) is not int
                or int(member.get("pid", 0)) <= 0
                or int(member["pid"]) in observed_pids
                or type(member.get("start_ticks")) is not int
                or int(member.get("start_ticks", 0)) <= 0
                or type(member.get("pgid")) is not int
                or type(member.get("session")) is not int
                or member.get("state") not in live_states | {"Z"}
                or (
                    member.get("executable") is not None
                    and not isinstance(member.get("executable"), str)
                )
                or not isinstance(member.get("cmdline_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", member["cmdline_sha256"])
                is None
            ):
                return False
            observed_pids.add(int(member["pid"]))
        return True

    def final_gate_timing_valid(candidate: object) -> bool:
        if (
            not isinstance(candidate, Mapping)
            or any(type(candidate.get(key)) is not float for key in final_gate_timing_keys)
            or type(final_gate_signature_completed) is not float
        ):
            return False
        deadline = finite_seconds(candidate.get("deadline_monotonic"))
        gate_started = finite_seconds(
            candidate.get("final_gate_started_monotonic")
        )
        maximum_duration = finite_seconds(
            candidate.get("maximum_final_gate_duration_seconds")
        )
        pre_signal = finite_seconds(candidate.get("pre_signal_monotonic"))
        elapsed = finite_seconds(candidate.get("final_gate_elapsed_seconds"))
        signature_completed = finite_seconds(final_gate_signature_completed)
        if any(
            value_candidate is None
            for value_candidate in (
                deadline,
                gate_started,
                maximum_duration,
                pre_signal,
                elapsed,
                signature_completed,
            )
        ):
            return False
        assert deadline is not None
        assert gate_started is not None
        assert maximum_duration is not None
        assert pre_signal is not None
        assert elapsed is not None
        assert signature_completed is not None
        return bool(
            gate_started == signature_completed
            and maximum_duration
            == float(fixed_contract["maximum_final_gate_duration_seconds"])
            and elapsed == pre_signal - gate_started
            and 0.0 < gate_started <= pre_signal
            and deadline > gate_started
            and elapsed >= 0.0
        )

    def ordered_gate_seconds(
        candidate: Mapping[str, Any],
        *proofs: object,
        observed_monotonic_ns: object | None = None,
        action_monotonic_ns: object | None = None,
    ) -> bool:
        gate_started = finite_seconds(
            candidate.get("final_gate_started_monotonic")
        )
        pre_signal = finite_seconds(candidate.get("pre_signal_monotonic"))
        if gate_started is None or pre_signal is None:
            return False
        ordered = [gate_started]
        for proof in proofs:
            observed = proof_monotonic_ns(proof)
            if observed is None:
                return False
            ordered.append(float(observed) / 1_000_000_000.0)
        if observed_monotonic_ns is not None:
            if type(observed_monotonic_ns) is not int or observed_monotonic_ns <= 0:
                return False
            ordered.append(float(observed_monotonic_ns) / 1_000_000_000.0)
        ordered.append(pre_signal)
        if any(right < left for left, right in zip(ordered, ordered[1:])):
            return False
        if action_monotonic_ns is not None:
            if type(action_monotonic_ns) is not int or action_monotonic_ns <= 0:
                return False
            if float(action_monotonic_ns) / 1_000_000_000.0 < pre_signal:
                return False
        return True

    def final_gate_adjudication_valid(candidate: object) -> bool:
        if (
            not isinstance(candidate, Mapping)
            or not final_gate_timing_valid(candidate)
            or not isinstance(candidate.get("classification"), str)
            or type(candidate.get("signal_attempted")) is not bool
            or type(candidate.get("signal_sent")) is not bool
            or not isinstance(candidate.get("errors"), list)
            or any(
                not isinstance(error, str) or not error
                for error in candidate.get("errors", [])
            )
        ):
            return False
        classification = candidate["classification"]
        signal_attempted_candidate = candidate["signal_attempted"]
        signal_sent_candidate = candidate["signal_sent"]
        deadline = float(candidate["deadline_monotonic"])
        pre_signal = float(candidate["pre_signal_monotonic"])
        maximum_duration = float(
            candidate["maximum_final_gate_duration_seconds"]
        )
        elapsed = float(candidate["final_gate_elapsed_seconds"])
        deadline_reached = pre_signal >= deadline
        duration_exceeded = elapsed > maximum_duration
        gate_within_contract = bool(
            not deadline_reached and not duration_exceeded
        )

        def expected_refusal_monitoring_errors(
            *non_timing_errors: str,
        ) -> list[str]:
            # The runner records the forced FINAL_GATE observation before it
            # validates the returned gate receipt.  A duration overrun is
            # therefore published first, followed by the receipt-level
            # deadline error and then any gate-local identity error.
            expected: list[str] = []
            if duration_exceeded:
                expected.append(
                    "FINAL_SIGNAL_GATE:WATCHDOG_FINAL_GATE_DURATION_EXCEEDED"
                )
            if deadline_reached:
                expected.append(
                    "FINAL_SIGNAL_GATE:WATCHDOG_DEADLINE_REACHED_BEFORE_SIGNAL"
                )
            expected.extend(
                f"FINAL_SIGNAL_GATE:{error}" for error in non_timing_errors
            )
            return list(dict.fromkeys(expected))

        def complete_gate_errors(*underlying_errors: str) -> list[str]:
            expected = list(underlying_errors)
            if duration_exceeded:
                expected.append("WATCHDOG_FINAL_GATE_DURATION_EXCEEDED")
            return list(dict.fromkeys(expected))

        def refused_gate_state_valid(
            *underlying_errors: str,
            receipt_errors: tuple[str, ...] = (),
        ) -> bool:
            expected_monitoring_errors = expected_refusal_monitoring_errors(
                *underlying_errors
            )
            expected_monitoring_errors.extend(receipt_errors)
            return bool(
                not proven
                and passive_exit is None
                and isinstance(outcome, Mapping)
                and outcome.get(
                    "permanently_disabled_after_unproven_evidence"
                )
                is True
                and watchdog_errors
                == list(dict.fromkeys(expected_monitoring_errors))
            )

        signal_action_keys = final_gate_timing_keys | {
            "classification", "at_utc", "monotonic_ns", "label", "signal",
            "signal_scope", "signal_attempted", "signal_sent", "group_sent",
            "group_error", "individual_identities_sent",
            "first_exact_group_proof", "final_exact_group_proof", "errors",
        }
        if signal_attempted_candidate:
            first = candidate.get("first_exact_group_proof")
            final = candidate.get("final_exact_group_proof")
            sent_candidate = signal_sent_candidate is True
            return bool(
                set(candidate) == signal_action_keys
                and gate_within_contract
                and classification
                == ("SIGTERM_SENT" if sent_candidate else "SIGNAL_DELIVERY_FAILED")
                and valid_utc_receipt_timestamp(candidate.get("at_utc"))
                and candidate.get("label")
                == "confirmed_zero_kf_post_shutdown_watchdog"
                and candidate.get("signal") == 15
                and candidate.get("signal_scope")
                == "EXACT_REVALIDATED_PROCESS_GROUP"
                and candidate.get("group_sent") is sent_candidate
                and candidate.get("individual_identities_sent") == []
                and (
                    candidate.get("group_error") is None
                    and candidate.get("errors") == []
                    if sent_candidate
                    else isinstance(candidate.get("group_error"), str)
                    and bool(candidate.get("group_error"))
                    and bool(candidate.get("errors"))
                    and all(
                        str(error).startswith("WATCHDOG_KILLPG_FAILED:")
                        for error in candidate.get("errors", [])
                    )
                )
                and valid_group_proof(first)
                and valid_group_proof(final)
                and strict_json_equal(
                    stable_member_projection(first),
                    stable_member_projection(final),
                )
                and ordered_gate_seconds(
                    candidate,
                    first,
                    final,
                    action_monotonic_ns=candidate.get("monotonic_ns"),
                )
                and (
                    sent_candidate
                    or refused_gate_state_valid(
                        *[str(error) for error in candidate.get("errors", [])],
                        receipt_errors=(
                            "WATCHDOG_SIGNAL_ATTEMPT_NOT_DELIVERED",
                        ),
                    )
                )
            )

        if signal_sent_candidate:
            return False
        phase = candidate.get("phase")
        if not isinstance(phase, str) or not phase:
            return False

        passive_base = final_gate_timing_keys | {
            "classification", "phase", "observed_at_utc",
            "observed_monotonic_ns", "leader_returncode",
            "reaped_before_next_sample", "reap", "signal_attempted", "signal_sent",
            "errors",
        }
        passive_extras = {
            "BEFORE_FIRST_FINAL_GROUP_PROOF": set(),
            "AFTER_FIRST_FINAL_GROUP_PROOF": {"terminal_transition_snapshot"},
            "AFTER_SECOND_FINAL_GROUP_PROOF": {
                "first_exact_group_proof", "terminal_transition_snapshot",
            },
            "BEFORE_KILLPG": {
                "first_exact_group_proof", "final_exact_group_proof",
            },
        }
        if classification == "LEADER_REAPED_BEFORE_SIGNAL":
            extras = passive_extras.get(phase)
            expected_gate_errors = complete_gate_errors()
            timing_refused = deadline_reached or duration_exceeded
            if (
                extras is None
                or set(candidate) != passive_base | extras
                or not valid_utc_receipt_timestamp(candidate.get("observed_at_utc"))
                or type(candidate.get("leader_returncode")) is not int
                or candidate.get("leader_returncode")
                != watchdog_child_returncode
                or candidate.get("reaped_before_next_sample") is not True
                or type(candidate.get("observed_monotonic_ns")) is not int
                or not valid_same_popen_reap(
                    candidate.get("reap"),
                    int(candidate.get("leader_returncode")),
                    int(candidate.get("observed_monotonic_ns", 0)),
                )
                or candidate.get("reap", {}).get("source")
                != "FINAL_GATE_POLL_THEN_WAIT_ZERO"
                or candidate.get("errors") != expected_gate_errors
                or (
                    timing_refused
                    and (
                        not refused_gate_state_valid()
                        or not isinstance(execution, Mapping)
                        or execution.get("child_reaped") is not True
                        or execution.get("timed_out") is not False
                    )
                )
                or (
                    not timing_refused
                    and (
                        not gate_within_contract
                        or candidate.get("errors") != []
                    )
                )
            ):
                return False
            if phase == "BEFORE_FIRST_FINAL_GROUP_PROOF":
                return ordered_gate_seconds(
                    candidate,
                    observed_monotonic_ns=candidate.get("observed_monotonic_ns"),
                )
            first = candidate.get("first_exact_group_proof")
            transition = candidate.get("terminal_transition_snapshot")
            if phase == "AFTER_FIRST_FINAL_GROUP_PROOF":
                return bool(
                    (valid_group_proof(transition)
                     or valid_terminal_transition_proof(transition))
                    and ordered_gate_seconds(
                        candidate,
                        transition,
                        observed_monotonic_ns=candidate.get(
                            "observed_monotonic_ns"
                        ),
                    )
                )
            if phase == "AFTER_SECOND_FINAL_GROUP_PROOF":
                return bool(
                    valid_group_proof(first)
                    and (valid_group_proof(transition)
                         or valid_terminal_transition_proof(transition))
                    and ordered_gate_seconds(
                        candidate,
                        first,
                        transition,
                        observed_monotonic_ns=candidate.get(
                            "observed_monotonic_ns"
                        ),
                    )
                )
            final = candidate.get("final_exact_group_proof")
            return bool(
                valid_group_proof(first)
                and valid_group_proof(final)
                and strict_json_equal(
                    stable_member_projection(first),
                    stable_member_projection(final),
                )
                and ordered_gate_seconds(
                    candidate,
                    first,
                    final,
                    observed_monotonic_ns=candidate.get("observed_monotonic_ns"),
                )
            )

        transition_base = final_gate_timing_keys | {
            "classification", "phase", "terminal_transition_snapshot",
            "signal_attempted", "signal_sent", "errors",
        }
        transition_extras = (
            set()
            if phase == "FIRST_FINAL_GROUP_PROOF"
            else {"first_exact_group_proof"}
            if phase == "SECOND_FINAL_GROUP_PROOF"
            else None
        )
        if classification == "TERMINAL_TRANSITION_PENDING_REAP":
            transition = candidate.get("terminal_transition_snapshot")
            first = candidate.get("first_exact_group_proof")
            underlying_errors = (
                list(transition.get("errors", []))
                if isinstance(transition, Mapping)
                else None
            )
            timing_refused = deadline_reached or duration_exceeded
            expected_errors = (
                complete_gate_errors(*underlying_errors)
                if isinstance(underlying_errors, list)
                else None
            )
            return bool(
                transition_extras is not None
                and set(candidate) == transition_base | transition_extras
                and valid_terminal_transition_proof(transition)
                and candidate.get("errors") == expected_errors
                and (
                    refused_gate_state_valid(*underlying_errors)
                    if timing_refused and isinstance(underlying_errors, list)
                    else gate_within_contract
                )
                and (
                    ordered_gate_seconds(candidate, transition)
                    if phase == "FIRST_FINAL_GROUP_PROOF"
                    else valid_group_proof(first)
                    and ordered_gate_seconds(candidate, first, transition)
                )
            )

        if classification != "LIVE_OR_UNKNOWN_GROUP_UNPROVEN":
            return False
        if phase == "FINAL_PRE_SIGNAL_GATE":
            first = candidate.get("first_exact_group_proof")
            final = candidate.get("final_exact_group_proof")
            expected_errors: list[str] = []
            first_projection = stable_member_projection(first)
            final_projection = stable_member_projection(final)
            membership_changed = bool(
                first_projection is not None
                and final_projection is not None
                and not strict_json_equal(first_projection, final_projection)
            )
            if membership_changed:
                expected_errors.append("FINAL_EXACT_GROUP_MEMBERSHIP_CHANGED")
            if deadline_reached:
                expected_errors.append("WATCHDOG_DEADLINE_REACHED_BEFORE_SIGNAL")
            if duration_exceeded:
                expected_errors.append(
                    "WATCHDOG_FINAL_GATE_DURATION_EXCEEDED"
                )
            final_pre_signal_keys = final_gate_timing_keys | {
                "classification", "phase", "first_exact_group_proof",
                "final_exact_group_proof", "signal_attempted", "signal_sent",
                "errors",
            }
            return bool(
                set(candidate) == final_pre_signal_keys
                and expected_errors
                and candidate.get("errors") == expected_errors
                and valid_group_proof(first)
                and valid_group_proof(final)
                and refused_gate_state_valid(
                    *(
                        ["FINAL_EXACT_GROUP_MEMBERSHIP_CHANGED"]
                        if membership_changed
                        else []
                    )
                )
                and ordered_gate_seconds(candidate, first, final)
            )
        leader_returncode_keys = {"leader_returncode"}
        live_variants: dict[str, tuple[set[str], tuple[str, ...]]] = {
            "FIRST_FINAL_GROUP_PROOF": (set(), ("transition",)),
            "AFTER_FIRST_FINAL_GROUP_PROOF": (
                leader_returncode_keys,
                ("transition",),
            ),
            "SECOND_FINAL_GROUP_PROOF": (
                {"first_exact_group_proof"},
                ("first", "transition"),
            ),
            "AFTER_SECOND_FINAL_GROUP_PROOF": (
                {"first_exact_group_proof"} | leader_returncode_keys,
                ("first", "transition"),
            ),
            "BEFORE_KILLPG": (
                {"first_exact_group_proof", "final_exact_group_proof"}
                | leader_returncode_keys,
                ("first", "final"),
            ),
        }
        variant = live_variants.get(phase)
        if variant is None:
            return False
        extras, sequence = variant
        live_base = final_gate_timing_keys | {
            "classification", "phase", "signal_attempted", "signal_sent",
            "errors",
        }
        if phase != "BEFORE_KILLPG":
            live_base.add("terminal_transition_snapshot")
        if set(candidate) != live_base | extras:
            return False
        if "leader_returncode" in extras and type(
            candidate.get("leader_returncode")
        ) is not int:
            return False
        if "leader_returncode" in extras and (
            candidate.get("leader_returncode") != watchdog_child_returncode
            or not isinstance(execution, Mapping)
            or execution.get("child_reaped") is not True
            or execution.get("timed_out") is not False
        ):
            return False
        first = candidate.get("first_exact_group_proof")
        final = candidate.get("final_exact_group_proof")
        transition = candidate.get("terminal_transition_snapshot")
        if phase in {"FIRST_FINAL_GROUP_PROOF", "AFTER_FIRST_FINAL_GROUP_PROOF"}:
            if (
                not failed_group_proof_valid(transition)
                or valid_terminal_transition_proof(transition)
            ):
                return False
            underlying_errors = list(transition.get("errors", []))
            proofs = (transition,)
        elif phase in {"SECOND_FINAL_GROUP_PROOF", "AFTER_SECOND_FINAL_GROUP_PROOF"}:
            if (
                not valid_group_proof(first)
                or not failed_group_proof_valid(transition)
                or valid_terminal_transition_proof(transition)
            ):
                return False
            underlying_errors = list(transition.get("errors", []))
            proofs = (first, transition)
        else:
            if (
                not valid_group_proof(first)
                or not valid_group_proof(final)
                or strict_json_equal(
                    stable_member_projection(first),
                    stable_member_projection(final),
                )
            ):
                return False
            underlying_errors = ["FINAL_EXACT_GROUP_MEMBERSHIP_CHANGED"]
            proofs = (first, final)
        return bool(
            candidate.get("errors")
            == complete_gate_errors(*underlying_errors)
            and refused_gate_state_valid(*underlying_errors)
            and ordered_gate_seconds(candidate, *proofs)
        )

    same_popen_reap_keys = {
        "schema_version", "source", "same_popen",
        "frozen_process_identity", "poll_observed_monotonic_ns",
        "poll_returncode", "wait_started_monotonic_ns",
        "wait_completed_monotonic_ns", "wait_timeout_seconds",
        "wait_returncode",
    }
    same_popen_reap_sources = {
        "LOOP_POLL_THEN_WAIT_ZERO",
        "SCHEDULED_BOUNDED_WAIT",
        "PERIODIC_PROOF_POLL_THEN_WAIT_ZERO",
        "PENDING_TEARDOWN_LOOP_POLL_THEN_WAIT_ZERO",
        "PENDING_TEARDOWN_BOUNDED_WAIT",
        "FINAL_GATE_POLL_THEN_WAIT_ZERO",
        "FINAL_GATE_PENDING_POLL_THEN_WAIT_ZERO",
    }

    def valid_same_popen_reap(
        candidate: object,
        returncode: int,
        adjudicated_ns: int,
    ) -> bool:
        if not isinstance(candidate, Mapping) or set(candidate) != same_popen_reap_keys:
            return False
        identity_candidate = candidate.get("frozen_process_identity")
        source = candidate.get("source")
        poll_ns = candidate.get("poll_observed_monotonic_ns")
        poll_returncode = candidate.get("poll_returncode")
        wait_started_ns = candidate.get("wait_started_monotonic_ns")
        wait_completed_ns = candidate.get("wait_completed_monotonic_ns")
        wait_timeout = candidate.get("wait_timeout_seconds")
        zero_wait_source = isinstance(source, str) and source.endswith(
            "POLL_THEN_WAIT_ZERO"
        )
        return bool(
            candidate.get("schema_version")
            == "aqua-fe-fair-stability-same-popen-reap-v10"
            and source in same_popen_reap_sources
            and candidate.get("same_popen") is True
            and strict_json_equal(
                identity_candidate,
                {
                    "pid": launch_pid,
                    "start_ticks": launch_start_ticks,
                    "pgid": launch_pid,
                    "session": launch_pid,
                },
            )
            and type(poll_ns) is int
            and type(wait_started_ns) is int
            and type(wait_completed_ns) is int
            and 0 < int(poll_ns) <= int(wait_started_ns) <= int(wait_completed_ns)
            and int(wait_completed_ns) <= int(adjudicated_ns)
            and type(wait_timeout) is float
            and math.isfinite(float(wait_timeout))
            and 0.0 <= float(wait_timeout)
            <= float(fixed_contract["maximum_poll_interval_seconds"])
            and type(candidate.get("wait_returncode")) is int
            and candidate.get("wait_returncode") == returncode
            and (
                type(poll_returncode) is int
                and poll_returncode == returncode
                and wait_timeout == 0.0
                if zero_wait_source
                else poll_returncode is None
            )
        )

    def valid_passive_exit(value_candidate: object) -> bool:
        if not isinstance(value_candidate, Mapping):
            return False
        phase = value_candidate.get("phase")
        evidence = value_candidate.get("evidence")
        last_snapshot = value_candidate.get("last_exact_group_snapshot")
        execution = result.get("execution")
        returncode = value_candidate.get("child_returncode")
        adjudicated_ns = value_candidate.get("adjudicated_monotonic_ns")
        reap = value_candidate.get("reap")
        if (
            set(value_candidate) != {
                "phase", "evidence", "last_exact_group_snapshot",
                "adjudicated_at_utc", "adjudicated_monotonic_ns",
                "child_returncode", "reaped_before_next_sample",
                "reap", "signal_attempted", "signal_sent",
            }
            or not isinstance(phase, str)
            or not phase
            or not isinstance(evidence, Mapping)
            or not valid_utc_receipt_timestamp(
                value_candidate.get("adjudicated_at_utc")
            )
            or type(adjudicated_ns) is not int
            or int(adjudicated_ns) <= 0
            or type(returncode) is not int
            or value_candidate.get("reaped_before_next_sample") is not True
            or value_candidate.get("signal_attempted") is not False
            or value_candidate.get("signal_sent") is not False
            or not isinstance(execution, Mapping)
            or execution.get("raw_returncode") != returncode
            or execution.get("child_reaped") is not True
            or execution.get("timed_out") is not False
            or not strict_json_equal(last_snapshot, outcome.get("last_exact_group_snapshot"))
            or not valid_same_popen_reap(reap, returncode, int(adjudicated_ns))
        ):
            return False

        reap_source = reap.get("source")

        reaped_base_keys = {
            "classification", "phase", "observed_at_utc",
            "observed_monotonic_ns", "leader_returncode",
            "reaped_before_next_sample", "signal_attempted", "signal_sent",
            "errors",
        }

        def valid_reaped_base(
            expected_classification: str,
            expected_phase: str,
            extra_keys: set[str],
        ) -> bool:
            observed_ns = evidence.get("observed_monotonic_ns")
            return bool(
                set(evidence) == reaped_base_keys | extra_keys
                and evidence.get("classification") == expected_classification
                and evidence.get("phase") == expected_phase
                and valid_utc_receipt_timestamp(evidence.get("observed_at_utc"))
                and type(observed_ns) is int
                and 0 < int(observed_ns) <= int(adjudicated_ns)
                and int(reap["wait_completed_monotonic_ns"])
                <= int(observed_ns)
                and evidence.get("leader_returncode") == returncode
                and evidence.get("reaped_before_next_sample") is True
                and evidence.get("signal_attempted") is False
                and evidence.get("signal_sent") is False
                and evidence.get("errors") == []
                and (
                    "reap" not in evidence
                    or strict_json_equal(evidence.get("reap"), reap)
                )
            )

        if phase.startswith("ORDINARY_PROCESS_EXIT:"):
            ordinary_phase = phase.split(":", 1)[1]
            if ordinary_phase not in {"LOOP_POLL", "SCHEDULED_WAIT"} or not valid_reaped_base(
                "ORDINARY_CHILD_REAPED", ordinary_phase, set()
            ):
                return False
            if reap_source != (
                "LOOP_POLL_THEN_WAIT_ZERO"
                if ordinary_phase == "LOOP_POLL"
                else "SCHEDULED_BOUNDED_WAIT"
            ):
                return False
            if last_snapshot is None:
                return True
            proof_ns = proof_monotonic_ns(last_snapshot)
            return bool(
                valid_group_proof(last_snapshot)
                and proof_ns is not None
                and proof_ns
                <= int(
                    reap[
                        "poll_observed_monotonic_ns"
                        if ordinary_phase == "LOOP_POLL"
                        else "wait_started_monotonic_ns"
                    ]
                )
            )

        if phase == "PERIODIC_EXACT_GROUP_PROOF":
            return bool(
                reap_source
                in {
                    "PERIODIC_PROOF_POLL_THEN_WAIT_ZERO",
                    "PENDING_TEARDOWN_LOOP_POLL_THEN_WAIT_ZERO",
                    "PENDING_TEARDOWN_BOUNDED_WAIT",
                }
                and valid_terminal_transition_proof(evidence)
                and strict_json_equal(last_snapshot, evidence)
                and proof_monotonic_ns(evidence)
                <= int(reap["poll_observed_monotonic_ns"])
            )
        if not phase.startswith("FINAL_SIGNAL_GATE:"):
            return False
        evidence_phase = evidence.get("phase")
        if (
            not isinstance(evidence_phase, str)
            or phase != f"FINAL_SIGNAL_GATE:{evidence_phase}"
            or not valid_group_proof(last_snapshot)
            or not strict_json_equal(evidence, final_gate_adjudication)
            or not final_gate_adjudication_valid(evidence)
        ):
            return False
        last_ns = proof_monotonic_ns(last_snapshot)
        if last_ns is None:
            return False
        classification = evidence.get("classification")
        if classification == "LEADER_REAPED_BEFORE_SIGNAL":
            extras_by_phase = {
                "BEFORE_FIRST_FINAL_GROUP_PROOF": final_gate_timing_keys
                | {"reap"},
                "AFTER_FIRST_FINAL_GROUP_PROOF": final_gate_timing_keys
                | {"terminal_transition_snapshot", "reap"},
                "AFTER_SECOND_FINAL_GROUP_PROOF": {
                    "first_exact_group_proof", "terminal_transition_snapshot", "reap",
                } | final_gate_timing_keys,
                "BEFORE_KILLPG": {
                    "first_exact_group_proof", "final_exact_group_proof", "reap",
                } | final_gate_timing_keys,
            }
            extra_keys = extras_by_phase.get(evidence_phase)
            if extra_keys is None or not valid_reaped_base(
                "LEADER_REAPED_BEFORE_SIGNAL", evidence_phase, extra_keys
            ):
                return False
            if reap_source != "FINAL_GATE_POLL_THEN_WAIT_ZERO":
                return False
            observed_ns = int(evidence["observed_monotonic_ns"])
            reap_poll_ns = int(reap["poll_observed_monotonic_ns"])
            if evidence_phase == "BEFORE_FIRST_FINAL_GROUP_PROOF":
                return last_ns <= reap_poll_ns
            first = evidence.get("first_exact_group_proof")
            transition = evidence.get("terminal_transition_snapshot")
            if evidence_phase == "AFTER_FIRST_FINAL_GROUP_PROOF":
                transition_ns = proof_monotonic_ns(transition)
                return bool(
                    (valid_group_proof(transition)
                     or valid_terminal_transition_proof(transition))
                    and transition_ns is not None
                    and last_ns <= transition_ns <= reap_poll_ns
                )
            if evidence_phase == "AFTER_SECOND_FINAL_GROUP_PROOF":
                first_ns = proof_monotonic_ns(first)
                transition_ns = proof_monotonic_ns(transition)
                return bool(
                    valid_group_proof(first)
                    and (valid_group_proof(transition)
                         or valid_terminal_transition_proof(transition))
                    and first_ns is not None
                    and transition_ns is not None
                    and last_ns <= first_ns <= transition_ns <= reap_poll_ns
                )
            final = evidence.get("final_exact_group_proof")
            first_ns = proof_monotonic_ns(first)
            final_ns = proof_monotonic_ns(final)
            return bool(
                valid_group_proof(first)
                and valid_group_proof(final)
                and stable_member_projection(first)
                == stable_member_projection(final)
                and first_ns is not None
                and final_ns is not None
                and last_ns <= first_ns <= final_ns <= reap_poll_ns
            )
        if classification != "TERMINAL_TRANSITION_PENDING_REAP":
            return False
        if reap_source not in {
            "FINAL_GATE_PENDING_POLL_THEN_WAIT_ZERO",
            "PENDING_TEARDOWN_LOOP_POLL_THEN_WAIT_ZERO",
            "PENDING_TEARDOWN_BOUNDED_WAIT",
        }:
            return False
        pending_base_keys = {
            "classification", "phase", "terminal_transition_snapshot",
            "signal_attempted", "signal_sent", "errors",
        }
        expected_keys = (
            pending_base_keys | final_gate_timing_keys
            if evidence_phase == "FIRST_FINAL_GROUP_PROOF"
            else pending_base_keys
            | final_gate_timing_keys
            | {"first_exact_group_proof"}
            if evidence_phase == "SECOND_FINAL_GROUP_PROOF"
            else None
        )
        transition = evidence.get("terminal_transition_snapshot")
        transition_ns = proof_monotonic_ns(transition)
        reap_poll_ns = int(reap["poll_observed_monotonic_ns"])
        gate_pre_signal = finite_seconds(evidence.get("pre_signal_monotonic"))
        if (
            expected_keys is None
            or set(evidence) != expected_keys
            or evidence.get("signal_attempted") is not False
            or evidence.get("signal_sent") is not False
            or not valid_terminal_transition_proof(transition)
            or evidence.get("errors") != transition.get("errors")
            or transition_ns is None
            or gate_pre_signal is None
            or transition_ns > reap_poll_ns
            or gate_pre_signal > float(reap_poll_ns) / 1_000_000_000.0
        ):
            return False
        if evidence_phase == "FIRST_FINAL_GROUP_PROOF":
            return last_ns <= transition_ns
        first = evidence.get("first_exact_group_proof")
        first_ns = proof_monotonic_ns(first)
        return bool(
            valid_group_proof(first)
            and first_ns is not None
            and last_ns <= first_ns <= transition_ns
        )

    def valid_final_signature(signature: object) -> bool:
        if not isinstance(signature, Mapping):
            return False
        shutdown = signature.get("shutdown_line_indices_zero_based")
        target_saving = signature.get("target_saving_line_indices_zero_based")
        all_saving = signature.get("all_saving_line_indices_zero_based")
        atlas_headers = signature.get("atlas_headers_after_target_saving")
        atlas_count = signature.get("atlas_map_count")
        map_rows = signature.get("map_rows")
        sample_size = signature.get("stdout_size_bytes")
        sample_sha256 = signature.get("stdout_sha256_at_sample")
        if (
            signature.get("parser_proven") is not True
            or signature.get("confirmed") is not True
            or signature.get("errors") != []
            or signature.get("stdout_regular_non_symlink") is not True
            or signature.get("trajectory_absent_non_symlink") is not True
            or signature.get("keyframe_trajectory_absent_non_symlink") is not True
            or signature.get("incomplete_tail_present") is not False
            or signature.get(
                "ordered_single_shutdown_before_single_target_saving"
            ) is not True
            or signature.get("only_target_saving_observed") is not True
            or signature.get("complete_unique_map_id_set") is not True
            or signature.get("every_map_zero_keyframes") is not True
            or signature.get("target_end_of_saving_observed") is not False
            or type(sample_size) is not int
            or int(sample_size) <= 0
            or not isinstance(sample_sha256, str)
            or re.fullmatch(
                r"[0-9a-f]{64}", sample_sha256
            ) is None
            or not isinstance(shutdown, list)
            or len(shutdown) != 1
            or type(shutdown[0]) is not int
            or not isinstance(target_saving, list)
            or len(target_saving) != 1
            or type(target_saving[0]) is not int
            or not strict_json_equal(all_saving, target_saving)
            or shutdown[0] >= target_saving[0]
            or type(atlas_count) is not int
            or int(atlas_count) < 1
            or not isinstance(atlas_headers, list)
            or len(atlas_headers) != 1
            or not isinstance(atlas_headers[0], Mapping)
            or atlas_headers[0].get("map_count") != atlas_count
            or type(atlas_headers[0].get("line_index_zero_based")) is not int
            or atlas_headers[0]["line_index_zero_based"] <= target_saving[0]
            or not isinstance(map_rows, list)
            or len(map_rows) != atlas_count
        ):
            return False
        try:
            current_stdout = (root / "headless.stdout.log").read_bytes()
            prefix = current_stdout[: int(sample_size)]
            decoded_prefix = prefix.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return False
        if (
            len(current_stdout) < int(sample_size)
            or len(prefix) != int(sample_size)
            or hashlib.sha256(prefix).hexdigest() != sample_sha256
            or not prefix.endswith(b"\n")
        ):
            return False
        lines = decoded_prefix.splitlines()
        target_save = f"Saving trajectory to {root / 'result/trajectory.txt'} ..."
        target_end = (
            f"End of saving trajectory to {root / 'result/trajectory.txt'} ..."
        )
        actual_shutdown = [
            index for index, line in enumerate(lines) if line == "Shutdown"
        ]
        actual_target_saving = [
            index for index, line in enumerate(lines) if line == target_save
        ]
        actual_all_saving = [
            index
            for index, line in enumerate(lines)
            if line.startswith("Saving trajectory to ")
        ]
        actual_atlas: list[dict[str, int]] = []
        if len(actual_target_saving) == 1:
            for index, line in enumerate(lines[actual_target_saving[0] + 1 :], actual_target_saving[0] + 1):
                match = re.fullmatch(r"There are ([0-9]+) maps in the atlas", line)
                if match:
                    actual_atlas.append(
                        {
                            "line_index_zero_based": index,
                            "map_count": int(match.group(1)),
                        }
                    )
        actual_map_rows: list[dict[str, int]] = []
        if len(actual_atlas) == 1:
            atlas_index = actual_atlas[0]["line_index_zero_based"]
            for index, line in enumerate(lines[atlas_index + 1 :], atlas_index + 1):
                match = re.fullmatch(r"  Map ([0-9]+) has ([0-9]+) KFs", line)
                if match:
                    actual_map_rows.append(
                        {
                            "line_index_zero_based": index,
                            "map_id": int(match.group(1)),
                            "keyframes": int(match.group(2)),
                        }
                    )
        if (
            not strict_json_equal(actual_shutdown, shutdown)
            or not strict_json_equal(actual_target_saving, target_saving)
            or not strict_json_equal(actual_all_saving, all_saving)
            or not strict_json_equal(actual_atlas, atlas_headers)
            or not strict_json_equal(actual_map_rows, map_rows)
            or target_end in lines
        ):
            return False
        expected_ids = set(range(atlas_count))
        observed_ids: set[int] = set()
        previous_index = int(atlas_headers[0]["line_index_zero_based"])
        for row in map_rows:
            if (
                not isinstance(row, Mapping)
                or set(row) != {"line_index_zero_based", "map_id", "keyframes"}
                or type(row.get("line_index_zero_based")) is not int
                or int(row.get("line_index_zero_based", -1)) <= previous_index
                or type(row.get("map_id")) is not int
                or type(row.get("keyframes")) is not int
                or row.get("keyframes") != 0
            ):
                return False
            previous_index = int(row["line_index_zero_based"])
            observed_ids.add(int(row["map_id"]))
        return observed_ids == expected_ids

    def valid_final_gate_chain() -> bool:
        if (
            not isinstance(outcome, Mapping)
            or "final_signal_gate_adjudication" not in value
            or "watchdog_action" not in value
            or any(
                key not in outcome
                for key in (
                    "final_signal_gate_signature",
                    "final_signal_gate_signature_completed_monotonic",
                    "final_signal_gate_adjudication",
                    "watchdog_action",
                )
            )
        ):
            return False
        if final_gate_adjudication is None:
            return bool(
                outcome_final_gate_adjudication is None
                and final_gate_signature is None
                and final_gate_signature_completed is None
                and action is None
                and signal_attempted is False
            )
        if (
            not isinstance(final_gate_adjudication, Mapping)
            or not strict_json_equal(
                final_gate_adjudication, outcome_final_gate_adjudication
            )
            or not final_gate_adjudication_valid(final_gate_adjudication)
            or not valid_final_signature(final_gate_signature)
            or not isinstance(outcome, Mapping)
            or not valid_group_proof(outcome.get("last_exact_group_snapshot"))
        ):
            return False
        last_ns = proof_monotonic_ns(outcome.get("last_exact_group_snapshot"))
        gate_started = finite_seconds(
            final_gate_adjudication.get("final_gate_started_monotonic")
        )
        gate_elapsed = finite_seconds(
            final_gate_adjudication.get("final_gate_elapsed_seconds")
        )
        lifetime_maximum_gap = finite_seconds(maximum_gap)
        gate_attempted = final_gate_adjudication.get("signal_attempted") is True
        gate_sent = final_gate_adjudication.get("signal_sent") is True
        gate_classification = final_gate_adjudication.get("classification")
        gate_deadline = finite_seconds(
            final_gate_adjudication.get("deadline_monotonic")
        )
        gate_pre_signal = finite_seconds(
            final_gate_adjudication.get("pre_signal_monotonic")
        )
        gate_maximum_duration = finite_seconds(
            final_gate_adjudication.get(
                "maximum_final_gate_duration_seconds"
            )
        )
        continuous_at_end = finite_seconds(continuous_seconds)
        if (
            last_ns is None
            or gate_started is None
            or gate_elapsed is None
            or lifetime_maximum_gap is None
            or gate_deadline is None
            or gate_pre_signal is None
            or gate_maximum_duration is None
            or continuous_at_end is None
            or lifetime_maximum_gap < gate_elapsed
            or float(last_ns) / 1_000_000_000.0 > gate_started
            or signal_attempted is not gate_attempted
            or sent is not gate_sent
        ):
            return False
        gate_timing_refused = bool(
            gate_pre_signal >= gate_deadline
            or gate_elapsed > gate_maximum_duration
        )
        candidate_was_cleared = bool(
            gate_classification
            in {
                "TERMINAL_TRANSITION_PENDING_REAP",
                "LIVE_OR_UNKNOWN_GROUP_UNPROVEN",
                "SIGNAL_DELIVERY_FAILED",
            }
            or (
                gate_classification == "LEADER_REAPED_BEFORE_SIGNAL"
                and gate_timing_refused
            )
        )
        candidate_was_retained = bool(
            gate_classification == "SIGTERM_SENT"
            or (
                gate_classification == "LEADER_REAPED_BEFORE_SIGNAL"
                and not gate_timing_refused
            )
        )
        if candidate_was_cleared:
            if (
                outcome.get("last_confirmed_signature") is not None
                or outcome.get("signature_first_observed_at_utc") is not None
                or continuous_at_end != 0.0
            ):
                return False
        elif candidate_was_retained:
            if (
                not strict_json_equal(
                    outcome.get("last_confirmed_signature"),
                    final_gate_signature,
                )
                or not valid_utc_receipt_timestamp(
                    outcome.get("signature_first_observed_at_utc")
                )
                or continuous_at_end
                < float(fixed_contract["fixed_grace_seconds"])
            ):
                return False
        else:
            return False
        if gate_attempted:
            return bool(
                isinstance(action, Mapping)
                and strict_json_equal(action, final_gate_adjudication)
            )
        return action is None

    def phase_gap_diagnostics_valid() -> bool:
        if (
            type(pre_candidate_gap_count) is not int
            or pre_candidate_gap_count < 0
            or type(confirmation_gap_reset_count) is not int
            or confirmation_gap_reset_count < 0
            or type(confirmation_candidate_count) is not int
            or confirmation_candidate_count < confirmation_gap_reset_count
            or confirmation_candidate_count > int(outcome.get("sample_count", -1))
            or not isinstance(phase_gap_events, list)
            or len(phase_gap_events)
            != pre_candidate_gap_count + confirmation_gap_reset_count
            or (
                isinstance(final_gate_adjudication, Mapping)
                and confirmation_candidate_count < 1
            )
        ):
            return False
        pre_maximum = finite_seconds(maximum_pre_candidate_gap)
        confirmation_maximum = finite_seconds(maximum_confirmation_gap)
        lifetime_maximum = finite_seconds(maximum_gap)
        maximum_allowed = float(fixed_contract["maximum_poll_interval_seconds"])
        if (
            pre_maximum is None
            or pre_maximum < 0.0
            or confirmation_maximum is None
            or confirmation_maximum < 0.0
            or lifetime_maximum is None
            or lifetime_maximum < max(pre_maximum, confirmation_maximum)
        ):
            return False
        expected_keys = {
            "event_index", "phase", "reason",
            "previous_observation_monotonic", "observed_monotonic",
            "gap_seconds", "maximum_allowed_seconds", "candidate_reset",
        }
        pre_gaps: list[float] = []
        confirmation_gaps: list[float] = []
        previous_event_observed: float | None = None
        final_gate_started = (
            finite_seconds(
                final_gate_adjudication.get("final_gate_started_monotonic")
            )
            if isinstance(final_gate_adjudication, Mapping)
            else None
        )
        for expected_index, event in enumerate(phase_gap_events, 1):
            if (
                not isinstance(event, Mapping)
                or set(event) != expected_keys
                or type(event.get("event_index")) is not int
                or event.get("event_index") != expected_index
                or not isinstance(event.get("reason"), str)
                or not event.get("reason")
            ):
                return False
            previous_observation = finite_seconds(
                event.get("previous_observation_monotonic")
            )
            observed = finite_seconds(event.get("observed_monotonic"))
            gap = finite_seconds(event.get("gap_seconds"))
            event_maximum = finite_seconds(event.get("maximum_allowed_seconds"))
            if (
                previous_observation is None
                or observed is None
                or gap is None
                or event_maximum != maximum_allowed
                or previous_observation < 0.0
                or observed <= previous_observation
                or (
                    previous_event_observed is not None
                    and previous_observation < previous_event_observed
                )
                or (
                    final_gate_started is not None
                    and observed > final_gate_started
                )
                or gap != observed - previous_observation
                or gap <= maximum_allowed
            ):
                return False
            previous_event_observed = observed
            phase = event.get("phase")
            if phase == "PRE_CANDIDATE":
                if event.get("candidate_reset") is not False:
                    return False
                pre_gaps.append(gap)
            elif phase == "CONFIRMATION":
                if event.get("candidate_reset") is not True:
                    return False
                confirmation_gaps.append(gap)
            else:
                return False
        return bool(
            len(pre_gaps) == pre_candidate_gap_count
            and len(confirmation_gaps) == confirmation_gap_reset_count
            and (
                pre_maximum == max(pre_gaps)
                if pre_gaps
                else pre_maximum <= maximum_allowed
            )
            and (
                confirmation_maximum == max(confirmation_gaps)
                if confirmation_gaps
                else confirmation_maximum <= maximum_allowed
            )
        )

    if (
        not isinstance(pipeline_codes, list)
        or not isinstance(algorithm_codes, list)
        or (unproven_code in pipeline_codes) != (not proven)
        or (algorithm_code in algorithm_codes) != sent
        or not isinstance(decision, Mapping)
        or decision.get("monitor_proven") is not proven
        or decision.get("sigterm_sent") is not sent
        or decision.get("retry_permitted") is not False
        or decision.get("pipeline_failure_code_if_unproven") != unproven_code
        or decision.get("algorithm_failure_code_if_sent") != algorithm_code
        or not isinstance(watchdog_errors, list)
        or any(not isinstance(error, str) or not error for error in watchdog_errors)
        or not isinstance(outcome_errors, list)
        or any(not isinstance(error, str) or not error for error in outcome_errors)
        or not strict_json_equal(
            watchdog_errors, list(dict.fromkeys(outcome_errors))
        )
        or (proven and watchdog_errors != [])
        or (not proven and watchdog_errors == [])
        or value.get("status")
        != (
            "SIGTERM_SENT_FOR_CONFIRMED_ZERO_KF_POST_SHUTDOWN_SAVE_HANG"
            if sent and proven
            else "PASSIVE_NO_WATCHDOG_SIGNAL"
            if proven
            else "WATCHDOG_SUPERVISION_UNPROVEN_FAIL_CLOSED"
        )
        or not isinstance(outcome, Mapping)
        or outcome.get("schema_version")
        != "aqua-fe-fair-stability-hfnet-zero-kf-watchdog-outcome-v10"
        or outcome.get("monitor_proven") is not proven
        or type(outcome.get("sample_count")) is not int
        or int(outcome.get("sample_count", -1)) < 0
        or outcome.get("target_poll_interval_seconds")
        != fixed_contract.get("target_poll_interval_seconds")
        or outcome.get("maximum_allowed_poll_interval_seconds")
        != fixed_contract.get("maximum_poll_interval_seconds")
        or outcome.get("fixed_signature_grace_seconds")
        != fixed_contract.get("fixed_grace_seconds")
        or outcome.get("total_timeout_seconds")
        != fixed_contract.get("estimator_total_timeout_seconds")
        or type(outcome.get("permanently_disabled_after_unproven_evidence"))
        is not bool
        or (
            proven
            and outcome.get("permanently_disabled_after_unproven_evidence")
            is not False
        )
        or type(signal_attempted) is not bool
        or outcome.get("sigterm_sent") is not sent
        or type(watchdog_child_returncode) not in (int, type(None))
        or not strict_json_equal(
            watchdog_child_returncode, outcome_child_returncode
        )
        or not strict_json_equal(
            watchdog_child_returncode, execution.get("raw_returncode")
        )
        or not strict_json_equal(outcome.get("watchdog_action"), action)
        or not valid_final_gate_chain()
        or not strict_json_equal(
            value.get("passive_exit_adjudication"), passive_exit
        )
        or not numeric_outcome_valid
        or not phase_gap_diagnostics_valid()
        or any(
            error.startswith("WATCHDOG_POLL_GAP_EXCEEDED:")
            for error in watchdog_errors
        )
        or not isinstance(runtime_receipt, Mapping)
        or runtime_receipt.get("schema_version")
        != "aqua-fe-fair-stability-runtime-resource-monitor-v10"
        or runtime_receipt.get("experiment_id") != EXPERIMENT_ID
        or not isinstance(execution, Mapping)
        or not isinstance(runtime_supervised, Mapping)
        or not isinstance(runtime_coverage, Mapping)
        or not isinstance(runtime_decision, Mapping)
        or runtime_supervised.get("pid") != launch_pid
        or not strict_json_equal(
            runtime_supervised.get("leader_identity"),
            {"pid": launch_pid, "start_ticks": launch_start_ticks},
        )
        or runtime_supervised.get("pgid") != launch_pid
        or runtime_supervised.get("returncode")
        != execution.get("raw_returncode")
        or not strict_json_equal(
            watchdog_child_returncode, runtime_supervised.get("returncode")
        )
        or runtime_coverage.get("process_group_empty")
        is not execution.get("supervised_process_group_empty_after_wait")
        or type(runtime_coverage.get("process_group_empty")) is not bool
        or not isinstance(
            runtime_supervised.get("active_owned_identities_at_finalize"), list
        )
        or (
            runtime_coverage.get("process_group_empty") is True
            and runtime_supervised.get("active_owned_identities_at_finalize") != []
        )
        or type(runtime_receipt.get("monitor_proven")) is not bool
        or type(runtime_receipt.get("intrusion_detected")) is not bool
        or not strict_json_equal(runtime_reasons, expected_runtime_reasons)
        or runtime_receipt.get("pipeline_valid") is not (not runtime_reasons)
        or runtime_decision.get("intrusion_detected")
        is not runtime_receipt.get("intrusion_detected")
        or runtime_decision.get("monitor_proven")
        is not runtime_receipt.get("monitor_proven")
        or not strict_json_equal(
            runtime_decision.get("pipeline_failure_reasons"), runtime_reasons
        )
        or (
            "MIDRUN_EXTERNAL_RESOURCE_INTRUSION" in pipeline_codes
        ) is not (runtime_receipt.get("intrusion_detected") is True)
        or (
            "RUNTIME_RESOURCE_MONITOR_UNPROVEN" in pipeline_codes
        ) is not (runtime_receipt.get("monitor_proven") is not True)
        or not isinstance(cleanup_actions, list)
        or not isinstance(watchdog_cleanup_actions, list)
        or (
            isinstance(action, Mapping)
            and (
                len(watchdog_cleanup_actions) != 1
                or not strict_json_equal(watchdog_cleanup_actions[0], action)
            )
        )
        or (action is None and watchdog_cleanup_actions != [])
        or value.get("signal_attempt_count") != int(signal_attempted)
        or value.get("signal_count") != int(sent)
        or value.get("signal") != ("SIGTERM" if sent else None)
        or value.get("signal_scope")
        != ("EXACT_REVALIDATED_PROCESS_GROUP" if sent else None)
        or not isinstance(final_outputs, Mapping)
        or final_outputs.get("trajectory_path")
        != str(root / "result/trajectory.txt")
        or final_outputs.get("keyframe_path")
        != str(root / "result/trajectory_keyframe.txt")
        or final_outputs.get("trajectory_absent_non_symlink")
        is not current_trajectory_absent
        or final_outputs.get("keyframe_absent_non_symlink")
        is not current_keyframe_absent
        or (proven and not sent and (signal_attempted or action is not None))
        or (passive_exit is not None and not valid_passive_exit(passive_exit))
        or (passive_exit is not None and (not proven or sent or action is not None))
        or (passive_exit is not None)
        is not natural_reaped_without_watchdog_signal
        or (
            passive_exit is not None
            and runtime_supervised.get("returncode")
            != passive_exit.get("child_returncode")
        )
        or (sent and not proven)
        or (
            sent
            and int(outcome.get("sample_count", 0))
            < math.ceil(
                float(fixed_contract["fixed_grace_seconds"])
                / float(fixed_contract["maximum_poll_interval_seconds"])
            )
        )
        or (
            sent
            and not valid_utc_receipt_timestamp(
                outcome.get("signature_first_observed_at_utc")
            )
        )
        or (
            sent
            and outcome.get("permanently_disabled_after_unproven_evidence")
            is not False
        )
    ):
        raise OrdinalError(f"HFNET_ZERO_KF_WATCHDOG_CLASSIFICATION_DRIFT:{path}")
    if sent and (
        not proven
        or value.get("status")
        != "SIGTERM_SENT_FOR_CONFIRMED_ZERO_KF_POST_SHUTDOWN_SAVE_HANG"
        or value.get("signal_attempt_count") != 1
        or value.get("signal_count") != 1
        or value.get("signal") != "SIGTERM"
        or value.get("signal_scope") != "EXACT_REVALIDATED_PROCESS_GROUP"
        or not isinstance(action, Mapping)
        or action.get("signal_sent") is not True
        or action.get("signal") != int(15)
        or action.get("signal_scope") != "EXACT_REVALIDATED_PROCESS_GROUP"
        or action.get("individual_identities_sent") != []
        or not isinstance(action.get("first_exact_group_proof"), Mapping)
        or not valid_group_proof(action["first_exact_group_proof"])
        or not isinstance(action.get("final_exact_group_proof"), Mapping)
        or not valid_group_proof(action["final_exact_group_proof"])
        or not strict_json_equal(
            stable_member_projection(action["first_exact_group_proof"]),
            stable_member_projection(action["final_exact_group_proof"]),
        )
        or not valid_group_proof(outcome.get("last_exact_group_snapshot"))
        or not valid_final_signature(outcome.get("last_confirmed_signature"))
        or action.get("signal_attempted") is not True
        or action.get("group_sent") is not True
        or action.get("group_error") is not None
        or action.get("errors") != []
        or action.get("label") != "confirmed_zero_kf_post_shutdown_watchdog"
        or not valid_utc_receipt_timestamp(action.get("at_utc"))
        or type(action.get("monotonic_ns")) is not int
        or int(action.get("monotonic_ns", 0)) <= 0
        or float(continuous_seconds) < float(fixed_contract["fixed_grace_seconds"])
        or final_outputs.get("trajectory_absent_non_symlink") is not True
        or final_outputs.get("keyframe_absent_non_symlink") is not True
    ):
        raise OrdinalError(f"HFNET_ZERO_KF_WATCHDOG_SIGNAL_DRIFT:{path}")
    _require_hfnet_watchdog_snapshot_unchanged(
        path, root, validated_watchdog_identity
    )


def systemd_started_without_result_state(
    experiment_root: Path,
    start_path: Path,
    cell: Mapping[str, Any],
    attempt_index: int,
) -> dict[str, object]:
    """Bind an incomplete attempt to its immutable systemd supervision chain."""

    start = json.loads(start_path.read_text(encoding="utf-8"))
    recorded = start.get("systemd_start_receipt")
    base = {
        "cell": dict(cell),
        "attempt_index": attempt_index,
        "attempt_root": str(start_path.parent),
        "start_claim": identity(start_path),
    }
    if not isinstance(recorded, Mapping):
        return {
            **base,
            "state": "SYSTEMD_AUTHORITY_UNPROVEN_STARTED_WITHOUT_RESULT",
            "systemd_failure_reason": "START_CLAIM_SYSTEMD_START_RECEIPT_MISSING",
        }
    receipt_path = Path(str(recorded.get("path", "")))
    supervision_root = experiment_root / "systemd_supervision"
    require_no_symlink_components(receipt_path, experiment_root)
    try:
        receipt_path.relative_to(supervision_root)
    except ValueError as error:
        raise OrdinalError(
            f"SYSTEMD_START_RECEIPT_OUTSIDE_SUPERVISION_ROOT:{receipt_path}"
        ) from error
    if not identity_matches(recorded, receipt_path):
        raise OrdinalError(f"SYSTEMD_START_RECEIPT_IDENTITY_DRIFT:{receipt_path}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (
        receipt.get("schema_version")
        != "aqua-fe-fair-stability-systemd-start-receipt-v10"
        or receipt.get("experiment_id") != EXPERIMENT_ID
    ):
        raise OrdinalError(f"SYSTEMD_START_RECEIPT_HEADER_INVALID:{receipt_path}")
    claim_identity = receipt.get("submission_claim")
    if not isinstance(claim_identity, Mapping):
        raise OrdinalError(f"SYSTEMD_SUBMISSION_CLAIM_MISSING:{receipt_path}")
    claim_path = Path(str(claim_identity.get("path", "")))
    require_no_symlink_components(claim_path, experiment_root)
    if not identity_matches(claim_identity, claim_path):
        raise OrdinalError(f"SYSTEMD_SUBMISSION_CLAIM_IDENTITY_DRIFT:{claim_path}")
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    if (
        claim.get("schema_version")
        != "aqua-fe-fair-stability-systemd-submission-v10"
        or claim.get("experiment_id") != EXPERIMENT_ID
        or claim.get("planned_ordinal") != int(cell["ordinal"])
        or claim.get("attempt_index") != attempt_index
        or claim.get("attempt_root") != str(start_path.parent)
        or claim.get("unit") != receipt.get("unit")
    ):
        raise OrdinalError(f"SYSTEMD_SUBMISSION_COORDINATE_DRIFT:{claim_path}")
    terminal_path = receipt_path.parent / "systemd_terminal_receipt.json"
    if terminal_path.is_symlink() or (
        terminal_path.exists() and not terminal_path.is_file()
    ):
        raise OrdinalError(f"SYSTEMD_TERMINAL_RECEIPT_INVALID:{terminal_path}")
    evidence = {
        "systemd_submission_claim": identity(claim_path),
        "systemd_start_receipt": identity(receipt_path),
        "systemd_terminal_receipt": (
            identity(terminal_path) if terminal_path.is_file() else None
        ),
    }
    if not terminal_path.is_file():
        return {
            **base,
            "state": "SYSTEMD_SUPERVISION_PENDING_OR_UNPROVEN",
            "systemd_failure_reason": (
                "UNIT_MAY_STILL_BE_ACTIVE_OR_EXEC_STOP_POST_RECEIPT_MISSING"
            ),
            "systemd_evidence": evidence,
        }
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    if (
        terminal.get("schema_version")
        != "aqua-fe-fair-stability-systemd-terminal-v10"
        or terminal.get("experiment_id") != EXPERIMENT_ID
        or terminal.get("unit") != receipt.get("unit")
        or terminal.get("invocation_id_environment")
        != receipt.get("invocation_id")
    ):
        raise OrdinalError(f"SYSTEMD_TERMINAL_RECEIPT_HEADER_INVALID:{terminal_path}")
    return {
        **base,
        "state": "SYSTEMD_TERMINATED_WITHOUT_RESULT",
        "systemd_failure_reason": "UNIT_TERMINAL_BUT_RUN_RESULT_ABSENT",
        "systemd_evidence": evidence,
        "systemd_terminal_tuple": terminal.get("observed_tuple"),
        "automatic_retry_permitted": False,
    }


def inspect_cell(experiment_root: Path, cell: Mapping[str, Any]) -> dict[str, Any]:
    base = attempt_root(experiment_root, cell, 1)
    require_no_symlink_components(base, experiment_root)
    existing_indices: list[int] = []
    if base.exists():
        existing_indices.append(1)
    if base.parent.is_dir():
        prefix = f"{base.name}__replenishment_"
        for candidate in base.parent.glob(f"{prefix}*"):
            match = re.fullmatch(re.escape(prefix) + r"([0-9]{3})", candidate.name)
            if (
                not match
                or int(match.group(1)) < 2
                or int(match.group(1)) > MAX_ATTEMPTS_PER_CELL
            ):
                raise OrdinalError(f"ATTEMPT_DIRECTORY_NAME_INVALID:{candidate}")
            existing_indices.append(int(match.group(1)))
    if existing_indices:
        ordered_indices = sorted(set(existing_indices))
        if len(ordered_indices) != len(existing_indices) or ordered_indices != list(
            range(1, ordered_indices[-1] + 1)
        ):
            raise OrdinalError(f"ATTEMPT_INDEX_GAP_OR_DUPLICATE:{cell['ordinal']}:{ordered_indices}")
    invalid_chain: list[dict[str, Any]] = []
    attempt_index = 1
    while attempt_index <= MAX_ATTEMPTS_PER_CELL:
        root = attempt_root(experiment_root, cell, attempt_index)
        require_no_symlink_components(root, experiment_root)
        manifest_path = root / "attempt_manifest.json"
        start_path = root / "start_claim.json"
        result_path = root / "run_result.json"
        invalid_receipt_path = root / "pipeline_invalid_receipt.json"
        later_root = (
            attempt_root(experiment_root, cell, attempt_index + 1)
            if attempt_index < MAX_ATTEMPTS_PER_CELL
            else None
        )
        if not root.exists():
            if later_root is not None and later_root.exists():
                raise OrdinalError(f"ATTEMPT_INDEX_GAP:{cell['ordinal']}:{attempt_index}")
            return {
                "state": "NEEDS_PREPARATION",
                "cell": dict(cell),
                "attempt_index": attempt_index,
                "attempt_root": str(root),
                "invalid_chain": invalid_chain,
            }
        if not manifest_path.is_file():
            raise OrdinalError(f"ATTEMPT_MANIFEST_MISSING:{root}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        hfnet_arm = str(cell["arm"]).startswith("hfnet_openloop_")
        expected_manifest_schema = (
            "aqua-fe-fair-stability-hfnet-attempt-v10"
            if hfnet_arm
            else "aqua-fe-fair-stability-vins-attempt-v10"
        )
        if (
            manifest.get("schema_version") != expected_manifest_schema
            or manifest.get("experiment_id") != EXPERIMENT_ID
            or not _coordinate_matches(manifest, cell, attempt_index)
        ):
            raise OrdinalError(f"ATTEMPT_MANIFEST_SCHEMA_OR_COORDINATE_MISMATCH:{root}")
        if result_path.is_file():
            if not start_path.is_file():
                raise OrdinalError(f"RESULT_WITHOUT_START_CLAIM:{root}")
            raw_result = result_path.read_bytes()
            validated_result_identity = {
                "path": str(result_path),
                "size_bytes": len(raw_result),
                "sha256": hashlib.sha256(raw_result).hexdigest(),
            }
            if not strict_json_equal(
                validated_result_identity, identity(result_path)
            ):
                raise OrdinalError(
                    f"RUN_RESULT_CHANGED_DURING_STATE_READ:{result_path}"
                )
            result = json.loads(raw_result.decode("utf-8"))
            expected_result_schema = (
                "aqua-fe-fair-stability-hfnet-result-v10"
                if hfnet_arm
                else "aqua-fe-fair-stability-vins-result-v10"
            )
            if (
                result.get("schema_version") != expected_result_schema
                or result.get("experiment_id") != EXPERIMENT_ID
                or not _coordinate_matches(result, cell, attempt_index)
                or not result_contract_valid(result)
            ):
                raise OrdinalError(f"RESULT_SCHEMA_OR_COORDINATE_MISMATCH:{root}")
            validated_semantic_artifacts = validate_result_semantic_evidence(
                root, result, cell, attempt_index
            )
            validate_controller_dispatch_execution_for_result(
                experiment_root, root, result
            )
            validated_runtime_monitor = validate_runtime_resource_monitor_evidence(
                root, result, cell, attempt_index
            )
            def require_validated_runtime_monitor() -> None:
                if not strict_json_equal(
                    validated_runtime_monitor,
                    identity(root / "runtime_resource_monitor.json"),
                ):
                    raise OrdinalError(
                        "RUNTIME_RESOURCE_MONITOR_CHANGED_DURING_STATE_INSPECTION:"
                        f"{root}"
                    )
            def require_validated_result() -> None:
                if not strict_json_equal(
                    validated_result_identity, identity(result_path)
                ):
                    raise OrdinalError(
                        f"RUN_RESULT_CHANGED_DURING_STATE_INSPECTION:{result_path}"
                    )
            def require_validated_semantic_artifacts() -> None:
                require_semantic_artifact_snapshot(validated_semantic_artifacts)
            if (
                hfnet_arm
                and "RUNTIME_RESOURCE_MONITOR_UNPROVEN"
                not in result.get("pipeline_failure_codes", [])
            ):
                validate_hfnet_watchdog_evidence(
                    root, manifest, result, cell, attempt_index
                )
            require_validated_runtime_monitor()
            require_validated_result()
            require_validated_semantic_artifacts()
            status = str(result.get("status"))
            if status in TERMINAL_STATUSES:
                if later_root is not None and later_root.exists():
                    raise OrdinalError(f"REPLENISHMENT_AFTER_ALGORITHM_TERMINAL:{root}")
                terminal_receipt = (
                    experiment_root / "ordinal_receipts"
                    / f"ordinal_{int(cell['ordinal']):03d}_terminal.json"
                )
                require_no_symlink_components(terminal_receipt, experiment_root)
                if terminal_receipt.is_symlink():
                    raise OrdinalError(f"TERMINAL_RECEIPT_SYMLINK:{terminal_receipt}")
                if terminal_receipt.exists() and not terminal_receipt.is_file():
                    raise OrdinalError(f"TERMINAL_RECEIPT_NONREGULAR:{terminal_receipt}")
                if terminal_receipt.is_file():
                    receipt_value = json.loads(terminal_receipt.read_text(encoding="utf-8"))
                    adoption_claim_record = receipt_value.get(
                        "systemd_adoption_claim"
                    )
                    adoption_claim_path = Path(
                        str(
                            adoption_claim_record.get("path", "")
                            if isinstance(adoption_claim_record, Mapping)
                            else ""
                        )
                    )
                    boundary = control_boundary(experiment_root)
                    if (
                        receipt_value.get("schema_version")
                        != "aqua-fe-fair-stability-ordinal-terminal-v10"
                        or not strict_json_equal(
                            [
                                receipt_value.get("planned_ordinal"),
                                receipt_value.get("case_id"),
                                receipt_value.get("arm"),
                                receipt_value.get("repeat"),
                                receipt_value.get("accepted_attempt_index"),
                            ],
                            [
                                int(cell["ordinal"]), str(cell["case_id"]),
                                str(cell["arm"]), int(cell["repeat"]), attempt_index,
                            ],
                        )
                        or not identity_matches(receipt_value.get("run_result"), result_path)
                        or not strict_json_equal(
                            receipt_value.get("run_result"),
                            validated_result_identity,
                        )
                        or not identity_matches(receipt_value.get("start_claim"), start_path)
                        or not identity_matches(receipt_value.get("attempt_manifest"), manifest_path)
                        or not identity_matches(
                            receipt_value.get("ordinal_dispatch_claim"),
                            root / "ordinal_dispatch_claim.json",
                        )
                        or not identity_matches(
                            receipt_value.get("runtime_resource_monitor"),
                            root / "runtime_resource_monitor.json",
                        )
                        or not strict_json_equal(
                            receipt_value.get("runtime_resource_monitor"),
                            validated_runtime_monitor,
                        )
                        or not strict_json_equal(
                            receipt_value.get("semantic_artifacts"),
                            validated_semantic_artifacts,
                        )
                        or receipt_value.get("terminal_status") != status
                        or not isinstance(receipt_value.get("clean_success"), bool)
                        or receipt_value.get("clean_success") is not bool(
                            result.get("clean_success")
                        )
                        or receipt_value.get("schedule_sha256") != SCHEDULE_SHA256
                        or not strict_json_equal(
                            receipt_value.get("invalid_attempt_chain"), invalid_chain
                        )
                        or not strict_json_equal(
                            receipt_value.get("controller"), boundary["controller"]
                        )
                        or not strict_json_equal(
                            receipt_value.get("systemd_supervisor"),
                            boundary["supervisor"],
                        )
                        or not strict_json_equal(
                            receipt_value.get("control_freeze"), boundary["control_freeze"]
                        )
                        or not strict_json_equal(
                            receipt_value.get("attempt_matrix_freeze"),
                            boundary["attempt_matrix_freeze"],
                        )
                        or receipt_value.get("experiment_id") != EXPERIMENT_ID
                        or not valid_utc_receipt_timestamp(
                            receipt_value.get("adopted_at_utc")
                        )
                        or not isinstance(adoption_claim_record, Mapping)
                        or not identity_matches(
                            adoption_claim_record, adoption_claim_path
                        )
                    ):
                        raise OrdinalError(f"TERMINAL_RECEIPT_MISMATCH:{terminal_receipt}")
                    require_no_symlink_components(adoption_claim_path, experiment_root)
                    supervision_root = experiment_root / "systemd_supervision"
                    try:
                        adoption_claim_path.relative_to(supervision_root)
                    except ValueError as error:
                        raise OrdinalError(
                            "SYSTEMD_ADOPTION_CLAIM_OUTSIDE_SUPERVISION_ROOT:"
                            f"{adoption_claim_path}"
                        ) from error
                    adoption_claim = json.loads(
                        adoption_claim_path.read_text(encoding="utf-8")
                    )
                    if (
                        adoption_claim.get("schema_version")
                        != "aqua-fe-fair-stability-systemd-adoption-claim-v10"
                        or adoption_claim.get("experiment_id") != EXPERIMENT_ID
                        or adoption_claim.get("planned_ordinal")
                        != int(cell["ordinal"])
                        or adoption_claim.get("attempt_index") != attempt_index
                        or adoption_claim.get("attempt_root") != str(root)
                    ):
                        raise OrdinalError(
                            f"SYSTEMD_ADOPTION_CLAIM_COORDINATE_DRIFT:{adoption_claim_path}"
                        )
                    final_adoption_path = (
                        adoption_claim_path.parent
                        / "systemd_adoption_receipt.json"
                    )
                    if final_adoption_path.is_symlink() or (
                        final_adoption_path.exists()
                        and not final_adoption_path.is_file()
                    ):
                        raise OrdinalError(
                            f"SYSTEMD_FINAL_ADOPTION_RECEIPT_INVALID:{final_adoption_path}"
                        )
                    if not final_adoption_path.is_file():
                        require_validated_runtime_monitor()
                        require_validated_result()
                        require_validated_semantic_artifacts()
                        return {
                            "state": "SYSTEMD_RESULT_PENDING_ADOPTION_FINALIZATION",
                            "cell": dict(cell),
                            "attempt_index": attempt_index,
                            "attempt_root": str(root),
                            "result": result,
                            "result_identity": validated_result_identity,
                            "terminal_receipt": str(terminal_receipt),
                            "systemd_adoption_claim": identity(
                                adoption_claim_path
                            ),
                            "invalid_chain": invalid_chain,
                        }
                    # The main state path must consume the same centralized,
                    # outcome-specific closure used by the supervisor.  In
                    # particular this revalidates the exact claim/final field
                    # sets, retry/timeout flags, result-bound dispatch, and
                    # the frozen terminal follow-up state.  The helper only
                    # recurses forward to a later ordinal when deriving that
                    # follow-up, so it cannot re-enter this cell.
                    finalized = validate_finalized_systemd_adoption(
                        experiment_root,
                        adoption_claim_path.parent,
                    )
                    final_adoption = finalized["receipt"]
                    chain = finalized["chain"]
                    if (
                        not identity_matches(
                            final_adoption.get("ordinal_terminal_receipt"),
                            terminal_receipt,
                        )
                        or adoption_claim.get("unit")
                        != chain["submission_claim"].get("unit")
                    ):
                        raise OrdinalError(
                            f"SYSTEMD_FINAL_ADOPTION_CHAIN_DRIFT:{final_adoption_path}"
                        )
                require_validated_runtime_monitor()
                require_validated_result()
                require_validated_semantic_artifacts()
                return {
                    "state": "TERMINAL" if terminal_receipt.is_file() else "TERMINAL_UNADOPTED",
                    "cell": dict(cell),
                    "attempt_index": attempt_index,
                    "attempt_root": str(root),
                    "result": result,
                    "result_identity": validated_result_identity,
                    "terminal_receipt": str(terminal_receipt),
                    "invalid_chain": invalid_chain,
                }
            if status != "PIPELINE_INVALID":
                raise OrdinalError(f"UNKNOWN_RESULT_STATUS:{root}:{status}")
            if invalid_receipt_path.is_symlink():
                raise OrdinalError(f"PIPELINE_INVALID_RECEIPT_SYMLINK:{invalid_receipt_path}")
            if invalid_receipt_path.exists() and not invalid_receipt_path.is_file():
                raise OrdinalError(f"PIPELINE_INVALID_RECEIPT_NONREGULAR:{invalid_receipt_path}")
            if invalid_receipt_path.is_file():
                raise OrdinalError(
                    f"PIPELINE_ADJUDICATION_DISABLED_ZERO_REPLACEMENT_V10:{root}"
                )
            if not invalid_receipt_path.is_file():
                if later_root is not None and later_root.exists():
                    raise OrdinalError(
                        f"REPLENISHMENT_BEFORE_PIPELINE_INVALID_ADJUDICATION:{root}"
                    )
                require_validated_runtime_monitor()
                require_validated_result()
                require_validated_semantic_artifacts()
                return {
                    "state": "PIPELINE_INVALID_FAIL_STOP_ZERO_RETRY",
                    "cell": dict(cell),
                    "attempt_index": attempt_index,
                    "attempt_root": str(root),
                    "result": result,
                    "result_identity": validated_result_identity,
                    "invalid_chain": invalid_chain,
                }
            invalid_receipt = json.loads(invalid_receipt_path.read_text(encoding="utf-8"))
            if invalid_receipt.get("accepted_as_external_pipeline_fault") is not True:
                raise OrdinalError(f"PIPELINE_INVALID_RECEIPT_REJECTED:{root}")
            boundary = control_boundary(experiment_root)
            evidence = invalid_receipt.get("evidence")
            if not isinstance(evidence, Mapping):
                raise OrdinalError(f"PIPELINE_INVALID_EVIDENCE_MISSING:{root}")
            required_evidence = (
                "attempt_manifest.json", "ordinal_dispatch_claim.json",
                "start_claim.json", "run_result.json",
            )
            if any(
                name not in evidence
                or not identity_matches(evidence.get(name), root / name)
                for name in required_evidence
            ):
                raise OrdinalError(f"PIPELINE_INVALID_REQUIRED_EVIDENCE_DRIFT:{root}")
            expected_evidence: dict[str, object] = {}
            for name in PIPELINE_EVIDENCE_NAMES:
                candidate = root / name
                if candidate.is_symlink() or (
                    candidate.exists() and not candidate.is_file()
                ):
                    raise OrdinalError(f"PIPELINE_INVALID_EVIDENCE_NONREGULAR:{candidate}")
                if candidate.is_file():
                    expected_evidence[name] = identity(candidate)
            if not strict_json_equal(evidence, expected_evidence):
                raise OrdinalError(f"PIPELINE_INVALID_EVIDENCE_DRIFT:{root}")
            systemd_adoption_record = invalid_receipt.get(
                "systemd_adoption_receipt"
            )
            systemd_adoption_path = Path(
                str(
                    systemd_adoption_record.get("path", "")
                    if isinstance(systemd_adoption_record, Mapping)
                    else ""
                )
            )
            if (
                invalid_receipt.get("schema_version")
                != "aqua-fe-fair-stability-pipeline-invalid-adjudication-v10"
                or invalid_receipt.get("automatic_retry_policy")
                != "EXPLICIT_EXTERNAL_TRANSIENT_ONLY_V10"
                or invalid_receipt.get("maximum_replacement_attempts_per_planned_cell")
                != MAX_REPLACEMENT_ATTEMPTS_PER_CELL
                or not identity_matches(invalid_receipt.get("run_result"), result_path)
                or not strict_json_equal(
                    invalid_receipt.get("run_result"),
                    validated_result_identity,
                )
                or not identity_matches(
                    invalid_receipt.get("runtime_resource_monitor"),
                    root / "runtime_resource_monitor.json",
                )
                or not strict_json_equal(
                    invalid_receipt.get("runtime_resource_monitor"),
                    validated_runtime_monitor,
                )
                or not strict_json_equal(
                    invalid_receipt.get("runtime_resource_monitor"),
                    evidence.get("runtime_resource_monitor.json"),
                )
                or not strict_json_equal(
                    invalid_receipt.get("semantic_artifacts"),
                    validated_semantic_artifacts,
                )
                or not strict_json_equal(
                    [
                        invalid_receipt.get("planned_ordinal"),
                        invalid_receipt.get("case_id"), invalid_receipt.get("arm"),
                        invalid_receipt.get("repeat"),
                        invalid_receipt.get("attempt_index"),
                    ],
                    [
                        int(cell["ordinal"]), str(cell["case_id"]),
                        str(cell["arm"]), int(cell["repeat"]), attempt_index,
                    ],
                )
                or invalid_receipt.get("schedule_sha256") != SCHEDULE_SHA256
                or not strict_json_equal(
                    invalid_receipt.get("pipeline_failure_codes"),
                    [str(value) for value in result.get("pipeline_failure_codes", [])],
                )
                or not strict_json_equal(
                    invalid_receipt.get(
                        "algorithm_failure_codes_observed_but_excluded_with_invalid_attempt"
                    ),
                    list(result.get("algorithm_failure_codes", [])),
                )
                or not strict_json_equal(
                    invalid_receipt.get("controller"), boundary["controller"]
                )
                or not strict_json_equal(
                    invalid_receipt.get("systemd_supervisor"),
                    boundary["supervisor"],
                )
                or not strict_json_equal(
                    invalid_receipt.get("control_freeze"), boundary["control_freeze"]
                )
                or not strict_json_equal(
                    invalid_receipt.get("attempt_matrix_freeze"),
                    boundary["attempt_matrix_freeze"],
                )
                or invalid_receipt.get("experiment_id") != EXPERIMENT_ID
                or not valid_utc_receipt_timestamp(
                    invalid_receipt.get("adjudicated_at_utc")
                )
                or not isinstance(systemd_adoption_record, Mapping)
                or not identity_matches(
                    systemd_adoption_record, systemd_adoption_path
                )
            ):
                raise OrdinalError(f"PIPELINE_INVALID_RECEIPT_RESULT_DRIFT:{root}")
            require_no_symlink_components(systemd_adoption_path, experiment_root)
            try:
                systemd_adoption_path.relative_to(
                    experiment_root / "systemd_supervision"
                )
            except ValueError as error:
                raise OrdinalError(
                    "PIPELINE_INVALID_SYSTEMD_ADOPTION_OUTSIDE_ROOT:"
                    f"{systemd_adoption_path}"
                ) from error
            systemd_adoption = json.loads(
                systemd_adoption_path.read_text(encoding="utf-8")
            )
            start_claim_value = json.loads(
                start_path.read_text(encoding="utf-8")
            )
            pipeline_chain_records = {
                key: systemd_adoption.get(key) for key in SYSTEMD_CHAIN_FILES
            }
            pipeline_chain = validate_systemd_chain(
                experiment_root,
                pipeline_chain_records,
                systemd_adoption_path.parent,
            )
            if (
                systemd_adoption.get("schema_version")
                != "aqua-fe-fair-stability-systemd-adoption-v10"
                or systemd_adoption.get("experiment_id") != EXPERIMENT_ID
                or systemd_adoption.get("ordinal_terminal_receipt") is not None
                or not strict_json_equal(
                    systemd_adoption.get("systemd_start_receipt"),
                    start_claim_value.get("systemd_start_receipt"),
                )
                or systemd_adoption.get("unit")
                != pipeline_chain["submission_claim"].get("unit")
                or systemd_adoption.get("controller_returncode")
                != pipeline_chain["systemd_execution_receipt"].get(
                    "controller_returncode"
                )
            ):
                raise OrdinalError(
                    f"PIPELINE_INVALID_SYSTEMD_ADOPTION_CHAIN_DRIFT:{systemd_adoption_path}"
                )
            pipeline_codes = [
                str(value) for value in result.get("pipeline_failure_codes", [])
            ]
            if (
                not pipeline_codes
                or len(pipeline_codes) != len(set(pipeline_codes))
                or any(
                    code not in AUTOMATIC_RETRY_PIPELINE_FAILURES
                    for code in pipeline_codes
                )
            ):
                raise OrdinalError(
                    f"PIPELINE_INVALID_RECEIPT_NONRETRYABLE_CODE:{root}"
                )
            prior_codes = {
                code
                for entry in invalid_chain
                for code in entry.get("pipeline_failure_codes", [])
            }
            if prior_codes.intersection(pipeline_codes):
                raise OrdinalError(
                    f"REPEATED_PIPELINE_FAILURE_CODE_HALT:{cell['ordinal']}"
                )
            require_validated_runtime_monitor()
            require_validated_result()
            require_validated_semantic_artifacts()
            invalid_chain.append(
                {
                    "attempt_index": attempt_index,
                    "attempt_root": str(root),
                    "pipeline_failure_codes": pipeline_codes,
                    "run_result": validated_result_identity,
                    "receipt": identity(invalid_receipt_path),
                }
            )
            if attempt_index == MAX_ATTEMPTS_PER_CELL:
                raise OrdinalError(
                    f"REPLACEMENT_LIMIT_EXHAUSTED:{cell['ordinal']}:"
                    f"{MAX_REPLACEMENT_ATTEMPTS_PER_CELL}"
                )
            attempt_index += 1
            continue
        if invalid_receipt_path.exists():
            raise OrdinalError(f"INVALID_RECEIPT_WITHOUT_RESULT:{root}")
        if start_path.exists():
            state = systemd_started_without_result_state(
                experiment_root, start_path, cell, attempt_index
            )
            state["invalid_chain"] = invalid_chain
            return state
        if later_root is not None and later_root.exists():
            raise OrdinalError(f"LATER_ATTEMPT_BEFORE_CURRENT_TERMINAL:{root}")
        return {
            "state": "READY",
            "cell": dict(cell),
            "attempt_index": attempt_index,
            "attempt_root": str(root),
            "invalid_chain": invalid_chain,
        }
    raise OrdinalError("ATTEMPT_INDEX_LIMIT_EXCEEDED")


def next_state(experiment_root: Path) -> dict[str, Any]:
    load_attempt_matrix(experiment_root)
    schedule = load_schedule(experiment_root)
    first_nonterminal: dict[str, Any] | None = None
    for position, cell in enumerate(schedule):
        state = inspect_cell(experiment_root, cell)
        if state["state"] == "TERMINAL":
            continue
        first_nonterminal = state
        for later in schedule[position + 1 :]:
            later_state = inspect_cell(experiment_root, later)
            later_root = Path(later_state["attempt_root"])
            if (
                later_state["state"] not in {"READY", "NEEDS_PREPARATION"}
                or int(later_state.get("attempt_index", 1)) != 1
                or bool(later_state.get("invalid_chain"))
                or (later_root / "ordinal_dispatch_claim.json").exists()
                or (later_root / "start_claim.json").exists()
                or (later_root / "run_result.json").exists()
            ):
                raise OrdinalError(f"LATER_CELL_STARTED_OUT_OF_ORDER:{later['ordinal']}")
        break
    return first_nonterminal or {"state": "COMPLETE", "completed": 120}


def authorize(
    experiment_root: Path,
    case_id: str,
    arm: str,
    repeat: int,
    attempt_index: int,
) -> dict[str, Any]:
    state = next_state(experiment_root)
    if state.get("state") != "READY":
        raise OrdinalError(f"NEXT_CELL_NOT_READY:{state.get('state')}")
    cell = state["cell"]
    requested = (case_id, arm, repeat, attempt_index)
    expected = (
        str(cell["case_id"]), str(cell["arm"]), int(cell["repeat"]), int(state["attempt_index"])
    )
    if requested != expected:
        raise OrdinalError(f"OUT_OF_ORDER_REQUEST:{requested}:EXPECTED:{expected}")
    return state


def verify_dispatch_claim(
    experiment_root: Path,
    attempt_root_path: Path,
    case_id: str,
    arm: str,
    repeat: int,
    attempt_index: int,
) -> dict[str, Any]:
    require_no_symlink_components(attempt_root_path, experiment_root)
    token = os.environ.get("FAIR_STABILITY_DISPATCH_TOKEN", "")
    if not token:
        raise OrdinalError("DISPATCH_TOKEN_MISSING")
    path = attempt_root_path / "ordinal_dispatch_claim.json"
    if not path.is_file() or path.is_symlink():
        raise OrdinalError("DISPATCH_CLAIM_MISSING_OR_INVALID")
    claim = json.loads(path.read_text(encoding="utf-8"))
    expected = [case_id, arm, repeat, attempt_index]
    observed = [
        claim.get("case_id"), claim.get("arm"),
        claim.get("repeat"), claim.get("attempt_index"),
    ]
    if not strict_json_equal(observed, expected):
        raise OrdinalError(f"DISPATCH_COORDINATE_MISMATCH:{observed}:{expected}")
    if claim.get("schema_version") != "aqua-fe-fair-stability-ordinal-dispatch-v10":
        raise OrdinalError("DISPATCH_SCHEMA_MISMATCH")
    if claim.get("experiment_id") != EXPERIMENT_ID:
        raise OrdinalError("DISPATCH_EXPERIMENT_ID_MISMATCH")
    if claim.get("schedule_sha256") != SCHEDULE_SHA256:
        raise OrdinalError("DISPATCH_SCHEDULE_MISMATCH")
    boundary = control_boundary(experiment_root)
    current_attempt_manifest = identity(attempt_root_path / "attempt_manifest.json")
    claimed_attempt_manifest = claim.get("attempt_manifest")
    if not strict_json_equal(claimed_attempt_manifest, current_attempt_manifest):
        raise OrdinalError("DISPATCH_ATTEMPT_MANIFEST_DRIFT")
    if claim.get("token_sha256") != hashlib.sha256(token.encode("ascii")).hexdigest():
        raise OrdinalError("DISPATCH_TOKEN_MISMATCH")
    if claim.get("dispatch_token") != token:
        raise OrdinalError("DISPATCH_EMBEDDED_TOKEN_MISMATCH")
    if not strict_json_equal(claim.get("controller"), boundary["controller"]):
        raise OrdinalError("DISPATCH_CONTROLLER_DRIFT")
    if not strict_json_equal(claim.get("control_freeze"), boundary["control_freeze"]):
        raise OrdinalError("DISPATCH_CONTROL_FREEZE_DRIFT")
    if not strict_json_equal(
        claim.get("attempt_matrix_freeze"), boundary["attempt_matrix_freeze"]
    ):
        raise OrdinalError("DISPATCH_ATTEMPT_MATRIX_FREEZE_DRIFT")
    if not strict_json_equal(
        claim.get("planned_ordinal"),
        authorize(experiment_root, case_id, arm, repeat, attempt_index)["cell"]["ordinal"],
    ):
        raise OrdinalError("DISPATCH_ORDINAL_MISMATCH")
    return {"claim": claim, "identity": identity(path)}
