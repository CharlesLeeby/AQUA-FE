#!/usr/bin/env python3
"""Build the outcome-blind P07 G0 template/lock before the first replay.

The builder hashes the backend queue/allocation/locks, evaluator precision
correction, absolute reference contracts, evaluator/core, and every
planner/classifier/collector/runner/publisher/reducer implementation.  It
refuses any queue whose algorithmic replay has progressed beyond PLANNED or
whose deterministic run/attempt output already exists.

By default the CLI only prints a preview.  ``--publish`` is required for an
exclusive write; this repository task intentionally does not use it.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime
import io
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    from scripts import build_p07_backend_formalization_adoption_v1 as adoption
    from scripts import build_p07_backend_formalization_review_evidence_v1 as review_evidence
    from scripts import build_p07_evaluator_epoch_ns_correction_lock_v1 as epoch_correction
    from scripts import build_p07_g0_reference_contracts_v1 as references
    from scripts import p07_backend_formal_io_v1 as formal_io
    from scripts import p07_backend_replay_common_v1 as backend
    from scripts import p07_g0_governance_v1 as gov
    from scripts import p07_g0_publisher_v1 as publisher
except ModuleNotFoundError:
    import build_p07_backend_formalization_adoption_v1 as adoption  # type: ignore
    import build_p07_backend_formalization_review_evidence_v1 as review_evidence  # type: ignore
    import build_p07_evaluator_epoch_ns_correction_lock_v1 as epoch_correction  # type: ignore
    import build_p07_g0_reference_contracts_v1 as references  # type: ignore
    import p07_backend_formal_io_v1 as formal_io  # type: ignore
    import p07_backend_replay_common_v1 as backend  # type: ignore
    import p07_g0_governance_v1 as gov  # type: ignore
    import p07_g0_publisher_v1 as publisher  # type: ignore


CODE_BINDINGS = tuple(gov.REQUIRED_CODE_BINDING_PATHS.items())


def _relative(root: Path, path: Path, *, label: str) -> str:
    root_absolute = root.absolute()
    path_absolute = path.absolute()
    try:
        return path_absolute.relative_to(root_absolute).as_posix()
    except ValueError as error:
        raise gov.G0GovernanceError(f"{label} escapes the workspace") from error


def _direct_bytes(root: Path, path: Path, *, label: str) -> bytes:
    try:
        content, _identity = formal_io.read_direct_bytes(
            root.absolute(), _relative(root, path, label=label)
        )
    except (formal_io.FormalIOError, OSError) as error:
        raise gov.G0GovernanceError(f"cannot directly read {label}: {path}") from error
    return content


def _direct_record(root: Path, path: Path, *, label: str) -> dict[str, object]:
    content = _direct_bytes(root, path, label=label)
    return {
        "path": _relative(root, path, label=label),
        "sha256": gov.sha256_bytes(content),
        "size_bytes": len(content),
    }


def _record_from_content(
    root: Path, path: Path, content: bytes, *, label: str
) -> dict[str, object]:
    return {
        "path": _relative(root, path, label=label),
        "sha256": gov.sha256_bytes(content),
        "size_bytes": len(content),
    }


def _direct_json_snapshot(
    root: Path, path: Path, *, label: str
) -> tuple[dict[str, Any], dict[str, object]]:
    content = _direct_bytes(root, path, label=label)
    value = gov._json_object_bytes(content, label=label)
    return value, _record_from_content(root, path, content, label=label)


def _direct_json(root: Path, path: Path, *, label: str) -> dict[str, Any]:
    value, _record = _direct_json_snapshot(root, path, label=label)
    return value


def _direct_csv_snapshot(
    root: Path, path: Path, *, label: str
) -> tuple[list[str], list[dict[str, str]], dict[str, object]]:
    content = _direct_bytes(root, path, label=label)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise gov.G0GovernanceError(f"invalid {label} UTF-8") from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    fields = list(reader.fieldnames or [])
    rows = [dict(row) for row in reader]
    if not fields or any(set(row) != set(fields) for row in rows):
        raise gov.G0GovernanceError(f"malformed {label} CSV")
    return fields, rows, _record_from_content(root, path, content, label=label)


def _direct_csv(root: Path, path: Path, *, label: str) -> tuple[list[str], list[dict[str, str]]]:
    fields, rows, _record = _direct_csv_snapshot(root, path, label=label)
    return fields, rows


def _timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise gov.G0GovernanceError("frozen_at must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise gov.G0GovernanceError("frozen_at must include a timezone")
    return value


def _code_records(root: Path) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for role, relative in CODE_BINDINGS:
        record = _direct_record(root, root / relative, label=f"G0 code {role}")
        record["role"] = role
        result.append(record)
    return result


def validate_backend_cardinality(
    queue_rows: Iterable[Mapping[str, str]],
) -> dict[str, Any]:
    rows = [dict(row) for row in queue_rows]
    by_window: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    indices: set[int] = set()
    run_ids: set[str] = set()
    for row in rows:
        backend.validate_queue_row(row)
        index = int(row["queue_index"])
        if index in indices or row["run_id"] in run_ids:
            raise gov.G0GovernanceError("duplicate backend queue index or run_id")
        indices.add(index)
        run_ids.add(row["run_id"])
        by_window[row["window_id"]][row["arm"]].append(row)
    if indices != set(range(1, len(rows) + 1)):
        raise gov.G0GovernanceError("backend queue indices are not contiguous")
    if len(by_window) != 20:
        raise gov.G0GovernanceError("backend queue must contain exactly 20 windows")
    applicable_d: list[str] = []
    for window_id, arms in by_window.items():
        required = {backend.B0_ARM, backend.B1_ARM, backend.P_ARM, backend.M_ARM}
        if not required.issubset(arms):
            raise gov.G0GovernanceError(f"{window_id} lacks a required backend arm")
        extras = set(arms) - required
        if extras not in (set(), {backend.D_ARM}):
            raise gov.G0GovernanceError(f"{window_id} has invalid backend arms")
        if backend.D_ARM in arms:
            applicable_d.append(window_id)
        for arm, arm_rows in arms.items():
            replay_indices = {int(row["replay_index"]) for row in arm_rows}
            slots = {row["algorithmic_slot"] for row in arm_rows}
            if replay_indices != {1, 2, 3} or slots != {"b01", "b02", "b03"}:
                raise gov.G0GovernanceError(
                    f"{window_id}/{arm} lacks exact replay-index pairing"
                )
    k = len(applicable_d)
    if len(rows) != 240 + 3 * k:
        raise gov.G0GovernanceError("backend queue is not 240+3k")
    route_counts = {
        "B0_DESCRIPTIVE": 60,
        "P_VS_B1": 60,
        "P_VS_M": 60,
        "P_VS_D": 3 * k,
    }
    return {
        "windows": 20,
        "applicable_d_windows": k,
        "applicable_d_window_ids": sorted(applicable_d),
        "backend_algorithmic_replay_jobs": len(rows),
        "g0_evaluation_jobs": sum(route_counts.values()),
        "routes": route_counts,
    }


def validate_pre_first_replay(
    queue_rows: Iterable[Mapping[str, str]],
    registry_rows: Iterable[Mapping[str, str]],
    *,
    root: Path,
    check_outputs_absent: bool,
) -> dict[str, object]:
    rows = [dict(row) for row in queue_rows]
    run_ids = {row["run_id"] for row in rows}
    chains: dict[str, list[dict[str, str]]] = defaultdict(list)
    for event in registry_rows:
        if event.get("stage") == "P07_BACKEND_REPLAY" and event.get("run_id") in run_ids:
            chains[event["run_id"]].append(dict(event))
    if set(chains) != run_ids:
        missing = sorted(run_ids - set(chains))
        raise gov.G0GovernanceError(
            f"backend queue is not fully preregistered: {missing[:3]}"
        )
    for run_id, events in chains.items():
        if len(events) != 1 or events[0].get("status") != "PLANNED":
            raise gov.G0GovernanceError(
                f"first replay already started or registry chain is noncanonical: {run_id}"
            )
    existing: list[str] = []
    if check_outputs_absent:
        for row in rows:
            for key in ("expected_run_dir", "expected_attempt_dir"):
                path = gov.workspace_path(root, row[key], label=f"queue {key}")
                if publisher.path_state_rooted(
                    root, path, label="pre-replay backend output"
                ) != "ABSENT":
                    existing.append(gov.display_path(root, path))
        if existing:
            raise gov.G0GovernanceError(
                f"backend output exists before G0 lock freeze: {existing[:3]}"
            )
    return {
        "registered_planned_runs": len(chains),
        "running_runs": 0,
        "terminal_runs": 0,
        "deterministic_outputs_existing": existing,
    }


def _validate_precision_lock(
    root: Path, path: Path
) -> tuple[dict[str, Any], dict[str, object]]:
    payload, record = _direct_json_snapshot(
        root, path, label="precision correction lock"
    )
    if (
        payload.get("schema_version")
        != "isj-p07-evaluator-precision-correction-lock-v1"
        or payload.get("status")
        != "FROZEN_OUTCOME_BLIND_ADDITIVE_EVALUATOR_PRECISION_CORRECTION"
    ):
        raise gov.G0GovernanceError("unexpected evaluator precision lock")
    gov.validate_self_hash(payload, "correction_lock_hash", label="precision lock")
    corrected = payload.get("corrected_implementation_binding")
    if not isinstance(corrected, Mapping):
        raise gov.G0GovernanceError("precision lock lacks corrected implementation")
    files = corrected.get("files")
    if not isinstance(files, list):
        raise gov.G0GovernanceError("precision lock corrected files are invalid")
    for record in files:
        if not isinstance(record, Mapping):
            raise gov.G0GovernanceError("precision lock file record is invalid")
        bound_path = gov.workspace_path(
            root, record.get("path"), label="precision implementation"
        )
        if any(
            _direct_record(
                root, bound_path, label="precision implementation"
            ).get(key)
            != record.get(key)
            for key in ("path", "sha256", "size_bytes")
        ):
            raise gov.G0GovernanceError("precision implementation record drift")
    return payload, record


def _validate_epoch_ns_lock(
    root: Path, path: Path
) -> tuple[dict[str, Any], dict[str, object]]:
    payload, record = _direct_json_snapshot(
        root, path, label="epoch-ns correction lock"
    )
    try:
        epoch_correction.validate_lock_payload(payload, root=root, verify_files=True)
    except ValueError as error:
        raise gov.G0GovernanceError(
            f"invalid evaluator epoch-ns correction lock: {error}"
        ) from error
    return payload, record


def build_lock_payload(
    *,
    root: Path,
    queue_path: Path,
    allocation_path: Path,
    queue_lock_path: Path,
    precision_lock_path: Path,
    epoch_ns_lock_path: Path,
    reference_contracts_path: Path,
    registry_path: Path,
    frozen_at: str,
    strict_backend_lock_validation: bool = True,
    check_outputs_absent: bool = True,
) -> dict[str, Any]:
    _fields, queue_rows, queue_record = _direct_csv_snapshot(
        root, queue_path, label="backend queue"
    )
    _allocation_fields, allocations, allocation_record = _direct_csv_snapshot(
        root, allocation_path, label="backend allocation"
    )
    _registry_fields, registry_rows, registry_record = _direct_csv_snapshot(
        root, registry_path, label="run registry"
    )
    counts = validate_backend_cardinality(queue_rows)
    allocation_by_index = {row["queue_index"]: row for row in allocations}
    if len(allocation_by_index) != len(queue_rows):
        raise gov.G0GovernanceError("backend allocation count/index mismatch")
    for row in queue_rows:
        allocation = allocation_by_index.get(row["queue_index"])
        if allocation is None:
            raise gov.G0GovernanceError("backend allocation lacks queue row")
        backend.validate_allocation(row, allocation)

    queue_lock, queue_lock_record = _direct_json_snapshot(
        root, queue_lock_path, label="backend queue lock"
    )
    if strict_backend_lock_validation:
        backend.validate_queue_lock(root, queue_lock_path)
    else:
        # Fixture mode still requires the queue-lock self hash.
        gov.validate_self_hash(
            queue_lock, "backend_queue_lock_hash", label="backend queue lock"
        )

    precision, precision_record = _validate_precision_lock(root, precision_lock_path)
    epoch_ns, epoch_ns_record = _validate_epoch_ns_lock(root, epoch_ns_lock_path)
    corrected = epoch_ns["corrected_implementation_binding"]
    parent_epoch_binding = epoch_ns.get("parent_precision_correction_lock")
    if (
        not isinstance(parent_epoch_binding, Mapping)
        or parent_epoch_binding.get("correction_lock_hash")
        != precision.get("correction_lock_hash")
        or any(
            parent_epoch_binding.get(key) != precision_record.get(key)
            for key in ("path", "sha256", "size_bytes")
        )
    ):
        raise gov.G0GovernanceError(
            "epoch-ns correction does not bind the exact precision parent lock"
        )
    queue_protocols = {row.get("evaluator_protocol_sha256") for row in queue_rows}
    queue_implementations = {
        row.get("evaluator_implementation_sha256") for row in queue_rows
    }
    if queue_protocols != {epoch_ns["protocol_binding"]["sha256"]}:
        raise gov.G0GovernanceError(
            "backend queue evaluator protocol differs from epoch-ns correction lock"
        )
    if queue_implementations != {corrected["implementation_bundle_sha256"]}:
        raise gov.G0GovernanceError(
            "backend queue evaluator implementation differs from precision lock"
        )
    reference_payload, reference_contracts_record = _direct_json_snapshot(
        root, reference_contracts_path, label="G0 reference contracts"
    )
    reference_hash = references.validate_reference_contracts(
        reference_payload, root=root, verify_artifacts=True
    )
    reference_windows = {
        str(record["window_id"])
        for record in reference_payload["contracts"]
        if isinstance(record, Mapping)
    }
    queue_windows = {row["window_id"] for row in queue_rows}
    if reference_windows != queue_windows:
        raise gov.G0GovernanceError("reference contracts do not match backend queue windows")
    if reference_payload.get("source_backend_queue") != queue_record:
        raise gov.G0GovernanceError(
            "reference contracts bind a different backend queue snapshot"
        )
    prefirst = validate_pre_first_replay(
        queue_rows,
        registry_rows,
        root=root,
        check_outputs_absent=check_outputs_absent,
    )

    template: dict[str, Any] = {
        "schema_version": "isj-p07-g0-evaluation-template-v1",
        "scientific_unit": "sequence_not_replay",
        "replay_indices": [1, 2, 3],
        "minimum_evaluable_replays": 2,
        "pairing_rule": "EQUAL_REPLAY_INDEX_ONLY",
        "routes": {
            "B0_DESCRIPTIVE": {
                "route": "G0_B0_REFERENCE_SUPPORT_DESCRIPTIVE_V1",
                "arms": [backend.B0_ARM],
                "metric_role": "DESCRIPTIVE_ONLY_NOT_AN_INFERENTIAL_CONTRAST",
            },
            "P_VS_B1": {
                "route": "G0_PAIRWISE_COMMON_SUPPORT_V1",
                "arms": [backend.P_ARM, backend.B1_ARM],
            },
            "P_VS_M": {
                "route": "G0_PAIRWISE_COMMON_SUPPORT_V1",
                "arms": [backend.P_ARM, backend.M_ARM],
            },
            "P_VS_D": {
                "route": "G0_PAIRWISE_COMMON_SUPPORT_V1",
                "arms": [backend.P_ARM, backend.D_ARM],
                "conditional": True,
            },
        },
        "counts": counts,
        "reference_contracts": {
            "path": gov.display_path(root, reference_contracts_path),
            "sha256": reference_contracts_record["sha256"],
            "self_hash": reference_hash,
            "absolute_window_rule": (
                "FIRST_LAST_ACTUAL_REFERENCE_SAMPLE_AFTER_FROZEN_WINDOW_SELECTION"
            ),
            "relative_queue_seconds_as_epoch_forbidden": True,
            "same_window_all_arms_replays_exact": True,
        },
        "evaluator": {
            "profile_rule": "QUEUE_EVALUATOR_PROFILE_ID_EXACT",
            "protocol_sha256": epoch_ns["protocol_binding"]["sha256"],
            "implementation_bundle_sha256": corrected[
                "implementation_bundle_sha256"
            ],
            "rpe_delta_s": 1.0,
            "minimum_ape_poses": 30,
            "minimum_ape_span_s": 10.0,
            "minimum_common_coverage": 0.70,
            "minimum_rpe_pairs": 10,
        },
        "failure_policy": {
            "hard_failure_any_of_three": True,
            "solver_risk_any_of_three": True,
            "infrastructure_replacements_do_not_consume_algorithmic_slots": True,
            "hard_failure_precedes_numeric_effect": True,
            "queue_telemetry_policy": (
                "QUEUE_TELEMETRY_NOT_INSTRUMENTED_NO_ZERO_IMPUTATION"
            ),
            "queue_risk_is_diagnostic_not_hard_failure": True,
            "queue_unknown_alone_does_not_make_replay_incomplete": True,
        },
    }
    payload: dict[str, Any] = {
        "schema_version": gov.LOCK_SCHEMA,
        "status": gov.LOCK_STATUS,
        "frozen_at": _timestamp(frozen_at),
        "formalization_adoption": adoption.adoption_authority_binding(root=root),
        "formalization_review_evidence": (
            review_evidence.review_evidence_authority_binding(root=root)
        ),
        "frozen_inputs": [
            {
                **record,
                "role": role,
            }
            for role, record in (
                ("backend_queue", queue_record),
                ("backend_allocation", allocation_record),
                ("backend_queue_lock", queue_lock_record),
                ("evaluator_precision_correction_lock", precision_record),
                ("evaluator_epoch_ns_correction_lock", epoch_ns_record),
                ("reference_contracts", reference_contracts_record),
            )
        ],
        "mutable_registry_prefix": {
            **registry_record,
        },
        "backend_bindings": {
            "queue_lock_self_hash": queue_lock.get("backend_queue_lock_hash"),
            "precision_correction_self_hash": precision.get("correction_lock_hash"),
            "epoch_ns_correction_self_hash": epoch_ns.get(
                "epoch_ns_correction_lock_hash"
            ),
            "reference_contracts_self_hash": reference_hash,
        },
        "code_bindings": _code_records(root),
        "evaluation_template": template,
        "evaluation_template_hash": gov.canonical_json_hash(template),
        "pre_first_replay_proof": prefirst,
        "outcome_blind_audit": {
            "backend_replay_executed": False,
            "real_backend_trajectory_read": False,
            "ape_artifact_read": False,
            "rpe_artifact_read": False,
            "evaluator_executed": False,
            "result_artifact_read": False,
            "workspace_result_discovery_used": False,
        },
        "outcome_boundary": gov.LOCK_OUTCOME_BOUNDARY,
    }
    payload["evaluation_lock_hash"] = gov.canonical_json_hash(payload)
    gov.validate_lock_payload(payload, root=root, verify_files=True)
    return payload


def _publication_guard_records(
    root: Path, payload: Mapping[str, Any]
) -> list[Mapping[str, object]]:
    frozen = payload.get("frozen_inputs")
    code = payload.get("code_bindings")
    registry = payload.get("mutable_registry_prefix")
    adoption_binding = payload.get("formalization_adoption")
    evidence_binding = payload.get("formalization_review_evidence")
    if (
        not isinstance(frozen, list)
        or not isinstance(code, list)
        or not isinstance(registry, Mapping)
        or not isinstance(adoption_binding, Mapping)
        or not isinstance(evidence_binding, Mapping)
    ):
        raise gov.G0GovernanceError(
            "G0 evaluation lock lacks transactional input records"
        )
    records: list[Mapping[str, object]] = [
        *frozen,
        *code,
        registry,
        adoption_binding,
        evidence_binding,
    ]
    reference_bindings = [
        record
        for record in frozen
        if isinstance(record, Mapping) and record.get("role") == "reference_contracts"
    ]
    if len(reference_bindings) != 1:
        raise gov.G0GovernanceError(
            "G0 evaluation lock lacks one reference-contract binding"
        )
    reference_path = gov.workspace_path(
        root,
        reference_bindings[0].get("path"),
        label="G0 transactional reference contracts",
    )
    reference_payload, _record = _direct_json_snapshot(
        root, reference_path, label="G0 transactional reference contracts"
    )
    for key in ("source_backend_queue", "reference_audit"):
        value = reference_payload.get(key)
        if not isinstance(value, Mapping):
            raise gov.G0GovernanceError(
                f"G0 reference contracts lack transactional {key}"
            )
        records.append(value)
    contracts = reference_payload.get("contracts")
    if not isinstance(contracts, list):
        raise gov.G0GovernanceError(
            "G0 reference contracts lack transactional artifacts"
        )
    for contract in contracts:
        artifact = contract.get("reference_artifact") if isinstance(contract, Mapping) else None
        if not isinstance(artifact, Mapping):
            raise gov.G0GovernanceError(
                "G0 reference contract transactional artifact is malformed"
            )
        records.append(artifact)
    return records


def publish_lock_transactional(
    *,
    root: Path,
    output: Path,
    payload: Mapping[str, Any],
    queue_path: Path,
    allocation_path: Path,
    queue_lock_path: Path,
    precision_lock_path: Path,
    epoch_ns_lock_path: Path,
    reference_contracts_path: Path,
    registry_path: Path,
) -> dict[str, object]:
    frozen_at = payload.get("frozen_at")
    if not isinstance(frozen_at, str):
        raise gov.G0GovernanceError("G0 evaluation lock lacks frozen_at")

    def validate_fresh_rebuild() -> None:
        rebuilt = build_lock_payload(
            root=root,
            queue_path=queue_path,
            allocation_path=allocation_path,
            queue_lock_path=queue_lock_path,
            precision_lock_path=precision_lock_path,
            epoch_ns_lock_path=epoch_ns_lock_path,
            reference_contracts_path=reference_contracts_path,
            registry_path=registry_path,
            frozen_at=frozen_at,
            strict_backend_lock_validation=True,
            check_outputs_absent=False,
        )
        if formal_io.json_bytes(rebuilt) != formal_io.json_bytes(payload):
            raise gov.G0GovernanceError(
                "G0 evaluation lock differs from fresh live rebuild"
            )

    return publisher.publish_json_transactional_rooted(
        root,
        output,
        payload,
        guard_records=_publication_guard_records(root, payload),
        validate=validate_fresh_rebuild,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=gov.ROOT)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--allocation", type=Path, required=True)
    parser.add_argument("--queue-lock", type=Path, required=True)
    parser.add_argument("--precision-lock", type=Path, required=True)
    parser.add_argument("--epoch-ns-lock", type=Path, required=True)
    parser.add_argument("--reference-contracts", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--frozen-at", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    payload = build_lock_payload(
        root=args.root,
        queue_path=args.queue,
        allocation_path=args.allocation,
        queue_lock_path=args.queue_lock,
        precision_lock_path=args.precision_lock,
        epoch_ns_lock_path=args.epoch_ns_lock,
        reference_contracts_path=args.reference_contracts,
        registry_path=args.registry,
        frozen_at=args.frozen_at,
    )
    if args.publish:
        if args.output is None:
            raise SystemExit("--publish requires --output")
        try:
            publish_lock_transactional(
                root=args.root,
                output=args.output,
                payload=payload,
                queue_path=args.queue,
                allocation_path=args.allocation,
                queue_lock_path=args.queue_lock,
                precision_lock_path=args.precision_lock,
                epoch_ns_lock_path=args.epoch_ns_lock,
                reference_contracts_path=args.reference_contracts,
                registry_path=args.registry,
            )
        except (formal_io.FormalIOError, FileExistsError) as error:
            raise gov.G0GovernanceError(
                f"cannot publish G0 evaluation lock: {args.output}"
            ) from error
    elif args.output is not None:
        raise SystemExit("--output without --publish is forbidden; use stdout preview")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
