#!/usr/bin/env python3
"""Materialize and validate P07 G0 jobs from frozen terminal bindings.

No run-directory discovery is permitted.  The caller supplies an explicit,
self-hashed terminal-binding index.  The materializer validates every binding
against the hash-bound backend queue and the pre-replay G0 lock, then creates
equal-replay-index B0/P-B1/P-M/(conditional P-D) jobs.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import io
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

try:
    from scripts import p07_backend_evaluation_v1 as evaluation
    from scripts import p07_backend_replay_common_v1 as backend
    from scripts import p07_g0_governance_v1 as gov
    from scripts import p07_g0_publisher_v1 as publisher
except ModuleNotFoundError:
    import p07_backend_evaluation_v1 as evaluation  # type: ignore
    import p07_backend_replay_common_v1 as backend  # type: ignore
    import p07_g0_governance_v1 as gov  # type: ignore
    import p07_g0_publisher_v1 as publisher  # type: ignore


INDEX_SCHEMA = "isj-p07-g0-terminal-binding-index-v1"
INDEX_STATUS = "COMPLETE_EXPLICIT_TERMINAL_BINDING_INDEX"
INDEX_RECORD_KEYS = {
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


def build_terminal_index(
    binding_paths: Sequence[Path], *, root: Path
) -> dict[str, Any]:
    records: list[dict[str, object]] = []
    identities: set[tuple[object, ...]] = set()
    for path in binding_paths:
        payload = publisher.read_json_direct_rooted(
            root, path, label="terminal binding"
        )
        binding_hash = gov.validate_terminal_binding(payload, root=root, verify_files=True)
        identity = (
            payload["window_id"],
            payload["arm"],
            payload["replay_index"],
        )
        if identity in identities:
            raise gov.G0GovernanceError(f"duplicate terminal binding identity: {identity}")
        identities.add(identity)
        record = publisher.direct_file_record_rooted(
            root, path, label="terminal binding"
        )
        record.update(
            {
                "terminal_binding_hash": binding_hash,
                "queue_index": payload["queue_index"],
                "run_id": payload["run_id"],
                "window_id": payload["window_id"],
                "arm": payload["arm"],
                "replay_index": payload["replay_index"],
                "backend_algorithmic_slot": payload["backend_algorithmic_slot"],
                "source_run_id": payload["source_run_id"],
                "source_provenance_kind": payload["source_provenance_kind"],
                "source_provenance_hash": payload["source_provenance_hash"],
                "evaluation_lock_hash": payload["evaluation_lock_hash"],
                "backend_execution_lock_hash": payload[
                    "backend_execution_lock_hash"
                ],
                "g0_execution_authority_hash": payload[
                    "g0_execution_authority_hash"
                ],
            }
        )
        records.append(record)
    records.sort(key=lambda item: int(item["queue_index"]))
    payload: dict[str, Any] = {
        "schema_version": INDEX_SCHEMA,
        "status": INDEX_STATUS,
        "bindings": records,
        "count": len(records),
        "outcome_boundary": gov.OUTCOME_BOUNDARY,
    }
    payload["terminal_index_hash"] = gov.canonical_json_hash(payload)
    return payload


def validate_terminal_index(
    payload: Mapping[str, Any], *, root: Path, verify_files: bool = True
) -> tuple[str, list[dict[str, Any]]]:
    if set(payload) != {
        "schema_version",
        "status",
        "bindings",
        "count",
        "outcome_boundary",
        "terminal_index_hash",
    }:
        raise gov.G0GovernanceError("terminal index keys differ")
    if payload.get("schema_version") != INDEX_SCHEMA or payload.get("status") != INDEX_STATUS:
        raise gov.G0GovernanceError("unexpected terminal index schema/status")
    if payload.get("outcome_boundary") != gov.OUTCOME_BOUNDARY:
        raise gov.G0GovernanceError("terminal index outcome boundary differs")
    digest = gov.validate_self_hash(payload, "terminal_index_hash", label="terminal index")
    records = payload.get("bindings")
    if not isinstance(records, list) or payload.get("count") != len(records):
        raise gov.G0GovernanceError("terminal index count mismatch")
    bindings: list[dict[str, Any]] = []
    identities: set[tuple[object, ...]] = set()
    binding_hashes: set[str] = set()
    queue_indices: set[int] = set()
    for index, record in enumerate(records):
        if not isinstance(record, Mapping) or set(record) != INDEX_RECORD_KEYS:
            raise gov.G0GovernanceError("terminal index record is invalid")
        path = gov.workspace_path(
            root, record.get("path"), label=f"terminal index {index}"
        )
        direct = publisher.direct_file_record_rooted(
            root, path, label=f"terminal index {index}"
        )
        if any(
            direct.get(key) != record.get(key)
            for key in ("path", "sha256", "size_bytes")
        ):
            raise gov.G0GovernanceError("terminal index file record mismatch")
        binding = publisher.read_json_direct_rooted(
            root, path, label="terminal binding"
        )
        binding_hash = gov.validate_terminal_binding(
            binding, root=root, verify_files=verify_files
        )
        if binding_hash != record.get("terminal_binding_hash"):
            raise gov.G0GovernanceError("terminal index self-hash binding mismatch")
        queue_index = record.get("queue_index")
        if type(queue_index) is not int or queue_index in queue_indices:
            raise gov.G0GovernanceError("terminal index queue index is invalid/duplicate")
        queue_indices.add(queue_index)
        if binding_hash in binding_hashes:
            raise gov.G0GovernanceError("duplicate terminal binding hash")
        binding_hashes.add(binding_hash)
        expected = {
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
        }
        gov.exact_json_identity(record, expected, label="terminal index record")
        identity = (binding["window_id"], binding["arm"], binding["replay_index"])
        if identity in identities:
            raise gov.G0GovernanceError("duplicate terminal index algorithmic slot")
        identities.add(identity)
        bindings.append(binding)
    return digest, bindings


def _frozen_input_path(
    lock: Mapping[str, Any], *, root: Path, filename: str
) -> Path:
    records = lock.get("frozen_inputs")
    if not isinstance(records, list):
        raise gov.G0GovernanceError("G0 lock frozen_inputs is invalid")
    matches: list[Path] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        path = Path(str(record.get("path", "")))
        if path.name == filename:
            bound_path = gov.workspace_path(root, path, label=filename)
            direct = publisher.direct_file_record_rooted(
                root, bound_path, label=filename
            )
            if any(
                direct.get(key) != record.get(key)
                for key in ("path", "sha256", "size_bytes")
            ):
                raise gov.G0GovernanceError(
                    f"{filename} direct file record differs from frozen binding"
                )
            matches.append(bound_path)
    if len(matches) != 1:
        raise gov.G0GovernanceError(f"G0 lock must bind one {filename}")
    return matches[0]


def _terminal_to_core(binding: Mapping[str, Any]) -> dict[str, Any]:
    wrapper = binding["classification"]
    assert isinstance(wrapper, Mapping)
    classification = wrapper["classification"]
    assert isinstance(classification, Mapping)
    artifacts = binding["artifact_bindings"]
    assert isinstance(artifacts, Mapping)
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
        "arm_time_offset_s": binding.get("arm_time_offset_s", 0.0),
        "reference": binding["reference"],
        "evaluator_profile_id": binding["evaluator_profile_id"],
        "evaluator_protocol_sha256": binding["evaluator_protocol_sha256"],
        "evaluator_script_sha256": binding["evaluator_script_sha256"],
        "classification": dict(classification),
    }


def _read_csv_direct_rooted(
    root: Path, path: Path, *, label: str
) -> tuple[list[str], list[dict[str, str]]]:
    content, _record = publisher._read_direct_bytes(root, path, label=label)
    try:
        text = content.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text, newline=""))
        fields = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    except (UnicodeDecodeError, csv.Error) as error:
        raise gov.G0GovernanceError(f"invalid {label} CSV: {path}") from error
    if not fields or any(set(row) != set(fields) for row in rows):
        raise gov.G0GovernanceError(f"malformed {label} CSV: {path}")
    return fields, rows


def _queue_map(lock: Mapping[str, Any], *, root: Path) -> dict[int, dict[str, str]]:
    path = _frozen_input_path(lock, root=root, filename="backend_replay_queue_v1.csv")
    _fields, rows = _read_csv_direct_rooted(
        root, path, label="frozen backend replay queue"
    )
    result: dict[int, dict[str, str]] = {}
    for row in rows:
        backend.validate_queue_row(row)
        index = int(row["queue_index"])
        if index in result:
            raise gov.G0GovernanceError("duplicate queue index in frozen backend queue")
        result[index] = row
    return result


def _validate_binding_queue_identity(
    binding: Mapping[str, Any], row: Mapping[str, str]
) -> None:
    expected = {
        "queue_index": int(row["queue_index"]),
        "window_id": row["window_id"],
        "arm": row["arm"],
        "replay_index": int(row["replay_index"]),
        "backend_algorithmic_slot": row["algorithmic_slot"],
        "source_run_id": row["source_run_id"],
        "source_provenance_kind": row["source_provenance_kind"],
        "source_provenance_hash": row["source_provenance_hash"],
    }
    gov.exact_json_identity(binding, expected, label="terminal binding/backend queue")
    provenance = binding.get("backend_terminal_provenance")
    if (
        not isinstance(provenance, Mapping)
        or provenance.get("base_queue_row") != dict(row)
        or not isinstance(provenance.get("effective_queue_row"), Mapping)
        or binding.get("run_id")
        != provenance["effective_queue_row"].get("run_id")
    ):
        raise gov.G0GovernanceError(
            "terminal effective-run provenance differs from backend queue"
        )
    if binding.get("evaluator_profile_id") != row.get("evaluator_profile_id"):
        raise gov.G0GovernanceError("terminal evaluator profile differs from backend queue")
    if binding.get("evaluator_protocol_sha256") != row.get("evaluator_protocol_sha256"):
        raise gov.G0GovernanceError("terminal evaluator protocol differs from backend queue")


def _safe_job_filename(job_id: str) -> str:
    if not gov.SAFE_ID_RE.fullmatch(job_id):
        raise gov.G0GovernanceError(f"unsafe G0 job_id: {job_id}")
    return job_id.replace(":", "__") + ".json"


def materialize_plan(
    lock: Mapping[str, Any],
    terminal_index: Mapping[str, Any],
    *,
    root: Path,
    job_root: Path,
    result_root_relative: str,
    terminal_index_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    lock_hash = gov.validate_lock_payload(lock, root=root, verify_files=True)
    index_hash, bindings = validate_terminal_index(
        terminal_index, root=root, verify_files=True
    )
    terminal_index_bytes, terminal_index_file = publisher._read_direct_bytes(
        root, terminal_index_path, label="terminal binding index"
    )
    terminal_index_snapshot = gov._json_object_bytes(
        terminal_index_bytes, label="terminal binding index"
    )
    if terminal_index_snapshot != dict(terminal_index):
        raise gov.G0GovernanceError(
            "terminal index payload differs from its direct frozen file"
        )
    queue = _queue_map(lock, root=root)
    if len(bindings) != len(queue):
        raise gov.G0GovernanceError("terminal index does not cover the frozen backend queue")
    by_queue = {int(binding["queue_index"]): binding for binding in bindings}
    if set(by_queue) != set(queue):
        raise gov.G0GovernanceError("terminal index/backend queue indices differ")
    for index, row in queue.items():
        _validate_binding_queue_identity(by_queue[index], row)

    execution_hashes = {
        str(binding["backend_execution_lock_hash"]) for binding in bindings
    }
    authority_hashes = {
        str(binding["g0_execution_authority_hash"]) for binding in bindings
    }
    evaluation_hashes = {str(binding["evaluation_lock_hash"]) for binding in bindings}
    execution_records = {
        gov.canonical_json_hash(
            dict(binding["artifact_bindings"]["backend_execution_lock"])
        ): binding["artifact_bindings"]["backend_execution_lock"]
        for binding in bindings
    }
    if (
        execution_hashes == set()
        or len(execution_hashes) != 1
        or len(authority_hashes) != 1
        or evaluation_hashes != {lock_hash}
        or len(execution_records) != 1
    ):
        raise gov.G0GovernanceError(
            "terminal bindings do not share one execution/G0 authority"
        )
    backend_execution_lock_hash = next(iter(execution_hashes))
    g0_execution_authority_hash = next(iter(authority_hashes))
    backend_execution_lock_record = next(iter(execution_records.values()))

    template_counts = lock["evaluation_template"]["counts"]
    d_applicability = {
        window_id: any(
            row["window_id"] == window_id and row["arm"] == backend.D_ARM
            for row in queue.values()
        )
        for window_id in sorted({row["window_id"] for row in queue.values()})
    }
    core_records = [_terminal_to_core(by_queue[index]) for index in sorted(by_queue)]
    core_jobs = evaluation.build_evaluation_plan(
        core_records,
        d_applicability=d_applicability,
        output_root=result_root_relative,
    )
    if len(core_jobs) != int(template_counts["g0_evaluation_jobs"]):
        raise gov.G0GovernanceError("materialized core job count differs from template")

    # Production contracts must use exact absolute integer-ns endpoints.  The
    # existing primitive still accepts relative legacy fixtures, so enforce
    # this stronger invariant at the production materializer boundary.
    window_references: dict[str, Mapping[str, Any]] = {}
    for binding in bindings:
        reference = binding["reference"]
        assert isinstance(reference, Mapping)
        if not isinstance(reference.get("window_start_ns"), int) or not isinstance(
            reference.get("window_end_ns"), int
        ):
            raise gov.G0GovernanceError("terminal reference lacks integer-ns endpoints")
        if int(reference["window_start_ns"]) < 100_000_000 * 1_000_000_000:
            raise gov.G0GovernanceError("relative seconds cannot be used as G0 epoch")
        previous = window_references.setdefault(str(binding["window_id"]), reference)
        if previous != reference:
            raise gov.G0GovernanceError(
                "same-window arms/replays have different reference contracts"
            )

    ordered_bindings = sorted(bindings, key=lambda value: int(value["queue_index"]))
    terminal_binding_hashes = [
        binding["terminal_binding_hash"] for binding in ordered_bindings
    ]
    core_job_hashes = [gov.canonical_json_hash(job) for job in core_jobs]
    basis: dict[str, Any] = {
        "evaluation_lock_hash": lock_hash,
        "evaluation_template_hash": lock["evaluation_template_hash"],
        "terminal_index_hash": index_hash,
        "terminal_index_file": terminal_index_file,
        "terminal_binding_hashes": terminal_binding_hashes,
        "result_root_relative": result_root_relative,
        "core_job_hashes": core_job_hashes,
        "core_jobs_hash": gov.canonical_json_hash(
            {"core_job_hashes": core_job_hashes}
        ),
        "backend_execution_lock_hash": backend_execution_lock_hash,
        "g0_execution_authority_hash": g0_execution_authority_hash,
        "backend_execution_lock": dict(backend_execution_lock_record),
    }
    basis_hash = gov.canonical_json_hash(basis)
    materialized: list[dict[str, Any]] = []
    job_records: list[dict[str, object]] = []
    binding_by_identity = {
        (binding["window_id"], binding["arm"], binding["replay_index"]): binding
        for binding in bindings
    }
    for core_job, core_job_hash in zip(core_jobs, core_job_hashes):
        output_absolute = gov.workspace_path(
            root, core_job["output_dir"], label="materialized G0 output"
        )
        if not output_absolute.is_absolute():
            raise AssertionError("workspace_path unexpectedly returned a relative path")
        arm_bindings: dict[str, Any] = {}
        for arm, raw in core_job["arms"].items():
            identity = (core_job["window_id"], arm, core_job["replay_index"])
            terminal = binding_by_identity[identity]
            if terminal["run_id"] != raw["run_id"]:
                raise gov.G0GovernanceError("core/terminal run_id mismatch")
            arm_bindings[arm] = {
                "run_id": raw["run_id"],
                "arm": arm,
                "replay_index": core_job["replay_index"],
                "terminal_binding": terminal,
            }
        first_binding = next(iter(arm_bindings.values()))["terminal_binding"]
        reference_artifact = first_binding["artifact_bindings"]["reference"]
        payload: dict[str, Any] = {
            "schema_version": gov.JOB_SCHEMA,
            "status": gov.JOB_STATUS,
            "job_id": core_job["job_id"],
            "plan_basis_hash": basis_hash,
            "evaluation_lock_hash": lock_hash,
            "backend_execution_lock_hash": backend_execution_lock_hash,
            "g0_execution_authority_hash": g0_execution_authority_hash,
            "backend_execution_lock": dict(backend_execution_lock_record),
            "evaluation_job": core_job,
            "input_bindings": arm_bindings,
            "reference_binding": {
                "contract": core_job["reference"],
                "artifact": reference_artifact,
            },
            "output_dir_absolute": os.fspath(output_absolute),
            "execution_policy": {
                "absolute_workspace_output_required": True,
                "destination_must_not_exist": True,
                "all_input_sha256_revalidated_before_evaluator": True,
                "summary_job_run_replay_arm_identity_required": True,
                "receipt_and_output_manifest_required": True,
            },
            "outcome_boundary": gov.OUTCOME_BOUNDARY,
        }
        payload["job_hash"] = gov.canonical_json_hash(payload)
        filename = _safe_job_filename(str(core_job["job_id"]))
        path = job_root / filename
        job_records.append(
            {
                "job_id": core_job["job_id"],
                "job_hash": payload["job_hash"],
                "core_job_hash": core_job_hash,
                "path": gov.display_path(root, path),
                "window_id": core_job["window_id"],
                "replay_index": core_job["replay_index"],
                "route": core_job["route"],
                "contrast_name": core_job["contrast_name"],
                "output_dir_absolute": os.fspath(output_absolute),
            }
        )
        materialized.append(payload)

    route_counts: dict[str, int] = defaultdict(int)
    for job in core_jobs:
        route_counts[str(job["contrast_name"])] += 1
    plan: dict[str, Any] = {
        "schema_version": gov.PLAN_SCHEMA,
        "status": gov.PLAN_STATUS,
        "evaluation_lock_hash": lock_hash,
        "plan_basis": basis,
        "plan_basis_hash": basis_hash,
        "jobs": job_records,
        "counts": {
            "jobs": len(job_records),
            "routes": dict(sorted(route_counts.items())),
            "terminal_bindings": len(bindings),
        },
        "outcome_boundary": gov.OUTCOME_BOUNDARY,
    }
    plan["plan_hash"] = gov.canonical_json_hash(plan)
    validated_plan_context: dict[str, Any] = {}
    gov.validate_plan_payload(
        plan,
        lock=lock,
        root=root,
        _context_out=validated_plan_context,
    )
    for job in materialized:
        gov.validate_job_payload(
            job,
            plan=plan,
            lock=lock,
            root=root,
            # The immediately preceding full plan validation already verified
            # every indexed terminal, lock, execution authority, and scientific
            # input.  Reusing its opaque process-local context keeps this loop
            # semantic-only instead of reopening the same authority 180 times.
            verify_inputs=False,
            _validated_plan_context=validated_plan_context,
        )
    # A second independent full validation is the post-use fence.  It catches
    # any queue/index/terminal/input drift that occurred while the 180 job
    # payloads were checked against the in-memory authority context.
    gov.validate_plan_payload(plan, lock=lock, root=root)
    return plan, materialized


def publish_plan_bundle(
    plan: Mapping[str, Any],
    jobs: Sequence[Mapping[str, Any]],
    *,
    root: Path,
    job_root: Path,
    plan_name: str = "plan_v1.json",
) -> Path:
    staging = job_root.with_name(f".{job_root.name}.staging-{plan['plan_basis_hash'][:16]}")
    by_id = {str(job["job_id"]): job for job in jobs}
    expected: dict[str, Mapping[str, Any]] = {
        _safe_job_filename(job_id): payload for job_id, payload in by_id.items()
    }
    expected[plan_name] = plan

    def validate_or_complete(directory: Path, *, allow_complete: bool) -> None:
        observed = set(
            publisher.list_direct_regular_files_rooted(
                root, directory, label="G0 plan bundle"
            )
        )
        if not observed.issubset(expected):
            raise gov.G0GovernanceError(
                f"unexpected G0 plan crash evidence in {directory}"
            )
        for name in sorted(observed):
            if publisher.read_json_direct_rooted(
                root, directory / name, label="G0 plan bundle file"
            ) != expected[name]:
                raise gov.G0GovernanceError(
                    f"existing G0 plan bundle file differs: {directory / name}"
                )
        missing = set(expected) - observed
        if missing and not allow_complete:
            raise gov.G0GovernanceError("published G0 plan bundle is incomplete")
        for name in sorted(missing):
            publisher.write_json_exclusive_rooted(
                root, directory / name, expected[name]
            )
        if set(
            publisher.list_direct_regular_files_rooted(
                root, directory, label="G0 plan bundle"
            )
        ) != set(expected):
            raise gov.G0GovernanceError("G0 plan bundle completion mismatch")

    job_state = publisher.path_state_rooted(
        root, job_root, label="G0 plan destination"
    )
    staging_state = publisher.path_state_rooted(
        root, staging, label="G0 plan staging"
    )
    if job_state == "DIRECTORY":
        validate_or_complete(job_root, allow_complete=False)
        return job_root / plan_name
    if job_state != "ABSENT":
        raise gov.G0GovernanceError("G0 plan destination is not a direct directory")
    if staging_state == "DIRECTORY":
        # Exact deterministic crash reconciliation: preserve and reject any
        # divergent byte identity, but safely complete missing exclusive files.
        validate_or_complete(staging, allow_complete=True)
        publisher.rename_directory_noreplace(staging, job_root, root=root)
        validate_or_complete(job_root, allow_complete=False)
        return job_root / plan_name
    if staging_state != "ABSENT":
        raise gov.G0GovernanceError("G0 plan staging is not a direct directory")
    publisher.create_workspace_directory(
        root, staging, create_parents=True, label="G0 plan staging"
    )
    for record in plan["jobs"]:
        job_id = str(record["job_id"])
        filename = _safe_job_filename(job_id)
        publisher.write_json_exclusive_rooted(
            root, staging / filename, by_id[job_id]
        )
    staged_plan = staging / plan_name
    publisher.write_json_exclusive_rooted(root, staged_plan, plan)
    # Atomic directory publication makes a crash either an auditable staging
    # directory or a complete no-clobber job root.
    publisher.rename_directory_noreplace(staging, job_root, root=root)
    validate_or_complete(job_root, allow_complete=False)
    return job_root / plan_name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--terminal-index", type=Path, required=True)
    parser.add_argument("--job-root", type=Path, required=True)
    parser.add_argument("--result-root-relative", required=True)
    parser.add_argument("--root", type=Path, default=gov.ROOT)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    lock = publisher.read_json_direct_rooted(
        args.root, args.lock, label="G0 evaluation lock"
    )
    index = publisher.read_json_direct_rooted(
        args.root, args.terminal_index, label="terminal binding index"
    )
    plan, jobs = materialize_plan(
        lock,
        index,
        root=args.root,
        job_root=args.job_root,
        result_root_relative=args.result_root_relative,
        terminal_index_path=args.terminal_index,
    )
    if args.publish:
        path = publish_plan_bundle(
            plan, jobs, root=args.root, job_root=args.job_root
        )
        print(f"plan={path}")
    else:
        print(
            json.dumps(
                {
                    "mode": "READ_ONLY_PLAN_PREVIEW",
                    "plan_hash": plan["plan_hash"],
                    "jobs": len(jobs),
                    "counts": plan["counts"],
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
