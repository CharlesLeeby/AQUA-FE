#!/usr/bin/env python3
"""Validate one P07 backend replay input without launching VINS or reading outcomes."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

try:
    from scripts import p07_backend_replay_common_v1 as common
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import p07_backend_replay_common_v1 as common  # type: ignore


NATIVEQ_CONTRACT_HASH = "39eaea6d26e6f5a881ef2b17b898cbda75c7aba8087ce447fe897e2fe0bdfce0"
M_CONTRACT_HASH = "4e31a9a29e8ee2198535de6b0bce01550b17077434e8e01ed68057822d4eace4"
SCHEMA_VERSION = "isj-p07-backend-replay-input-check-v1"
ALLOWED_FRONTEND_AUDIT_SCHEMAS = {
    "isj-p07-b1-frontend-export-audit-v2",
    "isj-p07-mp-frontend-export-audit-v2",
    "isj-p07-a01-frontend-export-audit-v3",
    "isj-p07-frontend-export-audit-v3",
    "isj-p07-frontend-export-audit-v4",
}


def _load_hash_bound_json(path: Path, expected_hash: str, *, label: str) -> dict[str, Any]:
    if common.sha256(path) != expected_hash:
        raise common.BackendReplayViolation(f"{label} SHA-256 mismatch: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise common.BackendReplayViolation(f"invalid {label} JSON: {path}") from error
    if not isinstance(payload, dict):
        raise common.BackendReplayViolation(f"{label} is not a JSON object")
    return payload


def _same_regular_file(left: Path, raw_right: str, root: Path) -> bool:
    try:
        right = common.workspace_path(root, raw_right, label="attested feature bag")
        return os.path.samefile(left, right)
    except (OSError, common.BackendReplayViolation):
        return False


def _validate_attestation(
    row: Mapping[str, str],
    *,
    root: Path,
    bag_path: Path,
    canonical_bag_path: Path,
    attestation_path: Path,
) -> dict[str, Any]:
    payload = _load_hash_bound_json(
        attestation_path, row["attestation_sha256"], label="bag attestation"
    )
    arm = row["arm"]
    expected_bag_hash = row["feature_bag_sha256"]
    if payload.get("contract_pass") is not True:
        raise common.BackendReplayViolation("bag attestation is not contract PASS")
    if payload.get("feature_bag_sha256") != expected_bag_hash:
        raise common.BackendReplayViolation("attestation/bag SHA binding mismatch")
    if not _same_regular_file(
        canonical_bag_path, str(payload.get("feature_bag", "")), root
    ):
        raise common.BackendReplayViolation("attestation names a different feature bag")

    if arm == common.M_ARM:
        if (
            payload.get("schema_version") != "aqua-fe-p05-xfeat-bag-attestation-v1"
            or payload.get("status") != "PASS"
            or payload.get("baseline_id") != common.M_ARM
            or payload.get("backend_contract_hash") != M_CONTRACT_HASH
        ):
            raise common.BackendReplayViolation("M attestation identity/contract mismatch")
    elif arm in common.NATIVEQ_ARMS:
        if (
            payload.get("schema_version") != "aqua-fe-nativeq-bag-attestation-v1"
            or payload.get("backend_contract_hash") != NATIVEQ_CONTRACT_HASH
        ):
            raise common.BackendReplayViolation("native-q attestation identity/contract mismatch")
    else:
        raise common.BackendReplayViolation(f"attestation is not valid for arm {arm}")
    return payload


def _validate_frontend_audit(
    row: Mapping[str, str],
    payload: Mapping[str, Any],
    *,
    root: Path,
    bag_path: Path,
    canonical_bag_path: Path,
    attestation_path: Path,
    canonical_attestation_path: Path,
) -> None:
    schema = str(payload.get("schema_version", ""))
    if schema not in ALLOWED_FRONTEND_AUDIT_SCHEMAS:
        raise common.BackendReplayViolation("input audit is not a P07 frontend export audit")
    if (
        payload.get("status") != "PASS"
        or payload.get("window_id") != row["window_id"]
        or payload.get("arm") != row["arm"]
        or payload.get("held_out_trajectory_outcome_read") is not False
        or payload.get("forbidden_outcome_artifacts") != []
    ):
        raise common.BackendReplayViolation("frontend input audit identity/status mismatch")
    feature = payload.get("feature_bag")
    attestation = payload.get("attestation")
    if not isinstance(feature, dict) or not isinstance(attestation, dict):
        raise common.BackendReplayViolation("frontend audit lacks bag/attestation records")
    if feature.get("sha256") != row["feature_bag_sha256"]:
        raise common.BackendReplayViolation("frontend audit feature-bag SHA mismatch")
    if not _same_regular_file(
        canonical_bag_path, str(feature.get("path", "")), root
    ):
        raise common.BackendReplayViolation("frontend audit names a different feature bag")
    if attestation.get("sha256") != row["attestation_sha256"]:
        raise common.BackendReplayViolation("frontend audit attestation SHA mismatch")
    try:
        audited_attestation = common.workspace_path(
            root, str(attestation.get("path", "")), label="audited attestation"
        )
    except common.BackendReplayViolation as error:
        raise common.BackendReplayViolation("frontend audit attestation path is invalid") from error
    if not os.path.samefile(canonical_attestation_path, audited_attestation):
        raise common.BackendReplayViolation("frontend audit names a different attestation")


def _validate_exact_drop_audit(
    row: Mapping[str, str],
    payload: Mapping[str, Any],
    *,
    root: Path,
    bag_path: Path,
    canonical_bag_path: Path,
) -> None:
    if (
        payload.get("schema_version") != "aqua-fe-whole-lineage-exact-drop-audit-v1"
        or payload.get("contract_pass") is not True
        or payload.get("decision") != "PASS_EXACT_WHOLE_LINEAGE_DROP"
        or payload.get("forbidden_outcomes_accessed") != []
    ):
        raise common.BackendReplayViolation("D exact-drop audit did not PASS exactly")
    inputs = payload.get("inputs")
    checks = payload.get("checks")
    if not isinstance(inputs, dict) or not isinstance(checks, dict):
        raise common.BackendReplayViolation("D exact-drop audit is incomplete")
    if inputs.get("drop_bag_sha256") != row["feature_bag_sha256"]:
        raise common.BackendReplayViolation("D audit drop-bag SHA mismatch")
    if not _same_regular_file(
        canonical_bag_path, str(inputs.get("drop_bag", "")), root
    ):
        raise common.BackendReplayViolation("D audit names a different drop bag")
    required = {
        "drop_feature_payload_equals_filtered_proposed_payload_byte_for_byte",
        "learned_births_and_all_lineage_continuations_absent_from_drop",
        "message_count_order_topic_type_md5_record_timestamp_exact",
        "non_dropped_observation_order_fields_channels_exact",
        "nonfeature_serialized_bytes_exact",
    }
    if any(checks.get(name) is not True for name in required):
        raise common.BackendReplayViolation("D exact-drop audit lacks a required exact check")


def check_row_inputs(
    row: Mapping[str, str],
    *,
    root: Path = common.ROOT,
    bag_path_override: Path | None = None,
    attestation_path_override: Path | None = None,
    input_audit_path_override: Path | None = None,
) -> dict[str, Any]:
    common.validate_queue_row(row)
    if row["arm"] == common.B0_ARM:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "queue_index": int(row["queue_index"]),
            "run_id": row["run_id"],
            "arm": row["arm"],
            "feature_bag_reuse": False,
            "checks": {
                "b0_reuse_fields_empty": True,
                "feature_bag_not_opened": True,
                "trajectory_outcome_read": False,
            },
        }

    canonical_bag_path = common.workspace_path(
        root, row["feature_bag"], label="feature bag"
    )
    canonical_attestation_path = common.workspace_path(
        root, row["attestation_path"], label="bag attestation"
    )
    canonical_audit_path = common.workspace_path(
        root, row["input_audit_path"], label="input audit"
    )
    bag_path = bag_path_override or canonical_bag_path
    attestation_path = attestation_path_override or canonical_attestation_path
    audit_path = input_audit_path_override or canonical_audit_path
    expected_run = common.output_path(root, row["expected_run_dir"], label="expected run dir")
    expected_attempt = common.output_path(
        root, row["expected_attempt_dir"], label="expected attempt dir"
    )
    for output in (expected_run, expected_attempt):
        try:
            if os.path.commonpath([canonical_bag_path, output]) == os.fspath(output):
                raise common.BackendReplayViolation("feature bag is inside a replay output path")
        except ValueError:
            pass

    observed_bag_hash = common.sha256(bag_path)
    if observed_bag_hash != row["feature_bag_sha256"]:
        raise common.BackendReplayViolation("feature bag SHA differs from frozen queue")
    attestation = _validate_attestation(
        row,
        root=root,
        bag_path=bag_path,
        canonical_bag_path=canonical_bag_path,
        attestation_path=attestation_path,
    )
    audit = _load_hash_bound_json(
        audit_path, row["input_audit_sha256"], label="input audit"
    )
    if row["arm"] == common.D_ARM:
        _validate_exact_drop_audit(
            row,
            audit,
            root=root,
            bag_path=bag_path,
            canonical_bag_path=canonical_bag_path,
        )
    else:
        _validate_frontend_audit(
            row,
            audit,
            root=root,
            bag_path=bag_path,
            canonical_bag_path=canonical_bag_path,
            attestation_path=attestation_path,
            canonical_attestation_path=canonical_attestation_path,
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "queue_index": int(row["queue_index"]),
        "run_id": row["run_id"],
        "window_id": row["window_id"],
        "arm": row["arm"],
        "feature_bag_reuse": True,
        "feature_bag": {
            "path": common.display_path(root, canonical_bag_path),
            "sha256": observed_bag_hash,
            "size_bytes": bag_path.stat().st_size,
        },
        "attestation": {
            "path": common.display_path(root, canonical_attestation_path),
            "sha256": row["attestation_sha256"],
            "schema_version": attestation.get("schema_version"),
        },
        "input_audit": {
            "path": common.display_path(root, canonical_audit_path),
            "sha256": row["input_audit_sha256"],
            "schema_version": audit.get("schema_version"),
            "decision": audit.get("decision", audit.get("status")),
        },
        "checks": {
            "queue_bag_hash_exact": True,
            "attestation_hash_and_bag_binding_exact": True,
            "input_audit_hash_and_bag_binding_exact": True,
            "whole_lineage_exact_drop_required_for_d": row["arm"] == common.D_ARM,
            "trajectory_outcome_read": False,
            "consumer_bytes_from_sealed_overrides": all(
                value is not None
                for value in (
                    bag_path_override,
                    attestation_path_override,
                    input_audit_path_override,
                )
            ),
        },
    }


def load_bound_row(
    index: int,
    *,
    root: Path,
    queue_path: Path,
    allocation_path: Path,
) -> tuple[dict[str, str], dict[str, str]]:
    row = common.indexed_row(queue_path, index)
    allocation = common.indexed_row(allocation_path, index)
    common.validate_queue_row(row)
    common.validate_allocation(row, allocation)
    return row, allocation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-index", type=int, required=True)
    parser.add_argument("--root", type=Path, default=common.ROOT)
    parser.add_argument("--queue", type=Path, default=common.DEFAULT_QUEUE)
    parser.add_argument("--allocation", type=Path, default=common.DEFAULT_ALLOCATION)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    row, _allocation = load_bound_row(
        args.queue_index,
        root=args.root,
        queue_path=args.queue,
        allocation_path=args.allocation,
    )
    report = check_row_inputs(row, root=args.root)
    if args.output is not None:
        common.write_json_exclusive(args.output, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
