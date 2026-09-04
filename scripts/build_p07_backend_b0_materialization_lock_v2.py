#!/usr/bin/env python3
"""Build the additive P07 B0-v2 materialization authority.

The lock authorizes only preparation of the twenty replay inputs.  It does
not run a frontend/backend, start VINS, or inspect a trajectory outcome.  A
live write is deliberately downstream of the formalization adoption and its
review-evidence lock; absent authorities fail closed.
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Dict, Mapping, Optional, Sequence

try:
    from scripts import build_p07_backend_formalization_adoption_v1 as adoption
    from scripts import build_p07_backend_formalization_review_evidence_v1 as review
    from scripts import build_p07_backend_hf_checksum_semantics_correction_v1 as hf
    from scripts import p07_backend_actual_consumed_core_v2 as actual
    from scripts import p07_backend_b0_legacy_recipe_authority_v1 as legacy
    from scripts import p07_backend_b0_plan_v2 as b0
    from scripts import p07_backend_effective_checksum_resolver_v1 as resolver
    from scripts import p07_backend_formal_io_v1 as formal_io
    from scripts import p07_backend_replay_common_v1 as replay_common
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    import build_p07_backend_formalization_adoption_v1 as adoption  # type: ignore
    import build_p07_backend_formalization_review_evidence_v1 as review  # type: ignore
    import build_p07_backend_hf_checksum_semantics_correction_v1 as hf  # type: ignore
    import p07_backend_actual_consumed_core_v2 as actual  # type: ignore
    import p07_backend_b0_legacy_recipe_authority_v1 as legacy  # type: ignore
    import p07_backend_b0_plan_v2 as b0  # type: ignore
    import p07_backend_effective_checksum_resolver_v1 as resolver  # type: ignore
    import p07_backend_formal_io_v1 as formal_io  # type: ignore
    import p07_backend_replay_common_v1 as replay_common  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
P07_RELATIVE = "papers/ieee_sensors_journal_experiments/p07"
OUTPUT_RELATIVE = P07_RELATIVE + "/backend_b0_materialization_lock_v2.json"
SCHEMA_VERSION = "isj-p07-backend-b0-materialization-lock-v2"
STATUS = "FROZEN_READY_FOR_EXPLICIT_B0_V2_MATERIALIZATION_ONLY"
SELF_HASH_FIELD = "b0_materialization_lock_v2_hash"
OUTCOME_BOUNDARY = "B0_INPUT_PREPARATION_ONLY_NO_VINS_APE_RPE_TRAJECTORY"
NTNU_WINDOW_UPPER_BOUND_BYTES = 512 * 1024 * 1024
CAPACITY_RESERVE_BYTES = 2 * 1024**3
MINIMUM_FREE_BYTES = 3 * 1024**3
MARGIN_NUMERATOR = 6
MARGIN_DENOMINATOR = 5

LEGACY_OUTPUTS_FORBIDDEN = (
    P07_RELATIVE + "/backend_b0_materialization_lock_v1.json",
    P07_RELATIVE + "/backend_b0_materialization_intent_v1.json",
    P07_RELATIVE + "/backend_b0_materialization_receipt_v1.json",
    P07_RELATIVE + "/backend_b0_play_inputs_v1.json",
    P07_RELATIVE + "/backend_b0_formalization_adoption_prelock_v1.json",
    P07_RELATIVE + "/backend_b0_formalization_adoption_action_intent_v1.json",
    P07_RELATIVE + "/backend_b0_formalization_adoption_closeout_v1.json",
)

BUILDER_RELATIVE = "scripts/build_p07_backend_b0_materialization_lock_v2.py"
TEST_RELATIVE = "scripts/tests/test_p07_backend_b0_materialization_lock_v2.py"
SOURCE_PATHS = (
    BUILDER_RELATIVE,
    TEST_RELATIVE,
    "scripts/p07_backend_b0_legacy_recipe_authority_v1.py",
    "scripts/tests/test_p07_backend_b0_legacy_recipe_authority_v1.py",
    "scripts/p07_backend_b0_plan_v2.py",
    "scripts/tests/test_p07_backend_b0_plan_v2.py",
    "scripts/p07_backend_actual_consumed_core_v2.py",
    "scripts/tests/test_p07_backend_actual_consumed_core_v2.py",
    "scripts/p07_backend_effective_checksum_resolver_v1.py",
    "scripts/tests/test_p07_backend_effective_checksum_resolver_v1.py",
    "scripts/build_p07_backend_hf_checksum_semantics_correction_v1.py",
    "scripts/tests/test_p07_backend_hf_checksum_semantics_correction_v1.py",
    "scripts/p07_ntnu_window_fanout_v1.py",
    "scripts/tests/test_p07_ntnu_window_fanout_v1.py",
    "scripts/p07_backend_formal_io_v1.py",
    "scripts/tests/test_p07_backend_formal_io_v1.py",
    "scripts/p07_backend_replay_common_v1.py",
    "scripts/tests/test_p07_backend_runtime_identity_v1.py",
    "scripts/build_p07_backend_formalization_adoption_v1.py",
    "scripts/tests/test_p07_backend_formalization_adoption_v1.py",
    "scripts/build_p07_backend_formalization_review_evidence_v1.py",
    "scripts/tests/test_p07_backend_formalization_review_evidence_v1.py",
)

_HEX64 = re.compile(r"[0-9a-f]{64}")


class B0MaterializationLockV2Error(RuntimeError):
    """The B0-v2 materialization authority is not closed or reproducible."""


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def document_hash(payload: Mapping[str, Any], field: str) -> str:
    clone = copy.deepcopy(dict(payload))
    clone[field] = ""
    return hashlib.sha256(canonical_json(clone).encode("utf-8")).hexdigest()


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=True))


def _timestamp(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise B0MaterializationLockV2Error("frozen_at is absent")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise B0MaterializationLockV2Error("frozen_at is not ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise B0MaterializationLockV2Error("frozen_at must be timezone-aware")
    return value


def _safe_relative(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise B0MaterializationLockV2Error(label + " path is not a string")
    pure = PurePosixPath(value)
    if (
        not value
        or "\x00" in value
        or pure.is_absolute()
        or ".." in pure.parts
        or any(part in {"", "."} for part in pure.parts)
    ):
        raise B0MaterializationLockV2Error(label + " path is unsafe")
    return value


def _record(value: Any, *, label: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"path", "sha256", "size_bytes"}:
        raise B0MaterializationLockV2Error(label + " record schema drift")
    path = _safe_relative(value.get("path"), label=label)
    digest = value.get("sha256")
    size = value.get("size_bytes")
    if (
        not isinstance(digest, str)
        or _HEX64.fullmatch(digest) is None
        or type(size) is not int
        or size < 0
    ):
        raise B0MaterializationLockV2Error(label + " record identity drift")
    return {"path": path, "sha256": digest, "size_bytes": size}


def _authority_binding(value: Any, *, hash_field: str, label: str) -> Dict[str, Any]:
    expected = {"path", "sha256", "size_bytes", hash_field}
    if not isinstance(value, Mapping) or set(value) != expected:
        raise B0MaterializationLockV2Error(label + " authority schema drift")
    record = _record(
        {key: value[key] for key in ("path", "sha256", "size_bytes")}, label=label
    )
    authority_hash = value.get(hash_field)
    if not isinstance(authority_hash, str) or _HEX64.fullmatch(authority_hash) is None:
        raise B0MaterializationLockV2Error(label + " self-hash drift")
    return {**record, hash_field: authority_hash}


def _legacy_binding(payload: Mapping[str, Any]) -> Dict[str, Any]:
    legacy.validate_authority_payload(payload)
    encoded = canonical_json(payload).encode("utf-8")
    return {
        "schema_version": legacy.SCHEMA_VERSION,
        "self_hash_field": legacy.SELF_HASH_FIELD,
        "self_hash": payload[legacy.SELF_HASH_FIELD],
        "canonical_sha256": hashlib.sha256(encoded).hexdigest(),
        "canonical_size_bytes": len(encoded),
    }


def _hf_binding(value: Any) -> Dict[str, Any]:
    return _authority_binding(value, hash_field=hf.SELF_HASH_FIELD, label="HF correction")


def _source_bindings(values: Sequence[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    records = [_record(value, label="source binding") for value in values]
    paths = [record["path"] for record in records]
    if paths != sorted(SOURCE_PATHS) or len(paths) != len(set(paths)):
        raise B0MaterializationLockV2Error("source closure path/order drift")
    return records


def _target_states(
    core: Mapping[str, Any], observations: Mapping[str, Optional[Mapping[str, Any]]]
) -> list[Dict[str, Any]]:
    if not isinstance(observations, Mapping):
        raise B0MaterializationLockV2Error("target observations are malformed")
    result: list[Dict[str, Any]] = []
    expected_paths = {str(entry["target"]["path"]) for entry in core["entries"]}
    if set(observations) != expected_paths:
        raise B0MaterializationLockV2Error("target observation coverage drift")
    for entry in sorted(core["entries"], key=lambda item: str(item["window_id"])):
        target = entry["target"]
        path = str(target["path"])
        observed = observations[path]
        expected_sha = target["content_sha256"]
        expected_size = target["size_bytes"]
        if observed is None:
            state = {
                "window_id": entry["window_id"],
                "path": path,
                "state": "ABSENT",
                "expected_sha256": expected_sha,
                "expected_size_bytes": expected_size,
                "observed_record": None,
            }
        else:
            if expected_sha is None or expected_size is None:
                raise B0MaterializationLockV2Error(
                    "unresolved NTNU target must be absent before freeze"
                )
            record = _record(observed, label="existing target")
            if (
                record["path"] != path
                or record["sha256"] != expected_sha
                or record["size_bytes"] != expected_size
            ):
                raise B0MaterializationLockV2Error("existing target identity drift")
            state = {
                "window_id": entry["window_id"],
                "path": path,
                "state": "EXACT_EXISTING",
                "expected_sha256": expected_sha,
                "expected_size_bytes": expected_size,
                "observed_record": record,
            }
        result.append(state)
    if len(result) != 20:
        raise B0MaterializationLockV2Error("target state count drift")
    return result


def _materialization_units(core: Mapping[str, Any]) -> list[Dict[str, Any]]:
    singles: list[Dict[str, Any]] = []
    ntnu: list[Dict[str, Any]] = []
    for entry in sorted(core["entries"], key=lambda item: str(item["window_id"])):
        if entry["dataset_family"] == "ntnu":
            ntnu.append(
                {
                    "window_id": entry["window_id"],
                    "target_path": entry["target"]["path"],
                    "selection": entry["materialization"]["selection"],
                    "expected_output": entry["materialization"]["expected_output"],
                }
            )
            continue
        recipe = entry["materialization"]["v1_recipe"]
        singles.append(
            {
                "unit_id": "single:" + str(entry["window_id"]),
                "kind": "LEGACY_EXACT_SINGLE_TARGET",
                "window_ids": [entry["window_id"]],
                "source_path": recipe["source_raw_path"],
                "target_paths": [entry["target"]["path"]],
                "expected_sha256": entry["target"]["content_sha256"],
                "expected_size_bytes": entry["target"]["size_bytes"],
                "disposition": recipe["disposition"],
                "publication": "RENAMEAT2_NOREPLACE_FROM_RETAINED_STAGE",
            }
        )
    group = {
        "unit_id": "group:ntnu:fjord_6:three_closed_record_windows",
        "kind": "NTNU_SINGLE_TRAVERSAL_THREE_WINDOW_FANOUT",
        "window_ids": [item["window_id"] for item in ntnu],
        "source_path": b0.NTNU_SOURCE_PATH,
        "target_paths": [item["target_path"] for item in ntnu],
        "windows": ntnu,
        "per_window_upper_bound_bytes": NTNU_WINDOW_UPPER_BOUND_BYTES,
        "publication": "DURABLE_STAGE_RECEIPT_THEN_RENAMEAT2_NOREPLACE",
    }
    units = singles + [group]
    if len(singles) != 17 or len(ntnu) != 3 or len(units) != 18:
        raise B0MaterializationLockV2Error("materialization unit coverage drift")
    return units


def _capacity(states: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    missing_known = 0
    ntnu_missing = 0
    for item in states:
        if item["state"] != "ABSENT":
            continue
        size = item["expected_size_bytes"]
        if size is None:
            ntnu_missing += 1
        else:
            missing_known += int(size)
    if ntnu_missing != 3:
        raise B0MaterializationLockV2Error("all three unresolved NTNU targets must be absent")
    materialization_bound = missing_known + ntnu_missing * NTNU_WINDOW_UPPER_BOUND_BYTES
    with_margin = (
        materialization_bound * MARGIN_NUMERATOR + MARGIN_DENOMINATOR - 1
    ) // MARGIN_DENOMINATOR
    required = max(MINIMUM_FREE_BYTES, with_margin + CAPACITY_RESERVE_BYTES)
    return {
        "missing_known_target_bytes": missing_known,
        "ntnu_unresolved_window_count": ntnu_missing,
        "ntnu_per_window_upper_bound_bytes": NTNU_WINDOW_UPPER_BOUND_BYTES,
        "materialization_upper_bound_bytes": materialization_bound,
        "margin_numerator": MARGIN_NUMERATOR,
        "margin_denominator": MARGIN_DENOMINATOR,
        "reserve_bytes": CAPACITY_RESERVE_BYTES,
        "minimum_free_bytes": MINIMUM_FREE_BYTES,
        "required_free_bytes": required,
    }


def build_lock_payload(
    *,
    frozen_at: str,
    legacy_authority: Mapping[str, Any],
    effective_checksum_records: Sequence[Mapping[str, Any]],
    frozen_queue_authority: Mapping[str, Any],
    adoption_binding: Mapping[str, Any],
    review_evidence_binding: Mapping[str, Any],
    hf_correction_binding: Mapping[str, Any],
    source_bindings: Sequence[Mapping[str, Any]],
    target_observations: Mapping[str, Optional[Mapping[str, Any]]],
) -> Dict[str, Any]:
    legacy_snapshot = _clone(legacy_authority)
    legacy.validate_authority_payload(legacy_snapshot)
    core = b0.build_core_plan(
        frozen_windows=list(b0.FROZEN_WINDOWS.values()),
        validated_v1_plan_or_recipes=legacy_snapshot,
        effective_checksum_records=_clone(effective_checksum_records),
        frozen_queue_authority=frozen_queue_authority,
    )
    consumed = actual.build_actual_consumed_core(
        validated_b0_core=core,
        frozen_queue_authority=frozen_queue_authority,
    )
    states = _target_states(core, target_observations)
    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "frozen_at": _timestamp(frozen_at),
        "formalization_adoption": _authority_binding(
            adoption_binding,
            hash_field=adoption.SELF_HASH_FIELD,
            label="formalization adoption",
        ),
        "formalization_review_evidence": _authority_binding(
            review_evidence_binding,
            hash_field=review.SELF_HASH_FIELD,
            label="review evidence",
        ),
        "hf_checksum_semantics_correction": _hf_binding(hf_correction_binding),
        "legacy_recipe_authority_binding": _legacy_binding(legacy_snapshot),
        "legacy_recipe_authority": legacy_snapshot,
        "effective_checksum_records": sorted(
            _clone(effective_checksum_records), key=lambda item: str(item["path"])
        ),
        "b0_core_plan": core,
        "actual_consumed_pre_materialization_core": consumed,
        "pre_freeze_target_states": states,
        "materialization_units": _materialization_units(core),
        "capacity": _capacity(states),
        "source_bindings": _source_bindings(source_bindings),
        "counts": {
            "window_count": 20,
            "legacy_single_unit_count": 17,
            "ntnu_fanout_group_count": 1,
            "materialization_unit_count": 18,
            "b0_binding_count": 60,
            "preparation_mapping_count": 240,
            "actual_consumed_cell_count": 80,
            "actual_consumed_queue_binding_count": 240,
        },
        "policy": {
            "explicit_execute_required": True,
            "run_vins": False,
            "frontend_execution_authorized": False,
            "backend_replay_authorized": False,
            "ape_rpe_or_trajectory_read_authorized": False,
            "ntnu_full_source_runtime_playback_forbidden": True,
            "no_clobber": True,
            "failed_stages_preserved_never_automatically_deleted": True,
            "final_publication_requires_renameat2_noreplace": True,
            "actual_consumed_contract_remains_nonformal_until_materialization_closeout": True,
        },
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": OUTCOME_BOUNDARY,
        SELF_HASH_FIELD: "",
    }
    payload[SELF_HASH_FIELD] = document_hash(payload, SELF_HASH_FIELD)
    validate_lock_payload(
        payload,
        frozen_queue_authority=frozen_queue_authority,
        external_legacy_authority=legacy_snapshot,
        external_adoption_binding=adoption_binding,
        external_review_evidence_binding=review_evidence_binding,
        external_hf_correction_binding=hf_correction_binding,
        external_source_bindings=source_bindings,
        verify_sources=False,
        verify_live_authorities=False,
    )
    return payload


def _validate_sources_live(records: Sequence[Mapping[str, Any]], root: Path) -> None:
    for expected in records:
        content, _identity = formal_io.read_direct_bytes(root, str(expected["path"]))
        observed = {
            "path": expected["path"],
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
        if observed != expected:
            raise B0MaterializationLockV2Error(
                "bound source changed: " + str(expected["path"])
            )


def validate_lock_payload(
    payload: Mapping[str, Any],
    *,
    frozen_queue_authority: Mapping[str, Any],
    external_legacy_authority: Optional[Mapping[str, Any]] = None,
    external_adoption_binding: Optional[Mapping[str, Any]] = None,
    external_review_evidence_binding: Optional[Mapping[str, Any]] = None,
    external_hf_correction_binding: Optional[Mapping[str, Any]] = None,
    external_source_bindings: Optional[Sequence[Mapping[str, Any]]] = None,
    root: Path = ROOT,
    verify_sources: bool = False,
    verify_live_authorities: bool = False,
) -> str:
    expected_keys = {
        "schema_version", "status", "frozen_at", "formalization_adoption",
        "formalization_review_evidence", "hf_checksum_semantics_correction",
        "legacy_recipe_authority_binding", "legacy_recipe_authority",
        "effective_checksum_records", "b0_core_plan",
        "actual_consumed_pre_materialization_core", "pre_freeze_target_states",
        "materialization_units", "capacity", "source_bindings", "counts", "policy",
        "held_out_trajectory_outcome_read", "outcome_boundary", SELF_HASH_FIELD,
    }
    if not isinstance(payload, Mapping) or set(payload) != expected_keys:
        raise B0MaterializationLockV2Error("lock top-level schema drift")
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("status") != STATUS
        or payload.get(SELF_HASH_FIELD) != document_hash(payload, SELF_HASH_FIELD)
        or payload.get("held_out_trajectory_outcome_read") is not False
        or payload.get("outcome_boundary") != OUTCOME_BOUNDARY
    ):
        raise B0MaterializationLockV2Error("lock status/hash/outcome drift")
    _timestamp(str(payload["frozen_at"]))
    adoption_value = _authority_binding(
        payload["formalization_adoption"],
        hash_field=adoption.SELF_HASH_FIELD,
        label="formalization adoption",
    )
    review_value = _authority_binding(
        payload["formalization_review_evidence"],
        hash_field=review.SELF_HASH_FIELD,
        label="review evidence",
    )
    hf_value = _hf_binding(payload["hf_checksum_semantics_correction"])
    if external_adoption_binding is not None and adoption_value != _authority_binding(
        external_adoption_binding,
        hash_field=adoption.SELF_HASH_FIELD,
        label="external formalization adoption",
    ):
        raise B0MaterializationLockV2Error("external adoption binding differs")
    if external_review_evidence_binding is not None and review_value != _authority_binding(
        external_review_evidence_binding,
        hash_field=review.SELF_HASH_FIELD,
        label="external review evidence",
    ):
        raise B0MaterializationLockV2Error("external review binding differs")
    if external_hf_correction_binding is not None and hf_value != _hf_binding(
        external_hf_correction_binding
    ):
        raise B0MaterializationLockV2Error("external HF correction binding differs")
    legacy_snapshot = _clone(payload["legacy_recipe_authority"])
    legacy.validate_authority_payload(legacy_snapshot)
    if payload["legacy_recipe_authority_binding"] != _legacy_binding(legacy_snapshot):
        raise B0MaterializationLockV2Error("legacy authority binding drift")
    if external_legacy_authority is not None and legacy_snapshot != _clone(
        external_legacy_authority
    ):
        raise B0MaterializationLockV2Error("external legacy authority differs")
    effective_records = payload["effective_checksum_records"]
    if (
        not isinstance(effective_records, list)
        or len(effective_records) != 2
        or effective_records
        != sorted(_clone(effective_records), key=lambda item: str(item.get("path", "")))
    ):
        raise B0MaterializationLockV2Error("effective checksum record order/count drift")
    core = b0.build_core_plan(
        frozen_windows=list(b0.FROZEN_WINDOWS.values()),
        validated_v1_plan_or_recipes=legacy_snapshot,
        effective_checksum_records=effective_records,
        frozen_queue_authority=frozen_queue_authority,
    )
    if payload["b0_core_plan"] != core:
        raise B0MaterializationLockV2Error("embedded B0 core is not reproducible")
    b0.validate_core_plan(
        core, root=root, validated_v1_plan_or_recipes=legacy_snapshot
    )
    expected_consumed = actual.build_actual_consumed_core(
        validated_b0_core=core, frozen_queue_authority=frozen_queue_authority
    )
    if payload["actual_consumed_pre_materialization_core"] != expected_consumed:
        raise B0MaterializationLockV2Error("actual-consumed pre-core drift")
    states = _target_states(
        core,
        {
            str(item["path"]): item.get("observed_record")
            for item in payload["pre_freeze_target_states"]
            if isinstance(item, Mapping)
        },
    )
    if payload["pre_freeze_target_states"] != states:
        raise B0MaterializationLockV2Error("target-state evidence drift")
    if payload["materialization_units"] != _materialization_units(core):
        raise B0MaterializationLockV2Error("materialization-unit drift")
    if payload["capacity"] != _capacity(states):
        raise B0MaterializationLockV2Error("capacity derivation drift")
    source_records = _source_bindings(payload["source_bindings"])
    if external_source_bindings is not None and source_records != _source_bindings(
        external_source_bindings
    ):
        raise B0MaterializationLockV2Error("external source closure differs")
    expected_counts = {
        "window_count": 20, "legacy_single_unit_count": 17,
        "ntnu_fanout_group_count": 1, "materialization_unit_count": 18,
        "b0_binding_count": 60, "preparation_mapping_count": 240,
        "actual_consumed_cell_count": 80,
        "actual_consumed_queue_binding_count": 240,
    }
    expected_policy = {
        "explicit_execute_required": True, "run_vins": False,
        "frontend_execution_authorized": False, "backend_replay_authorized": False,
        "ape_rpe_or_trajectory_read_authorized": False,
        "ntnu_full_source_runtime_playback_forbidden": True, "no_clobber": True,
        "failed_stages_preserved_never_automatically_deleted": True,
        "final_publication_requires_renameat2_noreplace": True,
        "actual_consumed_contract_remains_nonformal_until_materialization_closeout": True,
    }
    if payload["counts"] != expected_counts or payload["policy"] != expected_policy:
        raise B0MaterializationLockV2Error("lock count/policy drift")
    if verify_sources:
        _validate_sources_live(source_records, root.absolute())
    if verify_live_authorities:
        if adoption.validate_adoption_authority_binding(adoption_value, root=root) != adoption_value:
            raise B0MaterializationLockV2Error("live adoption binding drift")
        if review.validate_review_evidence_authority_binding(review_value, root=root) != review_value:
            raise B0MaterializationLockV2Error("live review binding drift")
        lock = resolver.load_correction_lock(root=root)
        live_hf = {
            "path": resolver.CORRECTION_LOCK_RELATIVE,
            "sha256": hf_value["sha256"],
            "size_bytes": hf_value["size_bytes"],
            hf.SELF_HASH_FIELD: lock[hf.SELF_HASH_FIELD],
        }
        content, _identity = formal_io.read_direct_bytes(root, resolver.CORRECTION_LOCK_RELATIVE)
        live_hf["sha256"] = hashlib.sha256(content).hexdigest()
        live_hf["size_bytes"] = len(content)
        if live_hf != hf_value:
            raise B0MaterializationLockV2Error("live HF correction binding drift")
    return str(payload[SELF_HASH_FIELD])


def _source_records_live(root: Path) -> list[Dict[str, Any]]:
    result = []
    for relative in sorted(SOURCE_PATHS):
        content, _identity = formal_io.read_direct_bytes(root, relative)
        result.append({
            "path": relative,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        })
    return result


def _base_manifest_live(root: Path) -> Dict[str, str]:
    content, _identity = formal_io.read_direct_bytes(root, hf.DATASET_MANIFEST_RELATIVE)
    return hf._manifest_entries(content)


def _target_observations_live(core: Mapping[str, Any], root: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for entry in core["entries"]:
        target = entry["target"]
        relative = str(target["path"])
        lexical = root / relative
        try:
            leaf = os.lstat(lexical)
        except FileNotFoundError:
            result[relative] = None
            continue
        if stat.S_ISLNK(leaf.st_mode) or not stat.S_ISREG(leaf.st_mode) or leaf.st_nlink != 1:
            raise B0MaterializationLockV2Error("existing target is not direct/single-link")
        expected = target["content_sha256"]
        if not isinstance(expected, str):
            raise B0MaterializationLockV2Error("NTNU target collision before formal freeze")
        identity = replay_common.capture_canonical_input_identity(
            root, relative, expected_sha256=expected, verify_sha256=True
        )
        result[relative] = {
            "path": relative,
            "sha256": expected,
            "size_bytes": int(identity["resolved_target_identity"]["size_bytes"]),
        }
    return result


def build_live_lock(
    *,
    frozen_at: str,
    root: Path = ROOT,
    require_output_absent: bool = True,
) -> Dict[str, Any]:
    root = root.absolute()
    forbidden_paths = list(LEGACY_OUTPUTS_FORBIDDEN)
    if require_output_absent:
        forbidden_paths.insert(0, OUTPUT_RELATIVE)
    for forbidden in forbidden_paths:
        if formal_io.destination_exists(root, forbidden):
            raise FileExistsError(forbidden)
    adoption_binding = adoption.adoption_authority_binding(root=root)
    evidence_binding = review.review_evidence_authority_binding(root=root)
    correction_lock = resolver.load_correction_lock(root=root)
    correction_content, _identity = formal_io.read_direct_bytes(
        root, resolver.CORRECTION_LOCK_RELATIVE
    )
    hf_binding = {
        "path": resolver.CORRECTION_LOCK_RELATIVE,
        "sha256": hashlib.sha256(correction_content).hexdigest(),
        "size_bytes": len(correction_content),
        hf.SELF_HASH_FIELD: correction_lock[hf.SELF_HASH_FIELD],
    }
    base = _base_manifest_live(root)
    effective = [
        resolver.effective_content_record(path, base, correction_lock)
        for path in (b0.NTNU_SOURCE_PATH, b0.AFRL_RAW_PATH)
    ]
    legacy_authority = legacy.build_live_authority(root=root)
    queue_authority = b0.load_live_queue_authority(root=root)
    provisional = b0.build_core_plan(
        frozen_windows=list(b0.FROZEN_WINDOWS.values()),
        validated_v1_plan_or_recipes=legacy_authority,
        effective_checksum_records=effective,
        frozen_queue_authority=queue_authority,
    )
    observations = _target_observations_live(provisional, root)
    return build_lock_payload(
        frozen_at=frozen_at,
        legacy_authority=legacy_authority,
        effective_checksum_records=effective,
        frozen_queue_authority=queue_authority,
        adoption_binding=adoption_binding,
        review_evidence_binding=evidence_binding,
        hf_correction_binding=hf_binding,
        source_bindings=_source_records_live(root),
        target_observations=observations,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--frozen-at", required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.absolute()
    if not args.write:
        payload = build_live_lock(frozen_at=args.frozen_at, root=root)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    with formal_io.global_formal_lock():
        payload = build_live_lock(frozen_at=args.frozen_at, root=root)
        content = formal_io.json_bytes(payload)

        def guard() -> None:
            rebuilt = build_live_lock(
                frozen_at=args.frozen_at,
                root=root,
                require_output_absent=False,
            )
            if formal_io.json_bytes(rebuilt) != content:
                raise B0MaterializationLockV2Error(
                    "B0-v2 live authority changed across publication"
                )

        record = formal_io.publish_bytes_no_clobber(
            root,
            OUTPUT_RELATIVE,
            content,
            pre_link_guard=guard,
            post_link_guard=guard,
        )
    print(json.dumps({"status": "WRITTEN", "record": record}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
