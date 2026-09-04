#!/usr/bin/env python3
"""Freeze the additive P07 A02 M/P export execution contract."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
from datetime import datetime
from pathlib import Path

try:
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import audit_p07_mp_frontend_export_v2 as auditor
    from scripts import run_p07_mp_frontend_export_job_v2 as executor
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import audit_p07_mp_frontend_export_v2 as auditor  # type: ignore
    import run_p07_mp_frontend_export_job_v2 as executor  # type: ignore


OUTPUT = governance.P07 / "mp_smoke_execution_lock_v2.json"
B1_ATTEMPT = (
    governance.P07
    / "frontend_attempts/queue_001_isj_p07_aqualoc_archaeology_a02_0005_b1_attempt01"
)
B1_BAG = (
    governance.ROOT
    / "logs/aqualoc_archaeo_vins/"
    "external_klt_every2_isj_p07_aqualoc_archaeology_a02_0005_b1_attempt01/features.bag"
)
RAW_BAG = governance.ROOT / "datasets/aqualoc/rosbags/archaeo02_4500_5400.bag"
VINS_BINARY = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node")


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": auditor.display_path(path),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def external_file_record(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def tree_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def lock_hash(payload: dict[str, object]) -> str:
    clone = dict(payload)
    clone.pop("execution_lock_hash", None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def mutable_stream_snapshot(path: Path, *, latest_event_id: str | None = None) -> dict[str, object]:
    payload = file_record(path)
    payload["binding"] = "PREEXECUTION_APPEND_ONLY_PREFIX_SNAPSHOT"
    if latest_event_id is not None:
        payload["latest_required_event_id"] = latest_event_id
    return payload


def build_queue_item(index: int) -> dict[str, object]:
    row = auditor.queue_row(index)
    allocation = auditor.allocation_row(index)
    manifest = auditor.manifest_row(row["window_id"])
    expected_frames = auditor.expected_feature_frames(manifest, row["dataset_family"])
    if expected_frames != 450:
        raise ValueError(f"A02 expected feature frame count drift: {expected_frames}")
    if index == 2:
        guard = {
            "schema_version": "aqua-fe-p05-xfeat-backend-guard-decision-v1",
            "action": "ALLOW_M_XFEAT",
            "contract_hash": auditor.M_CONTRACT_HASH,
            "counts_as_result_field": "counts_as_modern_baseline=true",
        }
        attestation_suffix = ".p05-xfeat-contract.json"
    else:
        guard = {
            "schema_version": "aqua-fe-nativeq-backend-guard-decision-v1",
            "action": "ALLOW_LEARNED",
            "contract_hash": auditor.P_CONTRACT_HASH,
            "counts_as_result_field": "counts_as_proposed_result=true",
        }
        attestation_suffix = ".quality-contract.json"
    return {
        "queue_index": index,
        "run_id": allocation["run_id"],
        "window_id": row["window_id"],
        "arm": row["arm"],
        "tag": row["tag"],
        "command": row["command"],
        "command_sha256": row["command_sha256"],
        "expected_run_root": row["expected_run_root"],
        "expected_feature_bag": row["expected_feature_bag"],
        "feature_bag_resolution": row["feature_bag_resolution"],
        "expected_raw_images": 901,
        "expected_feature_frames": expected_frames,
        "expected_imu_messages": 9091,
        "expected_reference_messages": 46,
        "attestation_suffix": attestation_suffix,
        "guard": guard,
    }


def build_lock() -> dict[str, object]:
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    b1_allocation = auditor.allocation_row(1)
    b1_chain = executor.registry_chain(b1_allocation["run_id"])
    if (
        len(b1_chain) != 4
        or [row["status"] for row in b1_chain]
        != ["PLANNED", "RUNNING", "FAILED", "COMPLETED"]
        or b1_chain[-1]["registry_event_id"] != f"{b1_allocation['run_id']}_e03"
    ):
        raise ValueError("B1 correction chain is not the frozen e00/e01/e02/e03 precedent")
    closeout_path = B1_ATTEMPT / "audit_correction_closeout_v2.json"
    closeout = json.loads(closeout_path.read_text(encoding="utf-8"))
    if closeout.get("status") != "PASS_COMPLETED_WITH_PRESERVED_AUDITOR_FAILURE":
        raise ValueError("B1 correction closeout is not PASS")

    queue_items = [build_queue_item(2), build_queue_item(3)]
    for item in queue_items:
        chain = executor.registry_chain(str(item["run_id"]))
        if len(chain) != 1 or chain[0]["status"] != "PLANNED":
            raise ValueError(f"queue index {item['queue_index']} is not untouched PLANNED")
        row = auditor.queue_row(int(item["queue_index"]))
        collisions = executor.target_collisions(row)
        if collisions:
            raise FileExistsError(f"queue index {item['queue_index']} collision: {collisions}")
        attempt = executor.ATTEMPT_ROOT / f"queue_{int(item['queue_index']):03d}_{item['tag']}"
        if attempt.exists():
            raise FileExistsError(f"queue index {item['queue_index']} attempt collision: {attempt}")

    observed_b1_run_bytes = tree_size(B1_BAG.parent)
    cached_raw_bytes = RAW_BAG.stat().st_size if RAW_BAG.is_file() else 0
    uncached_raw_bytes = 0 if RAW_BAG.is_file() else cached_raw_bytes
    estimated_new_run_bytes = observed_b1_run_bytes * 4
    reserve_bytes = 2 * 1024**3
    estimated_required = math.ceil(
        (uncached_raw_bytes + estimated_new_run_bytes) * 1.20 + reserve_bytes
    )
    minimum_output = max(executor.BASE_MIN_OUTPUT_FREE_BYTES, estimated_required)
    output_usage = shutil.disk_usage(governance.ROOT / queue_items[0]["expected_run_root"])
    governance_usage = shutil.disk_usage(governance.P07)
    if output_usage.free < minimum_output:
        raise RuntimeError("insufficient output capacity to freeze M/P execution")
    if governance_usage.free < executor.MIN_GOVERNANCE_FREE_BYTES:
        raise RuntimeError("insufficient governance capacity to freeze M/P execution")

    artifacts = [
        governance.EXPORT_QUEUE,
        governance.QUEUE_LOCK,
        governance.ALLOCATION_CSV,
        governance.ANALYSIS_LOCK,
        governance.P07 / "execution_adapter_lock_v1.json",
        governance.METHOD_LOCK,
        governance.PROTOCOL,
        governance.D_QUEUE,
        governance.BUNDLE / "dataset_checksum_manifest.txt",
        governance.BUNDLE / "p05/backend_consumer_contract_xfeat_v1.json",
        governance.BUNDLE / "backend_quality_contract_v1.json",
        governance.P07 / "b1_auditor_correction_lock_v2.json",
        B1_ATTEMPT / "audit_v2.json",
        closeout_path,
        B1_BAG,
        governance.ROOT / "scripts/run_p07_mp_frontend_export_job_v2.py",
        governance.ROOT / "scripts/audit_p07_mp_frontend_export_v2.py",
        governance.ROOT / "scripts/build_p07_mp_smoke_execution_lock_v2.py",
        governance.ROOT / "scripts/tests/test_p07_mp_frontend_export_v2.py",
        governance.ROOT / "scripts/tests/test_p07_mp_smoke_execution_lock_v2.py",
        governance.ROOT / "scripts/run_p05_modern_xfeat_baseline_guarded_v2.sh",
        governance.ROOT / "scripts/run_p05_modern_xfeat_baseline.sh",
        governance.ROOT / "scripts/check_p05_xfeat_backend_contract_v1.py",
        governance.ROOT / "scripts/attest_p05_xfeat_feature_bag_v1.py",
        governance.ROOT / "scripts/run_isj_nativeq_contract_guarded_v4.sh",
        governance.ROOT / "scripts/run_isj_nativeq_legacy_candidate.sh",
        governance.ROOT / "scripts/run_xfeat_seedchain_arbitrated_eval.sh",
        governance.ROOT / "scripts/check_nativeq_backend_contract.py",
        governance.ROOT / "scripts/attest_nativeq_feature_bag.py",
        governance.ROOT / "scripts/run_aqualoc_archaeo_vins_eval.sh",
        governance.ROOT / "uw_frontend/ros/export_vins_features.py",
        governance.ROOT / "uw_frontend/configs/experiments/isj_p05_xfeat_pairwise_nativeq.yaml",
        governance.ROOT
        / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml",
    ]
    payload: dict[str, object] = {
        "schema_version": "isj-p07-mp-smoke-execution-lock-v2",
        "status": "FROZEN_READY_FOR_A02_M_P_EXPORT",
        "frozen_at": now(),
        "protocol_version": "isj-nativeq-v3-confirmatory-protocol-v1",
        "method_lock_hash": json.loads(
            governance.METHOD_LOCK.read_text(encoding="utf-8")
        )["method_lock_hash"],
        "queue_lock_hash": json.loads(
            governance.QUEUE_LOCK.read_text(encoding="utf-8")
        )["queue_lock_hash"],
        "allowed_queue_indices": [2, 3],
        "allowed_arms": [governance.M_ARM, governance.P_ARM],
        "execution_order": [2, 3],
        "window_id": "aqualoc_archaeology:A02:0005",
        "queue_items": queue_items,
        "dependencies": {
            "b1_parent_run_id": b1_allocation["run_id"],
            "b1_required_latest_event_id": b1_chain[-1]["registry_event_id"],
            "b1_required_latest_status": "COMPLETED",
            "b1_feature_bag": auditor.display_path(B1_BAG),
            "b1_feature_bag_sha256": sha256(B1_BAG),
            "b1_preserved_failed_event_id": b1_chain[2]["registry_event_id"],
            "queue_3_requires_queue_2_completed": True,
            "queue_3_completion_gates_d_slot": 4,
        },
        "guard_policy": {
            "run_guard_only_preflight_before_each_export": True,
            "outer_contract_fallback_counts_as_arm": False,
            "sanitized_inherited_environment_keys": sorted(executor.SANITIZED_ENV_KEYS),
        },
        "lineage_contract": {
            "source_codes": [10, 20, 30],
            "birth_rule": "first ID occurrence has is_learned=1 or learned source_code",
            "late_marker_policy": "FAIL_CLOSED",
            "count_unit": "DISTINCT_LEARNED_BORN_FEATURE_ID",
            "zero_count_action": "REQUIRE_P_AND_B1_FEATURE_BAGS_BYTE_IDENTICAL_THEN_NOT_APPLICABLE",
            "positive_count_action": "DERIVE_D_AND_REQUIRE_PASS_EXACT_WHOLE_LINEAGE_DROP",
            "invalid_parent_action": "UNRESOLVABLE_PARENT_FAILURE_AND_D_BLOCKED",
        },
        "no_clobber": {
            "target_collision_count": 0,
            "capacity_checked_before_attempt_directory_creation": True,
            "attempt_directory_must_not_exist": True,
            "p_tag_family_must_not_exist": True,
            "replacement_requires_new_run_id_and_attempt02_or_later_tag": True,
        },
        "capacity_gate": {
            "raw_bag_cached": RAW_BAG.is_file(),
            "cached_raw_bag_bytes": cached_raw_bytes,
            "uncached_raw_bytes": uncached_raw_bytes,
            "observed_b1_run_bytes": observed_b1_run_bytes,
            "estimated_new_m_p_and_d_run_bytes": estimated_new_run_bytes,
            "margin_multiplier": 1.20,
            "separate_reserve_bytes": reserve_bytes,
            "base_minimum_output_free_bytes": executor.BASE_MIN_OUTPUT_FREE_BYTES,
            "estimated_required_output_free_bytes": minimum_output,
            "minimum_governance_free_bytes": executor.MIN_GOVERNANCE_FREE_BYTES,
            "observed_output_free_bytes": output_usage.free,
            "observed_governance_free_bytes": governance_usage.free,
            "recompute_before_each_job": True,
        },
        "mutable_stream_prefix_snapshots": [
            mutable_stream_snapshot(
                governance.BUNDLE / "run_registry.csv",
                latest_event_id=b1_chain[-1]["registry_event_id"],
            ),
            mutable_stream_snapshot(governance.BUNDLE / "arm_applicability.csv"),
        ],
        "required_terminal_evidence": [
            "exact guard-only preflight PASS and exact in-command nonfallback guard PASS",
            "450 feature frames with 13-channel schema and 350 cap",
            "9091 copied IMU and 46 copied reference messages",
            "arm-specific contract-bound bag attestation",
            "frontend metrics and feature bag frame/observation equality",
            "P final bag resolved from exactly one self-consistent arbitration summary",
            "distinct learned-born lineage audit with late-marker fail-closed rule",
            "zero-action P byte identity to B1 or positive lineage count",
            "absence of VINS, trajectory, APE, and RPE artifacts",
            "input/output hashes and contiguous append-only registry chain",
        ],
        "artifacts": [file_record(path) for path in artifacts],
        "external_artifacts": [external_file_record(VINS_BINARY)],
        "vins_workspace": "/home/ma/SLAM/VINS-Fusion-origin",
        "forbidden_workspace": "/home/ma/SLAM/VINS-Fusion_3-15-WS",
        "outcome_boundary": "A02_M_P_FRONTEND_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY",
        "held_out_frontend_outcome_read": True,
        "held_out_trajectory_outcome_read": False,
        "next_action": "EXECUTE_QUEUE_INDEX_2_THEN_3_THEN_RESOLVE_D_SLOT_4",
    }
    payload["execution_lock_hash"] = lock_hash(payload)
    return payload


def main() -> int:
    payload = build_lock()
    temporary = OUTPUT.with_name(f"{OUTPUT.name}.partial.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, OUTPUT)
    print(
        "P07_MP_SMOKE_EXECUTION_LOCK_V2_PASS "
        f"hash={payload['execution_lock_hash']} order=2,3"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
