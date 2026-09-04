#!/usr/bin/env python3
"""Build the narrowed native-q v3 route lock before final P06 selection."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

try:
    from scripts.build_nativeq_backend_contract import file_record, payload_hash
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    from build_nativeq_backend_contract import file_record, payload_hash  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
DEFAULT_OUTPUT = BUNDLE / "method_lock_nativeq_legacy_candidate_v5.json"
V3_LOCK = BUNDLE / "method_lock_nativeq_legacy_candidate_v3.json"
V4_LOCK = BUNDLE / "method_lock_nativeq_legacy_candidate_v4.json"
ROUTE_CONTRACT = BUNDLE / "p04/nativeq_v3_route_contract_v1.json"
ROUTE_ADDENDUM = BUNDLE / "p04/nativeq_v3_route_addendum_v1.md"
BACKEND_CONTRACT = BUNDLE / "backend_quality_contract_v1.json"
P05_CONTRACT = BUNDLE / "p05/backend_consumer_contract_xfeat_v1.json"

ARTIFACTS = (
    V3_LOCK,
    V4_LOCK,
    ROUTE_CONTRACT,
    ROUTE_ADDENDUM,
    BACKEND_CONTRACT,
    P05_CONTRACT,
    BUNDLE / "p04/v3_control_identifiability_v1.json",
    BUNDLE / "p04/ntnu_fjord1_s83_d30_whole_lineage_exact_drop_audit_v1.json",
    BUNDLE / "p04/a03_5000_5900_actual_v3_attempt01b_export_audit_v1.json",
    BUNDLE / "p05/ntnu_fjord1_s83_d10_xfeat_bag_attestation_v1.json",
    ROOT / "scripts/run_isj_nativeq_contract_guarded_v4.sh",
    ROOT / "scripts/run_p05_modern_xfeat_baseline_guarded_v2.sh",
    ROOT / "scripts/run_p05_classical_contract_fallback_v2.sh",
    ROOT / "scripts/check_p05_xfeat_backend_contract_v1.py",
    ROOT / "scripts/attest_p05_xfeat_feature_bag_v1.py",
    ROOT / "scripts/audit_whole_lineage_exact_drop_v1.py",
    ROOT / "scripts/audit_p04_actual_v3_export_v1.py",
    ROOT / "scripts/build_p04_nativeq_v3_route_contract_v1.py",
    ROOT / "scripts/build_nativeq_legacy_method_lock_v5.py",
    ROOT / "scripts/tests/test_p05_backend_contract_guard_v1.py",
    ROOT / "scripts/tests/test_whole_lineage_exact_drop_v1.py",
    ROOT / "scripts/tests/test_p04_actual_v3_export_v1.py",
    ROOT / "scripts/tests/test_p04_nativeq_v3_route_contract_v1.py",
)


def load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def method_payload_hash(payload: dict[str, object]) -> str:
    clone = dict(payload)
    clone.pop("candidate_lock_hash", None)
    clone.pop("generated_at_utc", None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_payload() -> dict[str, object]:
    v3 = load_object(V3_LOCK)
    v4 = load_object(V4_LOCK)
    route = load_object(ROUTE_CONTRACT)
    backend = load_object(BACKEND_CONTRACT)
    p05 = load_object(P05_CONTRACT)
    if (
        v3.get("candidate_lock_hash")
        != "19b0e4754341d52d6c52e8b3da7409bf22d228ca4a775ae6efe92c072ce71f63"
        or v4.get("scientific_method_identity") != "UNCHANGED_FROM_V3"
    ):
        raise ValueError("base native-q method identity mismatch")
    if (
        route.get("schema_version") != "isj-p04-nativeq-v3-route-contract-v1"
        or route.get("status") != "READY_FOR_P06_FINAL_METHOD_FREEZE"
        or payload_hash(route) != route.get("contract_hash")
        or route.get("forbidden_outcomes_accessed") != []
    ):
        raise ValueError("P04 route contract mismatch")
    addendum = ROUTE_ADDENDUM.read_text(encoding="utf-8")
    if str(route["contract_hash"]) not in addendum:
        raise ValueError("route addendum does not bind the machine contract hash")
    if payload_hash(backend) != backend.get("contract_hash"):
        raise ValueError("proposed backend contract mismatch")
    if payload_hash(p05) != p05.get("contract_hash"):
        raise ValueError("P05 backend contract mismatch")

    arm_contract = route["arm_contract"]
    payload: dict[str, object] = {
        "schema_version": "isj-method-lock-nativeq-legacy-candidate-v5",
        "status": "READY_FOR_P06_FINAL_SELECTION",
        "protocol_version": "isj-nativeq-legacy-candidate-v5-narrowed-route",
        "scientific_method_identity": "UNCHANGED_FROM_V3",
        "base_scientific_lock_hash": v3["candidate_lock_hash"],
        "base_execution_guard_lock_hash": v4["candidate_lock_hash"],
        "p04_route_contract_hash": route["contract_hash"],
        "p04_stage_disposition": "PASS_WITH_H2_NOT_APPLICABLE_CARRIER_FEEDBACK",
        "H2_CONTROL_CONTRACT": "NOT_APPLICABLE_CARRIER_FEEDBACK",
        "arms": {
            "required_every_window": arm_contract["required_every_window"],
            "conditional_before_trajectory_outcome": arm_contract[
                "conditional_before_trajectory_outcome"
            ],
            "retired_no_slots": arm_contract["retired_no_slots"],
        },
        "entrypoints": {
            "P_legacy": "scripts/run_isj_nativeq_contract_guarded_v4.sh",
            "M": "scripts/run_p05_modern_xfeat_baseline_guarded_v2.sh",
            "D_audit": "scripts/audit_whole_lineage_exact_drop_v1.py",
        },
        "quality_contracts": {
            "P_B1_D": backend["contract_hash"],
            "M": p05["contract_hash"],
            "external_quality_mapping": "vins_safe_floor0p80_alpha0p65",
            "maximum_external_feature_budget": 350,
        },
        "applicability": route["d_legacy_applicability"],
        "claim_boundary": route["claim_boundary"],
        "artifacts": [file_record(path, root=ROOT) for path in ARTIFACTS],
        "blockers": [
            "P06 guarded final 10-low/10-normal selection has not run",
            "dataset_checksum_manifest.txt, arm_order.csv, protocol, and final method_lock.json are pending P06 finalization",
            "held-out P07 trajectory matrix has not run",
        ],
        "outcome_boundary": "METHOD_AND_FRONTEND_CONTRACT_ONLY_NO_HELD_OUT_OUTCOME",
        "forbidden_outcomes_accessed": [],
        "next_stage": "P06_GUARDED_FINAL_SELECTION",
    }
    payload["candidate_lock_hash"] = method_payload_hash(payload)
    return payload


def write_json_no_clobber(path: Path, payload: dict[str, object]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build_payload()
    write_json_no_clobber(args.output, payload)
    print(f"NATIVEQ_V5_ROUTE_LOCK PASS hash={payload['candidate_lock_hash']}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
