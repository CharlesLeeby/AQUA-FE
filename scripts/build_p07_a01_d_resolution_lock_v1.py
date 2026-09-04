#!/usr/bin/env python3
"""Freeze the A01 zero-lineage D applicability resolution."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

try:
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import audit_p07_a01_frontend_export_v3 as auditor
    from scripts import resolve_p07_a01_d_applicability_v1 as resolver
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import audit_p07_a01_frontend_export_v3 as auditor  # type: ignore
    import resolve_p07_a01_d_applicability_v1 as resolver  # type: ignore


OUTPUT = governance.P07 / "a01_d_resolution_lock_v1.json"


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    return resolver.sha256(path)


def file_record(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": auditor.display_path(path),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def stream_snapshot(path: Path) -> dict[str, object]:
    record = file_record(path)
    record["binding"] = "PRE_RESOLUTION_APPEND_ONLY_PREFIX_SNAPSHOT"
    return record


def lock_hash(payload: dict[str, object]) -> str:
    return resolver.lock_hash(payload)


def build_lock() -> dict[str, object]:
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    with (governance.BUNDLE / "run_registry.csv").open(newline="", encoding="utf-8") as handle:
        registry = list(csv.DictReader(handle))
    parent_runs = []
    audits: dict[int, dict[str, object]] = {}
    artifacts: list[Path] = [
        governance.METHOD_LOCK,
        governance.PROTOCOL,
        governance.D_QUEUE,
        governance.QUEUE_LOCK,
        governance.P07 / "a01_frontend_execution_lock_v3.json",
    ]
    for index in (4, 5, 6):
        allocation = auditor.allocation_row(index)
        chain = [row for row in registry if row["run_id"] == allocation["run_id"]]
        if (
            len(chain) != 3
            or [row["status"] for row in chain] != ["PLANNED", "RUNNING", "COMPLETED"]
        ):
            raise ValueError(f"queue index {index} is not terminal COMPLETED")
        attempt = (
            governance.P07
            / f"frontend_attempts/queue_{index:03d}_{allocation['tag']}"
        )
        audit_path = attempt / "audit_v3.json"
        output_hashes = attempt / "output_hash_manifest.sha256"
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        if audit.get("status") != "PASS" or audit.get("run_id") != allocation["run_id"]:
            raise ValueError(f"queue index {index} audit is not exact PASS")
        audits[index] = audit
        artifacts.extend([audit_path, output_hashes])
        parent_runs.append(
            {
                "queue_index": index,
                "run_id": allocation["run_id"],
                "arm": allocation["arm"],
                "latest_registry_event_id": chain[-1]["registry_event_id"],
                "latest_registry_status": chain[-1]["status"],
                "output_hash_manifest": chain[-1]["output_hash_manifest"],
                "audit": auditor.display_path(audit_path),
                "audit_sha256": sha256(audit_path),
            }
        )
    p_audit = audits[5]
    lineage = p_audit.get("learned_lineages") or {}
    zero_action = p_audit.get("zero_action_identity") or {}
    if (
        p_audit.get("arbitration_summary", {}).get("profile") != "klt_safe_fallback"
        or lineage.get("accepted_learned_born_lineage_count") != 0
        or lineage.get("learned_born_observations") != 0
        or zero_action.get("status") != "PASS_BYTE_IDENTICAL_TO_B1"
        or zero_action.get("b1_feature_bag_sha256")
        != zero_action.get("p_feature_bag_sha256")
        or zero_action.get("p_feature_bag_sha256") != p_audit["feature_bag"]["sha256"]
    ):
        raise ValueError("A01 P audit is not exact zero-lineage B1-identical PASS")
    p_event = next(
        row
        for row in registry
        if row["run_id"] == resolver.P_RUN_ID and row["status"] == "COMPLETED"
    )
    if p_event["accepted_lineage_count"] != "0" or p_event["active"] != "false":
        raise ValueError("A01 P registry event is not zero-lineage inactive")
    _fields, applicability = resolver.read_csv_bytes(resolver.APPLICABILITY.read_bytes())
    rows = [row for row in applicability if resolver.is_a01_row(row)]
    if len(rows) != 1 or rows[0]["resolution"] != "PENDING_APPLICABILITY":
        raise ValueError("A01 D slot is not exactly one pending row")

    artifacts.extend(
        [
            governance.ROOT / p_audit["feature_bag"]["path"],
            governance.ROOT / zero_action["b1_feature_bag"],
            governance.ROOT / p_audit["raw_bag"]["path"],
            governance.ROOT / "scripts/resolve_p07_a01_d_applicability_v1.py",
            governance.ROOT / "scripts/build_p07_a01_d_resolution_lock_v1.py",
            governance.ROOT / "scripts/tests/test_p07_a01_d_resolution_v1.py",
        ]
    )
    payload: dict[str, object] = {
        "schema_version": "isj-p07-a01-d-resolution-lock-v1",
        "status": "FROZEN_READY_TO_APPEND_NOT_APPLICABLE",
        "frozen_at": now(),
        "protocol_version": "isj-nativeq-v3-confirmatory-protocol-v1",
        "window_id": "aqualoc_archaeology:A01:0018",
        "slot_index": 3,
        "locked_action": "APPEND_NOT_APPLICABLE_NO_D_BAG_NO_REPLAY_SLOT",
        "applicability_rule": "accepted_learned_born_lineage_count>0",
        "parent_runs": parent_runs,
        "parent_p": {
            "run_id": resolver.P_RUN_ID,
            "accepted_learned_born_lineage_count": 0,
            "active": False,
            "audit": next(row["audit"] for row in parent_runs if row["queue_index"] == 5),
            "audit_sha256": next(
                row["audit_sha256"] for row in parent_runs if row["queue_index"] == 5
            ),
            "profile": p_audit["arbitration_summary"]["profile"],
            "p_feature_bag": p_audit["feature_bag"]["path"],
            "p_feature_bag_sha256": p_audit["feature_bag"]["sha256"],
            "b1_feature_bag": zero_action["b1_feature_bag"],
            "b1_feature_bag_sha256": zero_action["b1_feature_bag_sha256"],
            "zero_action_identity": zero_action["status"],
        },
        "pending_row": rows[0],
        "terminal_contract": {
            "resolution": "NOT_APPLICABLE",
            "accepted_lineage_count": 0,
            "d_bag_created": False,
            "d_replay_slots_created": 0,
            "preserve_pending_row": True,
            "append_terminal_row": True,
        },
        "mutable_stream_prefix_snapshots": [
            stream_snapshot(governance.BUNDLE / "run_registry.csv"),
            stream_snapshot(governance.BUNDLE / "arm_applicability.csv"),
        ],
        "artifacts": [file_record(path) for path in artifacts],
        "outcome_boundary": "A01_D_APPLICABILITY_FRONTEND_ONLY_NO_VINS_APE_RPE_TRAJECTORY",
        "held_out_frontend_outcome_read": True,
        "held_out_trajectory_outcome_read": False,
        "next_action": "APPEND_A01_SLOT_3_NOT_APPLICABLE_ONCE",
    }
    payload["resolution_lock_hash"] = lock_hash(payload)
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
        "P07_A01_D_RESOLUTION_LOCK_V1_PASS "
        f"hash={payload['resolution_lock_hash']} action=NOT_APPLICABLE"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
