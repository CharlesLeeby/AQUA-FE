#!/usr/bin/env python3
"""Freeze the generalized no-clobber P07 frontend execution contract."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
from datetime import datetime
from pathlib import Path

try:
    from scripts import audit_p07_frontend_export_v3 as auditor
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import run_p07_frontend_export_job_v3 as executor
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as auditor  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import run_p07_frontend_export_job_v3 as executor  # type: ignore


OUTPUT = governance.P07 / "frontend_execution_lock_v3.json"
VINS_BINARY = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node")
START_INDEX = 7
MIB = 1024**2
GIB = 1024**3

RUN_ESTIMATES = {
    "aqualoc_archaeology": {
        governance.B1: 20 * MIB,
        governance.M_ARM: 20 * MIB,
        governance.P_ARM: 40 * MIB,
    },
    "aqualoc_harbor": {
        governance.B1: 20 * MIB,
        governance.M_ARM: 20 * MIB,
        governance.P_ARM: 40 * MIB,
    },
    "ntnu": {
        governance.B1: 16 * MIB,
        governance.M_ARM: 16 * MIB,
        governance.P_ARM: 32 * MIB,
    },
    "afrl": {
        governance.B1: 360 * MIB,
        governance.M_ARM: 360 * MIB,
        governance.P_ARM: 720 * MIB,
    },
}
RAW_WINDOW_CACHE_ESTIMATE = {
    "aqualoc_archaeology": 128 * MIB,
    "aqualoc_harbor": 128 * MIB,
    "ntnu": 0,
    "afrl": 0,
}
D_UPPER_ESTIMATE = {
    "aqualoc_archaeology": 20 * MIB,
    "aqualoc_harbor": 20 * MIB,
    "ntnu": 16 * MIB,
    "afrl": 16 * MIB,
}


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


def prefix_snapshot(path: Path) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "path": auditor.display_path(path),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
        "binding": "PREEXECUTION_APPEND_ONLY_PREFIX_SNAPSHOT",
    }


def lock_hash(payload: dict[str, object]) -> str:
    clone = dict(payload)
    clone.pop("execution_lock_hash", None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _a02_d_is_terminal() -> bool:
    rows = governance.read_csv(governance.BUNDLE / "arm_applicability.csv")
    matches = [
        row
        for row in rows
        if row["dataset_family"] == "aqualoc_archaeology"
        and row["sequence"] == "A02"
        and float(row["window_start"]) == 225.0
        and float(row["window_end"]) == 270.0
    ]
    return (
        len(matches) == 2
        and [row["resolution"] for row in matches]
        == ["PENDING_APPLICABILITY", "NOT_APPLICABLE"]
    )


def resolution_evidence(window_id: str) -> Path:
    manifest = auditor.manifest_row(window_id)
    rows = governance.read_csv(governance.BUNDLE / "arm_applicability.csv")
    matches = [
        row
        for row in rows
        if row["dataset_family"] == manifest["dataset_family"]
        and row["sequence"] == manifest["sequence"]
        and float(row["window_start"]) == float(manifest["window_start_s"])
        and float(row["window_end"]) == float(manifest["window_end_s"])
        and row["resolution"] != "PENDING_APPLICABILITY"
    ]
    if len(matches) != 1:
        raise ValueError(f"window {window_id} does not have one terminal D resolution")
    path = governance.ROOT / matches[0]["evidence_path"]
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def build_queue_items() -> tuple[list[dict[str, object]], dict[str, int]]:
    executor.install_generalized_contract()
    items: list[dict[str, object]] = []
    d_estimates: dict[str, int] = {}
    seen_windows: set[str] = set()
    for index in range(START_INDEX, 61):
        row = auditor.queue_row(index)
        allocation = auditor.allocation_row(index)
        manifest = auditor.manifest_row(row["window_id"])
        chain = executor.registry_chain(allocation["run_id"])
        if len(chain) != 1 or chain[-1]["status"] != "PLANNED":
            raise ValueError(f"queue index {index} is not untouched PLANNED")
        collisions = executor.target_collisions(row)
        if collisions:
            raise FileExistsError(f"queue index {index} target collision: {collisions}")
        attempt = executor.ATTEMPT_ROOT / f"queue_{index:03d}_{row['tag']}"
        if attempt.exists():
            raise FileExistsError(f"queue index {index} attempt collision: {attempt}")

        family = row["dataset_family"]
        estimate = int(RUN_ESTIMATES[family][row["arm"]])
        if row["window_id"] not in seen_windows:
            estimate += int(RAW_WINDOW_CACHE_ESTIMATE[family])
            seen_windows.add(row["window_id"])
        d_estimates[row["window_id"]] = int(D_UPPER_ESTIMATE[family])
        items.append(
            {
                "queue_index": index,
                "run_id": allocation["run_id"],
                "window_id": row["window_id"],
                "dataset_family": family,
                "arm": row["arm"],
                "tag": row["tag"],
                "command": row["command"],
                "command_sha256": row["command_sha256"],
                "expected_run_root": row["expected_run_root"],
                "expected_feature_bag": row["expected_feature_bag"],
                "feature_bag_resolution": row["feature_bag_resolution"],
                "expected_feature_frames": auditor.expected_feature_frames(
                    manifest, family
                ),
                "required_sensor_reference_topics": list(
                    auditor.SENSOR_TOPIC_REQUIREMENTS[family]
                ),
                "estimated_output_bytes": estimate,
            }
        )
    return items, d_estimates


def build_lock() -> dict[str, object]:
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    for index in range(1, START_INDEX):
        allocation = auditor.allocation_row(index)
        chain = executor.registry_chain(allocation["run_id"])
        if not chain or chain[-1]["status"] != "COMPLETED":
            raise ValueError(f"A02 predecessor queue index {index} is not COMPLETED")
    if not _a02_d_is_terminal():
        raise ValueError("A02 D slot is not terminal NOT_APPLICABLE")
    a01_resolution = resolution_evidence("aqualoc_archaeology:A01:0018")

    queue_items, d_estimates = build_queue_items()
    total_runs = sum(int(item["estimated_output_bytes"]) for item in queue_items)
    total_d = sum(d_estimates.values())
    margin = 1.20
    reserve = 2 * GIB
    first_window = str(queue_items[0]["window_id"])
    first_batch_runs = sum(
        int(item["estimated_output_bytes"])
        for item in queue_items
        if str(item["window_id"]) == first_window
    )
    first_batch_d = int(d_estimates[first_window])
    required = max(
        executor.BASE_MIN_OUTPUT_FREE_BYTES,
        math.ceil((first_batch_runs + first_batch_d) * margin + reserve),
    )
    output_usage = shutil.disk_usage(
        governance.ROOT / str(queue_items[0]["expected_run_root"])
    )
    governance_usage = shutil.disk_usage(governance.P07)
    if output_usage.free < required:
        raise RuntimeError(
            f"insufficient output capacity: free={output_usage.free} required={required}"
        )
    if governance_usage.free < executor.MIN_GOVERNANCE_FREE_BYTES:
        raise RuntimeError("insufficient governance capacity")

    artifacts = [
        governance.EXPORT_QUEUE,
        governance.QUEUE_LOCK,
        governance.ALLOCATION_CSV,
        governance.ANALYSIS_LOCK,
        governance.P07 / "execution_adapter_lock_v1.json",
        governance.P07 / "mp_smoke_execution_lock_v2.json",
        governance.P07 / "a02_d_resolution_lock_v1.json",
        governance.P07 / "d_resolutions/a02_0005_not_applicable_v1.json",
        governance.P07 / "a01_frontend_execution_lock_v3.json",
        a01_resolution,
        governance.METHOD_LOCK,
        governance.PROTOCOL,
        governance.D_QUEUE,
        governance.MANIFEST,
        governance.BUNDLE / "arm_order.csv",
        governance.BUNDLE / "dataset_checksum_manifest.txt",
        governance.BUNDLE / "backend_quality_contract_v1.json",
        governance.BUNDLE / "p05/backend_consumer_contract_xfeat_v1.json",
        governance.ROOT / "scripts/audit_p07_frontend_export_v3.py",
        governance.ROOT / "scripts/run_p07_frontend_export_job_v3.py",
        governance.ROOT / "scripts/resolve_p07_d_applicability_v2.py",
        governance.ROOT / "scripts/build_p07_d_resolution_lock_v2.py",
        governance.ROOT / "scripts/build_p07_frontend_execution_lock_v3.py",
        governance.ROOT / "scripts/run_p07_frontend_queue_v3.py",
        governance.ROOT / "scripts/audit_p07_a01_frontend_export_v3.py",
        governance.ROOT / "scripts/run_p07_a01_frontend_export_job_v3.py",
        governance.ROOT / "scripts/build_p07_a01_frontend_execution_lock_v3.py",
        governance.ROOT / "scripts/run_isj_b1_klt_nativeq_guarded_v1.sh",
        governance.ROOT / "scripts/run_p05_modern_xfeat_baseline_guarded_v2.sh",
        governance.ROOT / "scripts/run_p05_modern_xfeat_baseline.sh",
        governance.ROOT / "scripts/run_isj_nativeq_contract_guarded_v4.sh",
        governance.ROOT / "scripts/run_isj_nativeq_legacy_candidate.sh",
        governance.ROOT / "scripts/run_xfeat_seedchain_arbitrated_eval.sh",
        governance.ROOT / "scripts/check_b1_klt_nativeq_contract_v1.py",
        governance.ROOT / "scripts/check_p05_xfeat_backend_contract_v1.py",
        governance.ROOT / "scripts/check_nativeq_backend_contract.py",
        governance.ROOT / "scripts/attest_p05_xfeat_feature_bag_v1.py",
        governance.ROOT / "scripts/attest_nativeq_feature_bag.py",
        governance.ROOT / "scripts/filter_feature_bag_by_channel.py",
        governance.ROOT / "scripts/audit_whole_lineage_exact_drop_v1.py",
        governance.ROOT / "uw_frontend/ros/export_vins_features.py",
        governance.ROOT
        / "uw_frontend/configs/experiments/isj_p05_xfeat_pairwise_nativeq.yaml",
        governance.ROOT
        / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml",
    ]
    payload: dict[str, object] = {
        "schema_version": "isj-p07-frontend-execution-lock-v3",
        "status": "FROZEN_READY_FOR_QUEUE_INDEX_4_PLUS",
        "frozen_at": now(),
        "protocol_version": "isj-nativeq-v3-confirmatory-protocol-v1",
        "method_lock_hash": json.loads(
            governance.METHOD_LOCK.read_text(encoding="utf-8")
        )["method_lock_hash"],
        "queue_lock_hash": json.loads(
            governance.QUEUE_LOCK.read_text(encoding="utf-8")
        )["queue_lock_hash"],
        "allowed_queue_indices": list(range(START_INDEX, 61)),
        "allowed_arms": [governance.B1, governance.M_ARM, governance.P_ARM],
        "execution_order": list(range(START_INDEX, 61)),
        "queue_items": queue_items,
        "dependencies": {
            "required_completed_queue_indices": list(range(1, START_INDEX)),
            "a02_d_required_resolution": "NOT_APPLICABLE",
            "a01_d_required_terminal_evidence": auditor.display_path(a01_resolution),
        },
        "guard_policy": {
            "preflight_before_each_export": True,
            "outer_contract_fallback_counts_as_arm": False,
            "inherited_environment_is_sanitized": True,
        },
        "zero_action_policy": {
            "p_before_b1_may_defer_identity": True,
            "d_resolution_requires_byte_identical_p_and_b1": True,
            "trajectory_outcomes_remain_forbidden": True,
        },
        "no_clobber": {
            "attempt_directories_must_not_exist": True,
            "target_tag_families_must_not_exist": True,
            "replacement_requires_new_run_id_and_attempt02_or_later_tag": True,
        },
        "capacity_gate": {
            "estimated_remaining_run_bytes": total_runs,
            "d_upper_bound_bytes_by_window": d_estimates,
            "estimated_remaining_d_bytes": total_d,
            "batch_unit": "ONE_WINDOW_THREE_FRONTEND_ARMS_PLUS_CONDITIONAL_D",
            "initial_batch_window_id": first_window,
            "initial_batch_run_bytes": first_batch_runs,
            "initial_batch_d_upper_bound_bytes": first_batch_d,
            "margin_multiplier": margin,
            "separate_reserve_bytes": reserve,
            "base_minimum_output_free_bytes": executor.BASE_MIN_OUTPUT_FREE_BYTES,
            "initial_required_output_free_bytes": required,
            "observed_output_free_bytes": output_usage.free,
            "minimum_governance_free_bytes": executor.MIN_GOVERNANCE_FREE_BYTES,
            "observed_governance_free_bytes": governance_usage.free,
            "recompute_remaining_batch_before_each_job": True,
        },
        "mutable_stream_prefix_snapshots": [
            prefix_snapshot(governance.BUNDLE / "run_registry.csv"),
            prefix_snapshot(governance.BUNDLE / "arm_applicability.csv"),
        ],
        "required_terminal_evidence": [
            "exact nonfallback guard PASS",
            "expected feature frames and complete 13-channel schema",
            "350-feature cap and finite native q/sigma",
            "required family-specific copied sensor/reference topics",
            "arm-specific contract-bound attestation",
            "frontend metrics equal feature-bag observations",
            "P final bag resolved only from its arbitration summary",
            "zero-action exact B1 identity or positive lineage count",
            "absence of VINS, trajectory, APE, and RPE artifacts",
            "input/output hashes and contiguous append-only registry chain",
        ],
        "artifacts": [file_record(path) for path in dict.fromkeys(artifacts)],
        "external_artifacts": [external_file_record(VINS_BINARY)],
        "vins_workspace": "/home/ma/SLAM/VINS-Fusion-origin",
        "forbidden_workspace": "/home/ma/SLAM/VINS-Fusion_3-15-WS",
        "outcome_boundary": "QUEUE_7_60_FRONTEND_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY",
        "held_out_frontend_outcome_read": True,
        "held_out_trajectory_outcome_read": False,
        "next_action": "EXECUTE_QUEUE_INDEX_7_THROUGH_60_SERIAL_AND_RESOLVE_EACH_D_SLOT",
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
        "P07_FRONTEND_EXECUTION_LOCK_V3_PASS "
        f"hash={payload['execution_lock_hash']} jobs={len(payload['queue_items'])} "
        f"required_bytes={payload['capacity_gate']['initial_required_output_free_bytes']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
