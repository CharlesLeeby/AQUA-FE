#!/usr/bin/env python3
"""Validate the frozen P07 backend queue without opening trajectory outcomes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence

try:
    from scripts import build_p07_backend_replay_queue_v1 as builder
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_backend_replay_queue_v1 as builder  # type: ignore


OUTPUT = builder.P07 / "backend_queue_validation_v1.json"
REPORT_SCHEMA = "isj-p07-backend-queue-validation-v1"
HEX64 = re.compile(r"[0-9a-f]{64}")


def parse_csv(content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(content.decode("utf-8"), newline=""))
    fields = list(reader.fieldnames or [])
    rows = list(reader)
    if not fields or len(fields) != len(set(fields)) or any(None in row for row in rows):
        raise ValueError("invalid or ragged CSV bytes")
    return fields, rows


def _safe_relative(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(path.parts) and not path.is_absolute() and ".." not in path.parts


def _hash_at_root(root: Path, relative: str) -> str:
    return str(_record_at_root(root, relative)["sha256"])


def _record_at_root(root: Path, relative: str) -> dict[str, object]:
    if not _safe_relative(relative):
        raise ValueError(f"unsafe repository-relative path: {relative!r}")
    return dict(
        builder.rooted_io.direct_file_record_bound_input_rooted(
            root,
            root.joinpath(*PurePosixPath(relative).parts),
            label="backend queue validator artifact",
        )
    )


def _json_at_root(root: Path, relative: str) -> dict[str, object]:
    if not _safe_relative(relative):
        raise ValueError(f"unsafe repository-relative path: {relative!r}")
    content = builder.rooted_io.read_bytes_bound_input_rooted(
        root,
        root.joinpath(*PurePosixPath(relative).parts),
        label="backend queue validator JSON",
    )
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError(f"formal JSON must be an object: {relative}")
    return value


def _expected_run_dir(row: Mapping[str, str]) -> str:
    return (
        f"{builder.runner_root(row['dataset_family'])}/{row['runner_mode']}_"
        f"{row['runner_method']}_every{row['runner_every_n']}_{row['runner_tag']}"
    )


def _frozen_arm_orders(
    arm_order_rows: Sequence[Mapping[str, str]],
) -> dict[str, list[str]]:
    grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in arm_order_rows:
        grouped[str(row["window_id"])].append(row)
    return {
        window: [
            str(row["arm"])
            for row in sorted(rows, key=lambda item: int(item["order_position"]))
        ]
        for window, rows in grouped.items()
    }


def validate_artifacts(
    *,
    queue_content: bytes,
    allocation_content: bytes,
    lock_payload: Mapping[str, object],
    arm_order_rows: Sequence[Mapping[str, str]],
    root: Path = builder.ROOT,
    verify_source_files: bool = True,
    verify_locked_artifacts: bool = True,
    require_evaluator_correction: bool = True,
) -> list[str]:
    issues: list[str] = []
    try:
        queue_fields, queue = parse_csv(queue_content)
        allocation_fields, allocations = parse_csv(allocation_content)
    except (UnicodeDecodeError, ValueError) as exc:
        return [f"csv_parse:{exc}"]
    if queue_fields != builder.QUEUE_FIELDS:
        issues.append("queue_header_mismatch")
    if allocation_fields != builder.ALLOCATION_FIELDS:
        issues.append("allocation_header_mismatch")
    if lock_payload.get("schema_version") != builder.LOCK_SCHEMA:
        issues.append("queue_lock_schema_mismatch")
    if lock_payload.get("status") != "FROZEN_BACKEND_QUEUE_AWAITING_EXECUTION_LOCK":
        issues.append("queue_lock_status_mismatch")
    if lock_payload.get("backend_queue_lock_hash") != builder.lock_hash(lock_payload):
        issues.append("queue_lock_self_hash_mismatch")
    queue_record = lock_payload.get("backend_replay_queue")
    if not isinstance(queue_record, dict):
        issues.append("queue_lock_missing_queue_record")
    else:
        if queue_record.get("sha256") != builder.sha256_bytes(queue_content):
            issues.append("queue_content_hash_mismatch")
        if int(queue_record.get("size_bytes", -1)) != len(queue_content):
            issues.append("queue_content_size_mismatch")
        if queue_record.get("path") != builder.display_path(builder.BACKEND_QUEUE):
            issues.append("queue_content_path_mismatch")

    if not queue:
        issues.append("empty_queue")
        return sorted(set(issues))
    indices = [int(row["queue_index"]) for row in queue]
    if indices != list(range(1, len(queue) + 1)):
        issues.append("queue_indices_not_contiguous")
    if len({row["run_id"] for row in queue}) != len(queue):
        issues.append("duplicate_run_id")
    if len({row["expected_run_dir"] for row in queue}) != len(queue):
        issues.append("duplicate_expected_run_dir")
    if len({row["expected_attempt_dir"] for row in queue}) != len(queue):
        issues.append("duplicate_expected_attempt_dir")
    if not 240 <= len(queue) <= 300:
        issues.append("queue_count_outside_240_300")

    arm_counts = Counter(row["arm"] for row in queue)
    for arm in builder.REQUIRED_ARMS:
        if arm_counts[arm] != 60:
            issues.append(f"required_arm_count:{arm}:{arm_counts[arm]}")
    if arm_counts[builder.D_ARM] % 3 or arm_counts[builder.D_ARM] > 60:
        issues.append("conditional_d_count_invalid")
    if set(arm_counts).difference(builder.ALL_ARMS):
        issues.append("retired_or_unknown_arm_present")
    expected_jobs = 240 + arm_counts[builder.D_ARM]
    if len(queue) != expected_jobs:
        issues.append("base_plus_conditional_count_mismatch")
    if int(lock_payload.get("backend_replay_jobs", -1)) != len(queue):
        issues.append("queue_lock_job_count_mismatch")
    if int(lock_payload.get("conditional_d_jobs", -1)) != arm_counts[builder.D_ARM]:
        issues.append("queue_lock_d_job_count_mismatch")

    hashes_by_name = {
        "method_lock_hash",
        "environment_manifest_sha256",
        "evaluator_protocol_sha256",
        "evaluator_implementation_sha256",
        "failure_taxonomy_sha256",
    }
    for name in hashes_by_name:
        values = {row[name] for row in queue}
        if len(values) != 1 or not all(HEX64.fullmatch(value) for value in values):
            issues.append(f"invalid_or_mixed_hash:{name}")
    precision_correction = lock_payload.get("evaluator_precision_correction")
    epoch_correction = lock_payload.get("evaluator_epoch_ns_correction")
    if require_evaluator_correction:
        registry_prefix = lock_payload.get("mutable_registry_prefix")
        if (
            not isinstance(registry_prefix, dict)
            or registry_prefix.get("path") != builder.display_path(builder.RUN_REGISTRY)
        ):
            issues.append("mutable_registry_prefix_missing")
        if not isinstance(precision_correction, dict) or not isinstance(
            precision_correction.get("lock"), dict
        ):
            issues.append("evaluator_precision_correction_missing")
        else:
            lock_record = precision_correction["lock"]
            if (
                lock_record.get("path")
                != builder.display_path(builder.EVALUATOR_CORRECTION_LOCK)
                or not HEX64.fullmatch(
                    str(precision_correction.get("correction_lock_hash", ""))
                )
            ):
                issues.append("evaluator_precision_correction_identity_mismatch")
            if verify_locked_artifacts:
                try:
                    precision_relative = str(lock_record.get("path", ""))
                    observed = _hash_at_root(root, precision_relative)
                    precision_payload = _json_at_root(root, precision_relative)
                except (
                    FileNotFoundError,
                    ValueError,
                    builder.formal_io.FormalIOError,
                    builder.rooted_io.gov.G0GovernanceError,
                ):
                    issues.append("evaluator_precision_correction_lock_missing")
                else:
                    if observed != lock_record.get("sha256"):
                        issues.append("evaluator_precision_correction_lock_hash_drift")
                    precision_self_hash = str(
                        precision_payload.get("correction_lock_hash", "")
                    )
                    precision_clone = dict(precision_payload)
                    precision_clone.pop("correction_lock_hash", None)
                    if (
                        precision_payload.get("schema_version")
                        != "isj-p07-evaluator-precision-correction-lock-v1"
                        or precision_payload.get("status")
                        != "FROZEN_OUTCOME_BLIND_ADDITIVE_EVALUATOR_PRECISION_CORRECTION"
                        or precision_self_hash
                        != builder.sha256_bytes(
                            builder.canonical_json(precision_clone).encode("utf-8")
                        )
                        or precision_correction.get("correction_lock_hash")
                        != precision_self_hash
                    ):
                        issues.append(
                            "evaluator_precision_correction_self_hash_mismatch"
                        )
        if not isinstance(epoch_correction, dict) or not isinstance(
            epoch_correction.get("lock"), dict
        ):
            issues.append("evaluator_epoch_ns_correction_missing")
        else:
            implementation_values = {
                row["evaluator_implementation_sha256"] for row in queue
            }
            if implementation_values != {
                str(epoch_correction.get("implementation_bundle_sha256", ""))
            }:
                issues.append("evaluator_epoch_ns_correction_bundle_mismatch")
            lock_record = epoch_correction["lock"]
            if (
                lock_record.get("path")
                != builder.display_path(builder.EVALUATOR_EPOCH_CORRECTION_LOCK)
                or not HEX64.fullmatch(
                    str(epoch_correction.get("epoch_ns_correction_lock_hash", ""))
                )
                or epoch_correction.get("entrypoint")
                != "scripts/evaluate_vins_common_support_epoch_v2.py"
            ):
                issues.append("evaluator_epoch_ns_correction_identity_mismatch")
            if verify_locked_artifacts:
                try:
                    epoch_relative = str(lock_record.get("path", ""))
                    observed = _hash_at_root(root, epoch_relative)
                    epoch_payload = _json_at_root(root, epoch_relative)
                except (
                    FileNotFoundError,
                    ValueError,
                    builder.formal_io.FormalIOError,
                    builder.rooted_io.gov.G0GovernanceError,
                ):
                    issues.append("evaluator_epoch_ns_correction_lock_missing")
                else:
                    if observed != lock_record.get("sha256"):
                        issues.append("evaluator_epoch_ns_correction_lock_hash_drift")
                    try:
                        epoch_self_hash = builder.epoch_correction.validate_lock_payload(
                            epoch_payload, root=root, verify_files=True
                        )
                    except ValueError:
                        issues.append("evaluator_epoch_ns_correction_semantics_invalid")
                    else:
                        epoch_implementation = epoch_payload[
                            "corrected_implementation_binding"
                        ]
                        parent = epoch_payload["parent_precision_correction_lock"]
                        precision_metadata = (
                            precision_correction
                            if isinstance(precision_correction, dict)
                            else {}
                        )
                        precision_lock_metadata = precision_metadata.get("lock")
                        if not isinstance(precision_lock_metadata, dict):
                            precision_lock_metadata = {}
                        if (
                            epoch_correction.get("epoch_ns_correction_lock_hash")
                            != epoch_self_hash
                            or epoch_correction.get("entrypoint")
                            != epoch_implementation.get("entrypoint")
                            or epoch_correction.get("implementation_bundle_sha256")
                            != epoch_implementation.get(
                                "implementation_bundle_sha256"
                            )
                            or parent.get("correction_lock_hash")
                            != precision_metadata.get("correction_lock_hash")
                            or any(
                                parent.get(key)
                                != precision_lock_metadata.get(key)
                                for key in ("path", "sha256", "size_bytes")
                            )
                        ):
                            issues.append(
                                "evaluator_epoch_ns_correction_parent_or_metadata_mismatch"
                            )

    d_resolution_items = [
        item
        for item in lock_payload.get("d_resolutions", [])
        if isinstance(item, dict)
    ]
    d_resolution_map = {
        str(item.get("window_id")): str(item.get("resolution"))
        for item in d_resolution_items
    }
    if len(d_resolution_map) != 20 or set(d_resolution_map.values()).difference(
        {"APPLICABLE", "NOT_APPLICABLE"}
    ):
        issues.append("d_resolution_lock_map_invalid")
    if len(d_resolution_items) != 20:
        issues.append("d_resolution_lock_items_invalid")
    for item in d_resolution_items:
        provenance_payload = item.get("resolution_provenance")
        expected_hash = str(item.get("resolution_provenance_hash", ""))
        if (
            not isinstance(provenance_payload, dict)
            or not HEX64.fullmatch(expected_hash)
            or builder.frontend_provenance.provenance_hash(provenance_payload)
            != expected_hash
            or provenance_payload.get("window_id") != item.get("window_id")
            or provenance_payload.get("resolution") != item.get("resolution")
            or int(provenance_payload.get("slot_index", -1))
            != int(item.get("slot_index", -2))
            or provenance_payload.get("held_out_trajectory_outcome_read") is not False
        ):
            issues.append(f"d_resolution_provenance:{item.get('window_id')}")

    expected_orders = _frozen_arm_orders(arm_order_rows)
    order_identity = {
        (str(item["window_id"]), str(item["arm"])): item
        for item in arm_order_rows
    }
    by_window: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in queue:
        by_window[row["window_id"]].append(row)
        if row["schema_version"] != builder.SCHEMA:
            issues.append(f"queue_schema:{row['queue_index']}")
        if row["status"] != "PLANNED" or row["outcome_boundary"] != builder.OUTCOME_BOUNDARY:
            issues.append(f"queue_state_or_boundary:{row['queue_index']}")
        if row["capacity_policy"] != builder.CAPACITY_POLICY:
            issues.append(f"capacity_policy:{row['queue_index']}")
        frozen_order = order_identity.get((row["window_id"], row["arm"]))
        if frozen_order is None or (
            row["assignment_rank"] != str(frozen_order["assignment_rank"])
            or row["pattern_id"] != str(frozen_order["pattern_id"])
            or row["arm_order_position"] != str(frozen_order["order_position"])
            or row["arm_role"] != str(frozen_order["arm_role"])
        ):
            issues.append(f"arm_order_identity:{row['queue_index']}")
        if int(row["replay_index"]) not in {1, 2, 3}:
            issues.append(f"replay_index:{row['queue_index']}")
        if row["algorithmic_slot"] != f"b{int(row['replay_index']):02d}":
            issues.append(f"algorithmic_slot:{row['queue_index']}")
        expected_mode = "origin" if row["arm"] == builder.B0 else "external"
        expected_method = "xfeat" if row["arm"] == builder.M_ARM else "klt"
        if (
            row["runner_mode"] != expected_mode
            or row["runner_method"] != expected_method
            or row["runner_every_n"] != "2"
            or row["expected_run_dir"] != _expected_run_dir(row)
        ):
            issues.append(f"runner_identity:{row['queue_index']}")
        try:
            argv = json.loads(row["replay_argv_json"])
        except json.JSONDecodeError:
            argv = None
        expected_argv = [
            "python3",
            "scripts/run_p07_backend_replay_job_v1.py",
            "--queue-index",
            row["queue_index"],
            "--execution-lock",
            (
                "papers/ieee_sensors_journal_experiments/p07/"
                "backend_replay_execution_lock_v1.json"
            ),
        ]
        if argv != expected_argv:
            issues.append(f"replay_argv:{row['queue_index']}")
        if row["replay_argv_sha256"] != builder.sha256_bytes(
            row["replay_argv_json"].encode("utf-8")
        ):
            issues.append(f"replay_argv_hash:{row['queue_index']}")
        if not _safe_relative(row["expected_run_dir"]) or not _safe_relative(
            row["expected_attempt_dir"]
        ):
            issues.append(f"unsafe_output_path:{row['queue_index']}")
        source_fields = (
            "feature_bag",
            "feature_bag_sha256",
            "attestation_path",
            "attestation_sha256",
            "input_audit_path",
            "input_audit_sha256",
        )
        provenance_fields = (
            "source_run_id",
            "source_provenance_kind",
            "source_provenance_hash",
        )
        if any(not row[field] for field in provenance_fields) or not HEX64.fullmatch(
            row["source_provenance_hash"]
        ):
            issues.append(f"source_provenance_fields:{row['queue_index']}")
        if row["arm"] == builder.B0:
            if any(row[field] for field in source_fields):
                issues.append(f"b0_has_external_source:{row['queue_index']}")
            if row["source_frontend_queue_index"] or row["source_d_slot_index"]:
                issues.append(f"b0_has_source_index:{row['queue_index']}")
            if (
                row["source_run_id"]
                != f"B0_NATIVE_DATA:{row['window_id']}"
                or row["source_provenance_kind"] != builder.B0_PROVENANCE_KIND
            ):
                issues.append(f"b0_source_provenance_identity:{row['queue_index']}")
        else:
            if any(not row[field] for field in source_fields):
                issues.append(f"feature_arm_missing_source:{row['queue_index']}")
            for field in (
                "feature_bag_sha256",
                "attestation_sha256",
                "input_audit_sha256",
            ):
                if not HEX64.fullmatch(row[field]):
                    issues.append(f"source_hash_invalid:{row['queue_index']}:{field}")
            if row["arm"] == builder.D_ARM:
                if row["source_frontend_queue_index"] or not row["source_d_slot_index"]:
                    issues.append(f"d_source_index:{row['queue_index']}")
                if row["source_provenance_kind"] != builder.D_PROVENANCE_KIND:
                    issues.append(f"d_source_provenance_kind:{row['queue_index']}")
            elif not row["source_frontend_queue_index"] or row["source_d_slot_index"]:
                issues.append(f"frontend_source_index:{row['queue_index']}")
            elif row["source_provenance_kind"] not in {
                builder.frontend_provenance.CANONICAL,
                builder.frontend_provenance.AUDITOR_CORRECTION,
                builder.frontend_provenance.Q55_REPLACEMENT,
                builder.frontend_provenance.Q58_ORPHAN,
            }:
                issues.append(f"frontend_source_provenance_kind:{row['queue_index']}")
            if verify_source_files:
                for path_field, hash_field in (
                    ("feature_bag", "feature_bag_sha256"),
                    ("attestation_path", "attestation_sha256"),
                    ("input_audit_path", "input_audit_sha256"),
                ):
                    try:
                        observed = _hash_at_root(root, row[path_field])
                    except (
                        FileNotFoundError,
                        ValueError,
                        builder.rooted_io.gov.G0GovernanceError,
                    ):
                        issues.append(
                            f"source_file_missing_or_unsafe:{row['queue_index']}:{path_field}"
                        )
                    else:
                        if observed != row[hash_field]:
                            issues.append(
                                f"source_file_hash_drift:{row['queue_index']}:{path_field}"
                            )

    for window_id, rows in by_window.items():
        ordered = sorted(rows, key=lambda row: int(row["queue_index"]))
        grouped_arms: list[str] = []
        grouped_slots: dict[str, list[int]] = defaultdict(list)
        for row in ordered:
            if not grouped_arms or grouped_arms[-1] != row["arm"]:
                grouped_arms.append(row["arm"])
            grouped_slots[row["arm"]].append(int(row["replay_index"]))
        expected = [
            arm
            for arm in expected_orders.get(window_id, [])
            if arm in builder.REQUIRED_ARMS
            or (arm == builder.D_ARM and d_resolution_map.get(window_id) == "APPLICABLE")
        ]
        if grouped_arms != expected:
            issues.append(f"williams_order:{window_id}")
        if any(slots != [1, 2, 3] for slots in grouped_slots.values()):
            issues.append(f"nonserial_three_replays:{window_id}")
        has_d = builder.D_ARM in grouped_slots
        if has_d != (d_resolution_map.get(window_id) == "APPLICABLE"):
            issues.append(f"d_applicability_queue_mismatch:{window_id}")
    assignment_order = [
        int(rows[0]["assignment_rank"])
        for _window, rows in sorted(
            by_window.items(), key=lambda item: int(item[1][0]["queue_index"])
        )
    ]
    if assignment_order != sorted(assignment_order) or assignment_order != list(range(1, 21)):
        issues.append("assignment_rank_order")

    if len(allocations) != len(queue):
        issues.append("allocation_count_mismatch")
    allocation_by_index = {int(row["queue_index"]): row for row in allocations}
    if len(allocation_by_index) != len(allocations):
        issues.append("allocation_duplicate_queue_index")
    lock_hash_value = str(lock_payload.get("backend_queue_lock_hash", ""))
    join_fields = (
        "run_id",
        "window_id",
        "dataset_family",
        "sequence",
        "window_start_s",
        "window_end_s",
        "arm",
        "replay_index",
        "algorithmic_slot",
        "source_frontend_queue_index",
        "source_run_id",
        "source_provenance_kind",
        "source_provenance_hash",
        "feature_bag",
        "feature_bag_sha256",
        "attestation_path",
        "attestation_sha256",
        "expected_run_dir",
        "expected_attempt_dir",
    )
    for row in queue:
        index = int(row["queue_index"])
        allocation = allocation_by_index.get(index)
        if allocation is None:
            issues.append(f"allocation_missing:{index}")
            continue
        if allocation["schema_version"] != builder.ALLOCATION_SCHEMA:
            issues.append(f"allocation_schema:{index}")
        if any(allocation[field] != row[field] for field in join_fields):
            issues.append(f"allocation_join_mismatch:{index}")
        if (
            allocation["backend_replay"] != row["algorithmic_slot"]
            or allocation["allocated_at"] != str(lock_payload.get("frozen_at", ""))
            or allocation["status"] != "PLANNED"
            or allocation["method_lock_hash"] != row["method_lock_hash"]
            or allocation["backend_queue_lock_hash"] != lock_hash_value
            or allocation["outcome_boundary"] != builder.OUTCOME_BOUNDARY
        ):
            issues.append(f"allocation_contract:{index}")

    source_lock = {
        (str(item.get("window_id")), str(item.get("arm"))): item
        for item in lock_payload.get("source_evidence", [])
        if isinstance(item, dict)
    }
    row_sources = {
        (row["window_id"], row["arm"]): row
        for row in queue
    }
    if set(source_lock) != set(row_sources):
        issues.append("locked_source_set_mismatch")
    else:
        for key, row in row_sources.items():
            item = source_lock[key]
            for field in (
                "feature_bag",
                "feature_bag_sha256",
                "attestation_path",
                "attestation_sha256",
                "input_audit_path",
                "input_audit_sha256",
                "source_run_id",
                "source_provenance_kind",
                "source_provenance_hash",
            ):
                if str(item.get(field, "")) != row[field]:
                    issues.append(f"locked_source_value_mismatch:{key}:{field}")
            provenance_payload = item.get("source_provenance")
            if (
                not isinstance(provenance_payload, dict)
                or builder.frontend_provenance.provenance_hash(provenance_payload)
                != row["source_provenance_hash"]
                or provenance_payload.get("kind")
                != row["source_provenance_kind"]
                or provenance_payload.get("source_run_id")
                != row["source_run_id"]
                or provenance_payload.get("window_id") != row["window_id"]
                or provenance_payload.get("held_out_trajectory_outcome_read") is not False
            ):
                issues.append(f"locked_source_provenance_mismatch:{key}")
                continue
            if row["arm"] == builder.B0:
                manifest_row = provenance_payload.get("dataset_manifest_row")
                if (
                    provenance_payload.get("schema_version")
                    != "isj-p07-backend-b0-native-data-provenance-v1"
                    or not isinstance(manifest_row, dict)
                    or provenance_payload.get("dataset_manifest_row_sha256")
                    != builder.sha256_bytes(
                        builder.canonical_json(manifest_row).encode("utf-8")
                    )
                    or any(
                        str(manifest_row.get(field, "")) != row[field]
                        for field in (
                            "window_id",
                            "dataset_family",
                            "sequence",
                            "window_start_s",
                            "window_end_s",
                        )
                    )
                ):
                    issues.append(f"b0_locked_manifest_provenance:{key}")
            elif row["arm"] != builder.D_ARM:
                if provenance_payload.get("arm") != row["arm"]:
                    issues.append(f"frontend_locked_arm_provenance:{key}")

            if verify_source_files:
                records: list[object] = []
                if row["arm"] not in {builder.B0, builder.D_ARM}:
                    records.extend(
                        [
                            provenance_payload.get("audit"),
                            provenance_payload.get("output_hash_manifest"),
                        ]
                    )
                    governance = provenance_payload.get("governance_records")
                    if not isinstance(governance, list):
                        issues.append(f"frontend_governance_records:{key}")
                    else:
                        records.extend(governance)
                for record in records:
                    if not isinstance(record, dict):
                        issues.append(f"source_provenance_record_invalid:{key}")
                        continue
                    try:
                        relative = str(record.get("path", ""))
                        observed_record = _record_at_root(root, relative)
                        observed_hash = observed_record["sha256"]
                        observed_size = observed_record["size_bytes"]
                    except (
                        FileNotFoundError,
                        ValueError,
                        builder.rooted_io.gov.G0GovernanceError,
                    ):
                        issues.append(f"source_provenance_record_missing:{key}")
                    else:
                        if (
                            observed_hash != record.get("sha256")
                            or observed_size != int(record.get("size_bytes", -1))
                        ):
                            issues.append(f"source_provenance_record_drift:{key}")

    if verify_locked_artifacts:
        for item in lock_payload.get("artifacts", []):
            if not isinstance(item, dict):
                issues.append("locked_artifact_record_invalid")
                continue
            try:
                path = str(item["path"])
                observed_record = _record_at_root(root, path)
                observed_hash = observed_record["sha256"]
                observed_size = observed_record["size_bytes"]
            except (
                KeyError,
                FileNotFoundError,
                ValueError,
                builder.rooted_io.gov.G0GovernanceError,
            ):
                issues.append("locked_artifact_missing_or_unsafe")
                continue
            if observed_hash != item.get("sha256") or observed_size != int(
                item.get("size_bytes", -1)
            ):
                issues.append(f"locked_artifact_drift:{path}")
        for item in lock_payload.get("mutable_stream_prefix_snapshots", []):
            if not isinstance(item, dict):
                issues.append("mutable_prefix_record_invalid")
                continue
            try:
                relative = str(item["path"])
                if not _safe_relative(relative):
                    raise ValueError(relative)
                path = root.joinpath(*PurePosixPath(relative).parts)
                content = builder.rooted_io.read_bytes_bound_input_rooted(
                    root, path, label="backend mutable prefix"
                )
                size = int(item["size_bytes"])
            except (KeyError, FileNotFoundError, ValueError):
                issues.append("mutable_prefix_missing_or_unsafe")
                continue
            if len(content) < size or hashlib.sha256(content[:size]).hexdigest() != item.get(
                "sha256"
            ):
                issues.append(f"mutable_prefix_drift:{relative}")
    return sorted(set(issues))


def build_report(*, live_rebuild: bool = True) -> dict[str, object]:
    queue_content = builder.rooted_io.read_bytes_bound_input_rooted(
        builder.ROOT, builder.BACKEND_QUEUE, label="backend replay queue"
    )
    allocation_content = builder.rooted_io.read_bytes_bound_input_rooted(
        builder.ROOT, builder.BACKEND_ALLOCATION, label="backend allocation"
    )
    lock_content = builder.rooted_io.read_bytes_bound_input_rooted(
        builder.ROOT, builder.BACKEND_QUEUE_LOCK, label="backend queue lock"
    )
    lock_payload = json.loads(lock_content)
    arm_content = builder.rooted_io.read_bytes_bound_input_rooted(
        builder.ROOT, builder.ARM_ORDER, label="backend arm order"
    )
    _arm_fields, arm_order_rows = builder._parse_csv_content(
        builder.ARM_ORDER, arm_content
    )
    issues = validate_artifacts(
        queue_content=queue_content,
        allocation_content=allocation_content,
        lock_payload=lock_payload,
        arm_order_rows=arm_order_rows,
    )
    deterministic: dict[str, bool] = {}
    if live_rebuild:
        try:
            snapshot = builder.collect_live_snapshot()
            rebuilt = builder.build_outputs(
                snapshot, allocated_at=str(lock_payload["frozen_at"])
            )
        except Exception as exc:  # Preserve the exact validation failure in the report.
            issues.append(f"live_rebuild_failed:{type(exc).__name__}:{exc}")
        else:
            deterministic = {
                "queue_byte_identical": rebuilt[builder.BACKEND_QUEUE] == queue_content,
                "allocation_byte_identical": (
                    rebuilt[builder.BACKEND_ALLOCATION] == allocation_content
                ),
                "queue_lock_semantic_identical": (
                    json.loads(rebuilt[builder.BACKEND_QUEUE_LOCK]) == lock_payload
                ),
            }
            if not all(deterministic.values()):
                issues.append("deterministic_live_rebuild_mismatch")
    return {
        "schema_version": REPORT_SCHEMA,
        "status": "PASS" if not issues else "REVISE",
        "backend_queue_lock_hash": lock_payload.get("backend_queue_lock_hash"),
        "backend_replay_jobs": int(lock_payload.get("backend_replay_jobs", 0)),
        "conditional_d_jobs": int(lock_payload.get("conditional_d_jobs", 0)),
        "live_rebuild_requested": live_rebuild,
        "deterministic_live_rebuild": deterministic,
        "artifacts": {
            "queue_sha256": builder.sha256_bytes(queue_content),
            "allocation_sha256": builder.sha256_bytes(allocation_content),
            "queue_lock_sha256": builder.sha256(builder.BACKEND_QUEUE_LOCK),
        },
        "issues": sorted(set(issues)),
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": builder.OUTCOME_BOUNDARY,
    }


def write_no_clobber(path: Path, payload: Mapping[str, object]) -> None:
    builder.formal_io.publish_json_no_clobber(
        builder.ROOT,
        path.absolute().relative_to(builder.ROOT.absolute()).as_posix(),
        payload,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--structural-only", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    report = build_report(live_rebuild=not args.structural_only)
    if args.write:
        if args.structural_only:
            parser.error("canonical validation publication requires a live rebuild")
        if report["status"] != "PASS" or not all(
            report.get("deterministic_live_rebuild", {}).values()
        ):
            raise ValueError(
                "refusing to occupy canonical validation path with a non-live PASS"
            )
        write_no_clobber(OUTPUT, report)
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    print(
        f"P07_BACKEND_QUEUE_VALIDATION_{report['status']} "
        f"jobs={report['backend_replay_jobs']} d_jobs={report['conditional_d_jobs']}"
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
