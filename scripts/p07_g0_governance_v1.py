#!/usr/bin/env python3
"""Shared fail-closed primitives for P07 failure and G0 governance.

This module is deliberately outcome agnostic.  It validates immutable JSON/
CSV bindings, self hashes, materialized-plan membership, absolute workspace
outputs, and result manifests.  It never launches VINS or discovers a
trajectory/result directory.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable, Mapping, Sequence

try:
    from scripts import p07_backend_evaluation_v1 as evaluation
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import p07_backend_evaluation_v1 as evaluation  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
P07 = ROOT / "papers/ieee_sensors_journal_experiments/p07"
DEFAULT_REFERENCE_CONTRACTS = P07 / "g0_reference_contracts_v1.json"
DEFAULT_EVALUATION_LOCK = P07 / "g0_evaluation_lock_v1.json"

LOCK_SCHEMA = "isj-p07-g0-evaluation-lock-v1"
LOCK_STATUS = "FROZEN_OUTCOME_BLIND_BEFORE_FIRST_BACKEND_REPLAY"
PLAN_SCHEMA = "isj-p07-g0-evaluation-plan-v1"
PLAN_STATUS = "MATERIALIZED_FROM_FROZEN_G0_TEMPLATE"
JOB_SCHEMA = "isj-p07-g0-evaluation-job-v1"
JOB_STATUS = "PLANNED_FROM_FROZEN_G0_TEMPLATE"
TERMINAL_BINDING_SCHEMA = "isj-p07-g0-terminal-binding-v1"
TERMINAL_PROVENANCE_SCHEMA = (
    "isj-p07-backend-controller-terminal-provenance-v1"
)
FAILURE_EVIDENCE_SCHEMA = "isj-p07-backend-failure-evidence-v1"
CLASSIFICATION_SCHEMA = "isj-p07-backend-failure-classification-v1"
BOUND_SUMMARY_SCHEMA = "isj-p07-g0-bound-summary-v1"
RESULT_RECEIPT_SCHEMA = "isj-p07-g0-result-receipt-v1"
PUBLICATION_INTENT_SCHEMA = "isj-p07-g0-publication-intent-v1"
PUBLICATION_CLOSEOUT_SCHEMA = "isj-p07-g0-publication-closeout-v1"
REDUCTION_SCHEMA = "isj-p07-g0-full-reduction-v1"
EXECUTION_AUTHORITY_SCHEMA = "isj-p07-g0-pre-replay-execution-authority-v1"
EXECUTION_AUTHORITY_STATUS = "FROZEN_G0_AUTHORITY_BOUND_IN_BACKEND_EXECUTION_LOCK"
EXECUTION_LOCK_BINDING_KEY = "g0_pre_replay_authority"

OUTCOME_BOUNDARY = (
    "G0_GOVERNANCE_ONLY_NO_UNBOUND_TRAJECTORY_APE_RPE_RESULT_ACCESS"
)
LOCK_OUTCOME_BOUNDARY = (
    "FROZEN_BEFORE_FIRST_BACKEND_REPLAY_NO_TRAJECTORY_APE_RPE_RESULT_READ"
)

CLASSIFIER_INPUT_FIELDS = (
    "run_id",
    "window_id",
    "arm",
    "replay_index",
    "algorithmic_slot",
    "infrastructure_codes",
    "process",
    "trajectory",
    "initialization",
    "support",
    "solver_log_inspected",
    "solver_log_text",
    "queue",
)

FAILURE_EVIDENCE_KEYS = frozenset(
    {
        "schema_version",
        "queue_index",
        "run_id",
        "window_id",
        "arm",
        "replay_index",
        "backend_algorithmic_slot",
        "source_run_id",
        "source_provenance_kind",
        "source_provenance_hash",
        "algorithmic_slot",
        "infrastructure_codes",
        "process",
        "trajectory",
        "trajectory_artifact",
        "initialization",
        "support",
        "solver_log_inspected",
        "solver_log_text",
        "solver_log_artifact",
        "queue",
        "terminal_audit",
        "reference_contract_hash",
        "timestamp_policy",
        "governance_authority",
        "terminal_provenance",
        "outcome_boundary",
        "failure_evidence_hash",
    }
)

HASH_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")

# Private, process-local capability attached only by ``validate_plan_payload``.
# Callers cannot synthesize a serializable substitute: the identity check below
# is deliberately stronger than accepting a mapping with plausible hashes.
_VALIDATED_PLAN_CONTEXT_TOKEN = object()

REQUIRED_FROZEN_INPUT_ROLES = frozenset(
    {
        "backend_queue",
        "backend_allocation",
        "backend_queue_lock",
        "evaluator_precision_correction_lock",
        "evaluator_epoch_ns_correction_lock",
        "reference_contracts",
    }
)
REQUIRED_FROZEN_INPUT_PATHS = {
    "backend_queue": "papers/ieee_sensors_journal_experiments/p07/backend_replay_queue_v1.csv",
    "backend_allocation": "papers/ieee_sensors_journal_experiments/p07/backend_run_allocation_v1.csv",
    "backend_queue_lock": "papers/ieee_sensors_journal_experiments/p07/backend_queue_lock_v1.json",
    "evaluator_precision_correction_lock": (
        "papers/ieee_sensors_journal_experiments/p07/"
        "evaluator_precision_correction_lock_v1.json"
    ),
    "evaluator_epoch_ns_correction_lock": (
        "papers/ieee_sensors_journal_experiments/p07/"
        "evaluator_epoch_ns_correction_lock_v1.json"
    ),
    "reference_contracts": (
        "papers/ieee_sensors_journal_experiments/p07/g0_reference_contracts_v1.json"
    ),
}
REQUIRED_CODE_BINDING_ROLES = frozenset(
    {
        "evaluator",
        "evaluation_core",
        "planner_classifier_reducer_primitives",
        "g0_shared_governance",
        "reference_contract_builder",
        "template_lock_builder",
        "terminal_failure_collector",
        "plan_job_materializer_validator",
        "strict_g0_runner",
        "no_clobber_crash_reconcile_publisher",
        "full_reducer_orchestrator",
    }
)
REQUIRED_CODE_BINDING_PATHS = {
    "evaluator": "scripts/evaluate_vins_common_support_epoch_v2.py",
    "evaluation_core": "scripts/trajectory_eval_core.py",
    "planner_classifier_reducer_primitives": "scripts/p07_backend_evaluation_v1.py",
    "g0_shared_governance": "scripts/p07_g0_governance_v1.py",
    "reference_contract_builder": "scripts/build_p07_g0_reference_contracts_v1.py",
    "template_lock_builder": "scripts/build_p07_g0_evaluation_lock_v1.py",
    "terminal_failure_collector": "scripts/collect_p07_backend_failure_v1.py",
    "plan_job_materializer_validator": "scripts/materialize_p07_g0_jobs_v1.py",
    "strict_g0_runner": "scripts/run_p07_g0_evaluation_v1.py",
    "no_clobber_crash_reconcile_publisher": "scripts/p07_g0_publisher_v1.py",
    "full_reducer_orchestrator": "scripts/reduce_p07_g0_results_v1.py",
}


class G0GovernanceError(RuntimeError):
    """A P07 G0 governance, identity, hash, or no-clobber rule failed."""


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_hash(
    payload: Mapping[str, Any], hash_field: str | None = None
) -> str:
    value = dict(payload)
    if hash_field is not None:
        if hash_field not in value:
            raise G0GovernanceError(f"missing self-hash field: {hash_field}")
        value.pop(hash_field)
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _exact_json_equal(left: Any, right: Any) -> bool:
    try:
        return json.dumps(
            left,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8") == json.dumps(
            right,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return False


def require_hash(value: object, label: str) -> str:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        raise G0GovernanceError(f"{label} must be a lowercase SHA-256 digest")
    return value


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def display_path(root: Path, path: Path) -> str:
    root_abs = Path(os.path.abspath(os.fspath(root)))
    path_abs = Path(os.path.abspath(os.fspath(path)))
    try:
        return path_abs.relative_to(root_abs).as_posix()
    except ValueError:
        return os.fspath(path_abs)


def file_record(root: Path, path: Path) -> dict[str, object]:
    path = Path(path)
    if not path.is_file():
        raise G0GovernanceError(f"missing bound file: {path}")
    return {
        "path": display_path(root, path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _inside(root: Path, path: Path) -> bool:
    root_abs = os.path.abspath(os.fspath(root))
    path_abs = os.path.abspath(os.fspath(path))
    try:
        return os.path.commonpath((root_abs, path_abs)) == root_abs
    except ValueError:
        return False


def workspace_path(
    root: Path,
    value: object,
    *,
    label: str,
    require_absolute: bool = False,
) -> Path:
    if isinstance(value, bytes) or not isinstance(value, (str, os.PathLike)):
        raise G0GovernanceError(f"{label} path must be non-empty")
    raw_value = os.fspath(value)
    if not raw_value:
        raise G0GovernanceError(f"{label} path must be non-empty")
    raw = Path(raw_value)
    if require_absolute and not raw.is_absolute():
        raise G0GovernanceError(f"{label} must be an absolute workspace path")
    path = raw if raw.is_absolute() else root / raw
    path = Path(os.path.abspath(os.fspath(path)))
    if not _inside(root, path):
        raise G0GovernanceError(f"{label} escapes the workspace: {path}")
    return path


def validate_file_record(
    root: Path,
    record: Mapping[str, object],
    *,
    label: str,
    require_absolute: bool = False,
) -> Path:
    path = workspace_path(
        root, record.get("path"), label=label, require_absolute=require_absolute
    )
    if not path.is_file():
        raise G0GovernanceError(f"missing {label}: {path}")
    expected_size = record.get("size_bytes")
    if (
        isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or expected_size < 0
        or path.stat().st_size != expected_size
    ):
        raise G0GovernanceError(f"{label} size differs from binding: {path}")
    expected_hash = require_hash(record.get("sha256"), f"{label}.sha256")
    if sha256_file(path) != expected_hash:
        raise G0GovernanceError(f"{label} SHA-256 differs from binding: {path}")
    return path


def read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise G0GovernanceError(f"missing {label}: {path}")
    try:
        content = path.read_bytes()
    except OSError as error:
        raise G0GovernanceError(f"cannot read {label} JSON: {path}") from error
    try:
        return _json_object_bytes(content, label=label)
    except G0GovernanceError as error:
        raise G0GovernanceError(f"invalid {label} JSON: {path}") from error


def _publisher_module():
    try:
        from scripts import p07_g0_publisher_v1 as publisher
    except ModuleNotFoundError:
        import p07_g0_publisher_v1 as publisher  # type: ignore
    return publisher


def _backend_runtime_module():
    try:
        from scripts import p07_backend_replay_common_v1 as backend_runtime
    except ModuleNotFoundError:
        import p07_backend_replay_common_v1 as backend_runtime  # type: ignore
    return backend_runtime


def _backend_job_module():
    try:
        from scripts import run_p07_backend_replay_job_v1 as backend_job
    except ModuleNotFoundError:
        import run_p07_backend_replay_job_v1 as backend_job  # type: ignore
    return backend_job


def _backend_replacement_module():
    try:
        from scripts import allocate_p07_backend_replacement_v1 as replacement
    except ModuleNotFoundError:
        import allocate_p07_backend_replacement_v1 as replacement  # type: ignore
    return replacement


def _backend_controller_module():
    try:
        from scripts import run_p07_backend_serial_queue_v1 as controller
    except ModuleNotFoundError:
        import run_p07_backend_serial_queue_v1 as controller  # type: ignore
    return controller


def _failure_collector_module():
    try:
        from scripts import collect_p07_backend_failure_v1 as collector
    except ModuleNotFoundError:
        import collect_p07_backend_failure_v1 as collector  # type: ignore
    return collector


def _terminal_binding_to_core(binding: Mapping[str, Any]) -> dict[str, Any]:
    wrapper = binding.get("classification")
    artifacts = binding.get("artifact_bindings")
    if not isinstance(wrapper, Mapping) or not isinstance(
        wrapper.get("classification"), Mapping
    ) or not isinstance(artifacts, Mapping):
        raise G0GovernanceError("terminal binding cannot derive scientific core")
    trajectory = artifacts.get("trajectory")
    config = artifacts.get("config")
    return {
        "run_id": binding["run_id"],
        "window_id": binding["window_id"],
        "arm": binding["arm"],
        "replay_index": binding["replay_index"],
        "algorithmic_slot": True,
        "terminal": True,
        "trajectory_path": (
            trajectory["path"] if isinstance(trajectory, Mapping) else None
        ),
        "config_path": config["path"] if isinstance(config, Mapping) else None,
        "failure_evidence_path": artifacts["failure_evidence"]["path"],
        "arm_time_offset_s": binding["arm_time_offset_s"],
        "reference": binding["reference"],
        "evaluator_profile_id": binding["evaluator_profile_id"],
        "evaluator_protocol_sha256": binding["evaluator_protocol_sha256"],
        "evaluator_script_sha256": binding["evaluator_script_sha256"],
        "classification": dict(wrapper["classification"]),
    }


def _validate_direct_record(
    root: Path, record: Mapping[str, object], *, label: str
) -> Path:
    path = workspace_path(root, record.get("path"), label=label)
    observed = _publisher_module().direct_file_record_rooted(
        root, path, label=label
    )
    if any(
        observed.get(key) != record.get(key)
        for key in ("path", "sha256", "size_bytes")
    ):
        raise G0GovernanceError(f"{label} direct record differs")
    return path


def validate_bound_input_record(
    root: Path, record: Mapping[str, object], *, label: str
) -> Path:
    """Validate a direct file or one below an exact canonical input root."""

    path = workspace_path(root, record.get("path"), label=label)
    observed = _publisher_module().direct_file_record_bound_input_rooted(
        root, path, label=label
    )
    if any(
        observed.get(key) != record.get(key)
        for key in ("path", "sha256", "size_bytes")
    ):
        raise G0GovernanceError(f"{label} bound-input record differs")
    return path


def _read_direct_json(root: Path, path: Path, *, label: str) -> dict[str, Any]:
    return _publisher_module().read_json_direct_rooted(root, path, label=label)


def _direct_record(root: Path, path: Path, *, label: str) -> dict[str, object]:
    return _publisher_module().direct_file_record_rooted(root, path, label=label)


def _json_object_bytes(
    content: bytes, *, label: str, require_canonical: bool = True
) -> dict[str, Any]:
    def reject_duplicates(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise G0GovernanceError(f"duplicate JSON key in {label}: {key}")
            value[key] = item
        return value

    try:
        value = json.loads(
            content.decode("utf-8"), object_pairs_hook=reject_duplicates
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise G0GovernanceError(f"invalid {label} JSON") from error
    if not isinstance(value, dict):
        raise G0GovernanceError(f"{label} must be a JSON object")
    if require_canonical:
        expected = (
            json.dumps(
                value,
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        if content != expected:
            raise G0GovernanceError(f"{label} JSON is not canonical")
    return value


def _bound_json_snapshot(
    root: Path, record: Mapping[str, object], *, label: str
) -> dict[str, Any]:
    path = workspace_path(root, record.get("path"), label=label)
    content, observed = _publisher_module().read_bytes_and_record_bound_input_rooted(
        root, path, label=label
    )
    if (
        not isinstance(record.get("path"), str)
        or not isinstance(record.get("sha256"), str)
        or type(record.get("size_bytes")) is not int
        or any(
            type(observed.get(key)) is not type(record.get(key))
            or observed.get(key) != record.get(key)
            for key in ("path", "sha256", "size_bytes")
        )
    ):
        raise G0GovernanceError(f"{label} bound-input record differs")
    return _json_object_bytes(content, label=label)


def _direct_json_snapshot(
    root: Path, record: Mapping[str, object], *, label: str
) -> dict[str, Any]:
    path = workspace_path(root, record.get("path"), label=label)
    content, observed = _publisher_module()._read_direct_bytes(
        root, path, label=label
    )
    if (
        not isinstance(record.get("path"), str)
        or not isinstance(record.get("sha256"), str)
        or type(record.get("size_bytes")) is not int
        or any(
            type(observed.get(key)) is not type(record.get(key))
            or observed.get(key) != record.get(key)
            for key in ("path", "sha256", "size_bytes")
        )
    ):
        raise G0GovernanceError(f"{label} direct record differs")
    return _json_object_bytes(content, label=label)


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise G0GovernanceError(f"missing CSV: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    if not fields or any(set(row) != set(fields) for row in rows):
        raise G0GovernanceError(f"malformed CSV structure: {path}")
    return fields, rows


def write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    try:
        descriptor = os.open(
            os.fspath(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644
        )
    except FileExistsError as error:
        raise G0GovernanceError(f"refusing to clobber existing file: {path}") from error
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        directory = os.open(os.fspath(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        # The exclusive path is preserved as crash evidence.  Never silently
        # unlink a partially written formal/governed artifact.
        raise


def validate_self_hash(
    payload: Mapping[str, Any], field: str, *, label: str
) -> str:
    expected = require_hash(payload.get(field), f"{label}.{field}")
    actual = canonical_json_hash(payload, field)
    if actual != expected:
        raise G0GovernanceError(f"{label} self-hash mismatch")
    return expected


def row_sha256(row: Mapping[str, str]) -> str:
    return sha256_bytes(canonical_json_bytes(dict(row)))


def _require_exact_keys(
    value: Mapping[str, Any], expected: Iterable[str], *, label: str
) -> None:
    expected_set = set(expected)
    observed = set(value)
    if observed != expected_set:
        raise G0GovernanceError(
            f"{label} keys differ: missing={sorted(expected_set-observed)} "
            f"extra={sorted(observed-expected_set)}"
        )


def validate_lock_payload(
    payload: Mapping[str, Any],
    *,
    root: Path,
    verify_files: bool = True,
) -> str:
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "status",
            "frozen_at",
            "formalization_adoption",
            "formalization_review_evidence",
            "frozen_inputs",
            "mutable_registry_prefix",
            "backend_bindings",
            "code_bindings",
            "evaluation_template",
            "evaluation_template_hash",
            "pre_first_replay_proof",
            "outcome_blind_audit",
            "outcome_boundary",
            "evaluation_lock_hash",
        },
        label="G0 lock",
    )
    if payload.get("schema_version") != LOCK_SCHEMA or payload.get("status") != LOCK_STATUS:
        raise G0GovernanceError("unexpected G0 lock schema or status")
    lock_hash = validate_self_hash(payload, "evaluation_lock_hash", label="G0 lock")
    if payload.get("outcome_boundary") != LOCK_OUTCOME_BOUNDARY:
        raise G0GovernanceError("G0 lock outcome boundary mismatch")
    adoption_binding = payload.get("formalization_adoption")
    if (
        not isinstance(adoption_binding, Mapping)
        or set(adoption_binding)
        != {
            "path",
            "sha256",
            "size_bytes",
            "formalization_adoption_hash",
        }
        or adoption_binding.get("path")
        != "papers/ieee_sensors_journal_experiments/p07/backend_formalization_adoption_v1.json"
        or not HASH_RE.fullmatch(str(adoption_binding.get("sha256", "")))
        or type(adoption_binding.get("size_bytes")) is not int
        or int(adoption_binding["size_bytes"]) <= 0
        or not HASH_RE.fullmatch(
            str(adoption_binding.get("formalization_adoption_hash", ""))
        )
    ):
        raise G0GovernanceError("G0 lock formalization-adoption binding differs")
    evidence_binding = payload.get("formalization_review_evidence")
    if (
        not isinstance(evidence_binding, Mapping)
        or set(evidence_binding)
        != {"path", "sha256", "size_bytes", "formalization_review_evidence_hash"}
        or evidence_binding.get("path")
        != "papers/ieee_sensors_journal_experiments/p07/backend_formalization_review_evidence_lock_v1.json"
        or not HASH_RE.fullmatch(str(evidence_binding.get("sha256", "")))
        or type(evidence_binding.get("size_bytes")) is not int
        or int(evidence_binding["size_bytes"]) <= 0
        or not HASH_RE.fullmatch(
            str(evidence_binding.get("formalization_review_evidence_hash", ""))
        )
    ):
        raise G0GovernanceError("G0 lock formalization review-evidence binding differs")
    audit = payload.get("outcome_blind_audit")
    expected_audit_keys = {
        "backend_replay_executed",
        "real_backend_trajectory_read",
        "ape_artifact_read",
        "rpe_artifact_read",
        "evaluator_executed",
        "result_artifact_read",
        "workspace_result_discovery_used",
    }
    if (
        not isinstance(audit, Mapping)
        or set(audit) != expected_audit_keys
        or any(value is not False for value in audit.values())
    ):
        raise G0GovernanceError("G0 lock is not outcome blind")
    template = payload.get("evaluation_template")
    if not isinstance(template, Mapping):
        raise G0GovernanceError("G0 lock lacks evaluation_template")
    _require_exact_keys(
        template,
        {
            "schema_version",
            "scientific_unit",
            "replay_indices",
            "minimum_evaluable_replays",
            "pairing_rule",
            "routes",
            "counts",
            "reference_contracts",
            "evaluator",
            "failure_policy",
        },
        label="G0 evaluation template",
    )
    if template.get("schema_version") != "isj-p07-g0-evaluation-template-v1":
        raise G0GovernanceError("G0 evaluation-template schema differs")
    expected_template_hash = require_hash(
        payload.get("evaluation_template_hash"), "evaluation_template_hash"
    )
    if canonical_json_hash(template) != expected_template_hash:
        raise G0GovernanceError("evaluation template hash mismatch")
    counts = template.get("counts")
    if not isinstance(counts, Mapping):
        raise G0GovernanceError("evaluation template lacks counts")
    _require_exact_keys(
        counts,
        {
            "windows",
            "applicable_d_windows",
            "applicable_d_window_ids",
            "backend_algorithmic_replay_jobs",
            "g0_evaluation_jobs",
            "routes",
        },
        label="G0 evaluation-template counts",
    )
    try:
        windows = int(counts["windows"])
        k = int(counts["applicable_d_windows"])
        replay_jobs = int(counts["backend_algorithmic_replay_jobs"])
        evaluation_jobs = int(counts["g0_evaluation_jobs"])
    except (KeyError, TypeError, ValueError) as error:
        raise G0GovernanceError("invalid evaluation template counts") from error
    if windows != 20 or not 0 <= k <= windows:
        raise G0GovernanceError("evaluation template window/D count mismatch")
    if replay_jobs != 240 + 3 * k or evaluation_jobs != 180 + 3 * k:
        raise G0GovernanceError("evaluation template cardinality formula mismatch")
    routes = counts.get("routes")
    expected_routes = {
        "B0_DESCRIPTIVE": 60,
        "P_VS_B1": 60,
        "P_VS_M": 60,
        "P_VS_D": 3 * k,
    }
    if routes != expected_routes:
        raise G0GovernanceError("evaluation template route counts mismatch")
    if (
        template.get("replay_indices") != [1, 2, 3]
        or template.get("minimum_evaluable_replays") != 2
        or template.get("pairing_rule") != "EQUAL_REPLAY_INDEX_ONLY"
        or template.get("scientific_unit") != "sequence_not_replay"
    ):
        raise G0GovernanceError("evaluation template replay/pairing policy mismatch")
    route_contracts = template.get("routes")
    if not isinstance(route_contracts, Mapping) or set(route_contracts) != set(
        expected_routes
    ):
        raise G0GovernanceError("evaluation template route contracts differ")
    expected_route_arms = {
        "B0_DESCRIPTIVE": [evaluation.ARM_B0],
        "P_VS_B1": [evaluation.ARM_P, evaluation.ARM_B1],
        "P_VS_M": [evaluation.ARM_P, evaluation.ARM_M],
        "P_VS_D": [evaluation.ARM_P, evaluation.ARM_D],
    }
    for name, arms in expected_route_arms.items():
        contract = route_contracts.get(name)
        if not isinstance(contract, Mapping) or contract.get("arms") != arms:
            raise G0GovernanceError(f"evaluation template {name} arms mismatch")
        expected_contract_keys = {"route", "arms"}
        if name == "B0_DESCRIPTIVE":
            expected_contract_keys.add("metric_role")
        if name == "P_VS_D":
            expected_contract_keys.add("conditional")
        _require_exact_keys(
            contract,
            expected_contract_keys,
            label=f"G0 evaluation-template route {name}",
        )
        expected_route = (
            evaluation.ROUTE_B0_DESCRIPTIVE
            if name == "B0_DESCRIPTIVE"
            else evaluation.ROUTE_PAIRWISE_COMMON_SUPPORT
        )
        if contract.get("route") != expected_route:
            raise G0GovernanceError(f"evaluation template {name} route mismatch")
    if (
        route_contracts["B0_DESCRIPTIVE"].get("metric_role")
        != "DESCRIPTIVE_ONLY_NOT_AN_INFERENTIAL_CONTRAST"
        or route_contracts["P_VS_D"].get("conditional") is not True
    ):
        raise G0GovernanceError("evaluation template route semantics mismatch")
    reference_policy = template.get("reference_contracts")
    if isinstance(reference_policy, Mapping):
        _require_exact_keys(
            reference_policy,
            {
                "path",
                "sha256",
                "self_hash",
                "absolute_window_rule",
                "relative_queue_seconds_as_epoch_forbidden",
                "same_window_all_arms_replays_exact",
            },
            label="G0 evaluation-template reference policy",
        )
    if (
        not isinstance(reference_policy, Mapping)
        or reference_policy.get("absolute_window_rule")
        != "FIRST_LAST_ACTUAL_REFERENCE_SAMPLE_AFTER_FROZEN_WINDOW_SELECTION"
        or reference_policy.get("relative_queue_seconds_as_epoch_forbidden") is not True
        or reference_policy.get("same_window_all_arms_replays_exact") is not True
    ):
        raise G0GovernanceError("evaluation template reference policy mismatch")
    evaluator_policy = template.get("evaluator")
    expected_evaluator_policy = {
        "rpe_delta_s": 1.0,
        "minimum_ape_poses": 30,
        "minimum_ape_span_s": 10.0,
        "minimum_common_coverage": 0.70,
        "minimum_rpe_pairs": 10,
    }
    if isinstance(evaluator_policy, Mapping):
        _require_exact_keys(
            evaluator_policy,
            {
                "profile_rule",
                "protocol_sha256",
                "implementation_bundle_sha256",
                *expected_evaluator_policy,
            },
            label="G0 evaluation-template evaluator policy",
        )
    if not isinstance(evaluator_policy, Mapping) or any(
        evaluator_policy.get(key) != value
        for key, value in expected_evaluator_policy.items()
    ):
        raise G0GovernanceError("evaluation template evaluator thresholds mismatch")
    failure_policy = template.get("failure_policy")
    required_failure_policy = {
        "hard_failure_any_of_three": True,
        "solver_risk_any_of_three": True,
        "infrastructure_replacements_do_not_consume_algorithmic_slots": True,
        "hard_failure_precedes_numeric_effect": True,
        "queue_telemetry_policy": (
            "QUEUE_TELEMETRY_NOT_INSTRUMENTED_NO_ZERO_IMPUTATION"
        ),
        "queue_risk_is_diagnostic_not_hard_failure": True,
        "queue_unknown_alone_does_not_make_replay_incomplete": True,
    }
    if isinstance(failure_policy, Mapping):
        _require_exact_keys(
            failure_policy,
            required_failure_policy,
            label="G0 evaluation-template failure policy",
        )
    if not isinstance(failure_policy, Mapping) or any(
        failure_policy.get(key) != value
        for key, value in required_failure_policy.items()
    ):
        raise G0GovernanceError("evaluation template failure policy mismatch")
    bindings = payload.get("frozen_inputs")
    code = payload.get("code_bindings")
    if not isinstance(bindings, Sequence) or isinstance(bindings, (str, bytes)):
        raise G0GovernanceError("G0 lock frozen_inputs must be a list")
    if not isinstance(code, Sequence) or isinstance(code, (str, bytes)):
        raise G0GovernanceError("G0 lock code_bindings must be a list")
    for records, expected_roles, label in (
        (bindings, REQUIRED_FROZEN_INPUT_ROLES, "frozen input"),
        (code, REQUIRED_CODE_BINDING_ROLES, "code binding"),
    ):
        roles = [
            record.get("role") if isinstance(record, Mapping) else None
            for record in records
        ]
        if len(roles) != len(set(roles)) or set(roles) != set(expected_roles):
            raise G0GovernanceError(f"G0 lock {label} roles differ")
        for record in records:
            if not isinstance(record, Mapping) or set(record) != {
                "path",
                "sha256",
                "size_bytes",
                "role",
            }:
                raise G0GovernanceError(f"G0 lock {label} record schema differs")
    frozen_by_role = {
        str(record["role"]): record
        for record in bindings
        if isinstance(record, Mapping)
    }
    for role, expected_path in REQUIRED_FROZEN_INPUT_PATHS.items():
        if frozen_by_role[role].get("path") != expected_path:
            raise G0GovernanceError(
                f"G0 lock frozen input path differs for role {role}"
            )
    code_by_role = {
        str(record["role"]): record
        for record in code
        if isinstance(record, Mapping)
    }
    for role, expected_path in REQUIRED_CODE_BINDING_PATHS.items():
        if code_by_role[role].get("path") != expected_path:
            raise G0GovernanceError(
                f"G0 lock code binding path differs for role {role}"
            )
    reference_binding = frozen_by_role["reference_contracts"]
    if (
        reference_policy.get("path") != reference_binding.get("path")
        or reference_policy.get("sha256") != reference_binding.get("sha256")
    ):
        raise G0GovernanceError("reference policy/frozen input binding mismatch")
    for key in ("protocol_sha256", "implementation_bundle_sha256"):
        require_hash(evaluator_policy.get(key), f"evaluator policy {key}")
    backend_bindings = payload.get("backend_bindings")
    if not isinstance(backend_bindings, Mapping) or set(backend_bindings) != {
        "queue_lock_self_hash",
        "precision_correction_self_hash",
        "epoch_ns_correction_self_hash",
        "reference_contracts_self_hash",
    }:
        raise G0GovernanceError("G0 lock backend self-hash bindings differ")
    for key, value in backend_bindings.items():
        require_hash(value, f"backend binding {key}")
    if reference_policy.get("self_hash") != backend_bindings.get(
        "reference_contracts_self_hash"
    ):
        raise G0GovernanceError("reference policy/backend self-hash mismatch")
    prefix = payload.get("mutable_registry_prefix")
    if (
        not isinstance(prefix, Mapping)
        or set(prefix) != {"path", "sha256", "size_bytes"}
        or not isinstance(prefix.get("path"), str)
        or prefix.get("path")
        != "papers/ieee_sensors_journal_experiments/run_registry.csv"
        or isinstance(prefix.get("size_bytes"), bool)
        or not isinstance(prefix.get("size_bytes"), int)
        or int(prefix["size_bytes"]) <= 0
    ):
        raise G0GovernanceError("G0 lock mutable registry prefix is invalid")
    require_hash(prefix.get("sha256"), "mutable registry prefix sha256")
    prefirst = payload.get("pre_first_replay_proof")
    if (
        not isinstance(prefirst, Mapping)
        or set(prefirst)
        != {
            "registered_planned_runs",
            "running_runs",
            "terminal_runs",
            "deterministic_outputs_existing",
        }
        or type(prefirst.get("registered_planned_runs")) is not int
        or type(prefirst.get("running_runs")) is not int
        or type(prefirst.get("terminal_runs")) is not int
        or prefirst.get("registered_planned_runs") != replay_jobs
        or prefirst.get("running_runs") != 0
        or prefirst.get("terminal_runs") != 0
        or prefirst.get("deterministic_outputs_existing") != []
    ):
        raise G0GovernanceError("G0 lock pre-first-replay proof mismatch")
    if verify_files:
        try:
            from scripts import build_p07_backend_formalization_adoption_v1 as adoption_validator
            from scripts import build_p07_backend_formalization_review_evidence_v1 as evidence_validator
        except ModuleNotFoundError:
            import build_p07_backend_formalization_adoption_v1 as adoption_validator  # type: ignore
            import build_p07_backend_formalization_review_evidence_v1 as evidence_validator  # type: ignore
        try:
            adoption_validator.validate_adoption_authority_binding(
                adoption_binding, root=root
            )
        except adoption_validator.AdoptionError as error:
            raise G0GovernanceError(
                "G0 lock formalization-adoption authority drift"
            ) from error
        try:
            evidence_validator.validate_review_evidence_authority_binding(
                evidence_binding, root=root
            )
        except evidence_validator.ReviewEvidenceError as error:
            raise G0GovernanceError(
                "G0 lock formalization review-evidence authority drift"
            ) from error
        seen: set[str] = set()
        for index, record in enumerate((*bindings, *code)):
            if not isinstance(record, Mapping):
                raise G0GovernanceError("G0 lock artifact record must be an object")
            path = _validate_direct_record(
                root, record, label=f"G0 lock artifact {index}"
            )
            key = os.path.abspath(os.fspath(path))
            if key in seen:
                raise G0GovernanceError(f"duplicate G0 lock artifact: {path}")
            seen.add(key)
        queue_lock_path = workspace_path(
            root,
            frozen_by_role["backend_queue_lock"]["path"],
            label="backend queue lock",
        )
        queue_lock = _read_direct_json(
            root, queue_lock_path, label="backend queue lock"
        )
        if validate_self_hash(
            queue_lock, "backend_queue_lock_hash", label="backend queue lock"
        ) != backend_bindings["queue_lock_self_hash"]:
            raise G0GovernanceError("backend queue-lock self-hash binding mismatch")
        try:
            from scripts import p07_backend_replay_common_v1 as backend_runtime
            from scripts import build_p07_evaluator_epoch_ns_correction_lock_v1 as epoch_validator
            from scripts import build_p07_g0_reference_contracts_v1 as reference_validator
        except ModuleNotFoundError:
            import p07_backend_replay_common_v1 as backend_runtime  # type: ignore
            import build_p07_evaluator_epoch_ns_correction_lock_v1 as epoch_validator  # type: ignore
            import build_p07_g0_reference_contracts_v1 as reference_validator  # type: ignore
        try:
            validated_queue_lock = backend_runtime.validate_queue_lock(
                root, queue_lock_path
            )
        except backend_runtime.BackendReplayViolation as error:
            raise G0GovernanceError(f"invalid nested backend queue lock: {error}") from error
        if validated_queue_lock != queue_lock:
            raise G0GovernanceError("backend queue lock changed during validation")
        queue_record = frozen_by_role["backend_queue"]
        allocation_record = frozen_by_role["backend_allocation"]
        queue_path = workspace_path(
            root, queue_record["path"], label="frozen backend queue"
        )
        allocation_path = workspace_path(
            root, allocation_record["path"], label="frozen backend allocation"
        )
        queue_bytes = _publisher_module().read_bytes_direct_rooted(
            root, queue_path, label="frozen backend queue"
        )
        allocation_bytes = _publisher_module().read_bytes_direct_rooted(
            root, allocation_path, label="frozen backend allocation"
        )
        try:
            _queue_fields, queue_rows = backend_runtime.parse_csv_bytes(
                queue_bytes, label="frozen backend queue"
            )
            _allocation_fields, allocation_rows = backend_runtime.parse_csv_bytes(
                allocation_bytes, label="frozen backend allocation"
            )
            queue_by_index = {row["queue_index"]: row for row in queue_rows}
            allocation_by_index = {
                row["queue_index"]: row for row in allocation_rows
            }
            if (
                len(queue_by_index) != len(queue_rows)
                or len(allocation_by_index) != len(allocation_rows)
                or set(queue_by_index) != set(allocation_by_index)
            ):
                raise G0GovernanceError(
                    "frozen backend queue/allocation index sets differ"
                )
            for index, row in queue_by_index.items():
                backend_runtime.validate_queue_row(row)
                backend_runtime.validate_allocation(row, allocation_by_index[index])
            backend_runtime._validate_queue_source_evidence(queue_lock, queue_rows)
        except backend_runtime.BackendReplayViolation as error:
            raise G0GovernanceError(
                f"invalid nested backend queue/allocation semantics: {error}"
            ) from error
        precision_path = workspace_path(
            root,
            frozen_by_role["evaluator_precision_correction_lock"]["path"],
            label="evaluator precision lock",
        )
        precision = _read_direct_json(
            root, precision_path, label="evaluator precision lock"
        )
        if validate_self_hash(
            precision, "correction_lock_hash", label="evaluator precision lock"
        ) != backend_bindings["precision_correction_self_hash"]:
            raise G0GovernanceError("precision-lock self-hash binding mismatch")
        epoch_path = workspace_path(
            root,
            frozen_by_role["evaluator_epoch_ns_correction_lock"]["path"],
            label="evaluator epoch-ns correction lock",
        )
        epoch = _read_direct_json(
            root, epoch_path, label="evaluator epoch-ns correction lock"
        )
        if validate_self_hash(
            epoch,
            "epoch_ns_correction_lock_hash",
            label="evaluator epoch-ns correction lock",
        ) != backend_bindings["epoch_ns_correction_self_hash"]:
            raise G0GovernanceError("epoch-ns correction-lock self-hash binding mismatch")
        try:
            epoch_validator.validate_lock_payload(
                epoch, root=root, verify_files=True
            )
        except ValueError as error:
            raise G0GovernanceError(
                f"invalid nested epoch-ns correction lock: {error}"
            ) from error
        epoch_implementation = epoch.get("corrected_implementation_binding")
        epoch_files = (
            epoch_implementation.get("files")
            if isinstance(epoch_implementation, Mapping)
            else None
        )
        if not isinstance(epoch_files, list):
            raise G0GovernanceError("epoch-ns correction implementation files missing")
        epoch_by_path = {
            str(record.get("path")): record
            for record in epoch_files
            if isinstance(record, Mapping)
        }
        for role, path in (
            ("evaluator", REQUIRED_CODE_BINDING_PATHS["evaluator"]),
            ("evaluation_core", REQUIRED_CODE_BINDING_PATHS["evaluation_core"]),
        ):
            expected_record = epoch_by_path.get(path)
            observed_record = code_by_role[role]
            if expected_record is None or any(
                observed_record.get(key) != expected_record.get(key)
                for key in ("path", "sha256", "size_bytes")
            ):
                raise G0GovernanceError(
                    f"G0 {role} binding differs from epoch-ns correction"
                )
        if (
            epoch_implementation.get("entrypoint")
            != REQUIRED_CODE_BINDING_PATHS["evaluator"]
            or evaluator_policy.get("implementation_bundle_sha256")
            != epoch_implementation.get("implementation_bundle_sha256")
        ):
            raise G0GovernanceError(
                "G0 evaluator template differs from epoch-ns correction"
            )
        epoch_protocol = epoch.get("protocol_binding")
        if (
            not isinstance(epoch_protocol, Mapping)
            or evaluator_policy.get("protocol_sha256")
            != epoch_protocol.get("sha256")
        ):
            raise G0GovernanceError(
                "G0 evaluator protocol differs from epoch-ns correction"
            )
        reference_path = workspace_path(
            root,
            frozen_by_role["reference_contracts"]["path"],
            label="reference contracts",
        )
        references = _read_direct_json(
            root, reference_path, label="reference contracts"
        )
        if validate_self_hash(
            references, "reference_contracts_hash", label="reference contracts"
        ) != backend_bindings["reference_contracts_self_hash"]:
            raise G0GovernanceError("reference-contract self-hash binding mismatch")
        source_queue = references.get("source_backend_queue")
        if not isinstance(source_queue, Mapping) or any(
            source_queue.get(key) != queue_record.get(key)
            for key in ("path", "sha256", "size_bytes")
        ):
            raise G0GovernanceError(
                "reference contracts bind a different frozen backend queue"
            )
        if (
            reference_validator.validate_reference_contracts(
                references, root=root, verify_artifacts=True
            )
            != backend_bindings["reference_contracts_self_hash"]
        ):
            raise G0GovernanceError("nested reference-contract semantics differ")
        registry_path = workspace_path(
            root, prefix["path"], label="mutable registry prefix"
        )
        registry_bytes = _publisher_module().read_bytes_direct_rooted(
            root, registry_path, label="mutable registry prefix"
        )
        prefix_size = int(prefix["size_bytes"])
        if (
            len(registry_bytes) < prefix_size
            or sha256_bytes(registry_bytes[:prefix_size]) != prefix["sha256"]
        ):
            raise G0GovernanceError("mutable registry prefix drift")
        try:
            prefix_text = registry_bytes[:prefix_size].decode("utf-8")
            reader = csv.DictReader(io.StringIO(prefix_text, newline=""))
            registry_fields = list(reader.fieldnames or [])
            registry_rows = [dict(row) for row in reader]
        except (UnicodeDecodeError, csv.Error) as error:
            raise G0GovernanceError("mutable registry prefix is not valid CSV") from error
        if (
            not registry_fields
            or not prefix_text.endswith("\n")
            or any(None in row or set(row) != set(registry_fields) for row in registry_rows)
        ):
            raise G0GovernanceError("mutable registry prefix CSV structure differs")
        queue_run_ids = {row["run_id"] for row in queue_rows}
        registry_by_run: dict[str, list[dict[str, str]]] = {
            run_id: [] for run_id in queue_run_ids
        }
        for row in registry_rows:
            run_id = row.get("run_id", "")
            if row.get("stage") == "P07_BACKEND_REPLAY" and run_id in registry_by_run:
                registry_by_run[run_id].append(row)
        if any(
            len(events) != 1 or events[0].get("status") != "PLANNED"
            for events in registry_by_run.values()
        ):
            raise G0GovernanceError(
                "mutable registry prefix does not prove one PLANNED event per replay"
            )
        rederived_prefirst = {
            "registered_planned_runs": len(registry_by_run),
            "running_runs": 0,
            "terminal_runs": 0,
            "deterministic_outputs_existing": [],
        }
        if not _exact_json_equal(prefirst, rederived_prefirst):
            raise G0GovernanceError("G0 pre-first-replay proof does not rederive")
    return lock_hash


def build_execution_authority_binding(
    lock_path: Path, *, root: Path
) -> dict[str, Any]:
    """Build the one-way G0 authority record embedded by execution-lock.

    The G0 lock already transitively binds queue/allocation/queue-lock,
    reference contracts, both evaluator corrections, and every evaluation source.
    The later execution-lock binds this record; the pre-replay G0 lock never
    refers back to execution-lock.
    """

    lock = _read_direct_json(root, lock_path, label="pre-replay G0 lock")
    lock_hash = validate_lock_payload(lock, root=root, verify_files=True)
    references = [
        record
        for record in lock["frozen_inputs"]
        if isinstance(record, Mapping) and record.get("role") == "reference_contracts"
    ]
    if len(references) != 1:
        raise G0GovernanceError("G0 lock lacks one reference-contract binding")
    payload: dict[str, Any] = {
        "schema_version": EXECUTION_AUTHORITY_SCHEMA,
        "status": EXECUTION_AUTHORITY_STATUS,
        "evaluation_lock": {
            **_direct_record(root, lock_path, label="pre-replay G0 lock"),
            "evaluation_lock_hash": lock_hash,
        },
        "evaluation_template_hash": lock["evaluation_template_hash"],
        "reference_contracts": {
            **dict(references[0]),
            "reference_contracts_hash": lock["backend_bindings"][
                "reference_contracts_self_hash"
            ],
        },
        "code_bindings_hash": canonical_json_hash(
            {"code_bindings": lock["code_bindings"]}
        ),
        "frozen_input_bindings_hash": canonical_json_hash(
            {"frozen_inputs": lock["frozen_inputs"]}
        ),
        "dependency_direction": "G0_LOCK_THEN_EXECUTION_LOCK_NO_CYCLE",
        "terminal_receipts_must_bind_both_locks": True,
        "outcome_boundary": LOCK_OUTCOME_BOUNDARY,
    }
    payload["g0_execution_authority_hash"] = canonical_json_hash(payload)
    validate_execution_authority_binding(payload, root=root)
    return payload


def validate_execution_authority_binding(
    payload: Mapping[str, Any], *, root: Path
) -> str:
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "status",
            "evaluation_lock",
            "evaluation_template_hash",
            "reference_contracts",
            "code_bindings_hash",
            "frozen_input_bindings_hash",
            "dependency_direction",
            "terminal_receipts_must_bind_both_locks",
            "outcome_boundary",
            "g0_execution_authority_hash",
        },
        label="G0 execution authority",
    )
    if (
        payload.get("schema_version") != EXECUTION_AUTHORITY_SCHEMA
        or payload.get("status") != EXECUTION_AUTHORITY_STATUS
    ):
        raise G0GovernanceError("unexpected G0 execution-authority schema/status")
    digest = validate_self_hash(
        payload,
        "g0_execution_authority_hash",
        label="G0 execution authority",
    )
    lock_record = payload.get("evaluation_lock")
    if not isinstance(lock_record, Mapping):
        raise G0GovernanceError("G0 execution authority lacks evaluation lock")
    _require_exact_keys(
        lock_record,
        {"path", "sha256", "size_bytes", "evaluation_lock_hash"},
        label="G0 execution authority evaluation lock",
    )
    lock_path = _validate_direct_record(
        root, lock_record, label="G0 evaluation lock"
    )
    lock = _read_direct_json(root, lock_path, label="G0 evaluation lock")
    lock_hash = validate_lock_payload(lock, root=root, verify_files=True)
    if lock_record.get("evaluation_lock_hash") != lock_hash:
        raise G0GovernanceError("execution authority G0 lock self-hash mismatch")
    if payload.get("evaluation_template_hash") != lock.get("evaluation_template_hash"):
        raise G0GovernanceError("execution authority template hash mismatch")
    if payload.get("code_bindings_hash") != canonical_json_hash(
        {"code_bindings": lock["code_bindings"]}
    ):
        raise G0GovernanceError("execution authority code bundle hash mismatch")
    if payload.get("frozen_input_bindings_hash") != canonical_json_hash(
        {"frozen_inputs": lock["frozen_inputs"]}
    ):
        raise G0GovernanceError("execution authority frozen-input hash mismatch")
    references = [
        record
        for record in lock["frozen_inputs"]
        if isinstance(record, Mapping) and record.get("role") == "reference_contracts"
    ]
    reference = payload.get("reference_contracts")
    if len(references) != 1 or not isinstance(reference, Mapping):
        raise G0GovernanceError("execution authority reference binding is invalid")
    _require_exact_keys(
        reference,
        {"path", "sha256", "size_bytes", "role", "reference_contracts_hash"},
        label="G0 execution authority reference contracts",
    )
    expected_reference = {
        **dict(references[0]),
        "reference_contracts_hash": lock["backend_bindings"][
            "reference_contracts_self_hash"
        ],
    }
    if not _exact_json_equal(reference, expected_reference):
        raise G0GovernanceError("execution authority reference binding mismatch")
    _validate_direct_record(root, reference, label="G0 reference contracts")
    if (
        payload.get("dependency_direction")
        != "G0_LOCK_THEN_EXECUTION_LOCK_NO_CYCLE"
        or payload.get("terminal_receipts_must_bind_both_locks") is not True
        or payload.get("outcome_boundary") != LOCK_OUTCOME_BOUNDARY
    ):
        raise G0GovernanceError("execution authority dependency/boundary mismatch")
    return digest


def _validate_backend_terminal_provenance(
    provenance: Mapping[str, Any],
    *,
    root: Path,
    frozen_queue_row: Mapping[str, str],
    terminal: Mapping[str, Any],
    artifact_bindings: Mapping[str, Any],
    registry_prefix_record: Mapping[str, Any],
    verify_files: bool,
) -> dict[str, str]:
    """Validate the effective backend attempt selected by the serial controller."""

    _require_exact_keys(
        provenance,
        {
            "schema_version",
            "queue_index",
            "base_queue_row",
            "effective_queue_row",
            "allowed_effective_row_overrides",
            "changed_effective_row_fields",
            "replacement_lock",
            "terminal_disposition",
            "terminal_registry_event",
            "terminal_registry_event_sha256",
            "output_manifest",
            "terminal_audit_path",
            "outcome_boundary",
            "terminal_provenance_hash",
        },
        label="backend controller terminal provenance",
    )
    if (
        provenance.get("schema_version") != TERMINAL_PROVENANCE_SCHEMA
        or provenance.get("outcome_boundary")
        != "BACKEND_CONTROLLER_TERMINAL_AUTHORITY_NO_APE_RPE_RESULT_READ"
        or validate_self_hash(
            provenance,
            "terminal_provenance_hash",
            label="backend controller terminal provenance",
        )
        != provenance.get("terminal_provenance_hash")
    ):
        raise G0GovernanceError("backend terminal provenance schema/boundary differs")
    if provenance.get("queue_index") != int(frozen_queue_row["queue_index"]):
        raise G0GovernanceError("backend terminal provenance queue index differs")
    base = provenance.get("base_queue_row")
    effective = provenance.get("effective_queue_row")
    if not isinstance(base, Mapping) or not _exact_json_equal(
        base, frozen_queue_row
    ) or not isinstance(effective, Mapping):
        raise G0GovernanceError("backend terminal base/effective row is invalid")
    effective_row = {str(key): str(value) for key, value in effective.items()}
    try:
        _backend_runtime_module().validate_queue_row(effective_row)
    except Exception as error:
        raise G0GovernanceError("backend terminal effective row is invalid") from error
    allowed = {
        "run_id",
        "runner_tag",
        "expected_run_dir",
        "expected_attempt_dir",
    }
    if provenance.get("allowed_effective_row_overrides") != sorted(allowed):
        raise G0GovernanceError("backend terminal allowed overrides differ")
    changed = {
        key
        for key in frozen_queue_row
        if effective_row.get(key) != frozen_queue_row.get(key)
    }
    expected_changed = [] if not changed else sorted(allowed)
    if changed not in (set(), allowed) or provenance.get(
        "changed_effective_row_fields"
    ) != expected_changed:
        raise G0GovernanceError("backend terminal effective override set differs")
    replacement_record = provenance.get("replacement_lock")
    if not changed:
        if replacement_record is not None:
            raise G0GovernanceError("base backend terminal unexpectedly binds replacement")
    else:
        if not isinstance(replacement_record, Mapping) or set(replacement_record) != {
            "path",
            "sha256",
            "size_bytes",
            "replacement_lock_hash",
            "attempt_number",
            "replacement_for",
        }:
            raise G0GovernanceError("backend terminal replacement binding differs")
        replacement_payload = _direct_json_snapshot(
            root, replacement_record, label="backend terminal replacement lock"
        )
        try:
            _backend_replacement_module().validate_replacement_lock_payload(
                replacement_payload,
                expected_relative_path=replacement_record["path"],
            )
        except Exception as error:
            raise G0GovernanceError("backend terminal replacement lock is invalid") from error
        if (
            replacement_record.get("replacement_lock_hash")
            != replacement_payload.get("replacement_lock_hash")
            or replacement_record.get("attempt_number")
            != replacement_payload.get("attempt_number")
            or replacement_record.get("replacement_for")
            != replacement_payload.get("replacement_for")
            or not _exact_json_equal(
                replacement_payload.get("base_queue_row"), frozen_queue_row
            )
            or not _exact_json_equal(
                replacement_payload.get("effective_queue_row"), effective_row
            )
        ):
            raise G0GovernanceError("backend terminal replacement provenance differs")

    for key, row_key in (
        ("queue_index", "queue_index"),
        ("run_id", "run_id"),
        ("window_id", "window_id"),
        ("arm", "arm"),
        ("source_run_id", "source_run_id"),
        ("source_provenance_kind", "source_provenance_kind"),
        ("source_provenance_hash", "source_provenance_hash"),
        ("evaluator_profile_id", "evaluator_profile_id"),
        ("evaluator_protocol_sha256", "evaluator_protocol_sha256"),
    ):
        expected: object = effective_row[row_key]
        if key == "queue_index":
            expected = int(str(expected))
        if terminal.get(key) != expected:
            raise G0GovernanceError(
                f"terminal {key} differs from effective backend row"
            )
    if (
        terminal.get("replay_index") != int(effective_row["replay_index"])
        or terminal.get("backend_algorithmic_slot")
        != effective_row["algorithmic_slot"]
    ):
        raise G0GovernanceError("terminal replay slot differs from effective backend row")

    disposition = provenance.get("terminal_disposition")
    if disposition not in {"COMPLETED", "ALGORITHM_HARD_FAILURE"}:
        raise G0GovernanceError("backend terminal disposition is not scientific terminal")
    registry_event = provenance.get("terminal_registry_event")
    if not isinstance(registry_event, Mapping) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in registry_event.items()
    ):
        raise G0GovernanceError("backend terminal registry event is invalid")
    if canonical_json_hash(registry_event) != provenance.get(
        "terminal_registry_event_sha256"
    ):
        raise G0GovernanceError("backend terminal registry event hash differs")
    if registry_event.get("run_id") != effective_row["run_id"]:
        raise G0GovernanceError("backend terminal registry run differs")

    attempt = effective_row["expected_attempt_dir"]
    expected_audit = f"{attempt}/audit_v1.json"
    expected_manifest = f"{attempt}/output_hash_manifest.sha256"
    audit_record = artifact_bindings.get("terminal_audit")
    manifest_record = provenance.get("output_manifest")
    if (
        provenance.get("terminal_audit_path") != expected_audit
        or not isinstance(audit_record, Mapping)
        or audit_record.get("path") != expected_audit
        or not isinstance(manifest_record, Mapping)
        or set(manifest_record) != {"path", "sha256", "size_bytes"}
        or manifest_record.get("path") != expected_manifest
        or registry_event.get("output_hash_manifest") != expected_manifest
    ):
        raise G0GovernanceError("backend terminal audit/manifest authority differs")
    if verify_files:
        try:
            selected_effective, selected_lock_path = (
                _backend_controller_module()._replacement_for_index(
                    root,
                    int(frozen_queue_row["queue_index"]),
                    frozen_queue_row,
                )
            )
        except Exception as error:
            raise G0GovernanceError(
                "backend controller replacement selection is invalid"
            ) from error
        if not _exact_json_equal(selected_effective, effective_row):
            raise G0GovernanceError(
                "backend terminal effective row is not controller-selected latest"
            )
        observed_lock_path = (
            replacement_record.get("path")
            if isinstance(replacement_record, Mapping)
            else None
        )
        if selected_lock_path != observed_lock_path:
            raise G0GovernanceError(
                "backend terminal replacement lock is not controller-selected latest"
            )
        _validate_direct_record(root, manifest_record, label="backend terminal manifest")
        backend_runtime = _backend_runtime_module()
        registry_path = workspace_path(
            root,
            registry_prefix_record.get("path"),
            label="canonical backend registry",
        )
        registry_bytes = _publisher_module().read_bytes_direct_rooted(
            root, registry_path, label="canonical backend registry"
        )
        try:
            _fields, registry_rows = backend_runtime.parse_csv_bytes(
                registry_bytes, label="canonical backend registry"
            )
        except Exception as error:
            raise G0GovernanceError("canonical backend registry is invalid") from error
        live = [
            row for row in registry_rows if row.get("run_id") == effective_row["run_id"]
        ]
        if not live:
            raise G0GovernanceError("backend terminal registry chain is absent")
        for index, row in enumerate(live):
            expected_event = f"{effective_row['run_id']}_e{index:02d}"
            expected_parent = "" if index == 0 else live[index - 1][
                "registry_event_id"
            ]
            if (
                row.get("registry_event_id") != expected_event
                or row.get("supersedes_event_id") != expected_parent
            ):
                raise G0GovernanceError(
                    "backend terminal canonical registry chain is invalid"
                )
        if not _exact_json_equal(live[-1], registry_event):
            raise G0GovernanceError("backend terminal event is not the live registry suffix")
        try:
            live_disposition = _backend_job_module().terminal_slot_disposition(
                root=root, row=effective_row, latest=live[-1]
            )
        except Exception as error:
            raise G0GovernanceError("live backend terminal disposition is invalid") from error
        if live_disposition != disposition:
            raise G0GovernanceError("live backend terminal disposition differs")
    return effective_row


def _validate_terminal_audit_output_authority(
    audit: Mapping[str, Any],
    *,
    root: Path,
    effective_queue_row: Mapping[str, str],
) -> None:
    """Bind audit-declared technical outputs to the effective run directory.

    Failure-evidence derivation may inspect only the canonical trajectory and
    VINS log locations emitted by the frozen backend auditor.  A rehashed
    audit cannot redirect that derivation to another workspace artifact.
    """

    run_dir = workspace_path(
        root,
        effective_queue_row["expected_run_dir"],
        label="terminal effective backend run directory",
    )
    if audit.get("run_dir") != display_path(root, run_dir):
        raise G0GovernanceError("terminal audit run directory authority differs")
    structure = audit.get("output_structure")
    if not isinstance(structure, Mapping):
        raise G0GovernanceError("terminal audit output structure is not an object")
    run_state = _publisher_module().path_state_bound_input_rooted(
        root, run_dir, label="terminal effective backend run directory"
    )
    if not structure:
        if run_state != "ABSENT":
            raise G0GovernanceError(
                "empty terminal audit output structure has an existing run directory"
            )
        return
    if run_state != "DIRECTORY":
        raise G0GovernanceError(
            "terminal audit output structure lacks its direct run directory"
        )
    expected_paths = {
        "vins_log": run_dir / "vins.log",
        "vins_environment": run_dir / "vins_env_manifest.txt",
        "trajectory": run_dir / "vins_output/vio.csv",
        "backend_replay_manifest": run_dir / "backend_replay_manifest.txt",
        "preparation_manifest": run_dir / "replay_manifest.txt",
        "ape_report": run_dir / "ape.txt",
        "rpe_report": run_dir / "rpe.txt",
        "ape_rpe_report": run_dir / "ape_rpe.json",
    }
    _require_exact_keys(
        structure,
        expected_paths,
        label="terminal audit output structure",
    )
    for name, expected_path in expected_paths.items():
        value = structure.get(name)
        if not isinstance(value, Mapping):
            raise G0GovernanceError(
                f"terminal audit output structure {name} is not an object"
            )
        _require_exact_keys(
            value,
            {"path", "exists", "size_bytes"},
            label=f"terminal audit output structure {name}",
        )
        if value.get("path") != os.fspath(expected_path):
            raise G0GovernanceError(
                f"terminal audit output structure {name} path differs"
            )
        exists = value.get("exists")
        size = value.get("size_bytes")
        if type(exists) is not bool:
            raise G0GovernanceError(
                f"terminal audit output structure {name} existence differs"
            )
        observed_state = _publisher_module().path_state_bound_input_rooted(
            root, expected_path, label=f"terminal audit output {name}"
        )
        if exists:
            if (
                type(size) is not int
                or size < 0
                or observed_state != "FILE"
                or _publisher_module().direct_file_record_bound_input_rooted(
                    root, expected_path, label=f"terminal audit output {name}"
                )["size_bytes"]
                != size
            ):
                raise G0GovernanceError(
                    f"terminal audit output structure {name} file/size differs"
                )
        elif size is not None or observed_state != "ABSENT":
            raise G0GovernanceError(
                f"terminal audit output structure {name} absence differs"
            )
    if any(
        structure[name].get("exists") is not False
        for name in ("ape_report", "rpe_report", "ape_rpe_report")
    ):
        raise G0GovernanceError("terminal audit declares forbidden APE/RPE output")


def validate_terminal_binding(
    payload: Mapping[str, Any], *, root: Path, verify_files: bool = True
) -> str:
    if payload.get("schema_version") != TERMINAL_BINDING_SCHEMA:
        raise G0GovernanceError("unexpected terminal binding schema")
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "queue_index",
            "run_id",
            "window_id",
            "arm",
            "replay_index",
            "backend_algorithmic_slot",
            "source_run_id",
            "source_provenance_kind",
            "source_provenance_hash",
            "algorithmic_slot",
            "terminal",
            "evaluation_lock_hash",
            "backend_execution_lock_hash",
            "g0_execution_authority_hash",
            "classification",
            "backend_terminal_provenance",
            "artifact_bindings",
            "reference",
            "reference_contract_hash",
            "arm_time_offset_s",
            "evaluator_profile_id",
            "evaluator_protocol_sha256",
            "evaluator_script_sha256",
            "outcome_boundary",
            "terminal_binding_hash",
        },
        label="terminal binding",
    )
    if payload.get("outcome_boundary") != OUTCOME_BOUNDARY:
        raise G0GovernanceError("terminal binding outcome boundary differs")
    binding_hash = validate_self_hash(
        payload, "terminal_binding_hash", label="terminal binding"
    )
    for key in ("queue_index", "replay_index"):
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise G0GovernanceError(f"terminal binding {key} must be an integer")
    if payload.get("replay_index") not in (1, 2, 3):
        raise G0GovernanceError("terminal binding replay index is invalid")
    for key in ("run_id", "window_id", "arm"):
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise G0GovernanceError(f"terminal binding {key} is empty")
    for key in (
        "backend_algorithmic_slot",
        "source_run_id",
        "source_provenance_kind",
    ):
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise G0GovernanceError(f"terminal binding {key} is empty")
    if payload.get("backend_algorithmic_slot") != f"b{payload['replay_index']:02d}":
        raise G0GovernanceError("terminal backend algorithmic slot mismatch")
    require_hash(payload.get("source_provenance_hash"), "terminal source provenance")
    if payload.get("terminal") is not True or payload.get("algorithmic_slot") is not True:
        raise G0GovernanceError("terminal binding is not a terminal algorithmic slot")
    evaluation_lock_hash = require_hash(
        payload.get("evaluation_lock_hash"), "terminal evaluation lock hash"
    )
    execution_lock_hash = require_hash(
        payload.get("backend_execution_lock_hash"),
        "terminal backend execution lock hash",
    )
    authority_hash = require_hash(
        payload.get("g0_execution_authority_hash"),
        "terminal G0 execution authority hash",
    )
    reference_contract_hash = require_hash(
        payload.get("reference_contract_hash"),
        "terminal reference contract hash",
    )
    arm_time_offset = payload.get("arm_time_offset_s")
    if type(arm_time_offset) is not float or repr(arm_time_offset) != "0.0":
        raise G0GovernanceError(
            "terminal arm_time_offset_s differs from frozen zero-offset protocol"
        )
    classification = payload.get("classification")
    if not isinstance(classification, Mapping):
        raise G0GovernanceError("terminal binding lacks classification")
    _require_exact_keys(
        classification,
        {
            "schema_version",
            "status",
            "run_id",
            "window_id",
            "arm",
            "replay_index",
            "failure_evidence",
            "classifier_implementation",
            "classification",
            "outcome_boundary",
            "classification_hash",
        },
        label="terminal classification wrapper",
    )
    core = classification.get("classification")
    if not isinstance(core, Mapping) or core.get("schema_version") != evaluation.SCHEMA_VERSION:
        raise G0GovernanceError("terminal binding classification wrapper is invalid")
    _require_exact_keys(
        core,
        {
            "schema_version",
            "run_id",
            "window_id",
            "arm",
            "replay_index",
            "algorithmic_slot",
            "classification_status",
            "incomplete_evidence_fields",
            "infrastructure_codes",
            "observed_hard_failure_codes",
            "hard_failure",
            "solver_risk_codes",
            "solver_risk",
            "queue_evidence_status",
            "queue_risk_codes",
            "numeric_evaluable_before_common_support",
        },
        label="terminal classification core",
    )
    if classification.get("schema_version") != CLASSIFICATION_SCHEMA:
        raise G0GovernanceError("terminal binding classification schema mismatch")
    validate_self_hash(classification, "classification_hash", label="classification")
    expected_identity = {
        "run_id": payload["run_id"],
        "window_id": payload["window_id"],
        "arm": payload["arm"],
        "replay_index": payload["replay_index"],
    }
    if any(
        classification.get(key) != value
        for key, value in expected_identity.items()
    ) or classification.get("outcome_boundary") != (
        "FAILURE_CLASSIFICATION_ONLY_NO_APE_RPE_OR_COMMON_SUPPORT_METRIC_READ"
    ):
        raise G0GovernanceError(
            "terminal classification wrapper identity/boundary differs"
        )
    if any(core.get(key) != value for key, value in expected_identity.items()):
        raise G0GovernanceError("terminal binding classification identity mismatch")
    if core.get("classification_status") not in ("EVALUABLE", "HARD_FAILURE"):
        raise G0GovernanceError("terminal binding classification is not terminal-complete")
    records = payload.get("artifact_bindings")
    if not isinstance(records, Mapping):
        raise G0GovernanceError("terminal binding lacks artifact_bindings")
    required = {
        "terminal_audit",
        "failure_evidence",
        "classification",
        "config",
        "reference",
        "g0_evaluation_lock",
        "backend_execution_lock",
    }
    if set(records) != required | {"trajectory"}:
        raise G0GovernanceError("terminal binding artifact keys differ")
    classification_status = core.get("classification_status")
    for key, record in records.items():
        if record is None and key in ("trajectory", "config"):
            if classification_status == "HARD_FAILURE":
                continue
            raise G0GovernanceError(f"evaluable terminal {key} binding is null")
        if not isinstance(record, Mapping) or set(record) != {
            "path",
            "sha256",
            "size_bytes",
        } or not isinstance(record.get("path"), str) or not isinstance(
            record.get("sha256"), str
        ) or type(record.get("size_bytes")) is not int:
            raise G0GovernanceError(
                f"terminal {key} binding is not an exact file record"
            )
    if verify_files:
        for key, record in records.items():
            if record is None:
                continue
            assert isinstance(record, Mapping)
            if key in {
                "g0_evaluation_lock",
                "backend_execution_lock",
                "failure_evidence",
                "classification",
            }:
                continue
            validate_bound_input_record(root, record, label=f"terminal {key}")
    if classification_status == "EVALUABLE" and (
        records.get("trajectory") is None or records.get("config") is None
    ):
        raise G0GovernanceError("evaluable terminal binding lacks trajectory/config")
    g0_record = records.get("g0_evaluation_lock")
    execution_record = records.get("backend_execution_lock")
    if not isinstance(g0_record, Mapping) or not isinstance(execution_record, Mapping):
        raise G0GovernanceError("terminal binding lacks both lock artifacts")
    g0_lock = _direct_json_snapshot(
        root, g0_record, label="terminal G0 lock"
    )
    if (
        validate_lock_payload(g0_lock, root=root, verify_files=verify_files)
        != evaluation_lock_hash
    ):
        raise G0GovernanceError("terminal G0 lock hash mismatch")
    if verify_files:
        execution_lock = _direct_json_snapshot(
            root,
            execution_record,
            label="terminal backend execution lock",
        )
        if validate_self_hash(
            execution_lock, "execution_lock_hash", label="backend execution lock"
        ) != execution_lock_hash:
            raise G0GovernanceError("terminal backend execution lock hash mismatch")
        authority = execution_lock.get(EXECUTION_LOCK_BINDING_KEY)
        if not isinstance(authority, Mapping):
            raise G0GovernanceError("execution lock lacks G0 pre-replay authority")
        if (
            validate_execution_authority_binding(authority, root=root)
            != authority_hash
            or authority["evaluation_lock"]["evaluation_lock_hash"]
            != evaluation_lock_hash
        ):
            raise G0GovernanceError("terminal execution/G0 authority mismatch")

    frozen_inputs = g0_lock.get("frozen_inputs")
    code_bindings = g0_lock.get("code_bindings")
    if not isinstance(frozen_inputs, list) or not isinstance(code_bindings, list):
        raise G0GovernanceError("terminal G0 lock bindings are invalid")
    reference_bindings = [
        record
        for record in frozen_inputs
        if isinstance(record, Mapping) and record.get("role") == "reference_contracts"
    ]
    queue_bindings = [
        record
        for record in frozen_inputs
        if isinstance(record, Mapping) and record.get("role") == "backend_queue"
    ]
    allocation_bindings = [
        record
        for record in frozen_inputs
        if isinstance(record, Mapping) and record.get("role") == "backend_allocation"
    ]
    classifier_bindings = [
        record
        for record in code_bindings
        if isinstance(record, Mapping)
        and record.get("role") == "planner_classifier_reducer_primitives"
    ]
    evaluator_bindings = [
        record
        for record in code_bindings
        if isinstance(record, Mapping) and record.get("role") == "evaluator"
    ]
    if (
        len(reference_bindings) != 1
        or len(queue_bindings) != 1
        or len(allocation_bindings) != 1
        or len(classifier_bindings) != 1
        or len(evaluator_bindings) != 1
    ):
        raise G0GovernanceError(
            "terminal G0 lock lacks exact queue/allocation/reference/classifier/evaluator bindings"
        )
    queue_path = _validate_direct_record(
        root, queue_bindings[0], label="terminal frozen backend queue"
    )
    queue_bytes = _publisher_module().read_bytes_direct_rooted(
        root, queue_path, label="terminal frozen backend queue"
    )
    allocation_path = _validate_direct_record(
        root,
        allocation_bindings[0],
        label="terminal frozen backend allocation",
    )
    if verify_files:
        execution_path = workspace_path(
            root,
            execution_record.get("path"),
            label="terminal backend execution lock",
        )
        try:
            strict_execution_lock = _backend_runtime_module().validate_execution_lock(
                root,
                execution_path,
                queue_path=queue_path,
                allocation_path=allocation_path,
            )
        except Exception as error:
            raise G0GovernanceError(
                "terminal backend execution lock fails strict semantic validation"
            ) from error
        if (
            strict_execution_lock.get("execution_lock_hash")
            != execution_lock_hash
            or not _exact_json_equal(strict_execution_lock, execution_lock)
        ):
            raise G0GovernanceError(
                "terminal strict execution-lock snapshot differs"
            )
    try:
        _queue_fields, frozen_queue_rows = _backend_runtime_module().parse_csv_bytes(
            queue_bytes, label="terminal frozen backend queue"
        )
    except Exception as error:
        raise G0GovernanceError("terminal frozen backend queue is invalid") from error
    queue_matches = [
        row
        for row in frozen_queue_rows
        if int(row.get("queue_index", -1)) == payload["queue_index"]
    ]
    if len(queue_matches) != 1:
        raise G0GovernanceError("terminal lacks one frozen backend queue row")
    frozen_queue_row = queue_matches[0]
    for terminal_key, queue_key in (
        ("window_id", "window_id"),
        ("arm", "arm"),
        ("replay_index", "replay_index"),
        ("backend_algorithmic_slot", "algorithmic_slot"),
        ("source_run_id", "source_run_id"),
        ("source_provenance_kind", "source_provenance_kind"),
        ("source_provenance_hash", "source_provenance_hash"),
        ("evaluator_profile_id", "evaluator_profile_id"),
        ("evaluator_protocol_sha256", "evaluator_protocol_sha256"),
    ):
        observed = payload.get(terminal_key)
        expected: object = frozen_queue_row.get(queue_key)
        if terminal_key == "replay_index":
            expected = int(str(expected))
        if observed != expected:
            raise G0GovernanceError(
                f"terminal {terminal_key} differs from frozen backend queue"
            )
    terminal_provenance = payload.get("backend_terminal_provenance")
    if not isinstance(terminal_provenance, Mapping):
        raise G0GovernanceError("terminal lacks backend controller provenance")
    effective_queue_row = _validate_backend_terminal_provenance(
        terminal_provenance,
        root=root,
        frozen_queue_row=frozen_queue_row,
        terminal=payload,
        artifact_bindings=records,
        registry_prefix_record=g0_lock["mutable_registry_prefix"],
        verify_files=verify_files,
    )
    _validate_direct_record(
        root,
        classifier_bindings[0],
        label="terminal frozen classifier implementation",
    )
    _validate_direct_record(
        root,
        evaluator_bindings[0],
        label="terminal frozen evaluator implementation",
    )
    reference_payload = _direct_json_snapshot(
        root,
        reference_bindings[0],
        label="terminal frozen reference contracts",
    )
    if (
        validate_self_hash(
            reference_payload,
            "reference_contracts_hash",
            label="terminal frozen reference contracts",
        )
        != g0_lock["backend_bindings"]["reference_contracts_self_hash"]
    ):
        raise G0GovernanceError("terminal reference-contract lock binding differs")
    frozen_reference_records = [
        record
        for record in reference_payload.get("contracts", [])
        if isinstance(record, Mapping)
        and record.get("window_id") == payload["window_id"]
    ]
    if len(frozen_reference_records) != 1:
        raise G0GovernanceError(
            "terminal window lacks one frozen G0 reference record"
        )
    frozen_reference_record = frozen_reference_records[0]

    reference = payload.get("reference")
    if not isinstance(reference, Mapping):
        raise G0GovernanceError("terminal binding lacks reference contract")
    start_ns = reference.get("window_start_ns")
    end_ns = reference.get("window_end_ns")
    if (
        isinstance(start_ns, bool)
        or not isinstance(start_ns, int)
        or isinstance(end_ns, bool)
        or not isinstance(end_ns, int)
        or start_ns < 100_000_000 * 1_000_000_000
        or end_ns <= start_ns
    ):
        raise G0GovernanceError(
            "production terminal reference must bind absolute integer-ns endpoints"
        )
    reference_artifact = records.get("reference")
    if not isinstance(reference_artifact, Mapping) or reference_artifact.get(
        "path"
    ) != reference.get("path"):
        raise G0GovernanceError("terminal reference contract/artifact path mismatch")
    if (
        reference_contract_hash
        != frozen_reference_record.get("reference_contract_hash")
        or not isinstance(
            frozen_reference_record.get("reference_contract"), Mapping
        )
        or not _exact_json_equal(
            reference,
            frozen_reference_record["reference_contract"],
        )
        or not isinstance(
            frozen_reference_record.get("reference_artifact"), Mapping
        )
        or not _exact_json_equal(
            reference_artifact,
            frozen_reference_record["reference_artifact"],
        )
    ):
        raise G0GovernanceError(
            "terminal reference hash/contract/artifact differs from frozen G0 record"
        )

    failure_record = records.get("failure_evidence")
    classification_record = records.get("classification")
    if not isinstance(failure_record, Mapping) or not isinstance(
        classification_record, Mapping
    ):
        raise G0GovernanceError(
            "terminal failure/classification artifact binding is invalid"
        )
    failure_evidence = _bound_json_snapshot(
        root, failure_record, label="terminal failure evidence"
    )
    classification_artifact = _bound_json_snapshot(
        root, classification_record, label="terminal classification artifact"
    )
    if not _exact_json_equal(classification_artifact, classification):
        raise G0GovernanceError(
            "terminal embedded classification differs from bound artifact"
        )
    if failure_evidence.get("schema_version") != FAILURE_EVIDENCE_SCHEMA:
        raise G0GovernanceError("terminal failure evidence schema differs")
    _require_exact_keys(
        failure_evidence,
        FAILURE_EVIDENCE_KEYS,
        label="terminal failure evidence",
    )
    for field, expected_keys in (
        ("process", {"exit_code", "timed_out"}),
        (
            "trajectory",
            {
                "present",
                "row_count",
                "finite",
                "strictly_increasing",
                "first_timestamp_ns",
                "last_timestamp_ns",
                "timestamp_source_formats",
                "timestamp_conversion",
            },
        ),
        (
            "initialization",
            {
                "success",
                "first_output_delay_s",
                "first_output_delay_ns",
                "first_output_at_or_after_reference_start_ns",
                "reference_window_start_ns",
            },
        ),
        ("support", {"coverage_ratio", "overlap_ns", "reference_span_ns"}),
        ("queue", {"evidence_status", "drop_rate", "backlog_growth_s"}),
        (
            "timestamp_policy",
            {
                "raw_integer_ns_preserved",
                "ordering_before_conversion",
                "subtraction_before_conversion",
                "absolute_epoch_required",
                "relative_queue_window_as_epoch_forbidden",
            },
        ),
    ):
        nested = failure_evidence.get(field)
        if not isinstance(nested, Mapping):
            raise G0GovernanceError(
                f"terminal failure evidence {field} must be an object"
            )
        _require_exact_keys(
            nested,
            expected_keys,
            label=f"terminal failure evidence {field}",
        )
    validate_self_hash(
        failure_evidence,
        "failure_evidence_hash",
        label="terminal failure evidence",
    )
    expected_failure_identity = {
        "queue_index": payload["queue_index"],
        "run_id": payload["run_id"],
        "window_id": payload["window_id"],
        "arm": payload["arm"],
        "replay_index": payload["replay_index"],
        "backend_algorithmic_slot": payload["backend_algorithmic_slot"],
        "source_run_id": payload["source_run_id"],
        "source_provenance_kind": payload["source_provenance_kind"],
        "source_provenance_hash": payload["source_provenance_hash"],
        "algorithmic_slot": True,
    }
    failure_identity_mismatches = [
        key
        for key, expected in expected_failure_identity.items()
        if not _exact_json_equal(failure_evidence.get(key), expected)
    ]
    if failure_identity_mismatches:
        raise G0GovernanceError(
            "terminal failure evidence identity/source provenance differs: "
            f"{failure_identity_mismatches}"
        )
    expected_governance_authority = {
        "evaluation_lock_hash": evaluation_lock_hash,
        "backend_execution_lock_hash": execution_lock_hash,
        "g0_execution_authority_hash": authority_hash,
    }
    if (
        not isinstance(failure_evidence.get("governance_authority"), Mapping)
        or not _exact_json_equal(
            failure_evidence["governance_authority"],
            expected_governance_authority,
        )
        or not isinstance(failure_evidence.get("terminal_audit"), Mapping)
        or not _exact_json_equal(
            failure_evidence["terminal_audit"], records["terminal_audit"]
        )
        or not _exact_json_equal(
            failure_evidence.get("trajectory_artifact"), records.get("trajectory")
        )
        or not _exact_json_equal(
            failure_evidence.get("terminal_provenance"), terminal_provenance
        )
    ):
        raise G0GovernanceError(
            "terminal failure evidence authority/audit/trajectory binding differs"
        )
    if verify_files:
        terminal_audit_record = records["terminal_audit"]
        assert isinstance(terminal_audit_record, Mapping)
        terminal_audit = _bound_json_snapshot(
            root,
            terminal_audit_record,
            label="terminal backend audit for failure-evidence rebuild",
        )
        terminal_audit_path = workspace_path(
            root,
            terminal_audit_record.get("path"),
            label="terminal backend audit for failure-evidence rebuild",
        )
        _validate_terminal_audit_output_authority(
            terminal_audit,
            root=root,
            effective_queue_row=effective_queue_row,
        )
        try:
            rebuilt_failure_evidence = _failure_collector_module().build_failure_evidence(
                effective_queue_row,
                terminal_audit,
                root=root,
                audit_path=terminal_audit_path,
                audit_record=terminal_audit_record,
                reference_record=frozen_reference_record,
                infrastructure_codes=(),
                algorithmic_slot=True,
                governance_authority=expected_governance_authority,
                terminal_provenance=terminal_provenance,
            )
        except Exception as error:
            raise G0GovernanceError(
                "terminal failure evidence cannot be deterministically rebuilt"
            ) from error
        if not _exact_json_equal(
            rebuilt_failure_evidence, failure_evidence
        ):
            raise G0GovernanceError(
                "terminal failure evidence differs from deterministic audit/artifact rebuild"
            )
    if (
        classification.get("status")
        != "PASS_CLASSIFIED_FROZEN_FAILURE_TAXONOMY"
        or not isinstance(classification.get("failure_evidence"), Mapping)
        or not _exact_json_equal(
            classification["failure_evidence"], failure_record
        )
        or not isinstance(
            classification.get("classifier_implementation"), Mapping
        )
        or not _exact_json_equal(
            classification["classifier_implementation"],
            classifier_bindings[0],
        )
    ):
        raise G0GovernanceError(
            "terminal classification provenance differs from frozen inputs"
        )
    if failure_evidence.get("reference_contract_hash") != reference_contract_hash:
        raise G0GovernanceError(
            "terminal failure evidence reference-contract hash differs"
        )
    classifier_input = {
        key: failure_evidence.get(key) for key in CLASSIFIER_INPUT_FIELDS
    }
    try:
        recomputed_classification = evaluation.classify_replay_evidence(
            classifier_input
        )
    except evaluation.EvaluationContractError as error:
        raise G0GovernanceError(
            f"terminal failure evidence cannot be classified: {error}"
        ) from error
    if not _exact_json_equal(core, recomputed_classification):
        raise G0GovernanceError(
            "terminal classification differs from frozen-classifier recomputation"
        )
    # Reuse the frozen core validator through a minimal terminal replay.  This
    # catches kind/topic/rate/window/gap mistakes without opening outcomes.
    synthetic = {
        "run_id": payload["run_id"],
        "window_id": payload["window_id"],
        "arm": payload["arm"],
        "replay_index": payload["replay_index"],
        "algorithmic_slot": True,
        "terminal": True,
        "trajectory_path": (
            records["trajectory"]["path"] if isinstance(records.get("trajectory"), Mapping) else None
        ),
        "config_path": (
            records["config"]["path"]
            if isinstance(records.get("config"), Mapping)
            else None
        ),
        "failure_evidence_path": records["failure_evidence"]["path"],
        "arm_time_offset_s": payload.get("arm_time_offset_s", 0.0),
        "reference": reference,
        "evaluator_profile_id": payload.get("evaluator_profile_id"),
        "evaluator_protocol_sha256": payload.get("evaluator_protocol_sha256"),
        "evaluator_script_sha256": payload.get("evaluator_script_sha256"),
        "classification": core,
    }
    # ``build_evaluation_plan`` performs the normalization, but doing so for a
    # lone arm is intentionally impossible.  Validate the pieces that remain
    # public and deterministic here.
    require_hash(synthetic["evaluator_protocol_sha256"], "evaluator protocol")
    require_hash(synthetic["evaluator_script_sha256"], "evaluator script")
    if not isinstance(synthetic["evaluator_profile_id"], str) or not synthetic[
        "evaluator_profile_id"
    ]:
        raise G0GovernanceError("terminal binding evaluator profile is empty")
    evaluator_policy = g0_lock.get("evaluation_template", {}).get("evaluator")
    if (
        not isinstance(evaluator_policy, Mapping)
        or evaluator_policy.get("profile_rule")
        != "QUEUE_EVALUATOR_PROFILE_ID_EXACT"
        or payload.get("evaluator_protocol_sha256")
        != evaluator_policy.get("protocol_sha256")
        or payload.get("evaluator_script_sha256")
        != evaluator_bindings[0].get("sha256")
    ):
        raise G0GovernanceError(
            "terminal evaluator identity differs from frozen G0 implementation"
        )
    return binding_hash


def validate_plan_payload(
    payload: Mapping[str, Any],
    *,
    lock: Mapping[str, Any],
    root: Path,
    _context_out: dict[str, Any] | None = None,
) -> str:
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "status",
            "evaluation_lock_hash",
            "plan_basis",
            "plan_basis_hash",
            "jobs",
            "counts",
            "outcome_boundary",
            "plan_hash",
        },
        label="G0 plan",
    )
    if payload.get("schema_version") != PLAN_SCHEMA or payload.get("status") != PLAN_STATUS:
        raise G0GovernanceError("unexpected G0 plan schema or status")
    if payload.get("outcome_boundary") != OUTCOME_BOUNDARY:
        raise G0GovernanceError("G0 plan outcome boundary differs")
    plan_hash = validate_self_hash(payload, "plan_hash", label="G0 plan")
    lock_hash = validate_self_hash(lock, "evaluation_lock_hash", label="G0 lock")
    if payload.get("evaluation_lock_hash") != lock_hash:
        raise G0GovernanceError("G0 plan lock binding mismatch")
    basis = payload.get("plan_basis")
    if not isinstance(basis, Mapping):
        raise G0GovernanceError("G0 plan lacks plan_basis")
    _require_exact_keys(
        basis,
        {
            "evaluation_lock_hash",
            "evaluation_template_hash",
            "terminal_index_hash",
            "terminal_index_file",
            "terminal_binding_hashes",
            "result_root_relative",
            "core_job_hashes",
            "core_jobs_hash",
            "backend_execution_lock_hash",
            "g0_execution_authority_hash",
            "backend_execution_lock",
        },
        label="G0 plan basis",
    )
    basis_hash = require_hash(payload.get("plan_basis_hash"), "plan_basis_hash")
    if canonical_json_hash(basis) != basis_hash:
        raise G0GovernanceError("G0 plan basis hash mismatch")
    if (
        basis.get("evaluation_lock_hash") != lock_hash
        or basis.get("evaluation_template_hash")
        != lock.get("evaluation_template_hash")
    ):
        raise G0GovernanceError("G0 plan basis lock/template authority differs")
    require_hash(
        basis.get("backend_execution_lock_hash"),
        "G0 plan backend execution lock hash",
    )
    require_hash(
        basis.get("g0_execution_authority_hash"),
        "G0 plan execution authority hash",
    )
    for key in (
        "evaluation_lock_hash",
        "evaluation_template_hash",
        "terminal_index_hash",
        "core_jobs_hash",
    ):
        require_hash(basis.get(key), f"G0 plan basis {key}")
    terminal_hashes = basis.get("terminal_binding_hashes")
    if not isinstance(terminal_hashes, list) or any(
        not isinstance(value, str) or HASH_RE.fullmatch(value) is None
        for value in terminal_hashes
    ) or len(set(terminal_hashes)) != len(terminal_hashes):
        raise G0GovernanceError("G0 plan terminal-binding hashes are invalid")
    terminal_index_file = basis.get("terminal_index_file")
    if (
        not isinstance(terminal_index_file, Mapping)
        or set(terminal_index_file) != {"path", "sha256", "size_bytes"}
    ):
        raise G0GovernanceError("G0 plan terminal-index file record differs")
    terminal_index = _direct_json_snapshot(
        root, terminal_index_file, label="G0 terminal-binding index"
    )
    if set(terminal_index) != {
        "schema_version",
        "status",
        "bindings",
        "count",
        "outcome_boundary",
        "terminal_index_hash",
    }:
        raise G0GovernanceError("G0 terminal-index keys differ")
    if (
        terminal_index.get("schema_version")
        != "isj-p07-g0-terminal-binding-index-v1"
        or terminal_index.get("status")
        != "COMPLETE_EXPLICIT_TERMINAL_BINDING_INDEX"
        or terminal_index.get("outcome_boundary") != OUTCOME_BOUNDARY
        or validate_self_hash(
            terminal_index, "terminal_index_hash", label="G0 terminal index"
        )
        != basis.get("terminal_index_hash")
    ):
        raise G0GovernanceError("G0 terminal-index authority differs")
    terminal_records = terminal_index.get("bindings")
    if (
        not isinstance(terminal_records, list)
        or terminal_index.get("count") != len(terminal_records)
    ):
        raise G0GovernanceError("G0 terminal-index count differs")
    index_hashes: list[str] = []
    index_queue_indices: set[int] = set()
    indexed_terminal_bindings: list[dict[str, Any]] = []
    terminal_index_record_keys = {
        "path",
        "sha256",
        "size_bytes",
        "terminal_binding_hash",
        "queue_index",
        "run_id",
        "window_id",
        "arm",
        "replay_index",
        "backend_algorithmic_slot",
        "source_run_id",
        "source_provenance_kind",
        "source_provenance_hash",
        "evaluation_lock_hash",
        "backend_execution_lock_hash",
        "g0_execution_authority_hash",
    }
    for record in terminal_records:
        if (
            not isinstance(record, Mapping)
            or set(record) != terminal_index_record_keys
        ):
            raise G0GovernanceError("G0 terminal-index record is invalid")
        binding_hash = require_hash(
            record.get("terminal_binding_hash"), "G0 terminal binding hash"
        )
        queue_index = record.get("queue_index")
        if type(queue_index) is not int or queue_index in index_queue_indices:
            raise G0GovernanceError("G0 terminal-index queue index differs")
        index_queue_indices.add(queue_index)
        index_hashes.append(binding_hash)
        binding = _direct_json_snapshot(
            root, record, label=f"G0 indexed terminal binding {queue_index}"
        )
        if validate_terminal_binding(binding, root=root, verify_files=True) != binding_hash:
            raise G0GovernanceError(
                "G0 indexed terminal binding self-hash differs"
            )
        expected_terminal_record = {
            "queue_index": binding["queue_index"],
            "run_id": binding["run_id"],
            "window_id": binding["window_id"],
            "arm": binding["arm"],
            "replay_index": binding["replay_index"],
            "backend_algorithmic_slot": binding["backend_algorithmic_slot"],
            "source_run_id": binding["source_run_id"],
            "source_provenance_kind": binding["source_provenance_kind"],
            "source_provenance_hash": binding["source_provenance_hash"],
            "evaluation_lock_hash": binding["evaluation_lock_hash"],
            "backend_execution_lock_hash": binding[
                "backend_execution_lock_hash"
            ],
            "g0_execution_authority_hash": binding[
                "g0_execution_authority_hash"
            ],
            "terminal_binding_hash": binding_hash,
        }
        exact_json_identity(
            record, expected_terminal_record, label="G0 terminal-index binding"
        )
        provenance = binding.get("backend_terminal_provenance")
        effective = (
            provenance.get("effective_queue_row")
            if isinstance(provenance, Mapping)
            else None
        )
        expected_terminal_path = (
            f"{effective.get('expected_attempt_dir')}/g0_terminal_binding_v1.json"
            if isinstance(effective, Mapping)
            else ""
        )
        if record.get("path") != expected_terminal_path:
            raise G0GovernanceError(
                "G0 terminal-index path is not the canonical effective-attempt binding"
            )
        indexed_terminal_bindings.append(binding)
    if index_hashes != terminal_hashes or len(set(index_hashes)) != len(index_hashes):
        raise G0GovernanceError(
            "G0 plan terminal hashes differ from the direct terminal index"
        )
    core_job_hashes = basis.get("core_job_hashes")
    if (
        not isinstance(core_job_hashes, list)
        or any(
            not isinstance(value, str) or HASH_RE.fullmatch(value) is None
            for value in core_job_hashes
        )
        or len(set(core_job_hashes)) != len(core_job_hashes)
        or canonical_json_hash({"core_job_hashes": core_job_hashes})
        != basis.get("core_jobs_hash")
    ):
        raise G0GovernanceError("G0 plan core-job hash derivation differs")
    result_root = basis.get("result_root_relative")
    if not isinstance(result_root, str):
        raise G0GovernanceError("G0 plan result root is invalid")
    result_root_path = PurePosixPath(result_root)
    if (
        not result_root
        or result_root_path.is_absolute()
        or ".." in result_root_path.parts
        or "." in result_root_path.parts
    ):
        raise G0GovernanceError("G0 plan result root is unsafe")
    d_applicability = {
        window_id: any(
            binding["window_id"] == window_id and binding["arm"] == evaluation.ARM_D
            for binding in indexed_terminal_bindings
        )
        for window_id in sorted(
            {str(binding["window_id"]) for binding in indexed_terminal_bindings}
        )
    }
    expected_core_jobs = evaluation.build_evaluation_plan(
        [_terminal_binding_to_core(binding) for binding in indexed_terminal_bindings],
        d_applicability=d_applicability,
        output_root=result_root,
    )
    expected_core_hashes = [canonical_json_hash(job) for job in expected_core_jobs]
    if (
        expected_core_hashes != core_job_hashes
        or canonical_json_hash({"core_job_hashes": expected_core_hashes})
        != basis.get("core_jobs_hash")
    ):
        raise G0GovernanceError(
            "G0 plan core jobs differ from deterministic terminal-index rebuild"
        )
    execution_record = basis.get("backend_execution_lock")
    if not isinstance(execution_record, Mapping) or set(execution_record) != {
        "path",
        "sha256",
        "size_bytes",
    }:
        raise G0GovernanceError("G0 plan lacks backend execution-lock artifact")
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise G0GovernanceError("G0 plan jobs must be a list")
    expected = int(lock["evaluation_template"]["counts"]["g0_evaluation_jobs"])
    if len(jobs) != expected:
        raise G0GovernanceError("G0 plan job count differs from frozen template")
    ids: set[str] = set()
    hashes: set[str] = set()
    paths: set[str] = set()
    for record in jobs:
        if not isinstance(record, Mapping):
            raise G0GovernanceError("G0 plan job membership record is invalid")
        _require_exact_keys(
            record,
            {
                "job_id",
                "job_hash",
                "core_job_hash",
                "path",
                "window_id",
                "replay_index",
                "route",
                "contrast_name",
                "output_dir_absolute",
            },
            label="G0 plan job membership",
        )
        job_id = record.get("job_id")
        if not isinstance(job_id, str) or not SAFE_ID_RE.fullmatch(job_id):
            raise G0GovernanceError("G0 plan job_id is unsafe")
        job_hash = require_hash(record.get("job_hash"), "plan job hash")
        require_hash(record.get("core_job_hash"), "plan core-job hash")
        path = record.get("path")
        if not isinstance(path, str) or not path:
            raise G0GovernanceError("G0 plan job path is empty")
        if job_id in ids or job_hash in hashes or path in paths:
            raise G0GovernanceError("duplicate G0 plan job identity/hash/path")
        ids.add(job_id)
        hashes.add(job_hash)
        paths.add(path)
    membership_core_hashes = [str(record["core_job_hash"]) for record in jobs]
    if membership_core_hashes != core_job_hashes:
        raise G0GovernanceError("G0 plan membership/core-job hashes differ")
    if len(expected_core_jobs) != len(jobs):
        raise G0GovernanceError("G0 deterministic core-job count differs")
    membership_parents: set[str] = set()
    for record, core_job, core_hash in zip(
        jobs, expected_core_jobs, expected_core_hashes
    ):
        expected_output = workspace_path(
            root, core_job["output_dir"], label="deterministic G0 output"
        )
        exact_json_identity(
            record,
            {
                "job_id": core_job["job_id"],
                "core_job_hash": core_hash,
                "window_id": core_job["window_id"],
                "replay_index": core_job["replay_index"],
                "route": core_job["route"],
                "contrast_name": core_job["contrast_name"],
                "output_dir_absolute": os.fspath(expected_output),
            },
            label="deterministic G0 plan membership",
        )
        membership_path = PurePosixPath(str(record["path"]))
        expected_filename = str(core_job["job_id"]).replace(":", "__") + ".json"
        if membership_path.name != expected_filename or not membership_path.parent.parts:
            raise G0GovernanceError("G0 plan job path is not canonical")
        membership_parents.add(membership_path.parent.as_posix())
    if len(membership_parents) != 1:
        raise G0GovernanceError("G0 plan jobs do not share one canonical bundle root")
    counts = payload.get("counts")
    if not isinstance(counts, Mapping) or counts.get("jobs") != len(jobs):
        raise G0GovernanceError("G0 plan counts mismatch")
    _require_exact_keys(
        counts,
        {"jobs", "routes", "terminal_bindings"},
        label="G0 plan counts",
    )
    routes = counts.get("routes")
    derived_routes: dict[str, int] = {}
    for record in jobs:
        contrast = record.get("contrast_name")
        route = record.get("route")
        if not isinstance(contrast, str) or not contrast or not isinstance(route, str) or not route:
            raise G0GovernanceError("G0 plan membership route/contrast is invalid")
        derived_routes[contrast] = derived_routes.get(contrast, 0) + 1
    if (
        type(counts.get("jobs")) is not int
        or type(counts.get("terminal_bindings")) is not int
        or not isinstance(routes, Mapping)
        or any(type(value) is not int or value < 0 for value in routes.values())
        or sum(routes.values()) != len(jobs)
        or dict(routes) != dict(sorted(derived_routes.items()))
        or counts["terminal_bindings"] != len(terminal_hashes)
    ):
        raise G0GovernanceError("G0 plan count details differ")
    if _context_out is not None:
        _context_out.clear()
        _context_out.update(
            {
                "_validation_token": _VALIDATED_PLAN_CONTEXT_TOKEN,
                "root_absolute": os.path.abspath(os.fspath(root)),
                "plan_hash": plan_hash,
                "evaluation_lock_hash": lock_hash,
                "terminal_index_hash": basis["terminal_index_hash"],
                "backend_execution_lock_hash": basis[
                    "backend_execution_lock_hash"
                ],
                "g0_execution_authority_hash": basis[
                    "g0_execution_authority_hash"
                ],
                "backend_execution_lock": dict(basis["backend_execution_lock"]),
                "terminal_by_queue_index": {
                    int(binding["queue_index"]): binding
                    for binding in indexed_terminal_bindings
                },
                "expected_core_jobs_by_id": {
                    str(job["job_id"]): job for job in expected_core_jobs
                },
            }
        )
    return plan_hash


def validate_job_payload(
    payload: Mapping[str, Any],
    *,
    plan: Mapping[str, Any],
    lock: Mapping[str, Any],
    root: Path,
    verify_inputs: bool = True,
    _validated_plan_context: Mapping[str, Any] | None = None,
) -> str:
    if _validated_plan_context is None:
        validate_lock_payload(lock, root=root, verify_files=False)
        plan_context: dict[str, Any] = {}
        plan_hash = validate_plan_payload(
            plan, lock=lock, root=root, _context_out=plan_context
        )
    else:
        plan_context = dict(_validated_plan_context)
        plan_hash = require_hash(plan.get("plan_hash"), "G0 plan hash")
        lock_hash = require_hash(
            lock.get("evaluation_lock_hash"), "G0 evaluation lock hash"
        )
        if (
            plan_context.get("_validation_token")
            is not _VALIDATED_PLAN_CONTEXT_TOKEN
            or plan_context.get("root_absolute")
            != os.path.abspath(os.fspath(root))
            or plan_context.get("plan_hash") != plan_hash
            or plan_context.get("evaluation_lock_hash")
            != lock_hash
            or canonical_json_hash(plan, "plan_hash") != plan_hash
            or canonical_json_hash(lock, "evaluation_lock_hash") != lock_hash
            or plan_context.get("terminal_index_hash")
            != plan.get("plan_basis", {}).get("terminal_index_hash")
            or plan_context.get("backend_execution_lock_hash")
            != plan.get("plan_basis", {}).get("backend_execution_lock_hash")
            or plan_context.get("g0_execution_authority_hash")
            != plan.get("plan_basis", {}).get("g0_execution_authority_hash")
            or not _exact_json_equal(
                plan_context.get("backend_execution_lock"),
                plan.get("plan_basis", {}).get("backend_execution_lock"),
            )
        ):
            raise G0GovernanceError("validated G0 plan context differs")
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "status",
            "job_id",
            "plan_basis_hash",
            "evaluation_lock_hash",
            "backend_execution_lock_hash",
            "g0_execution_authority_hash",
            "backend_execution_lock",
            "evaluation_job",
            "input_bindings",
            "reference_binding",
            "output_dir_absolute",
            "execution_policy",
            "outcome_boundary",
            "job_hash",
        },
        label="G0 job",
    )
    if payload.get("schema_version") != JOB_SCHEMA or payload.get("status") != JOB_STATUS:
        raise G0GovernanceError("unexpected materialized G0 job schema/status")
    if payload.get("outcome_boundary") != OUTCOME_BOUNDARY:
        raise G0GovernanceError("G0 job outcome boundary differs")
    job_hash = validate_self_hash(payload, "job_hash", label="G0 job")
    if payload.get("plan_basis_hash") != plan.get("plan_basis_hash"):
        raise G0GovernanceError("G0 job plan-basis binding mismatch")
    if payload.get("evaluation_lock_hash") != lock.get("evaluation_lock_hash"):
        raise G0GovernanceError("G0 job lock binding mismatch")
    execution_lock_hash = require_hash(
        payload.get("backend_execution_lock_hash"), "G0 job execution lock hash"
    )
    authority_hash = require_hash(
        payload.get("g0_execution_authority_hash"), "G0 job execution authority hash"
    )
    if (
        payload.get("backend_execution_lock_hash")
        != plan["plan_basis"].get("backend_execution_lock_hash")
        or payload.get("g0_execution_authority_hash")
        != plan["plan_basis"].get("g0_execution_authority_hash")
    ):
        raise G0GovernanceError("G0 job execution authority differs from plan")
    execution_record = payload.get("backend_execution_lock")
    plan_execution_record = plan["plan_basis"].get("backend_execution_lock")
    if (
        not isinstance(execution_record, Mapping)
        or set(execution_record) != {"path", "sha256", "size_bytes"}
        or not isinstance(plan_execution_record, Mapping)
        or not _exact_json_equal(execution_record, plan_execution_record)
    ):
        raise G0GovernanceError("G0 job execution-lock artifact differs from plan")
    if verify_inputs and _validated_plan_context is None:
        execution_path = _validate_direct_record(
            root, execution_record, label="G0 job backend execution lock"
        )
        execution_lock = _read_direct_json(
            root, execution_path, label="G0 job backend execution lock"
        )
        if validate_self_hash(
            execution_lock, "execution_lock_hash", label="backend execution lock"
        ) != execution_lock_hash:
            raise G0GovernanceError("G0 job backend execution lock hash mismatch")
        authority = execution_lock.get(EXECUTION_LOCK_BINDING_KEY)
        if not isinstance(authority, Mapping) or validate_execution_authority_binding(
            authority, root=root
        ) != authority_hash:
            raise G0GovernanceError("G0 job execution authority mismatch")
    elif _validated_plan_context is not None and (
        plan_context.get("backend_execution_lock_hash") != execution_lock_hash
        or plan_context.get("g0_execution_authority_hash") != authority_hash
        or not _exact_json_equal(
            plan_context.get("backend_execution_lock"), execution_record
        )
    ):
        raise G0GovernanceError(
            "G0 job execution authority differs from validated plan context"
        )
    core_job = payload.get("evaluation_job")
    if not isinstance(core_job, Mapping):
        raise G0GovernanceError("materialized job lacks evaluation_job")
    evaluation.validate_evaluation_job(core_job)
    core_keys = {
        "schema_version",
        "job_id",
        "window_id",
        "replay_index",
        "route",
        "metric_role",
        "contrast_name",
        "arms",
        "evaluation_disposition",
        "reference",
        "evaluator_profile_id",
        "evaluator_protocol_sha256",
        "evaluator_script_sha256",
        "output_dir",
    }
    if core_job.get("route") == evaluation.ROUTE_PAIRWISE_COMMON_SUPPORT:
        core_keys |= {"proposed_arm", "comparator_arm"}
    _require_exact_keys(core_job, core_keys, label="G0 scientific evaluation job")
    core_arms = core_job.get("arms")
    if not isinstance(core_arms, Mapping):
        raise G0GovernanceError("G0 scientific evaluation arms differ")
    for arm, raw in core_arms.items():
        if not isinstance(raw, Mapping):
            raise G0GovernanceError(f"G0 scientific arm {arm} is invalid")
        _require_exact_keys(
            raw,
            {
                "run_id",
                "arm",
                "replay_index",
                "trajectory_path",
                "config_path",
                "failure_evidence_path",
                "arm_time_offset_s",
                "classification",
            },
            label=f"G0 scientific arm {arm}",
        )
    if payload.get("job_id") != core_job.get("job_id"):
        raise G0GovernanceError("materialized/core job_id mismatch")
    membership = [
        item
        for item in plan["jobs"]
        if isinstance(item, Mapping) and item.get("job_id") == payload.get("job_id")
    ]
    if len(membership) != 1 or membership[0].get("job_hash") != job_hash:
        raise G0GovernanceError("G0 job is not an exact member of the validated plan")
    expected_membership = {
        "job_id": core_job["job_id"],
        "job_hash": job_hash,
        "core_job_hash": canonical_json_hash(core_job),
        "window_id": core_job["window_id"],
        "replay_index": core_job["replay_index"],
        "route": core_job["route"],
        "contrast_name": core_job["contrast_name"],
        "output_dir_absolute": payload.get("output_dir_absolute"),
    }
    exact_json_identity(
        membership[0], expected_membership, label="G0 plan job membership"
    )
    output = workspace_path(
        root,
        payload.get("output_dir_absolute"),
        label="G0 job output",
        require_absolute=True,
    )
    expected_output = workspace_path(
        root, core_job.get("output_dir"), label="core relative output"
    )
    if output != expected_output:
        raise G0GovernanceError("absolute output differs from frozen relative output")
    bindings = payload.get("input_bindings")
    if not isinstance(bindings, Mapping) or set(bindings) != set(core_job["arms"]):
        raise G0GovernanceError("G0 job arm input bindings differ from core job")
    terminal_by_queue = plan_context.get("terminal_by_queue_index")
    expected_core_by_id = plan_context.get("expected_core_jobs_by_id")
    if not isinstance(terminal_by_queue, Mapping) or not isinstance(
        expected_core_by_id, Mapping
    ):
        raise G0GovernanceError("validated G0 plan context is incomplete")
    expected_core = expected_core_by_id.get(str(payload.get("job_id")))
    if not isinstance(expected_core, Mapping) or not _exact_json_equal(
        expected_core, core_job
    ):
        raise G0GovernanceError(
            "G0 job scientific core differs from deterministic plan rebuild"
        )
    for arm, record in bindings.items():
        if not isinstance(record, Mapping):
            raise G0GovernanceError(f"G0 input binding for {arm} is invalid")
        _require_exact_keys(
            record,
            {"run_id", "arm", "replay_index", "terminal_binding"},
            label=f"G0 input binding {arm}",
        )
        raw = core_job["arms"][arm]
        if (
            record.get("run_id") != raw.get("run_id")
            or record.get("arm") != arm
            or record.get("replay_index") != core_job.get("replay_index")
        ):
            raise G0GovernanceError("G0 input run/replay/arm identity mismatch")
        terminal = record.get("terminal_binding")
        if not isinstance(terminal, Mapping):
            raise G0GovernanceError("G0 input lacks terminal binding")
        indexed_terminal = terminal_by_queue.get(terminal.get("queue_index"))
        if not isinstance(indexed_terminal, Mapping) or not _exact_json_equal(
            indexed_terminal, terminal
        ):
            raise G0GovernanceError(
                "G0 job embedded terminal differs from terminal-index bytes"
            )
        if (
            terminal.get("run_id") != raw.get("run_id")
            or terminal.get("window_id") != core_job.get("window_id")
            or terminal.get("arm") != arm
            or terminal.get("replay_index") != core_job.get("replay_index")
        ):
            raise G0GovernanceError("terminal/core G0 identity mismatch")
        if (
            terminal.get("evaluation_lock_hash") != lock.get("evaluation_lock_hash")
            or terminal.get("backend_execution_lock_hash") != execution_lock_hash
            or terminal.get("g0_execution_authority_hash") != authority_hash
        ):
            raise G0GovernanceError("terminal/job dual-lock authority mismatch")
        terminal_artifacts = terminal.get("artifact_bindings")
        terminal_wrapper = terminal.get("classification")
        if not isinstance(terminal_artifacts, Mapping) or not isinstance(
            terminal_wrapper, Mapping
        ) or not isinstance(terminal_wrapper.get("classification"), Mapping):
            raise G0GovernanceError("terminal/job scientific provenance is invalid")
        expected_raw = {
            "run_id": terminal["run_id"],
            "arm": terminal["arm"],
            "replay_index": terminal["replay_index"],
            "trajectory_path": (
                terminal_artifacts["trajectory"]["path"]
                if isinstance(terminal_artifacts.get("trajectory"), Mapping)
                else None
            ),
            "config_path": (
                terminal_artifacts["config"]["path"]
                if isinstance(terminal_artifacts.get("config"), Mapping)
                else None
            ),
            "failure_evidence_path": terminal_artifacts["failure_evidence"]["path"],
            "arm_time_offset_s": terminal["arm_time_offset_s"],
            "classification": terminal_wrapper["classification"],
        }
        if not _exact_json_equal(raw, expected_raw):
            raise G0GovernanceError(
                "G0 scientific arm differs from exact terminal provenance"
            )
        for scientific_key in (
            "reference",
            "evaluator_profile_id",
            "evaluator_protocol_sha256",
            "evaluator_script_sha256",
        ):
            expected_value = (
                terminal["reference"]
                if scientific_key == "reference"
                else terminal[scientific_key]
            )
            observed_value = core_job.get(scientific_key)
            if isinstance(expected_value, Mapping):
                if not isinstance(observed_value, Mapping) or not _exact_json_equal(
                    observed_value, expected_value
                ):
                    raise G0GovernanceError(
                        f"G0 job {scientific_key} differs from terminal"
                    )
            elif observed_value != expected_value:
                raise G0GovernanceError(
                    f"G0 job {scientific_key} differs from terminal"
                )
    reference = payload.get("reference_binding")
    if not isinstance(reference, Mapping):
        raise G0GovernanceError("G0 job lacks reference binding")
    _require_exact_keys(
        reference,
        {"contract", "artifact"},
        label="G0 job reference binding",
    )
    reference_contract = reference.get("contract")
    core_reference = core_job.get("reference")
    if (
        not isinstance(reference_contract, Mapping)
        or not isinstance(core_reference, Mapping)
        or not _exact_json_equal(reference_contract, core_reference)
    ):
        raise G0GovernanceError("G0 job reference contract mismatch")
    artifact = reference.get("artifact")
    if not isinstance(artifact, Mapping) or set(artifact) != {
        "path",
        "sha256",
        "size_bytes",
    }:
        raise G0GovernanceError("G0 job reference artifact binding is invalid")
    first_terminal = next(iter(bindings.values()))["terminal_binding"]
    first_terminal_artifact = first_terminal["artifact_bindings"]["reference"]
    if not _exact_json_equal(artifact, first_terminal_artifact):
        raise G0GovernanceError(
            "G0 job reference artifact differs from terminal provenance"
        )
    policy = payload.get("execution_policy")
    expected_policy = {
        "absolute_workspace_output_required": True,
        "destination_must_not_exist": True,
        "all_input_sha256_revalidated_before_evaluator": True,
        "summary_job_run_replay_arm_identity_required": True,
        "receipt_and_output_manifest_required": True,
    }
    if not isinstance(policy, Mapping) or not _exact_json_equal(
        policy, expected_policy
    ):
        raise G0GovernanceError("G0 job execution policy differs")
    if verify_inputs and _validated_plan_context is None:
        validate_bound_input_record(root, artifact, label="G0 reference")
    # The plan self-hash is intentionally not embedded into job bytes (which
    # would create a plan<->job hash cycle).  Loading and validating the plan,
    # then checking exact membership above, is the required binding.
    _ = plan_hash
    return job_hash


def validate_bound_summary(
    payload: Mapping[str, Any],
    *,
    job: Mapping[str, Any],
    plan: Mapping[str, Any],
    lock: Mapping[str, Any],
    root: Path,
    verify_raw_summary: bool = True,
    _validated_plan_context: Mapping[str, Any] | None = None,
) -> str:
    """Validate the identity wrapper around one evaluator (or skip) result."""

    job_hash = validate_job_payload(
        job,
        plan=plan,
        lock=lock,
        root=root,
        verify_inputs=False,
        _validated_plan_context=_validated_plan_context,
    )
    if _validated_plan_context is None:
        plan_hash = validate_plan_payload(plan, lock=lock, root=root)
    else:
        plan_hash = require_hash(
            _validated_plan_context.get("plan_hash"), "validated G0 plan hash"
        )
    if _validated_plan_context is None:
        lock_hash = validate_lock_payload(lock, root=root, verify_files=False)
    else:
        lock_hash = require_hash(
            lock.get("evaluation_lock_hash"), "validated G0 lock hash"
        )
        if (
            _validated_plan_context.get("_validation_token")
            is not _VALIDATED_PLAN_CONTEXT_TOKEN
            or _validated_plan_context.get("evaluation_lock_hash") != lock_hash
            or canonical_json_hash(lock, "evaluation_lock_hash") != lock_hash
        ):
            raise G0GovernanceError("validated G0 lock context differs")
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "status",
            "job_id",
            "job_hash",
            "plan_hash",
            "evaluation_lock_hash",
            "backend_execution_lock_hash",
            "g0_execution_authority_hash",
            "window_id",
            "replay_index",
            "route",
            "contrast_name",
            "evaluation_disposition",
            "arm_identities",
            "g0_summary",
            "raw_summary_artifact",
            "evaluator_process",
            "outcome_boundary",
            "bound_summary_hash",
        },
        label="bound summary",
    )
    if payload.get("schema_version") != BOUND_SUMMARY_SCHEMA:
        raise G0GovernanceError("unexpected bound summary schema")
    digest = validate_self_hash(payload, "bound_summary_hash", label="bound summary")
    core = job["evaluation_job"]
    expected = {
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
    }
    exact_json_identity(payload, expected, label="bound summary")
    identities = payload.get("arm_identities")
    if not isinstance(identities, Mapping) or set(identities) != set(core["arms"]):
        raise G0GovernanceError("bound summary arm identities differ from job")
    for arm, raw in core["arms"].items():
        identity = identities.get(arm)
        terminal = job["input_bindings"][arm]["terminal_binding"]
        if not isinstance(identity, Mapping):
            raise G0GovernanceError("bound summary arm identity is invalid")
        _require_exact_keys(
            identity,
            {"arm", "run_id", "replay_index", "terminal_binding_hash"},
            label=f"bound summary arm {arm}",
        )
        exact_json_identity(
            identity,
            {
                "arm": arm,
                "run_id": raw["run_id"],
                "replay_index": core["replay_index"],
                "terminal_binding_hash": terminal["terminal_binding_hash"],
            },
            label="bound summary arm",
        )
    summary = payload.get("g0_summary")
    summary_artifact = payload.get("raw_summary_artifact")
    if core["evaluation_disposition"] == "SKIP_NUMERIC_HARD_FAILURE":
        if payload.get("status") != "COMPLETED_FAILURE_ONLY_NO_NUMERIC_EVALUATION":
            raise G0GovernanceError("hard-failure bound summary status mismatch")
        if summary is not None or summary_artifact is not None:
            raise G0GovernanceError("hard-failure bound summary attached numeric output")
        evaluation.materialize_reducer_records(core, None)
    else:
        if payload.get("status") != "COMPLETED_NUMERIC_EVALUATION":
            raise G0GovernanceError("numeric bound summary status mismatch")
        if not isinstance(summary, Mapping) or not isinstance(summary_artifact, Mapping):
            raise G0GovernanceError("numeric bound summary lacks summary/artifact")
        _require_exact_keys(
            summary,
            {"protocol", "support", "reference", "arms"},
            label="bound scientific summary",
        )
        protocol = summary.get("protocol")
        support = summary.get("support")
        summary_reference = summary.get("reference")
        summary_arms = summary.get("arms")
        if (
            not isinstance(protocol, Mapping)
            or not isinstance(support, Mapping)
            or not isinstance(summary_reference, Mapping)
            or not isinstance(summary_arms, Mapping)
        ):
            raise G0GovernanceError("bound scientific summary nesting differs")
        _require_exact_keys(
            protocol,
            {
                "contrast_name",
                "reference",
                "evaluation_rate_hz",
                "nominal_reference_rate_hz",
                "nominal_estimate_rate_hz",
                "window_start_s",
                "window_end_s",
                "max_reference_gap_s",
                "max_estimate_gap_s",
                "rpe_delta_s",
                "body_to_camera_applied",
                "rpe_semantics",
                "reference_time_offset_s",
                "arm_time_offsets_s",
            },
            label="bound scientific protocol",
        )
        _require_exact_keys(
            support,
            {
                "grid_count",
                "matched_count",
                "common_span_s",
                "common_coverage",
                "segment_count",
                "rpe_pairs",
                "ape_valid",
                "rpe_valid",
                "window_duration_s",
            },
            label="bound scientific support",
        )
        _require_exact_keys(
            summary_reference,
            {
                "audit",
                "rejection_histogram",
                "valid_grid_count",
                "bracket_gap_p50_s",
                "bracket_gap_p95_s",
                "bracket_gap_max_s",
            },
            label="bound scientific reference",
        )
        arm_offsets = protocol.get("arm_time_offsets_s")
        if (
            protocol.get("contrast_name") != core.get("contrast_name")
            or not isinstance(arm_offsets, Mapping)
            or set(arm_offsets) != set(core["arms"])
            or any(type(value) is not float or repr(value) != "0.0" for value in arm_offsets.values())
            or set(summary_arms) != set(core["arms"])
        ):
            raise G0GovernanceError("bound scientific protocol/arm set differs")
        if set(summary_artifact) != {"path", "sha256", "size_bytes"}:
            raise G0GovernanceError("bound raw-summary artifact keys differ")
        evaluation.materialize_reducer_records(core, summary)
        if verify_raw_summary:
            observed_summary = _direct_json_snapshot(
                root, summary_artifact, label="raw G0 summary"
            )
            if not _exact_json_equal(observed_summary, summary):
                raise G0GovernanceError("bound/raw G0 summary JSON differs")
    process = payload.get("evaluator_process")
    if not isinstance(process, Mapping):
        raise G0GovernanceError("bound summary lacks evaluator process evidence")
    _require_exact_keys(
        process,
        {"executed", "exit_code", "vins_launched"},
        label="bound summary evaluator process",
    )
    expected_executed = core["evaluation_disposition"] == "EVALUATE_NUMERIC"
    if process.get("executed") is not expected_executed:
        raise G0GovernanceError("bound summary evaluator execution flag mismatch")
    if expected_executed and process.get("exit_code") != 0:
        raise G0GovernanceError("numeric evaluator did not exit successfully")
    if not expected_executed and process.get("exit_code") is not None:
        raise G0GovernanceError("failure-only job records an evaluator exit code")
    if process.get("vins_launched") is not False:
        raise G0GovernanceError("bound summary must not launch VINS")
    if payload.get("outcome_boundary") != OUTCOME_BOUNDARY:
        raise G0GovernanceError("bound summary outcome boundary mismatch")
    return digest


def render_sha256_manifest(records: Sequence[Mapping[str, object]]) -> bytes:
    lines: list[str] = []
    seen: set[str] = set()
    for record in sorted(records, key=lambda item: str(item["path"])):
        path = str(record["path"])
        digest = require_hash(record.get("sha256"), "manifest sha256")
        if not path or "\n" in path or path in seen:
            raise G0GovernanceError("invalid/duplicate output-manifest path")
        if PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
            raise G0GovernanceError("output-manifest paths must be safe and relative")
        seen.add(path)
        lines.append(f"{digest}  {path}\n")
    return "".join(lines).encode("utf-8")


def validate_output_manifest(directory: Path, manifest: Path) -> list[dict[str, object]]:
    if not manifest.is_file():
        raise G0GovernanceError(f"missing output manifest: {manifest}")
    records: list[dict[str, object]] = []
    seen: set[str] = set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([^\n]+)", line)
        if match is None:
            raise G0GovernanceError("malformed output manifest line")
        digest, relative = match.groups()
        rel = PurePosixPath(relative)
        if rel.is_absolute() or ".." in rel.parts or relative in seen:
            raise G0GovernanceError("unsafe/duplicate output manifest path")
        seen.add(relative)
        path = directory / relative
        if not path.is_file() or sha256_file(path) != digest:
            raise G0GovernanceError(f"output manifest mismatch: {path}")
        records.append(
            {"path": relative, "sha256": digest, "size_bytes": path.stat().st_size}
        )
    if not records:
        raise G0GovernanceError("empty output manifest")
    return records


def exact_json_identity(
    payload: Mapping[str, Any], expected: Mapping[str, object], *, label: str
) -> None:
    differences = {
        key: {"expected": value, "observed": payload.get(key)}
        for key, value in expected.items()
        if payload.get(key) != value
    }
    if differences:
        raise G0GovernanceError(f"{label} identity mismatch: {differences}")


__all__ = [
    "BOUND_SUMMARY_SCHEMA",
    "CLASSIFICATION_SCHEMA",
    "FAILURE_EVIDENCE_SCHEMA",
    "EXECUTION_AUTHORITY_SCHEMA",
    "EXECUTION_AUTHORITY_STATUS",
    "EXECUTION_LOCK_BINDING_KEY",
    "DEFAULT_EVALUATION_LOCK",
    "DEFAULT_REFERENCE_CONTRACTS",
    "G0GovernanceError",
    "JOB_SCHEMA",
    "JOB_STATUS",
    "LOCK_OUTCOME_BOUNDARY",
    "LOCK_SCHEMA",
    "LOCK_STATUS",
    "OUTCOME_BOUNDARY",
    "P07",
    "PLAN_SCHEMA",
    "PLAN_STATUS",
    "PUBLICATION_CLOSEOUT_SCHEMA",
    "PUBLICATION_INTENT_SCHEMA",
    "REDUCTION_SCHEMA",
    "RESULT_RECEIPT_SCHEMA",
    "REQUIRED_CODE_BINDING_ROLES",
    "REQUIRED_FROZEN_INPUT_ROLES",
    "REQUIRED_FROZEN_INPUT_PATHS",
    "REQUIRED_CODE_BINDING_PATHS",
    "ROOT",
    "TERMINAL_BINDING_SCHEMA",
    "canonical_json_bytes",
    "canonical_json_hash",
    "display_path",
    "build_execution_authority_binding",
    "exact_json_identity",
    "file_record",
    "read_csv",
    "read_json_object",
    "render_sha256_manifest",
    "require_hash",
    "row_sha256",
    "sha256_bytes",
    "sha256_file",
    "validate_file_record",
    "validate_execution_authority_binding",
    "validate_bound_summary",
    "validate_job_payload",
    "validate_lock_payload",
    "validate_output_manifest",
    "validate_plan_payload",
    "validate_self_hash",
    "validate_terminal_binding",
    "workspace_path",
    "write_json_exclusive",
]
