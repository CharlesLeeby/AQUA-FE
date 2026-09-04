#!/usr/bin/env python3
"""Freeze the additive P07 A01 B1/P/M frontend execution contract."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
from datetime import datetime
from pathlib import Path

try:
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import audit_p07_a01_frontend_export_v3 as auditor
    from scripts import run_p07_a01_frontend_export_job_v3 as executor
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import audit_p07_a01_frontend_export_v3 as auditor  # type: ignore
    import run_p07_a01_frontend_export_job_v3 as executor  # type: ignore


OUTPUT = governance.P07 / "a01_frontend_execution_lock_v3.json"
VINS_BINARY = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node")
A02_RAW = governance.ROOT / "datasets/aqualoc/rosbags/archaeo02_4500_5400.bag"
A01_RAW = governance.ROOT / "datasets/aqualoc/rosbags/archaeo01_16200_17100.bag"
A02_RUNS = [
    governance.ROOT
    / "logs/aqualoc_archaeo_vins/external_klt_every2_isj_p07_aqualoc_archaeology_a02_0005_b1_attempt01",
    governance.ROOT
    / "logs/aqualoc_archaeo_vins/external_xfeat_every2_isj_p07_aqualoc_archaeology_a02_0005_m_attempt01",
    governance.ROOT
    / "logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_isj_p07_aqualoc_archaeology_a02_0005_p_attempt01_probe_oldcontract_densecap",
    governance.ROOT
    / "logs/aqualoc_archaeo_vins/external_klt_every2_isj_p07_aqualoc_archaeology_a02_0005_p_attempt01_klt_safe_fallback",
]


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    return executor.sha256(path)


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


def stream_snapshot(path: Path) -> dict[str, object]:
    record = file_record(path)
    record["binding"] = "PREEXECUTION_APPEND_ONLY_PREFIX_SNAPSHOT"
    return record


def tree_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def lock_hash(payload: dict[str, object]) -> str:
    return executor.lock_hash(payload)


def latest_registry_events() -> dict[str, dict[str, str]]:
    with (governance.BUNDLE / "run_registry.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    latest: dict[str, dict[str, str]] = {}
    for row in rows:
        latest[row["run_id"]] = row
    return latest


def build_queue_item(index: int) -> dict[str, object]:
    row = auditor.queue_row(index)
    allocation = auditor.allocation_row(index)
    manifest = auditor.manifest_row(row["window_id"])
    expected_frames = auditor.v2.expected_feature_frames(manifest, row["dataset_family"])
    if expected_frames != 450:
        raise ValueError(f"A01 expected feature frame count drift: {expected_frames}")
    if row["arm"] == governance.B1:
        guard = {
            "schema_version": "aqua-fe-b1-klt-nativeq-guard-decision-v1",
            "action": "ALLOW_B1_KLT_NATIVEQ",
            "contract_hash": auditor.P_CONTRACT_HASH,
        }
        attestation_suffix = ".quality-contract.json"
    elif row["arm"] == governance.M_ARM:
        guard = {
            "schema_version": "aqua-fe-p05-xfeat-backend-guard-decision-v1",
            "action": "ALLOW_M_XFEAT",
            "contract_hash": auditor.M_CONTRACT_HASH,
        }
        attestation_suffix = ".p05-xfeat-contract.json"
    else:
        guard = {
            "schema_version": "aqua-fe-nativeq-backend-guard-decision-v1",
            "action": "ALLOW_LEARNED",
            "contract_hash": auditor.P_CONTRACT_HASH,
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
        "copied_topic_policy": "EXACTLY_MATCH_FRESH_RAW_BAG_IMU_AND_REFERENCE_COUNTS",
        "attestation_suffix": attestation_suffix,
        "guard": guard,
    }


def build_lock() -> dict[str, object]:
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    latest = latest_registry_events()
    prior = []
    for index in (1, 2, 3):
        allocation = auditor.allocation_row(index)
        event = latest[allocation["run_id"]]
        if event["status"] != "COMPLETED":
            raise ValueError(f"prior queue index {index} is not COMPLETED")
        prior.append(
            {
                "queue_index": index,
                "run_id": allocation["run_id"],
                "latest_event_id": event["registry_event_id"],
                "status": event["status"],
            }
        )
    with (governance.BUNDLE / "arm_applicability.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        applicability = list(csv.DictReader(handle))
    a02_terminal = [
        row
        for row in applicability
        if row["dataset_family"] == "aqualoc_archaeology"
        and row["sequence"] == "A02"
        and row["window_start"] == "225.0"
        and row["resolution"] == "NOT_APPLICABLE"
    ]
    if len(a02_terminal) != 1 or a02_terminal[0]["accepted_lineage_count"] != "0":
        raise ValueError("A02 D closeout is not the required prior terminal evidence")

    queue_items = [build_queue_item(index) for index in (4, 5, 6)]
    for item in queue_items:
        event = latest[str(item["run_id"])]
        if not event["registry_event_id"].endswith("_e00") or event["status"] != "PLANNED":
            raise ValueError(f"queue index {item['queue_index']} is not untouched PLANNED")
        row = auditor.queue_row(int(item["queue_index"]))
        collisions = executor.target_collisions(row)
        if collisions:
            raise FileExistsError(f"queue index {item['queue_index']} collision: {collisions}")
        attempt = executor.ATTEMPT_ROOT / f"queue_{int(item['queue_index']):03d}_{item['tag']}"
        if attempt.exists():
            raise FileExistsError(f"queue index {item['queue_index']} attempt collision: {attempt}")
    if A01_RAW.exists():
        raise FileExistsError(f"A01 raw bag unexpectedly exists before lock: {A01_RAW}")
    if not A02_RAW.is_file():
        raise FileNotFoundError(A02_RAW)

    observed_frontend_bytes = sum(tree_size(path) for path in A02_RUNS)
    estimated_raw_bytes = A02_RAW.stat().st_size
    estimated_d_bytes = tree_size(A02_RUNS[0])
    reserve_bytes = 2 * 1024**3
    estimated_required = math.ceil(
        (estimated_raw_bytes + observed_frontend_bytes + estimated_d_bytes) * 1.20
        + reserve_bytes
    )
    minimum_output = max(executor.BASE_MIN_OUTPUT_FREE_BYTES, estimated_required)
    output_usage = shutil.disk_usage(governance.ROOT / queue_items[0]["expected_run_root"])
    governance_usage = shutil.disk_usage(governance.P07)
    if output_usage.free < minimum_output:
        raise RuntimeError("insufficient output capacity to freeze A01 execution")
    if governance_usage.free < executor.MIN_GOVERNANCE_FREE_BYTES:
        raise RuntimeError("insufficient governance capacity to freeze A01 execution")

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
        governance.P07 / "mp_smoke_execution_lock_v2.json",
        governance.P07 / "d_resolutions/a02_0005_not_applicable_v1.json",
        governance.ROOT / "scripts/audit_p07_a01_frontend_export_v3.py",
        governance.ROOT / "scripts/run_p07_a01_frontend_export_job_v3.py",
        governance.ROOT / "scripts/build_p07_a01_frontend_execution_lock_v3.py",
        governance.ROOT / "scripts/tests/test_p07_a01_frontend_export_v3.py",
        governance.ROOT / "scripts/tests/test_p07_a01_frontend_execution_lock_v3.py",
        governance.ROOT / "scripts/run_isj_b1_klt_nativeq_guarded_v1.sh",
        governance.ROOT / "scripts/check_b1_klt_nativeq_contract_v1.py",
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
        governance.ROOT / "uw_frontend/datasets/aqualoc_raw_to_rosbag.py",
        governance.ROOT / "uw_frontend/ros/export_vins_features.py",
        governance.ROOT / "uw_frontend/configs/experiments/isj_p05_xfeat_pairwise_nativeq.yaml",
        governance.ROOT
        / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml",
    ]
    payload: dict[str, object] = {
        "schema_version": "isj-p07-a01-frontend-execution-lock-v3",
        "status": "FROZEN_READY_FOR_A01_B1_P_M_EXPORT",
        "frozen_at": now(),
        "protocol_version": "isj-nativeq-v3-confirmatory-protocol-v1",
        "method_lock_hash": json.loads(
            governance.METHOD_LOCK.read_text(encoding="utf-8")
        )["method_lock_hash"],
        "queue_lock_hash": json.loads(
            governance.QUEUE_LOCK.read_text(encoding="utf-8")
        )["queue_lock_hash"],
        "allowed_queue_indices": [4, 5, 6],
        "allowed_arms": [governance.B1, governance.P_ARM, governance.M_ARM],
        "execution_order": [4, 5, 6],
        "window_id": auditor.A01_WINDOW_ID,
        "queue_items": queue_items,
        "dependencies": {
            "prior_queue_events": prior,
            "a02_d_resolution": "NOT_APPLICABLE",
            "queue_5_requires_queue_4_completed": True,
            "queue_6_requires_queue_4_and_5_completed": True,
            "queue_5_completion_gates_d_slot": 3,
        },
        "raw_bag_contract": {
            "path": auditor.display_path(A01_RAW),
            "preexisting_at_freeze": False,
            "producer_queue_index": 4,
            "expected_images": 901,
            "imu_and_reference_counts": "MEASURE_FROM_FRESH_RAW_AND_MATCH_ALL_ARMS",
            "estimated_bytes_from_A02_window": estimated_raw_bytes,
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
            "raw_bag_must_not_exist_before_queue_4": True,
            "replacement_requires_new_run_id_and_attempt02_or_later_tag": True,
        },
        "capacity_gate": {
            "estimated_fresh_raw_bytes": estimated_raw_bytes,
            "observed_A02_four_frontend_run_bytes": observed_frontend_bytes,
            "estimated_applicable_d_bytes": estimated_d_bytes,
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
            stream_snapshot(governance.BUNDLE / "run_registry.csv"),
            stream_snapshot(governance.BUNDLE / "arm_applicability.csv"),
        ],
        "required_terminal_evidence": [
            "fresh readable raw bag with 901 images and positive IMU/reference counts",
            "exact guard-only preflight and exact in-command nonfallback guard PASS",
            "450 feature frames with exact 13-channel schema and 350 cap",
            "feature bag copied IMU/reference counts equal fresh raw bag",
            "arm-specific contract-bound bag attestation",
            "frontend metrics and feature bag frame/observation equality",
            "P final bag resolved from exactly one self-consistent arbitration summary",
            "distinct learned-born lineage audit and zero-action B1 byte identity when count=0",
            "absence of VINS, trajectory, APE, and RPE artifacts",
            "input/output hashes and contiguous append-only registry chain",
        ],
        "artifacts": [file_record(path) for path in artifacts],
        "external_artifacts": [external_file_record(VINS_BINARY)],
        "vins_workspace": "/home/ma/SLAM/VINS-Fusion-origin",
        "forbidden_workspace": "/home/ma/SLAM/VINS-Fusion_3-15-WS",
        "outcome_boundary": "A01_B1_P_M_FRONTEND_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY",
        "held_out_frontend_outcome_read": True,
        "held_out_trajectory_outcome_read": False,
        "next_action": "EXECUTE_QUEUE_INDEX_4_THEN_5_THEN_6_THEN_RESOLVE_D_SLOT_3",
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
        "P07_A01_FRONTEND_EXECUTION_LOCK_V3_PASS "
        f"hash={payload['execution_lock_hash']} order=4,5,6"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
