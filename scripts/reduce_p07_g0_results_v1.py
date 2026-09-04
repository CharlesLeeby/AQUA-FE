#!/usr/bin/env python3
"""Validate and reduce every result in one frozen P07 G0 evaluation plan.

The orchestrator follows only exact paths embedded in the validated plan and
jobs.  It validates each intent, closeout, receipt, output manifest, bound
summary, and job/run/replay/arm identity before invoking the existing frozen
2-of-3 and pairwise reducers.  It performs no result-directory discovery.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from scripts import p07_backend_evaluation_v1 as evaluation
    from scripts import p07_g0_governance_v1 as gov
    from scripts import p07_g0_publisher_v1 as publisher
except ModuleNotFoundError:
    import p07_backend_evaluation_v1 as evaluation  # type: ignore
    import p07_g0_governance_v1 as gov  # type: ignore
    import p07_g0_publisher_v1 as publisher  # type: ignore


REDUCTION_STATUS = "COMPLETE_ALL_FROZEN_G0_JOBS_REDUCED"


def _load_validated_job(
    record: Mapping[str, Any],
    *,
    root: Path,
    plan: Mapping[str, Any],
    lock: Mapping[str, Any],
    plan_context: Mapping[str, Any],
) -> tuple[Path, dict[str, Any]]:
    path = gov.workspace_path(root, record.get("path"), label="plan job")
    job = publisher.read_json_direct_rooted(
        root, path, label="materialized G0 job"
    )
    digest = gov.validate_job_payload(
        job,
        plan=plan,
        lock=lock,
        root=root,
        verify_inputs=True,
        _validated_plan_context=plan_context,
    )
    if digest != record.get("job_hash") or job.get("job_id") != record.get("job_id"):
        raise gov.G0GovernanceError("plan/job identity or self-hash mismatch")
    return path, job


def _expected_intent(
    job: Mapping[str, Any], plan: Mapping[str, Any], lock: Mapping[str, Any], *, root: Path
) -> dict[str, Any]:
    core = job["evaluation_job"]
    assert isinstance(core, Mapping)
    return publisher.build_publication_intent(
        root=root,
        job_id=str(job["job_id"]),
        job_hash=str(job["job_hash"]),
        plan_hash=str(plan["plan_hash"]),
        evaluation_lock_hash=str(lock["evaluation_lock_hash"]),
        backend_execution_lock_hash=str(job["backend_execution_lock_hash"]),
        g0_execution_authority_hash=str(job["g0_execution_authority_hash"]),
        evaluation_disposition=str(core["evaluation_disposition"]),
        output_dir=Path(str(job["output_dir_absolute"])),
    )


def _load_result(
    job: Mapping[str, Any],
    plan: Mapping[str, Any],
    lock: Mapping[str, Any],
    *,
    root: Path,
    plan_context: Mapping[str, Any],
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, object],
    dict[str, object],
]:
    expected = _expected_intent(job, plan, lock, root=root)
    intent_path = Path(str(expected["intent_path_absolute"]))
    closeout_path = Path(str(expected["closeout_path_absolute"]))
    destination = Path(str(expected["destination_absolute"]))
    intent = publisher.read_json_direct_rooted(
        root, intent_path, label="publication intent"
    )
    publisher.validate_publication_intent(intent, root=root)
    if intent != expected:
        raise gov.G0GovernanceError("publication intent differs from exact job authority")
    closeout = publisher.read_json_direct_rooted(
        root, closeout_path, label="publication closeout"
    )
    publisher.validate_closeout(closeout, intent=intent, root=root)
    with publisher.retained_sealed_result_snapshot(
        destination, intent=intent, root=root
    ) as snapshot:
        receipt, manifest_records, payload_bytes, seal_bytes = snapshot
        summary_records = [
            record
            for record in manifest_records
            if record.get("path") == publisher.BOUND_SUMMARY_NAME
        ]
        if len(summary_records) != 1:
            raise gov.G0GovernanceError(
                "result manifest does not bind one bound summary"
            )
        try:
            bound_bytes = payload_bytes[publisher.BOUND_SUMMARY_NAME]
            bound = gov._json_object_bytes(
                bound_bytes, label="retained bound G0 summary"
            )
        except (KeyError, gov.G0GovernanceError) as error:
            raise gov.G0GovernanceError(
                "retained bound G0 summary is invalid"
            ) from error
        expected_bound_record = {
            "path": publisher.BOUND_SUMMARY_NAME,
            "sha256": hashlib.sha256(bound_bytes).hexdigest(),
            "size_bytes": len(bound_bytes),
        }
        if dict(summary_records[0]) != expected_bound_record:
            raise gov.G0GovernanceError(
                "bound summary bytes differ from retained output manifest"
            )
        gov.validate_bound_summary(
            bound,
            job=job,
            plan=plan,
            lock=lock,
            root=root,
            verify_raw_summary=False,
            _validated_plan_context=plan_context,
        )
        raw_record = bound.get("raw_summary_artifact")
        if raw_record is not None:
            if not isinstance(raw_record, Mapping):
                raise gov.G0GovernanceError(
                    "retained bound summary raw artifact is invalid"
                )
            raw_absolute = gov.workspace_path(
                root, raw_record.get("path"), label="retained raw G0 summary"
            )
            try:
                raw_relative = raw_absolute.relative_to(destination).as_posix()
            except ValueError as error:
                raise gov.G0GovernanceError(
                    "raw G0 summary escapes retained result directory"
                ) from error
            if not raw_relative or raw_relative.startswith("../"):
                raise gov.G0GovernanceError(
                    "raw G0 summary has an unsafe retained path"
                )
            try:
                raw_bytes = payload_bytes[raw_relative]
                raw_summary = gov._json_object_bytes(
                    raw_bytes,
                    label="retained raw G0 summary",
                    require_canonical=False,
                )
            except (KeyError, gov.G0GovernanceError) as error:
                raise gov.G0GovernanceError(
                    "retained raw G0 summary is invalid"
                ) from error
            expected_raw_record = {
                "path": gov.display_path(root, raw_absolute),
                "sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "size_bytes": len(raw_bytes),
            }
            if dict(raw_record) != expected_raw_record or (
                gov.canonical_json_bytes(raw_summary)
                != gov.canonical_json_bytes(bound["g0_summary"])
            ):
                raise gov.G0GovernanceError(
                    "bound/raw G0 summary retained bytes differ"
                )
        if receipt.get("result_receipt_hash") != closeout.get(
            "result_receipt_hash"
        ):
            raise gov.G0GovernanceError(
                "retained result receipt differs from publication closeout"
            )
        receipt_bytes = seal_bytes[publisher.RECEIPT_NAME]
        manifest_bytes = seal_bytes[publisher.MANIFEST_NAME]
        receipt_record: dict[str, object] = {
            "path": gov.display_path(
                root, destination / publisher.RECEIPT_NAME
            ),
            "sha256": hashlib.sha256(receipt_bytes).hexdigest(),
            "size_bytes": len(receipt_bytes),
        }
        manifest_record: dict[str, object] = {
            "path": gov.display_path(
                root, destination / publisher.MANIFEST_NAME
            ),
            "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "size_bytes": len(manifest_bytes),
        }
        if closeout.get("receipt") != receipt_record or closeout.get(
            "output_manifest"
        ) != manifest_record:
            raise gov.G0GovernanceError(
                "retained seal bytes differ from publication closeout"
            )
    return bound, receipt, closeout, receipt_record, manifest_record


def build_full_reduction(
    plan: Mapping[str, Any],
    lock: Mapping[str, Any],
    *,
    root: Path,
) -> dict[str, Any]:
    lock_hash = gov.validate_lock_payload(lock, root=root, verify_files=True)
    plan_context: dict[str, Any] = {}
    plan_hash = gov.validate_plan_payload(
        plan, lock=lock, root=root, _context_out=plan_context
    )
    records_by_group: dict[tuple[str, str, str, str], list[dict[str, object]]] = (
        defaultdict(list)
    )
    receipt_bindings: list[dict[str, Any]] = []
    observed_jobs: set[str] = set()
    for membership in plan["jobs"]:
        if not isinstance(membership, Mapping):
            raise gov.G0GovernanceError("invalid plan job membership")
        _path, job = _load_validated_job(
            membership,
            root=root,
            plan=plan,
            lock=lock,
            plan_context=plan_context,
        )
        job_id = str(job["job_id"])
        if job_id in observed_jobs:
            raise gov.G0GovernanceError("duplicate reduction job_id")
        observed_jobs.add(job_id)
        bound, receipt, closeout, receipt_record, manifest_record = _load_result(
            job, plan, lock, root=root, plan_context=plan_context
        )
        core = job["evaluation_job"]
        assert isinstance(core, Mapping)
        reducer_records = evaluation.materialize_reducer_records(
            core, bound["g0_summary"]
        )
        for record in reducer_records:
            classification = record["classification"]
            assert isinstance(classification, Mapping)
            key = (
                str(classification["window_id"]),
                str(classification["arm"]),
                str(record["route"]),
                str(record["contrast_name"]),
            )
            records_by_group[key].append(record)
        receipt_bindings.append(
            {
                "job_id": job_id,
                "job_hash": job["job_hash"],
                "result_receipt_hash": receipt["result_receipt_hash"],
                "publication_closeout_hash": closeout["publication_closeout_hash"],
                "receipt": receipt_record,
                "output_manifest": manifest_record,
            }
        )
    expected_jobs = int(lock["evaluation_template"]["counts"]["g0_evaluation_jobs"])
    if len(observed_jobs) != expected_jobs:
        raise gov.G0GovernanceError("reduction does not cover every frozen G0 job")

    arm_reductions: list[dict[str, object]] = []
    reduction_by_key: dict[tuple[str, str, str], dict[str, object]] = {}
    for key in sorted(records_by_group):
        reduced = evaluation.reduce_window_arm_replays(records_by_group[key])
        arm_reductions.append(reduced)
        pair_key = (
            str(reduced["window_id"]),
            str(reduced["contrast_name"]),
            str(reduced["arm"]),
        )
        if pair_key in reduction_by_key:
            raise gov.G0GovernanceError("duplicate reduced window/contrast/arm")
        reduction_by_key[pair_key] = reduced

    pairwise: list[dict[str, object]] = []
    pair_groups: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for reduced in arm_reductions:
        if reduced["route"] == evaluation.ROUTE_PAIRWISE_COMMON_SUPPORT:
            pair_groups[(str(reduced["window_id"]), str(reduced["contrast_name"]))].append(
                reduced
            )
    for key in sorted(pair_groups):
        values = pair_groups[key]
        if len(values) != 2:
            raise gov.G0GovernanceError("pairwise reduction lacks exactly two arms")
        proposed = [item for item in values if item["arm"] == evaluation.ARM_P]
        comparator = [item for item in values if item["arm"] != evaluation.ARM_P]
        if len(proposed) != 1 or len(comparator) != 1:
            raise gov.G0GovernanceError("pairwise reduction arm roles are invalid")
        pairwise.append(evaluation.reduce_pairwise_contrast(proposed[0], comparator[0]))

    k = int(lock["evaluation_template"]["counts"]["applicable_d_windows"])
    if len(arm_reductions) != 100 + 2 * k or len(pairwise) != 40 + k:
        raise gov.G0GovernanceError("full reduction cardinality differs from template")
    payload: dict[str, Any] = {
        "schema_version": gov.REDUCTION_SCHEMA,
        "status": REDUCTION_STATUS,
        "evaluation_lock_hash": lock_hash,
        "plan_hash": plan_hash,
        "backend_execution_lock_hash": plan["plan_basis"][
            "backend_execution_lock_hash"
        ],
        "g0_execution_authority_hash": plan["plan_basis"][
            "g0_execution_authority_hash"
        ],
        "receipt_bindings": receipt_bindings,
        "window_arm_reductions": arm_reductions,
        "pairwise_contrasts": pairwise,
        "counts": {
            "jobs": len(observed_jobs),
            "receipts": len(receipt_bindings),
            "window_arm_reductions": len(arm_reductions),
            "pairwise_contrasts": len(pairwise),
            "applicable_d_windows": k,
        },
        "reduction_policy": {
            "equal_replay_index_jobs": True,
            "exact_replays_per_window_arm_contrast": 3,
            "minimum_evaluable_replays": 2,
            "hard_failure_any_of_three": True,
            "scientific_unit": "sequence_not_replay",
            "result_discovery_used": False,
        },
        "outcome_boundary": (
            "FROZEN_PLAN_RESULTS_ONLY_NO_UNBOUND_TRAJECTORY_OR_RESULT_DISCOVERY"
        ),
    }
    payload["full_reduction_hash"] = gov.canonical_json_hash(payload)
    _validate_full_reduction_static(payload, plan=plan, lock=lock)
    return payload


def _validate_full_reduction_static(
    payload: Mapping[str, Any], *, plan: Mapping[str, Any], lock: Mapping[str, Any]
) -> str:
    expected_top = {
        "schema_version",
        "status",
        "evaluation_lock_hash",
        "plan_hash",
        "backend_execution_lock_hash",
        "g0_execution_authority_hash",
        "receipt_bindings",
        "window_arm_reductions",
        "pairwise_contrasts",
        "counts",
        "reduction_policy",
        "outcome_boundary",
        "full_reduction_hash",
    }
    if set(payload) != expected_top:
        raise gov.G0GovernanceError("full reduction key set differs")
    if (
        payload.get("schema_version") != gov.REDUCTION_SCHEMA
        or payload.get("status") != REDUCTION_STATUS
    ):
        raise gov.G0GovernanceError("unexpected full reduction schema/status")
    digest = gov.validate_self_hash(
        payload, "full_reduction_hash", label="full G0 reduction"
    )
    if payload.get("plan_hash") != plan.get("plan_hash") or payload.get(
        "evaluation_lock_hash"
    ) != lock.get("evaluation_lock_hash"):
        raise gov.G0GovernanceError("full reduction authority binding mismatch")
    if (
        payload.get("backend_execution_lock_hash")
        != plan["plan_basis"].get("backend_execution_lock_hash")
        or payload.get("g0_execution_authority_hash")
        != plan["plan_basis"].get("g0_execution_authority_hash")
    ):
        raise gov.G0GovernanceError("full reduction execution authority mismatch")
    counts = payload.get("counts")
    if not isinstance(counts, Mapping):
        raise gov.G0GovernanceError("full reduction counts missing")
    k = int(lock["evaluation_template"]["counts"]["applicable_d_windows"])
    expected = {
        "jobs": 180 + 3 * k,
        "receipts": 180 + 3 * k,
        "window_arm_reductions": 100 + 2 * k,
        "pairwise_contrasts": 40 + k,
        "applicable_d_windows": k,
    }
    if dict(counts) != expected:
        raise gov.G0GovernanceError("full reduction counts are not frozen cardinalities")
    if len(payload.get("receipt_bindings", [])) != expected["receipts"]:
        raise gov.G0GovernanceError("full reduction receipt count mismatch")
    if len(payload.get("window_arm_reductions", [])) != expected[
        "window_arm_reductions"
    ]:
        raise gov.G0GovernanceError("full reduction window-arm count mismatch")
    if len(payload.get("pairwise_contrasts", [])) != expected["pairwise_contrasts"]:
        raise gov.G0GovernanceError("full reduction pairwise count mismatch")
    if payload.get("reduction_policy") != {
        "equal_replay_index_jobs": True,
        "exact_replays_per_window_arm_contrast": 3,
        "minimum_evaluable_replays": 2,
        "hard_failure_any_of_three": True,
        "scientific_unit": "sequence_not_replay",
        "result_discovery_used": False,
    } or payload.get("outcome_boundary") != (
        "FROZEN_PLAN_RESULTS_ONLY_NO_UNBOUND_TRAJECTORY_OR_RESULT_DISCOVERY"
    ):
        raise gov.G0GovernanceError("full reduction policy/boundary differs")
    receipt_bindings = payload.get("receipt_bindings")
    if not isinstance(receipt_bindings, list):
        raise gov.G0GovernanceError("full reduction receipt bindings are invalid")
    for record in receipt_bindings:
        if not isinstance(record, Mapping) or set(record) != {
            "job_id",
            "job_hash",
            "result_receipt_hash",
            "publication_closeout_hash",
            "receipt",
            "output_manifest",
        }:
            raise gov.G0GovernanceError("full reduction receipt binding shape differs")
        for key in ("receipt", "output_manifest"):
            artifact = record.get(key)
            if not isinstance(artifact, Mapping) or set(artifact) != {
                "path",
                "sha256",
                "size_bytes",
            }:
                raise gov.G0GovernanceError(
                    f"full reduction {key} record shape differs"
                )
    return digest


def validate_full_reduction(
    payload: Mapping[str, Any],
    *,
    plan: Mapping[str, Any],
    lock: Mapping[str, Any],
    root: Path,
) -> str:
    """Rebuild the reduction from sealed receipts and require byte-exact equality."""

    digest = _validate_full_reduction_static(payload, plan=plan, lock=lock)
    rebuilt = build_full_reduction(plan, lock, root=root)
    if gov.canonical_json_bytes(dict(payload)) != gov.canonical_json_bytes(rebuilt):
        raise gov.G0GovernanceError(
            "full reduction differs from deterministic sealed-result rebuild"
        )
    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=gov.ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    root = Path(os.path.abspath(os.fspath(args.root)))
    plan = publisher.read_json_direct_rooted(root, args.plan, label="G0 plan")
    lock = publisher.read_json_direct_rooted(root, args.lock, label="G0 lock")
    payload = build_full_reduction(plan, lock, root=root)
    if args.publish:
        if args.output is None:
            raise SystemExit("--publish requires --output")
        publisher.write_json_exclusive_rooted(root, args.output, payload)
    elif args.output is not None:
        raise SystemExit("--output without --publish is forbidden")
    print(json.dumps(payload if not args.publish else {
        "status": payload["status"],
        "full_reduction_hash": payload["full_reduction_hash"],
        "counts": payload["counts"],
        "output": os.fspath(args.output),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
