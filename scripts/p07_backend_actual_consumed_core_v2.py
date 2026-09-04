#!/usr/bin/env python3
"""Pure nonformal map of the inputs actually consumed by the 240 P07 runs.

The core has no publication, network, ROS, bag-reading, or execution effects.
It consumes a strictly validated B0 core plus the frozen queue authority and
normalizes them into content objects, path locations, 80 window/arm cells, and
240 immutable queue bindings.  Unknown NTNU derived-bag hashes remain explicit
and block execution; this module never invents a content identity for them.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

try:
    from scripts import p07_backend_b0_plan_v2 as b0
except ModuleNotFoundError:  # direct ``python scripts/...`` import
    import p07_backend_b0_plan_v2 as b0  # type: ignore


SCHEMA_VERSION = "isj-p07-backend-actual-consumed-core-v2"
STATUS = "NONFORMAL_VALIDATED_MAPPING_NOT_EXECUTION_AUTHORITY"
SELF_HASH_FIELD = "actual_consumed_core_hash"
OUTCOME_BOUNDARY = "ACTUAL_CONSUMED_INPUT_MAPPING_ONLY_NO_VINS_APE_RPE_TRAJECTORY"

ARMS = tuple(b0.ARMS)
B0_ARM = b0.B0_ARM
EXPECTED_FEATURE_CONTENT_SHA_COUNT = 40

AFRL_CAMERA_PATH = b0.AFRL_BUS_CAMCHAIN_PATH
AFRL_CAMERA_SHA256 = b0.AFRL_BUS_CAMCHAIN_SHA256
AFRL_IMU_PATH = b0.AFRL_IMU_PATH
AFRL_IMU_SHA256 = b0.AFRL_IMU_SHA256

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")
_FORBIDDEN_RUNTIME_PATH_FRAGMENTS = (
    "data_eligibility_manifest",
    "reference_audit",
    "groundtruth_files",
    "_raw_data.tar",
    "raw_input",
)

_CONTENT_TYPES = {
    "ROS1_BAG",
    "JSON_FEATURE_ATTESTATION",
    "JSON_FRONTEND_INPUT_AUDIT",
    "YAML_CAMERA_CALIBRATION",
    "YAML_IMU_CALIBRATION",
}
_ROLE_ORDER = (
    "REPLAY_BAG",
    "FEATURE_BAG",
    "FEATURE_ATTESTATION",
    "FRONTEND_INPUT_AUDIT",
    "PREPARATION_BAG",
    "AFRL_BUS_CAMCHAIN",
    "AFRL_IMU_CALIBRATION",
)


class ActualConsumedCoreV2Error(RuntimeError):
    """The consumed-input mapping is incomplete, ambiguous, or drifted."""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ActualConsumedCoreV2Error("value is not canonical JSON") from error


def _clone(value: Any) -> Any:
    return json.loads(_canonical(value))


def document_hash(payload: Mapping[str, Any], field: str) -> str:
    clone = dict(payload)
    clone.pop(field, None)
    return hashlib.sha256(_canonical(clone).encode("utf-8")).hexdigest()


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ActualConsumedCoreV2Error("invalid %s SHA-256" % label)
    return value


def _path(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("/")
        or ".." in value.split("/")
        or _SAFE_PATH.fullmatch(value) is None
    ):
        raise ActualConsumedCoreV2Error("invalid %s path" % label)
    return value


def _detached_authorities(
    validated_b0_core: Mapping[str, Any], frozen_queue_authority: Mapping[str, Any]
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    core_before = _canonical(validated_b0_core)
    core = json.loads(core_before)
    b0.validate_core_plan(core)
    if _canonical(validated_b0_core) != core_before:
        raise ActualConsumedCoreV2Error("B0 core changed while snapshotted")

    queue_before = _canonical(frozen_queue_authority)
    try:
        rows = b0._rows_from_queue_authority(frozen_queue_authority)
    except b0.B0CorePlanV2Error as error:
        raise ActualConsumedCoreV2Error("frozen queue authority is invalid") from error
    if _canonical(frozen_queue_authority) != queue_before:
        raise ActualConsumedCoreV2Error("queue authority changed while snapshotted")
    try:
        live_rows = b0._rows_from_queue_authority(b0.load_live_queue_authority())
    except b0.B0CorePlanV2Error as error:
        raise ActualConsumedCoreV2Error("live frozen queue authority is invalid") from error
    if rows != live_rows:
        raise ActualConsumedCoreV2Error(
            "supplied queue authority does not equal the exact frozen queue bytes"
        )
    return core, _clone(rows)


def _content_object_id(content_type: str, sha256: str) -> str:
    seed = {
        "schema_version": SCHEMA_VERSION,
        "content_type": content_type,
        "sha256": sha256,
    }
    return hashlib.sha256(_canonical(seed).encode("utf-8")).hexdigest()


def _location_id(path: str) -> str:
    seed = {"schema_version": SCHEMA_VERSION, "path": path}
    return hashlib.sha256(_canonical(seed).encode("utf-8")).hexdigest()


def _cell_id(window_id: str, arm: str) -> str:
    seed = {"schema_version": SCHEMA_VERSION, "window_id": window_id, "arm": arm}
    return hashlib.sha256(_canonical(seed).encode("utf-8")).hexdigest()


def _build_body(core: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    entries = core.get("entries")
    mappings = core.get("preparation_mappings")
    if not isinstance(entries, list) or not isinstance(mappings, list):
        raise ActualConsumedCoreV2Error("B0 core input lists are absent")
    entry_by_window = {str(entry["window_id"]): entry for entry in entries}
    mapping_by_index = {int(row["queue_index"]): row for row in mappings}
    if len(entry_by_window) != 20 or len(mapping_by_index) != 240 or len(rows) != 240:
        raise ActualConsumedCoreV2Error("B0/queue cardinality differs")

    content_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    locations_by_path: Dict[str, Dict[str, Any]] = {}

    def add_location(
        path: str,
        content_type: str,
        sha256: Any,
        size_bytes: Any,
        identity_status: str,
    ) -> str:
        canonical_path = _path(path, "runtime location")
        if any(fragment in canonical_path for fragment in _FORBIDDEN_RUNTIME_PATH_FRAGMENTS):
            raise ActualConsumedCoreV2Error("forbidden non-runtime path entered locations")
        if content_type not in _CONTENT_TYPES:
            raise ActualConsumedCoreV2Error("unknown content type")
        object_id = None
        canonical_sha = None
        if sha256 is not None:
            canonical_sha = _sha(sha256, "content")
            key = (content_type, canonical_sha)
            object_id = _content_object_id(*key)
            content_by_key.setdefault(
                key,
                {
                    "content_object_id": object_id,
                    "content_type": content_type,
                    "sha256": canonical_sha,
                },
            )
        if size_bytes is not None and (type(size_bytes) is not int or size_bytes <= 0):
            raise ActualConsumedCoreV2Error("location size is invalid")
        record = {
            "location_id": _location_id(canonical_path),
            "path": canonical_path,
            "content_type": content_type,
            "content_object_id": object_id,
            "sha256": canonical_sha,
            "size_bytes": size_bytes,
            "identity_status": identity_status,
        }
        previous = locations_by_path.get(canonical_path)
        if previous is not None and previous != record:
            raise ActualConsumedCoreV2Error("one path has conflicting content identity")
        locations_by_path[canonical_path] = record
        return str(record["location_id"])

    preparation_location_by_window: Dict[str, str] = {}
    for window_id, entry in entry_by_window.items():
        target = entry.get("target")
        if not isinstance(target, Mapping):
            raise ActualConsumedCoreV2Error("B0 target is absent")
        preparation_location_by_window[window_id] = add_location(
            str(target.get("path")),
            "ROS1_BAG",
            target.get("content_sha256"),
            target.get("size_bytes"),
            str(target.get("identity_status")),
        )

    camera_location = add_location(
        AFRL_CAMERA_PATH,
        "YAML_CAMERA_CALIBRATION",
        AFRL_CAMERA_SHA256,
        None,
        "FROZEN_EXACT_CALIBRATION_SHA256",
    )
    imu_location = add_location(
        AFRL_IMU_PATH,
        "YAML_IMU_CALIBRATION",
        AFRL_IMU_SHA256,
        None,
        "FROZEN_EXACT_CALIBRATION_SHA256",
    )

    queue_cells: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
    queue_bindings: List[Dict[str, Any]] = []
    for raw_row in rows:
        try:
            queue_index = int(raw_row["queue_index"])
            replay_index = int(raw_row["replay_index"])
            window_id = str(raw_row["window_id"])
            arm = str(raw_row["arm"])
            run_id = str(raw_row["run_id"])
        except (KeyError, TypeError, ValueError) as error:
            raise ActualConsumedCoreV2Error("queue identity is malformed") from error
        mapping = mapping_by_index.get(queue_index)
        if (
            mapping is None
            or window_id not in entry_by_window
            or arm not in ARMS
            or replay_index not in (1, 2, 3)
            or mapping.get("run_id") != run_id
            or mapping.get("window_id") != window_id
            or mapping.get("arm") != arm
            or mapping.get("replay_index") != replay_index
        ):
            raise ActualConsumedCoreV2Error("queue/B0 mapping identity differs")
        key = (window_id, arm)
        queue_cells.setdefault(key, []).append(raw_row)
        queue_bindings.append(
            {
                "queue_index": queue_index,
                "run_id": run_id,
                "immutable_queue_row_hash": mapping["immutable_queue_row_hash"],
                "window_id": window_id,
                "arm": arm,
                "replay_index": replay_index,
                "cell_id": _cell_id(window_id, arm),
            }
        )

    expected_cells = {(window_id, arm) for window_id in entry_by_window for arm in ARMS}
    if set(queue_cells) != expected_cells:
        raise ActualConsumedCoreV2Error("queue does not form exact 20 x 4 cells")

    cells: List[Dict[str, Any]] = []
    for window_id in sorted(entry_by_window):
        entry = entry_by_window[window_id]
        for arm in ARMS:
            cell_rows = sorted(queue_cells[(window_id, arm)], key=lambda row: int(row["replay_index"]))
            if [int(row["replay_index"]) for row in cell_rows] != [1, 2, 3]:
                raise ActualConsumedCoreV2Error("cell does not contain exact three replays")
            bindings: List[Dict[str, str]] = []
            preparation_id = preparation_location_by_window[window_id]
            if arm == B0_ARM:
                bindings.extend(
                    [
                        {"role": "REPLAY_BAG", "location_id": preparation_id},
                        {"role": "PREPARATION_BAG", "location_id": preparation_id},
                    ]
                )
                for row in cell_rows:
                    if any(
                        row.get(key)
                        for key in (
                            "feature_bag", "feature_bag_sha256", "attestation_path",
                            "attestation_sha256", "input_audit_path", "input_audit_sha256",
                        )
                    ):
                        raise ActualConsumedCoreV2Error("B0 cell contains frontend artifacts")
            else:
                fields = (
                    "feature_bag", "feature_bag_sha256", "attestation_path",
                    "attestation_sha256", "input_audit_path", "input_audit_sha256",
                )
                frozen = tuple(cell_rows[0].get(field) for field in fields)
                if any(tuple(row.get(field) for field in fields) != frozen for row in cell_rows[1:]):
                    raise ActualConsumedCoreV2Error("three replays do not reuse one frontend cell")
                feature_path, feature_sha, att_path, att_sha, audit_path, audit_sha = frozen
                feature_id = add_location(
                    str(feature_path), "ROS1_BAG", feature_sha, None,
                    "FROZEN_QUEUE_FEATURE_CONTENT_SHA256",
                )
                attestation_id = add_location(
                    str(att_path), "JSON_FEATURE_ATTESTATION", att_sha, None,
                    "FROZEN_QUEUE_ATTESTATION_SHA256",
                )
                audit_id = add_location(
                    str(audit_path), "JSON_FRONTEND_INPUT_AUDIT", audit_sha, None,
                    "FROZEN_QUEUE_INPUT_AUDIT_SHA256",
                )
                bindings.extend(
                    [
                        {"role": "FEATURE_BAG", "location_id": feature_id},
                        {"role": "FEATURE_ATTESTATION", "location_id": attestation_id},
                        {"role": "FRONTEND_INPUT_AUDIT", "location_id": audit_id},
                        {"role": "PREPARATION_BAG", "location_id": preparation_id},
                    ]
                )
            if entry.get("dataset_family") == "afrl":
                bindings.extend(
                    [
                        {"role": "AFRL_BUS_CAMCHAIN", "location_id": camera_location},
                        {"role": "AFRL_IMU_CALIBRATION", "location_id": imu_location},
                    ]
                )
            bindings.sort(key=lambda item: _ROLE_ORDER.index(item["role"]))
            cells.append(
                {
                    "cell_id": _cell_id(window_id, arm),
                    "window_id": window_id,
                    "dataset_family": entry["dataset_family"],
                    "arm": arm,
                    "replay_indices": [1, 2, 3],
                    "location_bindings": bindings,
                }
            )

    content_objects = sorted(content_by_key.values(), key=lambda item: item["content_object_id"])
    path_locations = sorted(locations_by_path.values(), key=lambda item: item["path"])
    queue_bindings.sort(key=lambda item: item["queue_index"])
    feature_locations = [item for item in path_locations if item["identity_status"] == "FROZEN_QUEUE_FEATURE_CONTENT_SHA256"]
    attestation_locations = [item for item in path_locations if item["identity_status"] == "FROZEN_QUEUE_ATTESTATION_SHA256"]
    audit_locations = [item for item in path_locations if item["identity_status"] == "FROZEN_QUEUE_INPUT_AUDIT_SHA256"]
    feature_content_count = len({item["content_object_id"] for item in feature_locations})
    if (
        len(cells) != 80
        or len(queue_bindings) != 240
        or len(feature_locations) != 60
        or len(attestation_locations) != 60
        or len(audit_locations) != 60
        or feature_content_count != EXPECTED_FEATURE_CONTENT_SHA_COUNT
    ):
        raise ActualConsumedCoreV2Error("actual-consumed core cardinality differs")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "b0_core_hash": core[b0.SELF_HASH_FIELD],
        "queue_authority": {
            "path": b0.FROZEN_QUEUE_RELATIVE,
            "sha256": b0.FROZEN_QUEUE_SHA256,
            "size_bytes": b0.FROZEN_QUEUE_SIZE_BYTES,
        },
        "window_count": 20,
        "arm_count": 4,
        "cell_count": 80,
        "queue_binding_count": 240,
        "content_object_count": len(content_objects),
        "path_location_count": len(path_locations),
        "feature_bag_path_count": 60,
        "feature_content_object_count": feature_content_count,
        "feature_attestation_path_count": 60,
        "frontend_input_audit_path_count": 60,
        "unresolved_content_location_count": sum(
            item["content_object_id"] is None for item in path_locations
        ),
        "content_objects": content_objects,
        "path_locations": path_locations,
        "cells": cells,
        "queue_bindings": queue_bindings,
        "policy": {
            "formal_artifact": False,
            "materialization_authorized": False,
            "execution_authorized": False,
            "trajectory_outcome_read": False,
            "raw_archives_are_runtime_inputs": False,
            "reference_or_eligibility_files_are_runtime_inputs": False,
            "unresolved_content_identity_blocks_execution": True,
        },
        "outcome_boundary": OUTCOME_BOUNDARY,
    }


def build_actual_consumed_core(
    *,
    validated_b0_core: Mapping[str, Any],
    frozen_queue_authority: Mapping[str, Any]
) -> Dict[str, Any]:
    core, rows = _detached_authorities(validated_b0_core, frozen_queue_authority)
    payload = _build_body(core, rows)
    payload[SELF_HASH_FIELD] = document_hash(payload, SELF_HASH_FIELD)
    validate_actual_consumed_core(
        payload,
        validated_b0_core=core,
        frozen_queue_authority=frozen_queue_authority,
    )
    return payload


def validate_actual_consumed_core(
    payload: Mapping[str, Any],
    *,
    validated_b0_core: Mapping[str, Any],
    frozen_queue_authority: Mapping[str, Any]
) -> str:
    if not isinstance(payload, Mapping):
        raise ActualConsumedCoreV2Error("actual-consumed core is not an object")
    observed = _clone(payload)
    observed_hash = observed.get(SELF_HASH_FIELD)
    if observed_hash != document_hash(observed, SELF_HASH_FIELD):
        raise ActualConsumedCoreV2Error("actual-consumed core self-hash differs")
    core, rows = _detached_authorities(validated_b0_core, frozen_queue_authority)
    expected = _build_body(core, rows)
    expected[SELF_HASH_FIELD] = document_hash(expected, SELF_HASH_FIELD)
    if observed != expected:
        raise ActualConsumedCoreV2Error("actual-consumed core authority/schema drift")
    return str(observed_hash)


__all__ = [
    "ActualConsumedCoreV2Error",
    "EXPECTED_FEATURE_CONTENT_SHA_COUNT",
    "SCHEMA_VERSION",
    "SELF_HASH_FIELD",
    "build_actual_consumed_core",
    "document_hash",
    "validate_actual_consumed_core",
]
