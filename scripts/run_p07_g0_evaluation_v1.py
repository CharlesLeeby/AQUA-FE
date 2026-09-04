#!/usr/bin/env python3
"""Strict command wrapper for the frozen P07 G0 evaluation routes.

Without ``--execute`` this script is read-only and prints the argv that would
be used.  It never launches VINS and it does not discover artifacts from a run
directory; every trajectory/config/reference path must already be bound by an
audited evaluation job.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
from decimal import Decimal
import fcntl
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping

try:
    from scripts import p07_backend_evaluation_v1 as evaluation
    from scripts import p07_g0_governance_v1 as gov
    from scripts import p07_g0_publisher_v1 as publisher
    from scripts import p07_backend_replay_common_v1 as backend
    from scripts.p07_backend_evaluation_v1 import (
        EvaluationContractError,
        ROUTE_B0_DESCRIPTIVE,
        ROUTE_PAIRWISE_COMMON_SUPPORT,
        validate_evaluation_job,
    )
except ModuleNotFoundError:
    import p07_backend_evaluation_v1 as evaluation  # type: ignore
    import p07_g0_governance_v1 as gov  # type: ignore
    import p07_g0_publisher_v1 as publisher  # type: ignore
    import p07_backend_replay_common_v1 as backend  # type: ignore
    from p07_backend_evaluation_v1 import (  # type: ignore
        EvaluationContractError,
        ROUTE_B0_DESCRIPTIVE,
        ROUTE_PAIRWISE_COMMON_SUPPORT,
        validate_evaluation_job,
    )


DEFAULT_EVALUATOR = Path("scripts/evaluate_vins_common_support_epoch_v2.py")
DEFAULT_PROTOCOL = Path(
    "papers/ieee_sensors_journal_experiments/evaluator_protocol_v1.md"
)
SEALED_BASE_RELATIVE = "scripts/evaluate_vins_common_support.py"
SEALED_CORE_RELATIVE = "scripts/trajectory_eval_core.py"
SEALED_BASE_ENV = "AQUAFE_P07_SEALED_EVALUATOR_BASE"
SEALED_CORE_ENV = "AQUAFE_P07_SEALED_EVALUATOR_CORE"


@contextmanager
def sealed_bound_input(
    root: Path, record: Mapping[str, object], *, label: str
):
    """Yield an immutable procfd copy and reject any source drift on exit."""

    path = gov.workspace_path(root, record.get("path"), label=label)
    content, observed = publisher.read_bytes_and_record_bound_input_rooted(
        root, path, label=label
    )
    if any(
        observed.get(key) != record.get(key)
        for key in ("path", "sha256", "size_bytes")
    ):
        raise gov.G0GovernanceError(f"{label} record differs before evaluator")
    try:
        before_identity = backend.capture_canonical_input_identity(
            root,
            str(record["path"]),
            expected_sha256=str(record["sha256"]),
            verify_sha256=True,
        )
    except backend.BackendReplayViolation as error:
        raise gov.G0GovernanceError(
            f"{label} canonical identity differs before evaluator: {error}"
        ) from error
    required_os = ("memfd_create", "MFD_ALLOW_SEALING", "MFD_CLOEXEC")
    required_fcntl = (
        "F_ADD_SEALS",
        "F_GET_SEALS",
        "F_SEAL_SEAL",
        "F_SEAL_SHRINK",
        "F_SEAL_GROW",
        "F_SEAL_WRITE",
    )
    if any(not hasattr(os, name) for name in required_os) or any(
        not hasattr(fcntl, name) for name in required_fcntl
    ):
        raise gov.G0GovernanceError("platform lacks sealed evaluator-input memfd")
    descriptor = os.memfd_create(
        "p07-g0-evaluator-input", os.MFD_ALLOW_SEALING | os.MFD_CLOEXEC
    )
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise gov.G0GovernanceError("short write to evaluator-input memfd")
            view = view[written:]
        os.lseek(descriptor, 0, os.SEEK_SET)
        seals = (
            fcntl.F_SEAL_SHRINK
            | fcntl.F_SEAL_GROW
            | fcntl.F_SEAL_WRITE
            | fcntl.F_SEAL_SEAL
        )
        fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, seals)
        if fcntl.fcntl(descriptor, fcntl.F_GET_SEALS) != seals:
            raise gov.G0GovernanceError("evaluator-input memfd seals differ")
        yield f"/proc/self/fd/{descriptor}", descriptor
        after_content, after_record = (
            publisher.read_bytes_and_record_bound_input_rooted(
                root, path, label=f"{label} post-evaluator"
            )
        )
        try:
            after_identity = backend.capture_canonical_input_identity(
                root,
                str(record["path"]),
                expected_sha256=str(record["sha256"]),
                verify_sha256=True,
            )
        except backend.BackendReplayViolation as error:
            raise gov.G0GovernanceError(
                f"{label} canonical identity differs after evaluator: {error}"
            ) from error
        if (
            after_content != content
            or after_record != observed
            or after_identity != before_identity
        ):
            raise gov.G0GovernanceError(f"{label} source drifted during evaluator")
    finally:
        os.close(descriptor)


def _numeric_input_records(
    job: Mapping[str, Any]
) -> list[tuple[str, dict[str, object]]]:
    core = job.get("evaluation_job")
    reference_binding = job.get("reference_binding")
    input_bindings = job.get("input_bindings")
    if (
        not isinstance(core, Mapping)
        or not isinstance(reference_binding, Mapping)
        or not isinstance(input_bindings, Mapping)
    ):
        raise gov.G0GovernanceError("numeric job input bindings are invalid")
    reference_record = reference_binding.get("artifact")
    if not isinstance(reference_record, Mapping):
        raise gov.G0GovernanceError("numeric job lacks reference artifact")
    result: list[tuple[str, dict[str, object]]] = [
        (str(core["reference"]["path"]), dict(reference_record))
    ]
    arms = core.get("arms")
    if not isinstance(arms, Mapping):
        raise gov.G0GovernanceError("numeric job arms are invalid")
    for arm, arm_core in arms.items():
        binding = input_bindings.get(arm)
        terminal = binding.get("terminal_binding") if isinstance(binding, Mapping) else None
        artifacts = terminal.get("artifact_bindings") if isinstance(terminal, Mapping) else None
        if not isinstance(arm_core, Mapping) or not isinstance(artifacts, Mapping):
            raise gov.G0GovernanceError(f"numeric job {arm} artifacts are invalid")
        for field, artifact_key in (
            ("trajectory_path", "trajectory"),
            ("config_path", "config"),
        ):
            record = artifacts.get(artifact_key)
            if not isinstance(record, Mapping) or record.get("path") != arm_core.get(field):
                raise gov.G0GovernanceError(
                    f"numeric job {arm} {artifact_key} binding differs"
                )
            result.append((str(arm_core[field]), dict(record)))
    by_path: dict[str, dict[str, object]] = {}
    for path, record in result:
        previous = by_path.setdefault(path, record)
        if previous != record:
            raise gov.G0GovernanceError(
                f"numeric job reuses {path} with different records"
            )
    return sorted(by_path.items())


def _protected_code_and_lock_records(
    lock: Mapping[str, Any], *, root: Path
) -> list[tuple[str, dict[str, object]]]:
    records: list[tuple[str, dict[str, object]]] = []
    for record in lock.get("code_bindings", []):
        if isinstance(record, Mapping):
            records.append((f"G0 code {record.get('role')}", dict(record)))
    frozen = {
        str(record.get("role")): record
        for record in lock.get("frozen_inputs", [])
        if isinstance(record, Mapping)
    }
    for role in (
        "evaluator_precision_correction_lock",
        "evaluator_epoch_ns_correction_lock",
    ):
        record = frozen.get(role)
        if not isinstance(record, Mapping):
            raise gov.G0GovernanceError(f"G0 lock lacks protected {role}")
        records.append((f"G0 frozen {role}", dict(record)))
    epoch_record = frozen["evaluator_epoch_ns_correction_lock"]
    epoch_path = gov.workspace_path(root, epoch_record["path"], label="epoch lock")
    epoch = publisher.read_json_direct_rooted(root, epoch_path, label="epoch lock")
    implementation = epoch.get("corrected_implementation_binding")
    protocol = epoch.get("protocol_binding")
    parent = epoch.get("parent_precision_correction_lock")
    if not isinstance(implementation, Mapping) or not isinstance(
        implementation.get("files"), list
    ):
        raise gov.G0GovernanceError("epoch lock lacks protected implementation files")
    for record in implementation["files"]:
        if isinstance(record, Mapping):
            records.append(("epoch implementation", dict(record)))
    for label, record in (("epoch protocol", protocol), ("epoch precision parent", parent)):
        if not isinstance(record, Mapping):
            raise gov.G0GovernanceError(f"epoch lock lacks protected {label}")
        records.append((label, dict(record)))

    precision_record = frozen["evaluator_precision_correction_lock"]
    precision_path = gov.workspace_path(
        root, precision_record["path"], label="precision lock"
    )
    precision = publisher.read_json_direct_rooted(
        root, precision_path, label="precision lock"
    )
    corrected = precision.get("corrected_implementation_binding")
    if not isinstance(corrected, Mapping) or not isinstance(corrected.get("files"), list):
        raise gov.G0GovernanceError("precision lock lacks protected implementation files")
    for record in corrected["files"]:
        if isinstance(record, Mapping):
            records.append(("precision implementation", dict(record)))

    by_path: dict[str, tuple[str, dict[str, object]]] = {}
    for label, record in records:
        path = record.get("path")
        if not isinstance(path, str):
            raise gov.G0GovernanceError(f"{label} record lacks path")
        previous = by_path.setdefault(path, (label, record))
        if any(
            previous[1].get(key) != record.get(key)
            for key in ("path", "sha256", "size_bytes")
        ):
            raise gov.G0GovernanceError(f"protected code record differs for {path}")
    return [by_path[path] for path in sorted(by_path)]


def _backend_execution_lock_snapshot(
    job: Mapping[str, Any], *, root: Path
) -> tuple[dict[str, Any], dict[str, object]]:
    record = job.get("backend_execution_lock")
    if not isinstance(record, Mapping) or set(record) != {
        "path",
        "sha256",
        "size_bytes",
    }:
        raise gov.G0GovernanceError("G0 job backend execution-lock record differs")
    path = gov.workspace_path(
        root, record.get("path"), label="G0 job backend execution lock"
    )
    content, observed = publisher.read_bytes_and_record_bound_input_rooted(
        root, path, label="G0 job backend execution lock"
    )
    if observed != dict(record):
        raise gov.G0GovernanceError("G0 job backend execution lock drifted")
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise gov.G0GovernanceError(
            "G0 job backend execution lock is invalid JSON"
        ) from error
    if not isinstance(payload, dict) or gov.validate_self_hash(
        payload, "execution_lock_hash", label="G0 backend execution lock"
    ) != job.get("backend_execution_lock_hash"):
        raise gov.G0GovernanceError("G0 backend execution-lock authority differs")
    return payload, observed


def _python_interpreter_binding(
    job: Mapping[str, Any], *, root: Path
) -> dict[str, object]:
    execution_lock, _record = _backend_execution_lock_snapshot(job, root=root)
    external = execution_lock.get("external_runtime_bindings")
    binding = (
        external.get("python_interpreter")
        if isinstance(external, Mapping)
        else None
    )
    if not isinstance(binding, Mapping) or set(binding) != {
        "path",
        "sha256",
        "size_bytes",
    }:
        raise gov.G0GovernanceError(
            "backend execution lock lacks exact Python interpreter authority"
        )
    expected_path = backend.EXTERNAL_RUNTIME_BINDING_PATHS.get(
        "python_interpreter"
    )
    if binding.get("path") != os.fspath(expected_path):
        raise gov.G0GovernanceError("frozen Python interpreter path differs")
    return dict(binding)


@contextmanager
def sealed_python_interpreter(
    job: Mapping[str, Any], *, root: Path
):
    binding = _python_interpreter_binding(job, root=root)
    lease = backend.SealedFileLease(
        Path(str(binding["path"])),
        str(binding["sha256"]),
        role="python_interpreter",
        label="G0 frozen Python interpreter",
        expected_size_bytes=int(binding["size_bytes"]),
    )
    try:
        lease.__enter__()
        if lease.fd is None:
            raise gov.G0GovernanceError("sealed Python interpreter fd is absent")
        yield lease.proc_path, lease.fd
        lease.verify_unchanged()
    except backend.BackendReplayViolation as error:
        raise gov.G0GovernanceError(
            f"G0 frozen Python interpreter lease failed: {error}"
        ) from error
    finally:
        lease.close()


def build_g0_command(
    job: Mapping[str, object],
    *,
    evaluator_script: str = str(DEFAULT_EVALUATOR),
    python_interpreter: str = "python3",
    output_dir_override: str | None = None,
    input_path_overrides: Mapping[str, str] | None = None,
) -> list[str]:
    """Return deterministic evaluator argv after enforcing the route contract."""

    validate_evaluation_job(job, require_executable=True)
    reference = job["reference"]
    arms = job["arms"]
    assert isinstance(reference, Mapping)
    assert isinstance(arms, Mapping)

    overrides = dict(input_path_overrides or {})

    def secured(raw: object) -> str:
        value = str(raw)
        return overrides.get(value, value)

    command = [python_interpreter, "-I", evaluator_script]
    if reference["kind"] == "tum":
        command.extend(("--reference-tum", secured(reference["path"])))
    else:
        command.extend(
            (
                "--reference-bag",
                secured(reference["path"]),
                "--reference-topic",
                str(reference["topic"]),
            )
        )
    # Canonical lexical arm order makes command hashing deterministic.  The
    # evaluator intersects support, so argv order cannot privilege an arm.
    for arm_name in sorted(arms):
        arm = arms[arm_name]
        assert isinstance(arm, Mapping)
        command.extend(
            ("--arm", f"{arm_name}={secured(arm['trajectory_path'])}")
        )
        command.extend(
            ("--arm-config", f"{arm_name}={secured(arm['config_path'])}")
        )
        command.extend(
            (
                "--arm-time-offset-s",
                f"{arm_name}={float(arm.get('arm_time_offset_s', 0.0)):.17g}",
            )
        )
    window_start = (
        str(Decimal(int(reference["window_start_ns"])) / Decimal(1_000_000_000))
        if "window_start_ns" in reference
        else f"{float(reference['window_start_s']):.17g}"
    )
    window_end = (
        str(Decimal(int(reference["window_end_ns"])) / Decimal(1_000_000_000))
        if "window_end_ns" in reference
        else f"{float(reference['window_end_s']):.17g}"
    )
    command.extend(
        (
            "--reference-time-offset-s",
            f"{float(reference['reference_time_offset_s']):.17g}",
            "--nominal-reference-rate-hz",
            f"{float(reference['nominal_reference_rate_hz']):.17g}",
            "--nominal-estimate-rate-hz",
            f"{float(reference['nominal_estimate_rate_hz']):.17g}",
            "--max-reference-gap-s",
            f"{float(reference['max_reference_gap_s']):.17g}",
            "--max-estimate-gap-s",
            f"{float(reference['max_estimate_gap_s']):.17g}",
            "--window-start-s",
            window_start,
            "--window-end-s",
            window_end,
            "--rpe-delta-s",
            "1",
            "--min-ape-poses",
            "30",
            "--min-ape-span-s",
            "10",
            "--min-common-coverage",
            "0.70",
            "--min-rpe-pairs",
            "10",
            "--contrast-name",
            str(job["contrast_name"]),
            "--output-dir",
            str(output_dir_override or job["output_dir"]),
        )
    )
    return command


def validate_bound_hashes(
    job: Mapping[str, object], evaluator_script: Path, evaluator_protocol: Path, *, root: Path
) -> None:
    actual_script = publisher.direct_file_record_rooted(
        root, evaluator_script, label="G0 evaluator entrypoint"
    )["sha256"]
    actual_protocol = publisher.direct_file_record_rooted(
        root, evaluator_protocol, label="G0 evaluator protocol"
    )["sha256"]
    if actual_script != job.get("evaluator_script_sha256"):
        raise EvaluationContractError("evaluator script hash differs from job binding")
    if actual_protocol != job.get("evaluator_protocol_sha256"):
        raise EvaluationContractError("evaluator protocol hash differs from job binding")


def _plan_membership_path(
    job: Mapping[str, Any], plan: Mapping[str, Any], *, root: Path
) -> Path:
    matches = [
        item
        for item in plan["jobs"]
        if isinstance(item, Mapping) and item.get("job_id") == job.get("job_id")
    ]
    if len(matches) != 1:
        raise gov.G0GovernanceError("job has no unique plan membership")
    return gov.workspace_path(root, matches[0]["path"], label="plan job membership")


def validate_production_inputs(
    job_path: Path,
    plan_path: Path,
    lock_path: Path,
    *,
    root: Path,
    evaluator_script: Path,
    evaluator_protocol: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Load and hash-validate the complete production authority chain."""

    root = Path(os.path.abspath(os.fspath(root)))
    job = publisher.read_json_direct_rooted(
        root, job_path, label="materialized G0 job"
    )
    plan = publisher.read_json_direct_rooted(
        root, plan_path, label="materialized G0 plan"
    )
    lock = publisher.read_json_direct_rooted(
        root, lock_path, label="frozen G0 evaluation lock"
    )
    gov.validate_lock_payload(lock, root=root, verify_files=True)
    validated_plan_context: dict[str, Any] = {}
    gov.validate_plan_payload(
        plan,
        lock=lock,
        root=root,
        _context_out=validated_plan_context,
    )
    gov.validate_job_payload(
        job,
        plan=plan,
        lock=lock,
        root=root,
        verify_inputs=True,
        _validated_plan_context=validated_plan_context,
    )
    expected_job_path = _plan_membership_path(job, plan, root=root)
    if Path(os.path.abspath(os.fspath(job_path))) != expected_job_path:
        raise gov.G0GovernanceError("loaded job path differs from plan membership path")
    core = job["evaluation_job"]
    assert isinstance(core, Mapping)
    evaluator_bindings = [
        record
        for record in lock.get("code_bindings", [])
        if isinstance(record, Mapping) and record.get("role") == "evaluator"
    ]
    if len(evaluator_bindings) != 1:
        raise gov.G0GovernanceError("G0 lock lacks one frozen evaluator entrypoint")
    expected_evaluator = gov.workspace_path(
        root,
        evaluator_bindings[0].get("path"),
        label="frozen G0 evaluator entrypoint",
    )
    observed_evaluator = Path(os.path.abspath(os.fspath(evaluator_script)))
    if observed_evaluator != expected_evaluator:
        raise gov.G0GovernanceError(
            "CLI evaluator path differs from frozen G0 evaluator entrypoint"
        )
    validate_bound_hashes(
        core, evaluator_script, evaluator_protocol, root=root
    )
    output = gov.workspace_path(
        root,
        job["output_dir_absolute"],
        label="G0 output",
        require_absolute=True,
    )
    if publisher.path_state_rooted(root, output, label="G0 output") != "ABSENT":
        raise gov.G0GovernanceError(f"refusing existing G0 output: {output}")
    return job, plan, lock


def build_bound_summary(
    job: Mapping[str, Any],
    plan: Mapping[str, Any],
    lock: Mapping[str, Any],
    *,
    root: Path,
    staging: Path,
    numeric_summary: Mapping[str, Any] | None,
    evaluator_executed: bool,
    evaluator_exit_code: int | None,
    validated_plan_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    core = job["evaluation_job"]
    assert isinstance(core, Mapping)
    job_hash = gov.validate_self_hash(job, "job_hash", label="G0 job")
    plan_hash = gov.validate_self_hash(plan, "plan_hash", label="G0 plan")
    lock_hash = gov.validate_self_hash(lock, "evaluation_lock_hash", label="G0 lock")
    numeric = core["evaluation_disposition"] == "EVALUATE_NUMERIC"
    if numeric != (numeric_summary is not None):
        raise gov.G0GovernanceError("summary presence differs from evaluation disposition")
    if numeric:
        evaluation.materialize_reducer_records(core, numeric_summary)
        raw_staging = staging / "common_support_summary.json"
        if publisher.path_state_rooted(
            root, raw_staging, label="raw G0 summary"
        ) != "FILE":
            raise gov.G0GovernanceError("numeric evaluator lacks common-support summary")
        if publisher.read_json_direct_rooted(
            root, raw_staging, label="raw G0 summary"
        ) != numeric_summary:
            raise gov.G0GovernanceError("in-memory/raw evaluator summary differs")
        destination = Path(str(job["output_dir_absolute"]))
        direct_raw = publisher.direct_file_record_rooted(
            root, raw_staging, label="raw G0 summary"
        )
        raw_record: dict[str, object] | None = {
            "path": gov.display_path(root, destination / raw_staging.name),
            "sha256": direct_raw["sha256"],
            "size_bytes": direct_raw["size_bytes"],
        }
        status = "COMPLETED_NUMERIC_EVALUATION"
    else:
        evaluation.materialize_reducer_records(core, None)
        raw_record = None
        status = "COMPLETED_FAILURE_ONLY_NO_NUMERIC_EVALUATION"
    arm_identities: dict[str, Any] = {}
    for arm, raw in core["arms"].items():
        terminal = job["input_bindings"][arm]["terminal_binding"]
        arm_identities[arm] = {
            "arm": arm,
            "run_id": raw["run_id"],
            "replay_index": core["replay_index"],
            "terminal_binding_hash": terminal["terminal_binding_hash"],
        }
    payload: dict[str, Any] = {
        "schema_version": gov.BOUND_SUMMARY_SCHEMA,
        "status": status,
        "job_id": job["job_id"],
        "job_hash": job_hash,
        "plan_hash": plan_hash,
        "evaluation_lock_hash": lock_hash,
        "backend_execution_lock_hash": job["backend_execution_lock_hash"],
        "g0_execution_authority_hash": job["g0_execution_authority_hash"],
        "window_id": core["window_id"],
        "replay_index": core["replay_index"],
        "route": core["route"],
        "contrast_name": core["contrast_name"],
        "evaluation_disposition": core["evaluation_disposition"],
        "arm_identities": arm_identities,
        "g0_summary": dict(numeric_summary) if numeric_summary is not None else None,
        "raw_summary_artifact": raw_record,
        "evaluator_process": {
            "executed": evaluator_executed,
            "exit_code": evaluator_exit_code,
            "vins_launched": False,
        },
        "outcome_boundary": gov.OUTCOME_BOUNDARY,
    }
    payload["bound_summary_hash"] = gov.canonical_json_hash(payload)
    gov.validate_bound_summary(
        payload,
        job=job,
        plan=plan,
        lock=lock,
        root=root,
        verify_raw_summary=False,
        _validated_plan_context=validated_plan_context,
    )
    return payload


def _validated_existing_intent(
    expected: Mapping[str, Any], *, root: Path
) -> dict[str, Any]:
    path = Path(str(expected["intent_path_absolute"]))
    observed = publisher.read_json_direct_rooted(
        root, path, label="existing publication intent"
    )
    publisher.validate_publication_intent(observed, root=root)
    if observed != expected:
        raise gov.G0GovernanceError("existing publication intent differs from exact job")
    staging = Path(str(observed["staging_absolute"]))
    destination = Path(str(observed["destination_absolute"]))
    closeout = Path(str(observed["closeout_path_absolute"]))
    if any(
        publisher.path_state_rooted(root, candidate, label=label) != "ABSENT"
        for candidate, label in (
            (staging, "resume staging"),
            (destination, "resume destination"),
            (closeout, "resume closeout"),
        )
    ):
        raise gov.G0GovernanceError(
            "resume-intent is allowed only for intent-only crash state"
        )
    return observed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-json", type=Path, required=True)
    parser.add_argument("--plan-json", type=Path, required=True)
    parser.add_argument("--evaluation-lock", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, default=gov.ROOT)
    parser.add_argument("--evaluator-script", type=Path, default=DEFAULT_EVALUATOR)
    parser.add_argument("--evaluator-protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="execute the evaluator; omitted means emit argv only",
    )
    parser.add_argument(
        "--resume-intent",
        action="store_true",
        help="resume only an exact, validated intent-only crash state",
    )
    args = parser.parse_args()

    root = Path(os.path.abspath(os.fspath(args.workspace_root)))
    evaluator_script = gov.workspace_path(
        root, args.evaluator_script, label="evaluator script"
    )
    evaluator_protocol = gov.workspace_path(
        root, args.evaluator_protocol, label="evaluator protocol"
    )
    job, plan, lock = validate_production_inputs(
        args.job_json,
        args.plan_json,
        args.evaluation_lock,
        root=root,
        evaluator_script=evaluator_script,
        evaluator_protocol=evaluator_protocol,
    )
    core = job["evaluation_job"]
    assert isinstance(core, Mapping)
    python_interpreter_binding = _python_interpreter_binding(job, root=root)
    output = Path(str(job["output_dir_absolute"]))
    staging, intent_path, closeout_path = publisher.publication_paths(
        output, job_hash=str(job["job_hash"])
    )
    intent = publisher.build_publication_intent(
        root=root,
        job_id=str(job["job_id"]),
        job_hash=str(job["job_hash"]),
        plan_hash=str(plan["plan_hash"]),
        evaluation_lock_hash=str(lock["evaluation_lock_hash"]),
        backend_execution_lock_hash=str(job["backend_execution_lock_hash"]),
        g0_execution_authority_hash=str(job["g0_execution_authority_hash"]),
        evaluation_disposition=str(core["evaluation_disposition"]),
        output_dir=output,
    )
    command = (
        build_g0_command(
            core,
            evaluator_script=os.fspath(evaluator_script),
            python_interpreter=str(python_interpreter_binding["path"]),
            output_dir_override=os.fspath(staging),
        )
        if core["evaluation_disposition"] == "EVALUATE_NUMERIC"
        else None
    )
    if not args.execute:
        print(
            json.dumps(
                {
                    "mode": "READ_ONLY_COMMAND_PREVIEW",
                    "job_id": job["job_id"],
                    "job_hash": job["job_hash"],
                    "plan_hash": plan["plan_hash"],
                    "evaluation_lock_hash": lock["evaluation_lock_hash"],
                    "backend_execution_lock_hash": job[
                        "backend_execution_lock_hash"
                    ],
                    "g0_execution_authority_hash": job[
                        "g0_execution_authority_hash"
                    ],
                    "route": core["route"],
                    "evaluation_disposition": core["evaluation_disposition"],
                    "argv": command,
                    "destination_absolute": os.fspath(output),
                    "staging_absolute": os.fspath(staging),
                    "intent_path_absolute": os.fspath(intent_path),
                    "closeout_path_absolute": os.fspath(closeout_path),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.resume_intent:
        _validated_existing_intent(intent, root=root)
    else:
        publisher.create_publication_intent(intent_path, intent, root=root)
    publisher.create_workspace_directory(
        root,
        staging,
        create_parents=False,
        label="G0 evaluation staging",
    )
    with publisher.retained_workspace_directory(
        root,
        staging,
        label="G0 evaluator staging",
        relocated_to=output,
    ) as staging_fd:
        if command is not None:
            with ExitStack() as leases:
                path_overrides: dict[str, str] = {}
                pass_fds = [staging_fd]
                interpreter_proc_path, interpreter_fd = leases.enter_context(
                    sealed_python_interpreter(job, root=root)
                )
                pass_fds.append(interpreter_fd)
                for index, (path, record) in enumerate(_numeric_input_records(job)):
                    proc_path, descriptor = leases.enter_context(
                        sealed_bound_input(
                            root, record, label=f"G0 scientific input {index}"
                        )
                    )
                    path_overrides[path] = proc_path
                    pass_fds.append(descriptor)

                evaluator_proc_path: str | None = None
                sealed_code_paths: dict[str, str] = {}
                evaluator_relative = gov.display_path(root, evaluator_script)
                for index, (label, record) in enumerate(
                    _protected_code_and_lock_records(lock, root=root)
                ):
                    proc_path, descriptor = leases.enter_context(
                        sealed_bound_input(
                            root, record, label=f"{label} lease {index}"
                        )
                    )
                    if record.get("path") == evaluator_relative:
                        evaluator_proc_path = proc_path
                    sealed_code_paths[str(record.get("path"))] = proc_path
                    pass_fds.append(descriptor)
                if evaluator_proc_path is None:
                    raise gov.G0GovernanceError(
                        "protected code bundle lacks evaluator entrypoint"
                    )
                secured_command = build_g0_command(
                    core,
                    evaluator_script=evaluator_proc_path,
                    python_interpreter=interpreter_proc_path,
                    output_dir_override=f"/proc/self/fd/{staging_fd}",
                    input_path_overrides=path_overrides,
                )
                try:
                    sealed_base = sealed_code_paths[SEALED_BASE_RELATIVE]
                    sealed_core = sealed_code_paths[SEALED_CORE_RELATIVE]
                except KeyError as error:
                    raise gov.G0GovernanceError(
                        "protected code bundle lacks sealed evaluator base/core"
                    ) from error
                try:
                    evaluator_environment = backend.sanitized_child_environment(
                        extra={
                        SEALED_BASE_ENV: sealed_base,
                        SEALED_CORE_ENV: sealed_core,
                        }
                    )
                except backend.BackendReplayViolation as error:
                    raise gov.G0GovernanceError(
                        f"cannot construct isolated G0 evaluator environment: {error}"
                    ) from error
                process = subprocess.run(
                    tuple(secured_command),
                    check=False,
                    pass_fds=tuple(sorted(set(pass_fds))),
                    cwd=root,
                    env=evaluator_environment,
                )
            if process.returncode != 0:
                raise SystemExit(process.returncode)
            publisher.assert_retained_workspace_directory(
                root,
                staging,
                staging_fd,
                label="post-evaluator G0 staging",
            )
            raw_summary = publisher.read_json_retained_directory(
                staging_fd,
                "common_support_summary.json",
                label="raw G0 summary",
            )
            bound = build_bound_summary(
                job,
                plan,
                lock,
                root=root,
                staging=staging,
                numeric_summary=raw_summary,
                evaluator_executed=True,
                evaluator_exit_code=0,
                validated_plan_context=validated_plan_context,
            )
        else:
            bound = build_bound_summary(
                job,
                plan,
                lock,
                root=root,
                staging=staging,
                numeric_summary=None,
                evaluator_executed=False,
                evaluator_exit_code=None,
                validated_plan_context=validated_plan_context,
            )
        publisher.write_json_exclusive_retained_directory(
            staging_fd,
            publisher.BOUND_SUMMARY_NAME,
            bound,
            label="bound G0 summary",
        )
        publisher.seal_staging_result_retained(
            intent, root=root, staging_fd=staging_fd
        )
        closeout = publisher.publish_staging(
            intent,
            root=root,
            closeout_path=closeout_path,
            staging_fd=staging_fd,
        )
    published_bound = publisher.read_json_direct_rooted(
        root,
        output / publisher.BOUND_SUMMARY_NAME, label="published bound summary"
    )
    gov.validate_bound_summary(
        published_bound,
        job=job,
        plan=plan,
        lock=lock,
        root=root,
        verify_raw_summary=True,
        _validated_plan_context=validated_plan_context,
    )
    print(
        json.dumps(
            {
                "status": closeout["status"],
                "job_id": job["job_id"],
                "result_receipt": os.fspath(output / publisher.RECEIPT_NAME),
                "output_manifest": os.fspath(output / publisher.MANIFEST_NAME),
                "publication_closeout": os.fspath(closeout_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
