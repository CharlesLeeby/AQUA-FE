#!/usr/bin/env python3
"""Build the additive, outcome-blind ROS bag epoch-ns evaluator correction.

The default command is read-only and prints a deterministic preview.  Only an
explicit ``--write`` may publish the future formal lock, using the shared
no-clobber formal publisher.  This builder reads only the exact governance and
source allowlist below; it never reads trajectories, APE/RPE, or result files.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from scripts import p07_backend_formal_io_v1 as formal_io
except ModuleNotFoundError:
    import p07_backend_formal_io_v1 as formal_io  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "evaluator_epoch_ns_correction_lock_v1.json"
)
PARENT_LOCK_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "evaluator_precision_correction_lock_v1.json"
)
PROTOCOL_RELATIVE = "papers/ieee_sensors_journal_experiments/evaluator_protocol_v1.md"
BASE_RELATIVE = "scripts/evaluate_vins_common_support.py"
CORE_RELATIVE = "scripts/trajectory_eval_core.py"
WRAPPER_RELATIVE = "scripts/evaluate_vins_common_support_epoch_v2.py"
BUILDER_RELATIVE = "scripts/build_p07_evaluator_epoch_ns_correction_lock_v1.py"
TEST_RELATIVE = "scripts/tests/test_p07_evaluator_epoch_ns_correction_v1.py"

SCHEMA_VERSION = "isj-p07-evaluator-epoch-ns-correction-lock-v1"
STATUS = "FROZEN_OUTCOME_BLIND_ADDITIVE_ROS_BAG_EPOCH_NS_CORRECTION"
SELF_HASH_FIELD = "epoch_ns_correction_lock_hash"
BASE_SHA256 = "ab6f2b5c1a10a41463657edee2724c022fc0248dc885096acb336e602384c110"
PARENT_SCHEMA = "isj-p07-evaluator-precision-correction-lock-v1"
PARENT_STATUS = "FROZEN_OUTCOME_BLIND_ADDITIVE_EVALUATOR_PRECISION_CORRECTION"
OUTCOME_BOUNDARY = "SOURCE_AND_GOVERNANCE_ONLY_NO_REAL_TRAJECTORY_APE_RPE_RESULT_READ"

ALLOWED_READ_PATHS = (
    PARENT_LOCK_RELATIVE,
    PROTOCOL_RELATIVE,
    BASE_RELATIVE,
    CORE_RELATIVE,
    WRAPPER_RELATIVE,
    BUILDER_RELATIVE,
    TEST_RELATIVE,
)


def canonical_json_hash(
    payload: Mapping[str, Any], excluded_key: str | None = None
) -> str:
    clone = dict(payload)
    if excluded_key is not None:
        clone.pop(excluded_key, None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("frozen_at must include a timezone")
    return value


def _record(root: Path, relative: str) -> tuple[dict[str, object], bytes]:
    content, identity = formal_io.read_direct_bytes(root, relative)
    return (
        {
            "path": relative,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        },
        content,
    )


def _json_object(content: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {label} JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _require_parent_file(
    parent: Mapping[str, Any], *, path: str, expected_sha256: str | None = None
) -> dict[str, Any]:
    binding = parent.get("corrected_implementation_binding")
    files = binding.get("files") if isinstance(binding, Mapping) else None
    if not isinstance(files, list):
        raise ValueError("parent precision lock lacks implementation files")
    matches = [item for item in files if isinstance(item, dict) and item.get("path") == path]
    if len(matches) != 1:
        raise ValueError(f"parent precision lock must bind exactly one {path}")
    record = dict(matches[0])
    if expected_sha256 is not None and record.get("sha256") != expected_sha256:
        raise ValueError(f"parent precision lock {path} SHA mismatch")
    return record


def _implementation_bundle_hash(records: Sequence[Mapping[str, object]]) -> str:
    encoded = json.dumps(
        list(records), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_lock_payload(
    payload: Mapping[str, Any], *, root: Path, verify_files: bool = True
) -> str:
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("status") != STATUS:
        raise ValueError("unexpected epoch-ns correction schema/status")
    observed = payload.get(SELF_HASH_FIELD)
    if observed != canonical_json_hash(payload, SELF_HASH_FIELD):
        raise ValueError("epoch-ns correction self-hash mismatch")
    expected_top_keys = {
        "schema_version",
        "status",
        "frozen_at",
        "parent_precision_correction_lock",
        "corrected_implementation_binding",
        "protocol_binding",
        "epoch_ns_correction",
        "governance_artifacts",
        "outcome_blind_audit",
        "scientific_method_identity",
        "correction_kind",
        "outcome_boundary",
        "next_action",
        SELF_HASH_FIELD,
    }
    if set(payload) != expected_top_keys:
        raise ValueError("epoch-ns correction top-level key set mismatch")
    if not isinstance(payload.get("frozen_at"), str):
        raise ValueError("epoch-ns correction frozen_at is invalid")
    _timestamp(str(payload["frozen_at"]))
    parent = payload.get("parent_precision_correction_lock")
    implementation = payload.get("corrected_implementation_binding")
    protocol = payload.get("protocol_binding")
    audit = payload.get("outcome_blind_audit")
    if not isinstance(parent, Mapping) or parent.get("correction_lock_hash") is None:
        raise ValueError("epoch-ns correction lacks parent lock binding")
    if not isinstance(implementation, Mapping):
        raise ValueError("epoch-ns correction lacks implementation binding")
    files = implementation.get("files")
    expected_paths = [BASE_RELATIVE, CORE_RELATIVE, WRAPPER_RELATIVE]
    if not isinstance(files, list) or [item.get("path") for item in files if isinstance(item, Mapping)] != expected_paths:
        raise ValueError("epoch-ns correction implementation paths differ")
    if implementation.get("entrypoint") != WRAPPER_RELATIVE:
        raise ValueError("epoch-ns correction entrypoint differs")
    if implementation.get("base_evaluator_sha256") != BASE_SHA256:
        raise ValueError("epoch-ns correction base evaluator SHA differs")
    if implementation.get("implementation_bundle_sha256") != _implementation_bundle_hash(files):
        raise ValueError("epoch-ns correction implementation bundle hash mismatch")
    if set(implementation) != {
        "entrypoint",
        "base_evaluator_sha256",
        "files",
        "implementation_bundle_sha256",
        "adapter_scope",
        "base_main_called",
        "base_loader_restored_in_finally",
        "sealed_base_core_procfd_required_at_formal_execution",
        "sealed_module_environment",
        "required_for_all_new_p07_g0_evaluation",
    } or any(
        implementation.get(key) is not True
        for key in (
            "base_main_called",
            "base_loader_restored_in_finally",
            "sealed_base_core_procfd_required_at_formal_execution",
            "required_for_all_new_p07_g0_evaluation",
        )
    ) or implementation.get("adapter_scope") != (
        "ROS_BAG_HEADER_STAMP_INTEGER_SECS_NSECS_TO_LONGDOUBLE_ONLY"
    ) or implementation.get("sealed_module_environment") != {
        "base": "AQUAFE_P07_SEALED_EVALUATOR_BASE",
        "core": "AQUAFE_P07_SEALED_EVALUATOR_CORE",
    }:
        raise ValueError("epoch-ns correction implementation semantics differ")
    if not isinstance(protocol, Mapping) or protocol.get("unchanged") is not True:
        raise ValueError("epoch-ns correction protocol is not frozen unchanged")
    if payload.get("epoch_ns_correction") != {
        "old_ros_bag_conversion": "float(message.header.stamp.to_sec())",
        "new_ros_bag_conversion": "np.longdouble(secs)+np.longdouble(nsecs)/1e9",
        "secs_nsecs_must_be_exact_python_ints": True,
        "bool_rejected": True,
        "nsecs_range": "0<=nsecs<1000000000",
        "metric_protocol_changed": False,
        "real_outcome_equivalence_claimed": False,
    }:
        raise ValueError("epoch-ns correction semantic literals differ")
    required_false = (
        "workspace_discovery_used",
        "real_trajectory_artifact_read",
        "ape_artifact_read",
        "rpe_artifact_read",
        "result_artifact_read",
        "vins_executed",
        "evaluator_executed",
        "evaluation_plan_generated",
        "backend_queue_generated",
    )
    if not isinstance(audit, Mapping) or any(audit.get(key) is not False for key in required_false):
        raise ValueError("epoch-ns correction outcome-blind audit is not all false")
    expected_audit = {
        "builder_allowed_read_paths": list(ALLOWED_READ_PATHS),
        **{key: False for key in required_false},
    }
    if dict(audit) != expected_audit:
        raise ValueError("epoch-ns correction outcome-blind audit differs")
    if payload.get("outcome_boundary") != OUTCOME_BOUNDARY:
        raise ValueError("epoch-ns correction outcome boundary differs")
    if (
        payload.get("scientific_method_identity") != "UNCHANGED_FROM_NATIVEQ_V3"
        or payload.get("correction_kind")
        != "ADDITIVE_ROS_BAG_TIMESTAMP_REPRESENTATION_CORRECTION"
        or payload.get("next_action")
        != "FREEZE_THIS_LOCK_BEFORE_BACKEND_QUEUE_AND_G0_LOCK"
    ):
        raise ValueError("epoch-ns correction governance literals differ")
    if verify_files:
        parent_record, parent_bytes = _record(root, PARENT_LOCK_RELATIVE)
        parent_payload = _json_object(parent_bytes, label="parent precision lock")
        if (
            parent_payload.get("schema_version") != PARENT_SCHEMA
            or parent_payload.get("status") != PARENT_STATUS
            or parent_payload.get("correction_lock_hash")
            != canonical_json_hash(parent_payload, "correction_lock_hash")
        ):
            raise ValueError("current parent precision lock is invalid")
        expected_parent = {
            **parent_record,
            "correction_lock_hash": parent_payload["correction_lock_hash"],
            "schema_version": parent_payload["schema_version"],
            "status": parent_payload["status"],
        }
        if dict(parent) != expected_parent:
            raise ValueError("epoch-ns correction exact parent binding differs")
        parent_protocol = parent_payload.get("protocol_binding")
        if not isinstance(parent_protocol, Mapping):
            raise ValueError("parent precision protocol binding is invalid")
        current_protocol, _protocol_bytes = _record(root, PROTOCOL_RELATIVE)
        expected_protocol = {
            **current_protocol,
            "parent_sha256": parent_protocol.get("current_sha256"),
            "unchanged": True,
            "protocol_identity": parent_protocol.get("protocol_identity"),
        }
        if dict(protocol) != expected_protocol:
            raise ValueError("epoch-ns correction exact protocol binding differs")
        expected_files = [
            _record(root, relative)[0]
            for relative in (BASE_RELATIVE, CORE_RELATIVE, WRAPPER_RELATIVE)
        ]
        if files != expected_files:
            raise ValueError("epoch-ns correction exact implementation records differ")
        records: list[Mapping[str, Any]] = [parent, *files]
        governance = payload.get("governance_artifacts")
        expected_governance = [
            _record(root, BUILDER_RELATIVE)[0],
            _record(root, TEST_RELATIVE)[0],
        ]
        if not isinstance(governance, list) or governance != expected_governance:
            raise ValueError("epoch-ns correction governance artifacts are invalid")
        records.extend(item for item in governance if isinstance(item, Mapping))
        records.append(protocol)
        for record in records:
            path = record.get("path")
            if not isinstance(path, str):
                raise ValueError("epoch-ns correction file record lacks path")
            current, _content = _record(root, path)
            expected = {key: record.get(key) for key in ("path", "sha256", "size_bytes")}
            if current != expected:
                raise ValueError(f"epoch-ns correction file drift: {path}")
    return str(observed)


def build_lock(
    *,
    root: Path = ROOT,
    frozen_at: str,
    require_output_absent: bool = True,
) -> dict[str, Any]:
    root = root.absolute()
    if require_output_absent and formal_io.destination_exists(root, OUTPUT_RELATIVE):
        raise FileExistsError(OUTPUT_RELATIVE)
    material = {relative: _record(root, relative) for relative in ALLOWED_READ_PATHS}
    records = {relative: pair[0] for relative, pair in material.items()}
    parent = _json_object(material[PARENT_LOCK_RELATIVE][1], label="parent precision lock")
    if parent.get("schema_version") != PARENT_SCHEMA or parent.get("status") != PARENT_STATUS:
        raise ValueError("unexpected parent precision correction lock")
    if parent.get("correction_lock_hash") != canonical_json_hash(parent, "correction_lock_hash"):
        raise ValueError("parent precision correction self-hash mismatch")
    parent_base = _require_parent_file(parent, path=BASE_RELATIVE, expected_sha256=BASE_SHA256)
    parent_core = _require_parent_file(parent, path=CORE_RELATIVE)
    if records[BASE_RELATIVE] != parent_base or records[CORE_RELATIVE] != parent_core:
        raise ValueError("parent precision implementation file drift")
    parent_protocol = parent.get("protocol_binding")
    if (
        not isinstance(parent_protocol, Mapping)
        or parent_protocol.get("unchanged") is not True
        or records[PROTOCOL_RELATIVE]["sha256"] != parent_protocol.get("current_sha256")
    ):
        raise ValueError("evaluator protocol drifted after parent correction")
    wrapper_text = material[WRAPPER_RELATIVE][1].decode("utf-8")
    required_markers = (
        "def ros_stamp_to_longdouble",
        'getattr(stamp, "secs", None)',
        'getattr(stamp, "nsecs", None)',
        "np.longdouble(secs)",
        "base.load_ros_reference = load_ros_reference",
        "finally:",
    )
    if any(marker not in wrapper_text for marker in required_markers):
        raise ValueError("additive epoch-ns wrapper marker is missing")
    if "message.header.stamp.to_sec" in wrapper_text:
        raise ValueError("additive epoch-ns wrapper still calls Time.to_sec")
    implementation_records = [
        records[BASE_RELATIVE],
        records[CORE_RELATIVE],
        records[WRAPPER_RELATIVE],
    ]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "frozen_at": _timestamp(frozen_at),
        "parent_precision_correction_lock": {
            **records[PARENT_LOCK_RELATIVE],
            "correction_lock_hash": parent["correction_lock_hash"],
            "schema_version": parent["schema_version"],
            "status": parent["status"],
        },
        "corrected_implementation_binding": {
            "entrypoint": WRAPPER_RELATIVE,
            "base_evaluator_sha256": BASE_SHA256,
            "files": implementation_records,
            "implementation_bundle_sha256": _implementation_bundle_hash(
                implementation_records
            ),
            "adapter_scope": "ROS_BAG_HEADER_STAMP_INTEGER_SECS_NSECS_TO_LONGDOUBLE_ONLY",
            "base_main_called": True,
            "base_loader_restored_in_finally": True,
            "sealed_base_core_procfd_required_at_formal_execution": True,
            "sealed_module_environment": {
                "base": "AQUAFE_P07_SEALED_EVALUATOR_BASE",
                "core": "AQUAFE_P07_SEALED_EVALUATOR_CORE",
            },
            "required_for_all_new_p07_g0_evaluation": True,
        },
        "protocol_binding": {
            **records[PROTOCOL_RELATIVE],
            "parent_sha256": parent_protocol["current_sha256"],
            "unchanged": True,
            "protocol_identity": parent_protocol.get("protocol_identity"),
        },
        "epoch_ns_correction": {
            "old_ros_bag_conversion": "float(message.header.stamp.to_sec())",
            "new_ros_bag_conversion": "np.longdouble(secs)+np.longdouble(nsecs)/1e9",
            "secs_nsecs_must_be_exact_python_ints": True,
            "bool_rejected": True,
            "nsecs_range": "0<=nsecs<1000000000",
            "metric_protocol_changed": False,
            "real_outcome_equivalence_claimed": False,
        },
        "governance_artifacts": [records[BUILDER_RELATIVE], records[TEST_RELATIVE]],
        "outcome_blind_audit": {
            "builder_allowed_read_paths": list(ALLOWED_READ_PATHS),
            "workspace_discovery_used": False,
            "real_trajectory_artifact_read": False,
            "ape_artifact_read": False,
            "rpe_artifact_read": False,
            "result_artifact_read": False,
            "vins_executed": False,
            "evaluator_executed": False,
            "evaluation_plan_generated": False,
            "backend_queue_generated": False,
        },
        "scientific_method_identity": "UNCHANGED_FROM_NATIVEQ_V3",
        "correction_kind": "ADDITIVE_ROS_BAG_TIMESTAMP_REPRESENTATION_CORRECTION",
        "outcome_boundary": OUTCOME_BOUNDARY,
        "next_action": "FREEZE_THIS_LOCK_BEFORE_BACKEND_QUEUE_AND_G0_LOCK",
    }
    payload[SELF_HASH_FIELD] = canonical_json_hash(payload, SELF_HASH_FIELD)
    validate_lock_payload(payload, root=root, verify_files=True)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--frozen-at", required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    payload = build_lock(root=args.root, frozen_at=args.frozen_at)
    if args.write:
        formal_io.publish_json_no_clobber(args.root.absolute(), OUTPUT_RELATIVE, payload)
    print(
        json.dumps(
            {
                "mode": "FORMAL_NO_CLOBBER_WRITE" if args.write else "READ_ONLY_PREVIEW",
                "path": OUTPUT_RELATIVE,
                SELF_HASH_FIELD: payload[SELF_HASH_FIELD],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
