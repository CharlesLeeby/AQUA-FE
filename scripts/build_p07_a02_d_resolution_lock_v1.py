#!/usr/bin/env python3
"""Freeze the A02 zero-lineage D applicability resolution."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

try:
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import audit_p07_mp_frontend_export_v2 as mp_auditor
    from scripts import resolve_p07_a02_d_applicability_v1 as resolver
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import audit_p07_mp_frontend_export_v2 as mp_auditor  # type: ignore
    import resolve_p07_a02_d_applicability_v1 as resolver  # type: ignore


OUTPUT = governance.P07 / "a02_d_resolution_lock_v1.json"
P_ATTEMPT = (
    governance.P07
    / "frontend_attempts/queue_003_isj_p07_aqualoc_archaeology_a02_0005_p_attempt01"
)
P_AUDIT = P_ATTEMPT / "audit_v2.json"
P_OUTPUT_HASHES = P_ATTEMPT / "output_hash_manifest.sha256"


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
        "path": mp_auditor.display_path(path),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def stream_snapshot(path: Path) -> dict[str, object]:
    record = file_record(path)
    record["binding"] = "PRE_RESOLUTION_APPEND_ONLY_PREFIX_SNAPSHOT"
    return record


def lock_hash(payload: dict[str, object]) -> str:
    return resolver.lock_hash(payload)


def registry_chain() -> list[dict[str, str]]:
    with (governance.BUNDLE / "run_registry.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [row for row in rows if row["run_id"] == resolver.P_RUN_ID]


def build_lock() -> dict[str, object]:
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    audit = json.loads(P_AUDIT.read_text(encoding="utf-8"))
    lineage = audit.get("learned_lineages") or {}
    zero_action = audit.get("zero_action_identity") or {}
    if (
        audit.get("status") != "PASS"
        or audit.get("arm") != governance.P_ARM
        or audit.get("arbitration_summary", {}).get("profile") != "klt_safe_fallback"
        or lineage.get("accepted_learned_born_lineage_count") != 0
        or lineage.get("learned_born_observations") != 0
        or zero_action.get("status") != "PASS_BYTE_IDENTICAL_TO_B1"
        or zero_action.get("b1_feature_bag_sha256")
        != zero_action.get("p_feature_bag_sha256")
        or zero_action.get("p_feature_bag_sha256") != audit["feature_bag"]["sha256"]
    ):
        raise ValueError("P audit is not the exact zero-lineage, B1-identical PASS")
    chain = registry_chain()
    if (
        len(chain) != 3
        or [row["status"] for row in chain] != ["PLANNED", "RUNNING", "COMPLETED"]
        or chain[-1]["accepted_lineage_count"] != "0"
        or chain[-1]["active"] != "false"
    ):
        raise ValueError("P registry chain is not the exact zero-lineage completion")
    _fields, applicability = resolver.read_csv_bytes(resolver.APPLICABILITY.read_bytes())
    rows = [row for row in applicability if resolver.is_a02_row(row)]
    if len(rows) != 1 or rows[0]["resolution"] != "PENDING_APPLICABILITY":
        raise ValueError("A02 D slot is not exactly one pending row")

    artifacts = [
        governance.METHOD_LOCK,
        governance.PROTOCOL,
        governance.D_QUEUE,
        governance.QUEUE_LOCK,
        governance.P07 / "mp_smoke_execution_lock_v2.json",
        P_AUDIT,
        P_OUTPUT_HASHES,
        governance.ROOT / audit["feature_bag"]["path"],
        governance.ROOT / zero_action["b1_feature_bag"],
        governance.ROOT / "scripts/resolve_p07_a02_d_applicability_v1.py",
        governance.ROOT / "scripts/build_p07_a02_d_resolution_lock_v1.py",
        governance.ROOT / "scripts/tests/test_p07_a02_d_resolution_v1.py",
    ]
    payload: dict[str, object] = {
        "schema_version": "isj-p07-a02-d-resolution-lock-v1",
        "status": "FROZEN_READY_TO_APPEND_NOT_APPLICABLE",
        "frozen_at": now(),
        "protocol_version": "isj-nativeq-v3-confirmatory-protocol-v1",
        "window_id": "aqualoc_archaeology:A02:0005",
        "slot_index": 4,
        "locked_action": "APPEND_NOT_APPLICABLE_NO_D_BAG_NO_REPLAY_SLOT",
        "applicability_rule": "accepted_learned_born_lineage_count>0",
        "parent_p": {
            "run_id": resolver.P_RUN_ID,
            "latest_registry_event_id": chain[-1]["registry_event_id"],
            "latest_registry_status": chain[-1]["status"],
            "accepted_learned_born_lineage_count": 0,
            "active": False,
            "audit": mp_auditor.display_path(P_AUDIT),
            "audit_sha256": sha256(P_AUDIT),
            "output_hash_manifest": chain[-1]["output_hash_manifest"],
            "profile": audit["arbitration_summary"]["profile"],
            "p_feature_bag": audit["feature_bag"]["path"],
            "p_feature_bag_sha256": audit["feature_bag"]["sha256"],
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
        "outcome_boundary": "A02_D_APPLICABILITY_FRONTEND_ONLY_NO_VINS_APE_RPE_TRAJECTORY",
        "held_out_frontend_outcome_read": True,
        "held_out_trajectory_outcome_read": False,
        "next_action": "APPEND_A02_SLOT_4_NOT_APPLICABLE_ONCE",
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
        "P07_A02_D_RESOLUTION_LOCK_V1_PASS "
        f"hash={payload['resolution_lock_hash']} action=NOT_APPLICABLE"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
