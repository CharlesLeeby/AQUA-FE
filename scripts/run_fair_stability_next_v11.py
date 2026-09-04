#!/usr/bin/python3
"""Single ordinal dispatcher for the systemd-supervised v11 experiment."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from typing import Any, Mapping, Sequence
import uuid


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from fair_stability_ordinal_common_v11 import (  # noqa: E402
    AUTOMATIC_RETRY_PIPELINE_FAILURES,
    EXPERIMENT_ID,
    MAX_ATTEMPTS_PER_CELL,
    MAX_REPLACEMENT_ATTEMPTS_PER_CELL,
    PIPELINE_EVIDENCE_NAMES,
    SCHEDULE_SHA256,
    TERMINAL_SYSTEMD_OUTCOME,
    TERMINAL_STATUSES,
    canonical_json,
    expected_runner_returncode_for_status,
    identity,
    identity_matches,
    load_attempt_matrix,
    load_schedule,
    next_state,
    strict_json_equal,
    SYSTEMD_CHAIN_FILES,
    validate_attempt_start_systemd_binding,
    validate_hfnet_watchdog_evidence,
    validate_result_semantic_evidence,
    require_semantic_artifact_snapshot,
    require_no_symlink_components,
    validate_runtime_resource_monitor_evidence,
    validate_systemd_chain,
    valid_prestart_resource_gate_v11,
    valid_v10_non_import_claims,
    attempt_root as common_attempt_root,
)


EXPERIMENT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v11"
)
VINS_ROOT = EXPERIMENT_ROOT / "vins_dev_nativeq_schedfix_runtimeexcl_v11"
BACKEND_FREEZE = VINS_ROOT / "backend_freeze.json"
MATRIX_FREEZE = EXPERIMENT_ROOT / "attempt_matrix_freeze_v11.json"
HFNET_RUNNER = ROOT / "scripts/run_fair_stability_hfnet_openloop_v11.py"
VINS_RUNNER = ROOT / "scripts/run_fair_stability_vins_replay_v11.py"
SYSTEMD_SUPERVISOR = ROOT / "scripts/run_fair_stability_systemd_supervisor_v11.py"
SUPERVISION_ROOT = EXPERIMENT_ROOT / "systemd_supervision"
CONTROLLER = Path(__file__).resolve()

class ControllerError(RuntimeError):
    pass


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_exclusive(path: Path, payload: bytes, mode: int = 0o444) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _require_supervision_path(path: Path) -> None:
    anchor = Path(os.path.abspath(SUPERVISION_ROOT))
    target = Path(os.path.abspath(path))
    try:
        relative = target.relative_to(anchor)
    except ValueError as error:
        raise ControllerError(f"SYSTEMD_AUTHORITY_PATH_OUTSIDE_ROOT:{target}") from error
    candidate = anchor
    if candidate.is_symlink():
        raise ControllerError(f"SYSTEMD_AUTHORITY_SYMLINK:{candidate}")
    for part in relative.parts:
        candidate /= part
        if candidate.is_symlink():
            raise ControllerError(f"SYSTEMD_AUTHORITY_SYMLINK:{candidate}")


def _load_json_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ControllerError(f"SYSTEMD_AUTHORITY_FILE_INVALID:{path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ControllerError(
            f"SYSTEMD_AUTHORITY_JSON_INVALID:{path}:{type(error).__name__}"
        ) from error
    if not isinstance(value, dict):
        raise ControllerError(f"SYSTEMD_AUTHORITY_JSON_NOT_OBJECT:{path}")
    return value


def open_regular_lock(path: Path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ControllerError(f"LOCK_PATH_INVALID:{path}")
    descriptor = os.open(
        path,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    return os.fdopen(descriptor, "r+b")


def verify_systemd_authority() -> dict[str, object]:
    """Require the exact live transient-service parent before any mutation."""

    raw_path = os.environ.get("FAIR_STABILITY_SYSTEMD_START_RECEIPT", "")
    invocation_id = os.environ.get("INVOCATION_ID", "")
    if not raw_path or not re.fullmatch(r"[0-9a-f]{32}", invocation_id):
        raise ControllerError("SYSTEMD_TRANSIENT_SERVICE_AUTHORITY_REQUIRED")
    path = Path(raw_path)
    _require_supervision_path(path)
    receipt = _load_json_object(path)
    if (
        receipt.get("schema_version")
        != "aqua-fe-fair-stability-systemd-start-receipt-v11"
        or receipt.get("experiment_id") != EXPERIMENT_ID
        or receipt.get("invocation_id") != invocation_id
    ):
        raise ControllerError("SYSTEMD_START_RECEIPT_HEADER_INVALID")
    if receipt.get("controller_argv") != [
        "/usr/bin/python3", str(CONTROLLER), "run-next"
    ]:
        raise ControllerError("SYSTEMD_START_RECEIPT_CONTROLLER_ARGV_INVALID")
    frozen_context = receipt.get("frozen_context")
    expected_context = {
        "backend_freeze": identity(BACKEND_FREEZE),
        "attempt_matrix_freeze": identity(MATRIX_FREEZE),
        "controller": identity(CONTROLLER),
        "supervisor": identity(SYSTEMD_SUPERVISOR),
    }
    if not strict_json_equal(frozen_context, expected_context):
        raise ControllerError("SYSTEMD_START_RECEIPT_FROZEN_CONTEXT_DRIFT")
    freeze = _load_json_object(BACKEND_FREEZE)
    controls = freeze.get("controls")
    if not isinstance(controls, Mapping) or not strict_json_equal(
        controls.get(SYSTEMD_SUPERVISOR.name), identity(SYSTEMD_SUPERVISOR)
    ):
        raise ControllerError("SYSTEMD_SUPERVISOR_NOT_FROZEN_OR_DRIFTED")
    claim_identity = receipt.get("submission_claim")
    if not isinstance(claim_identity, Mapping):
        raise ControllerError("SYSTEMD_SUBMISSION_CLAIM_IDENTITY_MISSING")
    claim_path = Path(str(claim_identity.get("path", "")))
    _require_supervision_path(claim_path)
    if not strict_json_equal(claim_identity, identity(claim_path)):
        raise ControllerError("SYSTEMD_SUBMISSION_CLAIM_IDENTITY_DRIFT")
    claim = _load_json_object(claim_path)
    if (
        claim.get("schema_version") != "aqua-fe-fair-stability-systemd-submission-v11"
        or claim.get("experiment_id") != EXPERIMENT_ID
        or claim.get("unit") != receipt.get("unit")
    ):
        raise ControllerError("SYSTEMD_SUBMISSION_CLAIM_HEADER_INVALID")
    current_state = next_state(EXPERIMENT_ROOT)
    if not strict_json_equal(claim.get("ordinal_state_before_submit"), current_state):
        raise ControllerError("SYSTEMD_SUBMISSION_ORDINAL_OR_ATTEMPT_DRIFT")
    service_process = receipt.get("service_process")
    verified_unit = receipt.get("verified_unit")
    if not isinstance(service_process, Mapping) or not isinstance(verified_unit, Mapping):
        raise ControllerError("SYSTEMD_LIVE_SERVICE_IDENTITY_MISSING")
    if int(service_process.get("pid", -1)) != os.getppid():
        raise ControllerError("SYSTEMD_SERVICE_ENTRY_NOT_DIRECT_PARENT")
    control_group = str(verified_unit.get("control_group", ""))
    cgroups = service_process.get("cgroup_paths")
    if not control_group or not isinstance(cgroups, list) or control_group not in cgroups:
        raise ControllerError("SYSTEMD_SERVICE_ENTRY_CGROUP_BINDING_INVALID")
    return {"path": str(path), "identity": identity(path), "receipt": receipt}


def verify_control_freeze() -> dict[str, Any]:
    if not BACKEND_FREEZE.is_file():
        raise ControllerError("VINS_BACKEND_AND_CONTROL_FREEZE_MISSING")
    freeze = json.loads(BACKEND_FREEZE.read_text(encoding="utf-8"))
    if freeze.get("status") != "FROZEN_BEFORE_NEW_VINS_REPLAY":
        raise ControllerError("BACKEND_FREEZE_STATUS_INVALID")
    claims = freeze.get("claims")
    if not isinstance(claims, Mapping) or any(
        claims.get(f"v{version}_results_imported") is not False
        for version in range(1, 11)
    ) or not valid_v10_non_import_claims(claims):
        raise ControllerError("BACKEND_FREEZE_PRIOR_RESULTS_IMPORT_CLAIM_INVALID")
    frozen_controls = freeze.get("controls", {})
    for path in (
        CONTROLLER,
        HFNET_RUNNER,
        SYSTEMD_SUPERVISOR,
        SCRIPT_DIR / "fair_stability_ordinal_common_v11.py",
    ):
        expected = frozen_controls.get(path.name)
        observed = identity(path)
        if not isinstance(expected, Mapping) or (
            observed["size_bytes"], observed["sha256"]
        ) != (expected.get("size_bytes"), expected.get("sha256")):
            raise ControllerError(f"CONTROL_NOT_FROZEN_OR_DRIFTED:{path.name}")
    expected_vins_runner = freeze.get("runner")
    observed_vins_runner = identity(VINS_RUNNER)
    if not isinstance(expected_vins_runner, Mapping) or (
        observed_vins_runner["size_bytes"], observed_vins_runner["sha256"]
    ) != (
        expected_vins_runner.get("size_bytes"), expected_vins_runner.get("sha256")
    ):
        raise ControllerError("VINS_RUNNER_NOT_FROZEN_OR_DRIFTED")
    backend = freeze.get("backend", {})
    for key in ("vins_node", "libvins_lib", "libcamera_models", "hfnet_binary", "hfnet_official_library"):
        expected = backend.get(key)
        if not isinstance(expected, Mapping):
            raise ControllerError(f"BACKEND_IDENTITY_MISSING:{key}")
        observed = identity(Path(str(expected.get("path", ""))))
        if (observed["size_bytes"], observed["sha256"]) != (
            expected.get("size_bytes"), expected.get("sha256")
        ):
            raise ControllerError(f"BACKEND_IDENTITY_DRIFT:{key}")
    for key in ("vins_ldd_closure", "hfnet_ldd_closure"):
        closure = backend.get(key)
        if not isinstance(closure, Mapping) or not isinstance(closure.get("resolved_files"), list):
            raise ControllerError(f"DYNAMIC_CLOSURE_MISSING:{key}")
        for expected in closure["resolved_files"]:
            if not isinstance(expected, Mapping):
                raise ControllerError(f"DYNAMIC_CLOSURE_ROW_INVALID:{key}")
            observed = identity(Path(str(expected.get("path", ""))))
            if (observed["size_bytes"], observed["sha256"]) != (
                expected.get("size_bytes"), expected.get("sha256")
            ):
                raise ControllerError(f"DYNAMIC_CLOSURE_DRIFT:{key}:{expected.get('path')}")
    dynamic_check = subprocess.run(
        ["/usr/bin/python3", str(VINS_RUNNER), "verify-freeze"],
        cwd=str(ROOT), check=False, capture_output=True, text=True,
    )
    if dynamic_check.returncode != 0:
        raise ControllerError(
            "FULL_BACKEND_FREEZE_REVERIFICATION_FAILED:"
            + dynamic_check.stderr[-2000:]
        )
    try:
        dynamic_value = json.loads(dynamic_check.stdout)
    except json.JSONDecodeError as error:
        raise ControllerError("FULL_BACKEND_FREEZE_REVERIFICATION_NOT_JSON") from error
    if dynamic_value.get("status") != "VERIFIED":
        raise ControllerError("FULL_BACKEND_FREEZE_REVERIFICATION_STATUS_INVALID")
    return freeze


def runner_argv(state: Mapping[str, Any], command: str) -> list[str]:
    cell = state["cell"]
    attempt_index = int(state["attempt_index"])
    common = [
        "--case", str(cell["case_id"]), "--repeat", str(cell["repeat"]),
        "--attempt-index", str(attempt_index),
    ]
    arm = str(cell["arm"])
    if arm.startswith("hfnet_openloop_"):
        return [
            "/usr/bin/python3", str(HFNET_RUNNER), command,
            *common, "--budget", arm.rsplit("_", 1)[1],
        ]
    return [
        "/usr/bin/python3", str(VINS_RUNNER), command,
        *common, "--arm", arm,
    ]


def run_command(argv: Sequence[str], environment: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv), cwd=str(ROOT), env=dict(environment) if environment else None,
        check=False, capture_output=True, text=True,
    )


def parse_runner_json(command: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    try:
        value = json.loads(command.stdout)
    except json.JSONDecodeError as error:
        raise ControllerError(
            f"RUNNER_STDOUT_NOT_JSON:rc={command.returncode}:stderr={command.stderr[-1000:]}"
        ) from error
    if not isinstance(value, dict):
        raise ControllerError("RUNNER_JSON_NOT_OBJECT")
    return value


def prepare_state(state: Mapping[str, Any]) -> dict[str, Any]:
    command = run_command(runner_argv(state, "prepare"))
    if command.returncode != 0:
        raise ControllerError(f"PREPARE_FAILED:{command.stderr[-2000:]}")
    parse_runner_json(command)
    updated = next_state(EXPERIMENT_ROOT)
    if updated.get("state") != "READY":
        raise ControllerError(f"PREPARE_DID_NOT_PRODUCE_READY:{updated.get('state')}")
    return updated


def revalidate_result_evidence(state: Mapping[str, Any]) -> dict[str, Any]:
    """Return one stable, fully revalidated result/monitor evidence snapshot."""

    cell = state["cell"]
    root = Path(state["attempt_root"])
    recorded = state.get("result")
    result_path = root / "run_result.json"
    result_identity = identity(result_path)
    reread = _load_json_object(result_path)
    if not isinstance(recorded, Mapping) or not strict_json_equal(reread, recorded):
        raise ControllerError("RUN_RESULT_CHANGED_BEFORE_FINAL_CLASSIFICATION")
    if not strict_json_equal(result_identity, identity(result_path)):
        raise ControllerError("RUN_RESULT_CHANGED_DURING_FINAL_CLASSIFICATION")
    monitor_identity = validate_runtime_resource_monitor_evidence(
        root, reread, cell, int(state["attempt_index"])
    )
    semantic_artifacts = validate_result_semantic_evidence(
        root, reread, cell, int(state["attempt_index"])
    )
    if (
        str(cell["arm"]).startswith("hfnet_openloop_")
        and "RUNTIME_RESOURCE_MONITOR_UNPROVEN"
        not in reread.get("pipeline_failure_codes", [])
    ):
        validate_hfnet_watchdog_evidence(
            root,
            _load_json_object(root / "attempt_manifest.json"),
            reread,
            cell,
            int(state["attempt_index"]),
        )
    if (
        not strict_json_equal(result_identity, identity(result_path))
        or not strict_json_equal(
            monitor_identity, identity(root / "runtime_resource_monitor.json")
        )
    ):
        raise ControllerError("EVIDENCE_CHANGED_DURING_FINAL_CLASSIFICATION")
    require_semantic_artifact_snapshot(semantic_artifacts)
    return {
        "result": reread,
        "run_result": result_identity,
        "runtime_resource_monitor": monitor_identity,
        "semantic_artifacts": semantic_artifacts,
    }


def require_evidence_snapshot(
    root: Path, snapshot: Mapping[str, Any]
) -> None:
    """Pin the exact result and monitor bytes across receipt publication."""
    if (
        not strict_json_equal(
            identity(root / "run_result.json"), snapshot.get("run_result")
        )
        or not strict_json_equal(
            identity(root / "runtime_resource_monitor.json"),
            snapshot.get("runtime_resource_monitor"),
        )
    ):
        raise ControllerError("RESULT_OR_MONITOR_CHANGED_DURING_PUBLICATION")
    require_semantic_artifact_snapshot(snapshot.get("semantic_artifacts", {}))


def require_written_payload_identity(path: Path, payload: bytes) -> None:
    expected = {
        "path": str(path),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    if not strict_json_equal(identity(path), expected):
        raise ControllerError("PUBLISHED_RECEIPT_BYTES_DRIFT")


def adopt_terminal(
    state: Mapping[str, Any], systemd_adoption_claim_path: Path
) -> dict[str, Any]:
    verify_control_freeze()
    if state.get("state") != "TERMINAL_UNADOPTED":
        raise ControllerError("ADOPT_REQUIRES_TERMINAL_UNADOPTED")
    cell = state["cell"]
    root = Path(state["attempt_root"])
    result = state["result"]
    if result.get("status") not in TERMINAL_STATUSES:
        raise ControllerError("ADOPT_STATUS_NOT_TERMINAL")
    _require_supervision_path(systemd_adoption_claim_path)
    adoption_claim = _load_json_object(systemd_adoption_claim_path)
    if (
        adoption_claim.get("schema_version")
        != "aqua-fe-fair-stability-systemd-adoption-claim-v11"
        or adoption_claim.get("experiment_id") != EXPERIMENT_ID
        or not strict_json_equal(
            adoption_claim.get("ordinal_state_before_adoption"), state
        )
        or adoption_claim.get("attempt_root") != str(root)
        or adoption_claim.get("planned_ordinal") != int(cell["ordinal"])
        or adoption_claim.get("attempt_index") != int(state["attempt_index"])
    ):
        raise ControllerError("SYSTEMD_ADOPTION_CLAIM_STATE_MISMATCH")
    chain_records = {
        key: adoption_claim.get(key) for key in SYSTEMD_CHAIN_FILES
    }
    try:
        chain = validate_systemd_chain(
            EXPERIMENT_ROOT,
            chain_records,
            systemd_adoption_claim_path.parent,
        )
    except BaseException as error:
        raise ControllerError(
            f"SYSTEMD_TERMINAL_CHAIN_INVALID:{error}"
        ) from error
    execution = chain["systemd_execution_receipt"]
    controller_result = execution.get("controller_result")
    if (
        not isinstance(controller_result, Mapping)
        or execution.get("controller_returncode") != 0
        or controller_result.get("outcome") != TERMINAL_SYSTEMD_OUTCOME
        or not strict_json_equal(controller_result.get("state"), state)
        or not strict_json_equal(
            execution.get("ordinal_state_after_controller"), state
        )
        or type(adoption_claim.get("controller_returncode")) is not int
        or adoption_claim.get("controller_returncode") != 0
        or adoption_claim.get("controller_outcome")
        != TERMINAL_SYSTEMD_OUTCOME
        or adoption_claim.get("unit")
        != chain["submission_claim"].get("unit")
    ):
        raise ControllerError("SYSTEMD_TERMINAL_OUTCOME_CLOSURE_INVALID")
    validate_attempt_start_systemd_binding(
        EXPERIMENT_ROOT,
        root / "start_claim.json",
        adoption_claim.get("systemd_start_receipt"),
    )
    revalidate_result_evidence(state)
    final_adoption_path = (
        systemd_adoption_claim_path.parent / "systemd_adoption_receipt.json"
    )
    if final_adoption_path.exists() or final_adoption_path.is_symlink():
        raise ControllerError("SYSTEMD_FINAL_ADOPTION_PRECEDES_ORDINAL_ADOPTION")
    final_snapshot = revalidate_result_evidence(state)
    result = final_snapshot["result"]
    payload = {
        "schema_version": "aqua-fe-fair-stability-ordinal-terminal-v11",
        "experiment_id": EXPERIMENT_ID,
        "adopted_at_utc": now_utc(),
        "planned_ordinal": int(cell["ordinal"]),
        "case_id": str(cell["case_id"]),
        "arm": str(cell["arm"]),
        "repeat": int(cell["repeat"]),
        "accepted_attempt_index": int(state["attempt_index"]),
        "terminal_status": str(result["status"]),
        "clean_success": bool(result.get("clean_success")),
        "run_result": final_snapshot["run_result"],
        "start_claim": identity(root / "start_claim.json"),
        "attempt_manifest": identity(root / "attempt_manifest.json"),
        "ordinal_dispatch_claim": identity(root / "ordinal_dispatch_claim.json"),
        "runtime_resource_monitor": final_snapshot["runtime_resource_monitor"],
        "semantic_artifacts": final_snapshot["semantic_artifacts"],
        "invalid_attempt_chain": state.get("invalid_chain", []),
        "schedule_sha256": SCHEDULE_SHA256,
        "controller": identity(CONTROLLER),
        "systemd_supervisor": identity(SYSTEMD_SUPERVISOR),
        "control_freeze": identity(BACKEND_FREEZE),
        "attempt_matrix_freeze": identity(MATRIX_FREEZE),
        "systemd_adoption_claim": identity(systemd_adoption_claim_path),
    }
    target = Path(state["terminal_receipt"])
    encoded_payload = canonical_json(payload)
    require_evidence_snapshot(root, final_snapshot)
    write_exclusive(target, encoded_payload)
    require_evidence_snapshot(root, final_snapshot)
    require_written_payload_identity(target, encoded_payload)
    return payload


def automatic_retry_codes(state: Mapping[str, Any]) -> list[str]:
    """Validate the evidence shape, then enforce v11's zero-retry policy."""
    result = state["result"]
    raw_codes = result.get("pipeline_failure_codes")
    if (
        not isinstance(raw_codes, list)
        or not raw_codes
        or any(not isinstance(value, str) or not value for value in raw_codes)
        or len(set(raw_codes)) != len(raw_codes)
    ):
        raise ControllerError("PIPELINE_INVALID_WITHOUT_PIPELINE_FAILURE_CODE")
    codes = list(raw_codes)
    raise ControllerError(
        "PIPELINE_INVALID_HALT_MANUAL_ABANDONMENT_REQUIRED_ZERO_RETRY_V11:"
        f"{codes}"
    )

    # Unreachable historical policy logic retained for receipt diagnostics.
    persistent_or_control = sorted(
        code for code in codes if code not in AUTOMATIC_RETRY_PIPELINE_FAILURES
    )
    if persistent_or_control:
        raise ControllerError(
            "PERSISTENT_OR_CONTROL_PIPELINE_FAILURE_HALT_MANUAL_ABANDONMENT_REQUIRED:"
            f"{persistent_or_control}"
        )
    attempt_index = int(state.get("attempt_index", 0))
    if attempt_index >= MAX_ATTEMPTS_PER_CELL:
        raise ControllerError(
            "REPLACEMENT_LIMIT_EXHAUSTED_HALT_MANUAL_ABANDONMENT_REQUIRED:"
            f"{MAX_REPLACEMENT_ATTEMPTS_PER_CELL}"
        )
    prior_codes = {
        str(code)
        for entry in state.get("invalid_chain", [])
        if isinstance(entry, Mapping)
        for code in entry.get("pipeline_failure_codes", [])
    }
    repeated = sorted(prior_codes.intersection(codes))
    if repeated:
        raise ControllerError(
            "REPEATED_PIPELINE_FAILURE_CODE_HALT_MANUAL_ABANDONMENT_REQUIRED:"
            f"{repeated}"
        )
    return codes


def systemd_adoption_identity_for_attempt(root: Path) -> dict[str, object]:
    start = _load_json_object(root / "start_claim.json")
    start_record = start.get("systemd_start_receipt")
    if not isinstance(start_record, Mapping):
        raise ControllerError("ATTEMPT_SYSTEMD_START_RECEIPT_MISSING")
    start_path = Path(str(start_record.get("path", "")))
    _require_supervision_path(start_path)
    if not strict_json_equal(start_record, identity(start_path)):
        raise ControllerError("ATTEMPT_SYSTEMD_START_RECEIPT_DRIFT")
    adoption_path = start_path.parent / "systemd_adoption_receipt.json"
    adoption = _load_json_object(adoption_path)
    chain_records = {key: adoption.get(key) for key in SYSTEMD_CHAIN_FILES}
    chain = validate_systemd_chain(
        EXPERIMENT_ROOT, chain_records, adoption_path.parent
    )
    if (
        adoption.get("schema_version")
        != "aqua-fe-fair-stability-systemd-adoption-v11"
        or adoption.get("experiment_id") != EXPERIMENT_ID
        or not strict_json_equal(
            adoption.get("systemd_start_receipt"), start_record
        )
        or adoption.get("ordinal_terminal_receipt") is not None
        or adoption.get("unit") != chain["submission_claim"].get("unit")
        or adoption.get("controller_returncode")
        != chain["systemd_execution_receipt"].get("controller_returncode")
    ):
        raise ControllerError("ATTEMPT_SYSTEMD_ADOPTION_CHAIN_INVALID")
    return identity(adoption_path)


def adjudicate_pipeline_invalid(state: Mapping[str, Any]) -> dict[str, Any]:
    raise ControllerError(
        "PIPELINE_ADJUDICATION_DISABLED_ZERO_REPLACEMENT_V11"
    )

    # Unreachable historical receipt construction retained for diagnostics.
    initial_snapshot = revalidate_result_evidence(state)
    result = initial_snapshot["result"]
    codes = automatic_retry_codes(state)
    root = Path(state["attempt_root"])
    systemd_adoption = systemd_adoption_identity_for_attempt(root)
    final_snapshot = revalidate_result_evidence(state)
    result = final_snapshot["result"]
    codes = automatic_retry_codes(state)
    evidence: dict[str, object] = {}
    for name in PIPELINE_EVIDENCE_NAMES:
        path = root / name
        if path.is_file() and not path.is_symlink():
            evidence[name] = identity(path)
    evidence["run_result.json"] = final_snapshot["run_result"]
    evidence["runtime_resource_monitor.json"] = final_snapshot[
        "runtime_resource_monitor"
    ]
    payload = {
        "schema_version": "aqua-fe-fair-stability-pipeline-invalid-adjudication-v11",
        "experiment_id": EXPERIMENT_ID,
        "adjudicated_at_utc": now_utc(),
        "accepted_as_external_pipeline_fault": True,
        "automatic_retry_policy": "EXPLICIT_EXTERNAL_TRANSIENT_ONLY_V11",
        "maximum_replacement_attempts_per_planned_cell": (
            MAX_REPLACEMENT_ATTEMPTS_PER_CELL
        ),
        "case_id": state["cell"]["case_id"],
        "arm": state["cell"]["arm"],
        "repeat": state["cell"]["repeat"],
        "planned_ordinal": state["cell"]["ordinal"],
        "attempt_index": state["attempt_index"],
        "pipeline_failure_codes": codes,
        "algorithm_failure_codes_observed_but_excluded_with_invalid_attempt": result.get(
            "algorithm_failure_codes", []
        ),
        "run_result": final_snapshot["run_result"],
        "runtime_resource_monitor": final_snapshot["runtime_resource_monitor"],
        "semantic_artifacts": final_snapshot["semantic_artifacts"],
        "evidence": evidence,
        "schedule_sha256": SCHEDULE_SHA256,
        "controller": identity(CONTROLLER),
        "systemd_supervisor": identity(SYSTEMD_SUPERVISOR),
        "control_freeze": identity(BACKEND_FREEZE),
        "attempt_matrix_freeze": identity(MATRIX_FREEZE),
        "systemd_adoption_receipt": systemd_adoption,
    }
    target = root / "pipeline_invalid_receipt.json"
    encoded_payload = canonical_json(payload)
    require_evidence_snapshot(root, final_snapshot)
    write_exclusive(target, encoded_payload)
    require_evidence_snapshot(root, final_snapshot)
    require_written_payload_identity(target, encoded_payload)
    return payload


def dispatch_claim(state: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    root = Path(state["attempt_root"])
    path = root / "ordinal_dispatch_claim.json"
    if path.is_file():
        claim = json.loads(path.read_text(encoding="utf-8"))
        token = str(claim.get("dispatch_token", ""))
        if not token:
            raise ControllerError("EXISTING_DISPATCH_TOKEN_MISSING")
        if claim.get("controller", {}).get("sha256") != identity(CONTROLLER)["sha256"]:
            raise ControllerError("EXISTING_DISPATCH_CONTROLLER_DRIFT")
        return claim, token
    token = secrets.token_hex(32)
    cell = state["cell"]
    claim = {
        "schema_version": "aqua-fe-fair-stability-ordinal-dispatch-v11",
        "experiment_id": EXPERIMENT_ID,
        "created_at_utc": now_utc(),
        "planned_ordinal": int(cell["ordinal"]),
        "case_id": str(cell["case_id"]), "arm": str(cell["arm"]),
        "repeat": int(cell["repeat"]), "attempt_index": int(state["attempt_index"]),
        "attempt_manifest": identity(root / "attempt_manifest.json"),
        "schedule_sha256": SCHEDULE_SHA256,
        "controller": identity(CONTROLLER),
        "control_freeze": identity(BACKEND_FREEZE),
        "attempt_matrix_freeze": identity(MATRIX_FREEZE),
        "dispatch_token": token,
        "token_sha256": hashlib.sha256(token.encode("ascii")).hexdigest(),
    }
    write_exclusive(path, canonical_json(claim), 0o400)
    return claim, token


def dispatch(state: Mapping[str, Any]) -> dict[str, Any]:
    check = run_command(runner_argv(state, "check"))
    check_value = parse_runner_json(check)
    ready = check_value.get("ready")
    resource_gate_value = check_value.get("resource_gate")
    attempt_root_value = state.get("attempt_root")
    state_cell = state.get("cell")
    manifest: object = None
    expected_port: object = None
    coordinate_check_valid = False
    if isinstance(attempt_root_value, str) and isinstance(
        state_cell, Mapping
    ):
        manifest_path = Path(attempt_root_value) / "attempt_manifest.json"
        try:
            if manifest_path.is_symlink() or not manifest_path.is_file():
                raise OSError("attempt manifest unavailable")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = None
        arm = state_cell.get("arm")
        expected_port = (
            None
            if isinstance(arm, str) and arm.startswith("hfnet_openloop_")
            else manifest.get("port")
            if isinstance(manifest, Mapping)
            else None
        )
        coordinate_check_valid = bool(
            isinstance(manifest, Mapping)
            and strict_json_equal(check_value.get("attempt"), manifest)
            and isinstance(arm, str)
            and (
                arm.startswith("hfnet_openloop_")
                or type(expected_port) is int
            )
        )
    check_contract_valid = (
        type(ready) is bool
        and coordinate_check_valid
        and valid_prestart_resource_gate_v11(
            resource_gate_value,
            expected_ready=ready,
            expected_port=expected_port,
        )
        and ((ready is True and check.returncode == 0)
             or (ready is False and check.returncode == 2))
    )
    if not check_contract_valid:
        return {
            "outcome": (
                "EXPERIMENT_ABANDONMENT_REQUIRED_"
                "RESOURCE_CHECK_RETURN_CODE_BINDING_INVALID"
            ),
            "next": state,
            "resource_gate": resource_gate_value,
            "runner_returncode": check.returncode,
            "runner_ready": ready,
        }
    if ready is not True:
        return {
            "outcome": "RESOURCE_BLOCKED_NO_START",
            "next": state,
            "resource_gate": resource_gate_value,
            "runner_returncode": check.returncode,
        }
    claim, token = dispatch_claim(state)
    environment = dict(os.environ)
    environment["FAIR_STABILITY_DISPATCH_TOKEN"] = token
    command = run_command(runner_argv(state, "run"), environment)
    root = Path(state["attempt_root"])
    existing = sorted(root.glob("controller_dispatch_execution_*.json"))
    index = len(existing) + 1
    stdout_path = root / f"controller_dispatch_{index:03d}.stdout.log"
    stderr_path = root / f"controller_dispatch_{index:03d}.stderr.log"
    write_exclusive(stdout_path, command.stdout.encode("utf-8"))
    write_exclusive(stderr_path, command.stderr.encode("utf-8"))
    result_path = root / "run_result.json"
    recorded_result: dict[str, Any] | None = None
    result_record: dict[str, object] | None = None
    result_status: object = None
    expected_runner_returncode: int | None = None
    result_parse_error: str | None = None
    if result_path.is_file() and not result_path.is_symlink():
        result_record = identity(result_path)
        try:
            candidate = json.loads(result_path.read_text(encoding="utf-8"))
            if not isinstance(candidate, dict):
                raise ControllerError("RUN_RESULT_JSON_OBJECT_REQUIRED")
            recorded_result = candidate
            result_status = candidate.get("status")
            expected_runner_returncode = expected_runner_returncode_for_status(
                result_status
            )
        except (OSError, json.JSONDecodeError, ControllerError) as error:
            result_parse_error = f"{type(error).__name__}:{error}"
    elif result_path.exists() or result_path.is_symlink():
        result_parse_error = "RUN_RESULT_REGULAR_NON_SYMLINK_FILE_REQUIRED"
    runner_result_binding_valid: bool | None = None
    if result_record is not None:
        runner_result_binding_valid = (
            result_parse_error is None
            and expected_runner_returncode is not None
            and command.returncode == expected_runner_returncode
        )
    execution = {
        "schema_version": "aqua-fe-fair-stability-controller-dispatch-execution-v11",
        "experiment_id": EXPERIMENT_ID,
        "recorded_at_utc": now_utc(), "dispatch_index": index,
        "argv": runner_argv(state, "run"), "returncode": command.returncode,
        "stdout": identity(stdout_path), "stderr": identity(stderr_path),
        "dispatch_claim": identity(root / "ordinal_dispatch_claim.json"),
        "controller": identity(CONTROLLER),
        "attempt_matrix_freeze": identity(MATRIX_FREEZE),
        "run_result": result_record,
        "run_result_status": result_status if result_record is not None else None,
        "expected_runner_returncode_from_result_status": (
            expected_runner_returncode if result_record is not None else None
        ),
        "runner_result_returncode_binding_valid": runner_result_binding_valid,
        "run_result_parse_error": (
            result_parse_error if result_record is not None else None
        ),
    }
    execution_path = root / f"controller_dispatch_execution_{index:03d}.json"
    write_exclusive(execution_path, canonical_json(execution))
    execution_identity = identity(execution_path)
    verify_control_freeze()
    if result_record is not None and runner_result_binding_valid is not True:
        return {
            "outcome": (
                "EXPERIMENT_ABANDONMENT_REQUIRED_"
                "RUNNER_RESULT_RETURN_CODE_BINDING_INVALID"
            ),
            "dispatch_execution": execution_identity,
            "runner_returncode": command.returncode,
            "expected_runner_returncode": expected_runner_returncode,
            "run_result_status": result_status,
            "run_result_parse_error": result_parse_error,
        }
    if result_parse_error is not None and result_record is None:
        return {
            "outcome": (
                "EXPERIMENT_ABANDONMENT_REQUIRED_"
                "RUN_RESULT_PATH_OR_PUBLICATION_INVALID"
            ),
            "dispatch_execution": execution_identity,
            "runner_returncode": command.returncode,
            "run_result_parse_error": result_parse_error,
        }
    if result_record is None:
        if not (root / "start_claim.json").is_file():
            return {
                "outcome": "PRESTART_DISPATCH_BLOCKED_NO_ESTIMATOR_START",
                "dispatch_execution": execution_identity,
                "runner_stderr_tail": command.stderr[-2000:],
            }
        return {
            "outcome": "ADJUDICATION_REQUIRED_STARTED_OR_DISPATCH_FAILED_WITHOUT_RESULT",
            "dispatch_execution": execution_identity,
            "runner_stderr_tail": command.stderr[-2000:],
        }
    updated = next_state(EXPERIMENT_ROOT)
    if updated.get("state") == "TERMINAL_UNADOPTED":
        return {
            "outcome": "TERMINAL_RESULT_PENDING_SYSTEMD_ADOPTION",
            "state": updated,
            "runner_returncode": command.returncode,
            "dispatch_execution": execution_identity,
        }
    if updated.get("state") == "PIPELINE_INVALID_FAIL_STOP_ZERO_RETRY":
        return {
            "outcome": "PIPELINE_INVALID_FAIL_STOP_MANUAL_REVIEW_ZERO_RETRY",
            "state": updated, "runner_returncode": command.returncode,
            "dispatch_execution": execution_identity,
        }
    raise ControllerError(f"UNEXPECTED_STATE_AFTER_DISPATCH:{updated.get('state')}")


def freeze_attempt_matrix() -> dict[str, Any]:
    """Freeze the 120 pristine attempt manifests after both prepare-all passes."""
    verify_control_freeze()
    if MATRIX_FREEZE.exists() or MATRIX_FREEZE.is_symlink():
        raise ControllerError(f"ATTEMPT_MATRIX_FREEZE_EXISTS:{MATRIX_FREEZE}")
    schedule = load_schedule(EXPERIMENT_ROOT)
    rows: list[dict[str, Any]] = []
    for cell in schedule:
        root = common_attempt_root(EXPERIMENT_ROOT, cell, 1)
        manifest = root / "attempt_manifest.json"
        if root.is_symlink() or not root.is_dir() or not manifest.is_file():
            raise ControllerError(f"ATTEMPT_NOT_PREPARED:{cell['ordinal']}:{root}")
        require_no_symlink_components(root, EXPERIMENT_ROOT)
        observed_tree: dict[str, str] = {}
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                raise ControllerError(
                    f"ATTEMPT_PREPARED_TREE_SYMLINK:{cell['ordinal']}:{relative}"
                )
            if path.is_dir():
                observed_tree[relative] = "DIR"
            elif path.is_file():
                observed_tree[relative] = "FILE"
            else:
                raise ControllerError(
                    f"ATTEMPT_PREPARED_TREE_NONREGULAR:{cell['ordinal']}:{relative}"
                )
        hfnet_arm = str(cell["arm"]).startswith("hfnet_openloop_")
        expected_tree = (
            {
                "attempt_manifest.json": "FILE",
                "cam0_times_vins_matched.txt": "FILE",
                "result": "DIR",
                "run_local_model": "DIR",
                "run_local_model/HFNet-RT": "DIR",
                "run_local_model/HFNet-RT/HF-Net.cache": "FILE",
                "run_local_model/HFNet-RT/HF-Net.onnx": "FILE",
                "runtime_config_openloop.yaml": "FILE",
            }
            if hfnet_arm
            else {
                "attempt_manifest.json": "FILE",
                "vins_runtime_template.yaml": "FILE",
            }
        )
        if observed_tree != expected_tree:
            raise ControllerError(
                "ATTEMPT_NOT_PRISTINE_PREPARED_TREE:"
                f"{cell['ordinal']}:{observed_tree}"
            )
        value = json.loads(manifest.read_text(encoding="utf-8"))
        expected_schema = (
            "aqua-fe-fair-stability-hfnet-attempt-v11"
            if hfnet_arm
            else "aqua-fe-fair-stability-vins-attempt-v11"
        )
        expected = [
            expected_schema, EXPERIMENT_ID, str(cell["case_id"]), str(cell["arm"]),
            int(cell["repeat"]), 1,
        ]
        observed_arm = value.get("arm")
        if observed_arm is None and type(value.get("budget")) is int:
            observed_arm = f"hfnet_openloop_{value['budget']}"
        observed = [
            value.get("schema_version"), value.get("experiment_id"),
            value.get("case_id"), observed_arm,
            value.get("repeat"), value.get("attempt_index"),
        ]
        if observed != expected:
            raise ControllerError(
                f"ATTEMPT_MANIFEST_COORDINATE_MISMATCH:{cell['ordinal']}:{observed}"
            )
        frozen_paths = (
            {
                "selected_times": root / "cam0_times_vins_matched.txt",
                "runtime_config": root / "runtime_config_openloop.yaml",
                "local_onnx_pre": root / "run_local_model/HFNet-RT/HF-Net.onnx",
                "local_cache_seed_pre": root / "run_local_model/HFNet-RT/HF-Net.cache",
            }
            if hfnet_arm
            else {
                "runtime_config_template": root / "vins_runtime_template.yaml",
            }
        )
        for label, path in frozen_paths.items():
            if not identity_matches(value.get(label), path):
                raise ControllerError(
                    f"ATTEMPT_PREPARED_INPUT_DRIFT:{cell['ordinal']}:{label}"
                )
        rows.append(
            {
                "ordinal": int(cell["ordinal"]),
                "case_id": str(cell["case_id"]),
                "arm": str(cell["arm"]),
                "repeat": int(cell["repeat"]),
                "attempt_index": 1,
                "attempt_root": str(root),
                "maximum_replacement_attempts": MAX_REPLACEMENT_ATTEMPTS_PER_CELL,
                "maximum_total_attempts": MAX_ATTEMPTS_PER_CELL,
                "attempt_manifest": identity(manifest),
            }
        )
    receipts = EXPERIMENT_ROOT / "ordinal_receipts"
    if receipts.exists() and any(receipts.iterdir()):
        raise ControllerError("ORDINAL_RECEIPTS_EXIST_BEFORE_MATRIX_FREEZE")
    supervision = EXPERIMENT_ROOT / "systemd_supervision"
    if supervision.exists() and any(supervision.iterdir()):
        raise ControllerError("SYSTEMD_SUPERVISION_EXISTS_BEFORE_MATRIX_FREEZE")
    for lock_name in (
        ".gpu_serial.lock", ".ordinal_controller.lock", ".systemd_submit.lock",
    ):
        if (EXPERIMENT_ROOT / lock_name).exists() or (
            EXPERIMENT_ROOT / lock_name
        ).is_symlink():
            raise ControllerError(f"CONTROL_LOCK_EXISTS_BEFORE_MATRIX_FREEZE:{lock_name}")
    payload = {
        "schema_version": "aqua-fe-fair-stability-attempt-matrix-freeze-v11",
        "experiment_id": EXPERIMENT_ID,
        "status": "FROZEN_BEFORE_ANY_V11_ESTIMATOR_START",
        "frozen_at_utc": now_utc(),
        "experiment_manifest": identity(EXPERIMENT_ROOT / "experiment_manifest.json"),
        "planned_schedule": identity(EXPERIMENT_ROOT / "planned_schedule.json"),
        "backend_freeze": identity(BACKEND_FREEZE),
        "replacement_policy": {
            "automatic_retry_pipeline_failure_codes": sorted(
                AUTOMATIC_RETRY_PIPELINE_FAILURES
            ),
            "maximum_replacement_attempts_per_planned_cell": (
                MAX_REPLACEMENT_ATTEMPTS_PER_CELL
            ),
            "maximum_total_attempts_per_planned_cell": MAX_ATTEMPTS_PER_CELL,
            "same_pipeline_failure_code_may_repeat": False,
        },
        "attempts": rows,
        "claims": {
            "attempt_count": len(rows),
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
            "v10_results_imported": False,
            "v10_runtime_namespace_read": False,
            "v10_attempts_reused": False,
            "v10_cache_reused": False,
            "dispatch_claim_count": 0,
            "start_claim_count": 0,
            "run_result_count": 0,
            "terminal_receipt_count": 0,
        },
    }
    write_exclusive(MATRIX_FREEZE, canonical_json(payload))
    load_attempt_matrix(EXPERIMENT_ROOT)
    return payload


def run_next() -> dict[str, Any]:
    systemd_authority = verify_systemd_authority()
    verify_control_freeze()
    lock_path = EXPERIMENT_ROOT / ".ordinal_controller.lock"
    with open_regular_lock(lock_path) as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        state = next_state(EXPERIMENT_ROOT)
        if state.get("state") == "TERMINAL_UNADOPTED":
            return {
                "outcome": "SYSTEMD_ADOPTION_REQUIRED_FOR_TERMINAL_RESULT",
                "state": state, "systemd_authority": systemd_authority,
            }
        if state.get("state") == "COMPLETE":
            return {
                "outcome": "EXPERIMENT_COMPLETE", "state": state,
                "systemd_authority": systemd_authority,
            }
        if state.get("state") == "STARTED_WITHOUT_RESULT":
            return {
                "outcome": "EXPERIMENT_ABANDONMENT_REQUIRED_STARTED_WITHOUT_RESULT",
                "state": state, "systemd_authority": systemd_authority,
            }
        if str(state.get("state", "")).startswith("SYSTEMD_"):
            return {
                "outcome": f"EXPERIMENT_ABANDONMENT_REQUIRED_{state['state']}",
                "state": state, "systemd_authority": systemd_authority,
            }
        if state.get("state") == "PIPELINE_INVALID_FAIL_STOP_ZERO_RETRY":
            return {
                "outcome": (
                    "EXPERIMENT_ABANDONMENT_REQUIRED_PIPELINE_INVALID_ZERO_RETRY"
                ),
                "state": state,
                "systemd_authority": systemd_authority,
            }
        if state.get("state") == "NEEDS_PREPARATION":
            state = prepare_state(state)
        if state.get("state") != "READY":
            raise ControllerError(f"NEXT_STATE_NOT_DISPATCHABLE:{state.get('state')}")
        result = dispatch(state)
        result["systemd_authority"] = systemd_authority
        return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze-matrix", "status", "run-next"))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "freeze-matrix":
            result = freeze_attempt_matrix()
        elif args.command == "status":
            result = next_state(EXPERIMENT_ROOT)
        else:
            result = run_next()
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        if result.get("outcome") in {
            "RESOURCE_BLOCKED_NO_START",
            "PRESTART_DISPATCH_BLOCKED_NO_ESTIMATOR_START",
        }:
            return 75
        if str(result.get("outcome", "")).startswith("ADJUDICATION_REQUIRED"):
            return 4
        if str(result.get("outcome", "")).startswith(
            "EXPERIMENT_ABANDONMENT_REQUIRED"
        ):
            return 5
        return 0
    except BaseException as error:
        print(f"{type(error).__name__}:{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
