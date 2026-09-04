#!/usr/bin/python3
"""Fail-closed schedule state for fair-stability runtime-exclusive v6."""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timedelta
from pathlib import Path
import re
from typing import Any, Mapping


SCHEDULE_SHA256 = "8fdb07f404bc4a24a3866dc1acd6cf8a20b9c960b84d6a9e430299852bc655e8"
EXPERIMENT_ID = "fair-stability-positive-roster-openloop-runtimeexcl-v6"
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
TERMINAL_STATUSES = {"SUCCESS", "PARTIAL_NON_SUCCESS", "ALGORITHM_FAILURE"}
CONTROLLER_DISPATCH_EXECUTION_SCHEMA = (
    "aqua-fe-fair-stability-controller-dispatch-execution-v6"
)
MAX_REPLACEMENT_ATTEMPTS_PER_CELL = 2
MAX_ATTEMPTS_PER_CELL = 1 + MAX_REPLACEMENT_ATTEMPTS_PER_CELL
AUTOMATIC_RETRY_PIPELINE_FAILURES = frozenset({
    "MIDRUN_EXTERNAL_RESOURCE_INTRUSION",
})
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


def control_boundary(experiment_root: Path) -> dict[str, dict[str, object]]:
    """Bind receipts and dispatches to this controller and this frozen control set."""
    common = Path(__file__).resolve()
    controller = common.parent / "run_fair_stability_next_v6.py"
    supervisor = common.parent / "run_fair_stability_systemd_supervisor_v6.py"
    freeze_path = (
        experiment_root / "vins_dev_nativeq_schedfix_runtimeexcl_v6" / "backend_freeze.json"
    )
    require_no_symlink_components(freeze_path, experiment_root)
    freeze_identity = identity(freeze_path)
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    if freeze.get("status") != "FROZEN_BEFORE_NEW_VINS_REPLAY":
        raise OrdinalError("CONTROL_FREEZE_STATUS_INVALID")
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
        "attempt_matrix_freeze": identity(experiment_root / "attempt_matrix_freeze_v6.json"),
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
        "aqua-fe-fair-stability-systemd-submission-v6",
    ),
    "submission_receipt": (
        "submission_receipt.json",
        "aqua-fe-fair-stability-systemd-submit-receipt-v6",
    ),
    "systemd_start_receipt": (
        "systemd_start_receipt.json",
        "aqua-fe-fair-stability-systemd-start-receipt-v6",
    ),
    "systemd_execution_receipt": (
        "systemd_execution_receipt.json",
        "aqua-fe-fair-stability-systemd-execution-v6",
    ),
    "systemd_terminal_receipt": (
        "systemd_terminal_receipt.json",
        "aqua-fe-fair-stability-systemd-terminal-v6",
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
        != "aqua-fe-fair-stability-systemd-start-receipt-v6"
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
    """Validate a no-estimator submission that adjudicates a prior result."""
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
        != "aqua-fe-fair-stability-pipeline-invalid-adjudication-v6"
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
        != "aqua-fe-fair-stability-systemd-adoption-v6"
        or prior_adoption.get("experiment_id") != EXPERIMENT_ID
        or prior_adoption.get("ordinal_terminal_receipt") is not None
        or prior_adoption.get("unit") != prior_claim.get("unit")
        or prior_adoption.get("controller_returncode") != 0
        or prior_adoption.get("controller_outcome")
        != "PIPELINE_INVALID_REQUIRES_ADJUDICATION"
        or not isinstance(prior_adoption_claim, dict)
        or prior_adoption_claim.get("schema_version")
        != "aqua-fe-fair-stability-systemd-adoption-claim-v6"
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


def validate_systemd_chain(
    experiment_root: Path,
    records: Mapping[str, object],
    submission_directory: Path,
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
    if (
        not strict_json_equal(recorded_environment, FIXED_SERVICE_ENVIRONMENT)
        or not strict_json_equal(start.get("fixed_service_environment"), FIXED_SERVICE_ENVIRONMENT)
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
        or int(exit_status) != execution.get("controller_returncode")
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

    # If this service invocation published an algorithm result, independently
    # re-read the inner runner execution receipt.  A normal systemd/controller
    # exit cannot legitimize a result whose runner was signalled or otherwise
    # exited with a code inconsistent with the published status.
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
    if result_path.is_file() and not result_path.is_symlink():
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
        dispatch = validate_controller_dispatch_execution_for_result(
            experiment_root, claimed_attempt_root, result
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
        else:
            expected_outcome = (
                "TERMINAL_RESULT_PENDING_SYSTEMD_ADOPTION"
                if result.get("status") in TERMINAL_STATUSES
                else "PIPELINE_INVALID_REQUIRES_ADJUDICATION"
                if result.get("status") == "PIPELINE_INVALID"
                else None
            )
            dispatch_receipt = dispatch["receipt"]
            if (
                not isinstance(pre_state, Mapping)
                or pre_state.get("state") not in {"READY", "NEEDS_PREPARATION"}
                or pre_state.get("attempt_root") != str(claimed_attempt_root)
                or expected_outcome is None
                or execution.get("controller_returncode") != 0
                or controller_result.get("outcome") != expected_outcome
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
    """Verify the immutable 120-attempt v6 matrix without freezing later retries."""
    path = experiment_root / "attempt_matrix_freeze_v6.json"
    require_no_symlink_components(path, experiment_root)
    if path.is_symlink() or not path.is_file():
        raise OrdinalError("ATTEMPT_MATRIX_FREEZE_MISSING_OR_INVALID")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        value.get("schema_version")
        != "aqua-fe-fair-stability-attempt-matrix-freeze-v6"
        or value.get("experiment_id") != EXPERIMENT_ID
        or value.get("status") != "FROZEN_BEFORE_ANY_V6_ESTIMATOR_START"
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
            / "vins_dev_nativeq_schedfix_runtimeexcl_v6"
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
            experiment_root / "vins_dev_nativeq_schedfix_runtimeexcl_v6" / "attempts"
            / case_id / arm / f"repeat_{repeat:03d}"
        )
    if attempt_index < 1 or attempt_index > MAX_ATTEMPTS_PER_CELL:
        raise OrdinalError("ATTEMPT_INDEX_INVALID")
    return base if attempt_index == 1 else base.with_name(
        f"{base.name}__replenishment_{attempt_index:03d}"
    )


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


def result_contract_valid(value: Mapping[str, Any]) -> bool:
    """Verify the runner's deterministic status/failure-code derivation."""
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
    if (
        not isinstance(execution, Mapping)
        or execution.get("postprocess_signals_deferred") != []
    ):
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
    return (
        value.get("status") == expected_status
        and type(clean_success) is bool
        and (expected_status == "SUCCESS" or clean_success is False)
    )


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
    controller_path = Path(__file__).resolve().parent / "run_fair_stability_next_v6.py"
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


def validate_hfnet_watchdog_evidence(
    root: Path,
    manifest: Mapping[str, Any],
    result: Mapping[str, Any],
    cell: Mapping[str, Any],
    attempt_index: int,
) -> None:
    path = root / "zero_kf_post_shutdown_watchdog.json"
    recorded = result.get("zero_kf_post_shutdown_watchdog")
    if not isinstance(recorded, Mapping) or not identity_matches(recorded, path):
        raise OrdinalError(f"HFNET_ZERO_KF_WATCHDOG_IDENTITY_DRIFT:{path}")
    value = json.loads(path.read_text(encoding="utf-8"))
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
        != "aqua-fe-fair-stability-hfnet-zero-kf-post-shutdown-watchdog-v6"
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
        != "aqua-fe-fair-stability-hfnet-launch-receipt-v6"
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
        if errors not in (
            ["EXACT_GROUP_LEADER_IDENTITY_OR_ARGV_MISMATCH"],
            [
                "EXACT_GROUP_LEADER_IDENTITY_OR_ARGV_MISMATCH",
                "EXACT_GROUP_LEADER_DISAPPEARED_DURING_RECHECK",
            ],
        ) or len(members) != 1 or not isinstance(members[0], Mapping):
            return False
        member = members[0]
        return bool(
            set(member) == member_keys
            and member.get("pid") == launch_pid
            and member.get("start_ticks") == launch_start_ticks
            and member.get("pgid") == launch_pid
            and member.get("session") == launch_pid
            and member.get("state") == "Z"
            and member.get("executable") is None
            and member.get("cmdline_sha256") == hashlib.sha256(b"").hexdigest()
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
        if (
            set(value_candidate) != {
                "phase", "evidence", "last_exact_group_snapshot",
                "adjudicated_at_utc", "adjudicated_monotonic_ns",
                "child_returncode", "reaped_before_next_sample",
                "signal_attempted", "signal_sent",
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
        ):
            return False

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
                and evidence.get("leader_returncode") == returncode
                and evidence.get("reaped_before_next_sample") is True
                and evidence.get("signal_attempted") is False
                and evidence.get("signal_sent") is False
                and evidence.get("errors") == []
            )

        if phase.startswith("ORDINARY_PROCESS_EXIT:"):
            ordinary_phase = phase.split(":", 1)[1]
            if ordinary_phase not in {"LOOP_POLL", "SCHEDULED_WAIT"} or not valid_reaped_base(
                "ORDINARY_CHILD_REAPED", ordinary_phase, set()
            ):
                return False
            if last_snapshot is None:
                return True
            return bool(
                valid_group_proof(last_snapshot)
                and proof_monotonic_ns(last_snapshot)
                <= int(evidence["observed_monotonic_ns"])
            )

        if phase == "PERIODIC_EXACT_GROUP_PROOF":
            return bool(
                valid_terminal_transition_proof(evidence)
                and strict_json_equal(last_snapshot, evidence)
                and proof_monotonic_ns(evidence) <= int(adjudicated_ns)
            )
        if not phase.startswith("FINAL_SIGNAL_GATE:"):
            return False
        evidence_phase = evidence.get("phase")
        if (
            not isinstance(evidence_phase, str)
            or phase != f"FINAL_SIGNAL_GATE:{evidence_phase}"
            or not valid_group_proof(last_snapshot)
        ):
            return False
        last_ns = proof_monotonic_ns(last_snapshot)
        if last_ns is None:
            return False
        classification = evidence.get("classification")
        if classification == "LEADER_REAPED_BEFORE_SIGNAL":
            extras_by_phase = {
                "BEFORE_FIRST_FINAL_GROUP_PROOF": set(),
                "AFTER_FIRST_FINAL_GROUP_PROOF": {"terminal_transition_snapshot"},
                "AFTER_SECOND_FINAL_GROUP_PROOF": {
                    "first_exact_group_proof", "terminal_transition_snapshot",
                },
                "BEFORE_KILLPG": {
                    "first_exact_group_proof", "final_exact_group_proof",
                },
            }
            extra_keys = extras_by_phase.get(evidence_phase)
            if extra_keys is None or not valid_reaped_base(
                "LEADER_REAPED_BEFORE_SIGNAL", evidence_phase, extra_keys
            ):
                return False
            observed_ns = int(evidence["observed_monotonic_ns"])
            if evidence_phase == "BEFORE_FIRST_FINAL_GROUP_PROOF":
                return last_ns <= observed_ns
            first = evidence.get("first_exact_group_proof")
            transition = evidence.get("terminal_transition_snapshot")
            if evidence_phase == "AFTER_FIRST_FINAL_GROUP_PROOF":
                transition_ns = proof_monotonic_ns(transition)
                return bool(
                    (valid_group_proof(transition)
                     or valid_terminal_transition_proof(transition))
                    and transition_ns is not None
                    and last_ns <= transition_ns <= observed_ns
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
                    and last_ns <= first_ns <= transition_ns <= observed_ns
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
                and last_ns <= first_ns <= final_ns <= observed_ns
            )
        if classification != "TERMINAL_TRANSITION_PENDING_REAP":
            return False
        pending_base_keys = {
            "classification", "phase", "terminal_transition_snapshot",
            "signal_attempted", "signal_sent", "errors",
        }
        expected_keys = (
            pending_base_keys
            if evidence_phase == "FIRST_FINAL_GROUP_PROOF"
            else pending_base_keys | {"first_exact_group_proof"}
            if evidence_phase == "SECOND_FINAL_GROUP_PROOF"
            else None
        )
        transition = evidence.get("terminal_transition_snapshot")
        transition_ns = proof_monotonic_ns(transition)
        if (
            expected_keys is None
            or set(evidence) != expected_keys
            or evidence.get("signal_attempted") is not False
            or evidence.get("signal_sent") is not False
            or not valid_terminal_transition_proof(transition)
            or evidence.get("errors") != transition.get("errors")
            or transition_ns is None
            or transition_ns > int(adjudicated_ns)
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
        != "aqua-fe-fair-stability-hfnet-zero-kf-watchdog-outcome-v6"
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
        or not strict_json_equal(
            value.get("passive_exit_adjudication"), passive_exit
        )
        or not numeric_outcome_valid
        or not isinstance(runtime_receipt, Mapping)
        or runtime_receipt.get("schema_version")
        != "aqua-fe-fair-stability-runtime-resource-monitor-v6"
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
        or type(action.get("deadline_monotonic")) not in (int, float)
        or not math.isfinite(float(action.get("deadline_monotonic", 0.0)))
        or type(action.get("pre_signal_monotonic")) not in (int, float)
        or not math.isfinite(float(action.get("pre_signal_monotonic", 0.0)))
        or type(action.get("sample_started_monotonic")) not in (int, float)
        or not math.isfinite(float(action.get("sample_started_monotonic", 0.0)))
        or type(action.get("maximum_observation_gap_seconds")) not in (int, float)
        or not math.isfinite(
            float(action.get("maximum_observation_gap_seconds", 0.0))
        )
        or action.get("maximum_observation_gap_seconds")
        != fixed_contract["maximum_poll_interval_seconds"]
        or float(action.get("pre_signal_monotonic", 0.0))
        - float(action.get("sample_started_monotonic", 0.0))
        > float(action.get("maximum_observation_gap_seconds", 0.0))
        or float(action.get("pre_signal_monotonic", 0.0))
        >= float(action.get("deadline_monotonic", 0.0))
        or not (
            0.0
            <= float(action.get("sample_started_monotonic", -1.0))
            <= float(
                outcome["last_exact_group_snapshot"]["observed_monotonic_ns"]
            )
            / 1_000_000_000.0
            <= float(
                action["first_exact_group_proof"]["observed_monotonic_ns"]
            )
            / 1_000_000_000.0
            <= float(
                action["final_exact_group_proof"]["observed_monotonic_ns"]
            )
            / 1_000_000_000.0
            <= float(action.get("pre_signal_monotonic", -1.0))
            <= float(action.get("monotonic_ns", -1)) / 1_000_000_000.0
        )
        or float(continuous_seconds) < float(fixed_contract["fixed_grace_seconds"])
        or float(maximum_gap)
        > float(fixed_contract["maximum_poll_interval_seconds"])
        or final_outputs.get("trajectory_absent_non_symlink") is not True
        or final_outputs.get("keyframe_absent_non_symlink") is not True
    ):
        raise OrdinalError(f"HFNET_ZERO_KF_WATCHDOG_SIGNAL_DRIFT:{path}")


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
        != "aqua-fe-fair-stability-systemd-start-receipt-v6"
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
        != "aqua-fe-fair-stability-systemd-submission-v6"
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
        != "aqua-fe-fair-stability-systemd-terminal-v6"
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
            "aqua-fe-fair-stability-hfnet-attempt-v6"
            if hfnet_arm
            else "aqua-fe-fair-stability-vins-attempt-v6"
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
            result = json.loads(result_path.read_text(encoding="utf-8"))
            expected_result_schema = (
                "aqua-fe-fair-stability-hfnet-result-v6"
                if hfnet_arm
                else "aqua-fe-fair-stability-vins-result-v6"
            )
            if (
                result.get("schema_version") != expected_result_schema
                or result.get("experiment_id") != EXPERIMENT_ID
                or not _coordinate_matches(result, cell, attempt_index)
                or not result_contract_valid(result)
            ):
                raise OrdinalError(f"RESULT_SCHEMA_OR_COORDINATE_MISMATCH:{root}")
            validate_controller_dispatch_execution_for_result(
                experiment_root, root, result
            )
            if hfnet_arm:
                validate_hfnet_watchdog_evidence(
                    root, manifest, result, cell, attempt_index
                )
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
                        != "aqua-fe-fair-stability-ordinal-terminal-v6"
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
                        or not identity_matches(receipt_value.get("start_claim"), start_path)
                        or not identity_matches(receipt_value.get("attempt_manifest"), manifest_path)
                        or not identity_matches(
                            receipt_value.get("ordinal_dispatch_claim"),
                            root / "ordinal_dispatch_claim.json",
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
                        != "aqua-fe-fair-stability-systemd-adoption-claim-v6"
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
                        return {
                            "state": "SYSTEMD_RESULT_PENDING_ADOPTION_FINALIZATION",
                            "cell": dict(cell),
                            "attempt_index": attempt_index,
                            "attempt_root": str(root),
                            "result": result,
                            "result_identity": identity(result_path),
                            "terminal_receipt": str(terminal_receipt),
                            "systemd_adoption_claim": identity(
                                adoption_claim_path
                            ),
                            "invalid_chain": invalid_chain,
                        }
                    final_adoption = json.loads(
                        final_adoption_path.read_text(encoding="utf-8")
                    )
                    required_chain = {
                        "submission_claim": adoption_claim.get(
                            "submission_claim"
                        ),
                        "submission_receipt": adoption_claim.get(
                            "submission_receipt"
                        ),
                        "systemd_start_receipt": adoption_claim.get(
                            "systemd_start_receipt"
                        ),
                        "systemd_execution_receipt": adoption_claim.get(
                            "systemd_execution_receipt"
                        ),
                        "systemd_terminal_receipt": adoption_claim.get(
                            "systemd_terminal_receipt"
                        ),
                    }
                    validate_attempt_start_systemd_binding(
                        experiment_root,
                        start_path,
                        required_chain["systemd_start_receipt"],
                    )
                    chain = validate_systemd_chain(
                        experiment_root,
                        required_chain,
                        adoption_claim_path.parent,
                    )
                    if (
                        final_adoption.get("schema_version")
                        != "aqua-fe-fair-stability-systemd-adoption-v6"
                        or final_adoption.get("experiment_id") != EXPERIMENT_ID
                        or not identity_matches(
                            final_adoption.get("systemd_adoption_claim"),
                            adoption_claim_path,
                        )
                        or not identity_matches(
                            final_adoption.get("ordinal_terminal_receipt"),
                            terminal_receipt,
                        )
                        or any(
                            not strict_json_equal(
                                final_adoption.get(key), expected
                            )
                            for key, expected in required_chain.items()
                        )
                        or adoption_claim.get("unit")
                        != chain["submission_claim"].get("unit")
                        or adoption_claim.get("controller_returncode")
                        != chain["systemd_execution_receipt"].get(
                            "controller_returncode"
                        )
                        or final_adoption.get("unit")
                        != chain["submission_claim"].get("unit")
                        or final_adoption.get("controller_returncode")
                        != chain["systemd_execution_receipt"].get(
                            "controller_returncode"
                        )
                    ):
                        raise OrdinalError(
                            f"SYSTEMD_FINAL_ADOPTION_CHAIN_DRIFT:{final_adoption_path}"
                        )
                return {
                    "state": "TERMINAL" if terminal_receipt.is_file() else "TERMINAL_UNADOPTED",
                    "cell": dict(cell),
                    "attempt_index": attempt_index,
                    "attempt_root": str(root),
                    "result": result,
                    "result_identity": identity(result_path),
                    "terminal_receipt": str(terminal_receipt),
                    "invalid_chain": invalid_chain,
                }
            if status != "PIPELINE_INVALID":
                raise OrdinalError(f"UNKNOWN_RESULT_STATUS:{root}:{status}")
            if invalid_receipt_path.is_symlink():
                raise OrdinalError(f"PIPELINE_INVALID_RECEIPT_SYMLINK:{invalid_receipt_path}")
            if invalid_receipt_path.exists() and not invalid_receipt_path.is_file():
                raise OrdinalError(f"PIPELINE_INVALID_RECEIPT_NONREGULAR:{invalid_receipt_path}")
            if not invalid_receipt_path.is_file():
                if later_root is not None and later_root.exists():
                    raise OrdinalError(
                        f"REPLENISHMENT_BEFORE_PIPELINE_INVALID_ADJUDICATION:{root}"
                    )
                return {
                    "state": "PIPELINE_INVALID_UNADJUDICATED",
                    "cell": dict(cell),
                    "attempt_index": attempt_index,
                    "attempt_root": str(root),
                    "result": result,
                    "result_identity": identity(result_path),
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
                != "aqua-fe-fair-stability-pipeline-invalid-adjudication-v6"
                or invalid_receipt.get("automatic_retry_policy")
                != "EXPLICIT_EXTERNAL_TRANSIENT_ONLY_V6"
                or invalid_receipt.get("maximum_replacement_attempts_per_planned_cell")
                != MAX_REPLACEMENT_ATTEMPTS_PER_CELL
                or not identity_matches(invalid_receipt.get("run_result"), result_path)
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
                != "aqua-fe-fair-stability-systemd-adoption-v6"
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
            invalid_chain.append(
                {
                    "attempt_index": attempt_index,
                    "attempt_root": str(root),
                    "pipeline_failure_codes": pipeline_codes,
                    "run_result": identity(result_path),
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
    if claim.get("schema_version") != "aqua-fe-fair-stability-ordinal-dispatch-v6":
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
