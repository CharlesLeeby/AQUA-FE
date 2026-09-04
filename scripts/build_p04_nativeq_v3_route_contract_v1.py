#!/usr/bin/env python3
"""Build the narrowed native-q v3 P04 route contract without outcome access."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

try:
    from scripts.build_nativeq_backend_contract import file_record, payload_hash
    from scripts.check_p05_xfeat_backend_contract_v1 import attestation_payload_hash
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    from build_nativeq_backend_contract import file_record, payload_hash  # type: ignore
    from check_p05_xfeat_backend_contract_v1 import (  # type: ignore
        attestation_payload_hash,
    )


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
DEFAULT_OUTPUT = BUNDLE / "p04/nativeq_v3_route_contract_v1.json"
V3_LOCK = BUNDLE / "method_lock_nativeq_legacy_candidate_v3.json"
V4_LOCK = BUNDLE / "method_lock_nativeq_legacy_candidate_v4.json"
IDENTIFIABILITY = BUNDLE / "p04/v3_control_identifiability_v1.json"
DECISION = BUNDLE / "p04/implementation_decision_v3.md"
DROP_AUDIT = (
    BUNDLE / "p04/ntnu_fjord1_s83_d30_whole_lineage_exact_drop_audit_v1.json"
)
ZERO_ACTION_AUDIT = (
    BUNDLE / "p04/a03_5000_5900_actual_v3_attempt01b_export_audit_v1.json"
)
P05_CONTRACT = BUNDLE / "p05/backend_consumer_contract_xfeat_v1.json"
P05_ATTESTATION = (
    BUNDLE / "p05/ntnu_fjord1_s83_d10_xfeat_bag_attestation_v1.json"
)
P_GUARD = ROOT / "scripts/run_isj_nativeq_contract_guarded_v4.sh"
M_GUARD = ROOT / "scripts/run_p05_modern_xfeat_baseline_guarded_v2.sh"
DROP_AUDITOR = ROOT / "scripts/audit_whole_lineage_exact_drop_v1.py"
ZERO_ACTION_AUDITOR = ROOT / "scripts/audit_p04_actual_v3_export_v1.py"
P05_CHECKER = ROOT / "scripts/check_p05_xfeat_backend_contract_v1.py"
P05_ATTESTER = ROOT / "scripts/attest_p05_xfeat_feature_bag_v1.py"


def load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def validate_inputs() -> dict[str, dict[str, object]]:
    values = {
        "v3": load_object(V3_LOCK),
        "v4": load_object(V4_LOCK),
        "identifiability": load_object(IDENTIFIABILITY),
        "drop": load_object(DROP_AUDIT),
        "zero_action": load_object(ZERO_ACTION_AUDIT),
        "p05_contract": load_object(P05_CONTRACT),
        "p05_attestation": load_object(P05_ATTESTATION),
    }
    v3 = values["v3"]
    if (
        v3.get("schema_version") != "isj-method-lock-nativeq-legacy-candidate-v3"
        or v3.get("candidate_lock_hash")
        != "19b0e4754341d52d6c52e8b3da7409bf22d228ca4a775ae6efe92c072ce71f63"
    ):
        raise ValueError("native-q v3 scientific identity mismatch")
    v4 = values["v4"]
    if (
        v4.get("schema_version") != "isj-method-lock-nativeq-legacy-candidate-v4"
        or v4.get("scientific_method_identity") != "UNCHANGED_FROM_V3"
    ):
        raise ValueError("native-q v4 execution-guard identity mismatch")
    identifiability = values["identifiability"]
    disposition = identifiability.get("recommended_disposition")
    if (
        identifiability.get("status") != "PASS"
        or identifiability.get("decision")
        != "STRICT_MATCHED_CLASSICAL_CONTROL_NOT_IDENTIFIABLE_UNDER_V3"
        or not isinstance(disposition, dict)
        or disposition.get("H2_CONTROL_CONTRACT")
        != "NOT_APPLICABLE_CARRIER_FEEDBACK"
        or disposition.get("main_confirmatory_arms")
        != ["B0", "B1", "P_legacy", "M"]
    ):
        raise ValueError("P04 identifiability disposition mismatch")
    drop = values["drop"]
    if (
        drop.get("contract_pass") is not True
        or drop.get("decision") != "PASS_EXACT_WHOLE_LINEAGE_DROP"
        or drop.get("forbidden_outcomes_accessed") != []
    ):
        raise ValueError("whole-lineage exact-drop audit has not passed")
    zero_action = values["zero_action"]
    if (
        zero_action.get("contract_pass") is not True
        or zero_action.get("decision")
        != "PASS_ACTUAL_V3_ZERO_ACTION_KLT_FALLBACK"
        or zero_action.get("forbidden_outcomes_accessed") != []
    ):
        raise ValueError("actual-v3 zero-action export audit has not passed")
    p05_contract = values["p05_contract"]
    if (
        p05_contract.get("schema_version")
        != "aqua-fe-p05-xfeat-backend-consumer-contract-v1"
        or p05_contract.get("status")
        != "FROZEN_DEVELOPMENT_P05_CONSUMER_CONTRACT"
        or payload_hash(p05_contract) != p05_contract.get("contract_hash")
    ):
        raise ValueError("P05 backend-consumer contract mismatch")
    p05_attestation = values["p05_attestation"]
    if (
        p05_attestation.get("status") != "PASS"
        or p05_attestation.get("contract_pass") is not True
        or p05_attestation.get("backend_contract_hash")
        != p05_contract.get("contract_hash")
        or attestation_payload_hash(p05_attestation)
        != p05_attestation.get("attestation_hash")
    ):
        raise ValueError("P05 bag attestation mismatch")
    return values


def build_payload() -> dict[str, object]:
    values = validate_inputs()
    v3 = values["v3"]
    v4 = values["v4"]
    p05_contract = values["p05_contract"]
    payload: dict[str, object] = {
        "schema_version": "isj-p04-nativeq-v3-route-contract-v1",
        "status": "READY_FOR_P06_FINAL_METHOD_FREEZE",
        "scientific_method": {
            "profile": "isj-nativeq-legacy-candidate-v3",
            "candidate_lock_hash": v3["candidate_lock_hash"],
            "identity_change": "NONE",
            "execution_guard": "isj-nativeq-legacy-candidate-v4-guarded-execution",
            "execution_guard_lock_hash": v4["candidate_lock_hash"],
        },
        "claim_boundary": {
            "allowed": (
                "A gated learned-seeded persistent frontend is evaluated against "
                "strong KLT and modern XFeat baselines under a frozen native-q consumer."
            ),
            "forbidden": [
                "learned measurements are uniformly superior to classical features",
                "detector source has a common-carrier causal effect under frozen v3",
                "D_legacy removes the complete learned frontend",
                "development A03 or NTNU results are held-out confirmation",
            ],
        },
        "arm_contract": {
            "required_every_window": [
                "B0_native_vins_origin_v1",
                "B1_klt_nativeq_v3",
                "P_legacy_nativeq_xfeat_seedchain_v3",
                "M_xfeat_pairwise_nativeq_v1",
            ],
            "conditional_before_trajectory_outcome": [
                "D_legacy_exact_lineage_drop_v3"
            ],
            "retired_no_slots": [
                "C_legacy_independent_classical_v3",
                "B2_all_eligible",
            ],
            "maximum_external_feature_budget": 350,
            "dose_contract": "SAME_MAXIMUM_BUDGET_NOT_EQUAL_REALIZED_COUNT",
            "backend_quality": "vins_safe_floor0p80_alpha0p65",
        },
        "hypothesis_disposition": {
            "H2_CONTROL_CONTRACT": "NOT_APPLICABLE_CARRIER_FEEDBACK",
            "H2_paper_result": "INCONCLUSIVE_NOT_TESTED_UNDER_FROZEN_V3",
            "H3_DROP_CONTRACT": "CONDITIONAL_DIRECT_BACKEND_EXPOSURE_EFFECT",
        },
        "d_legacy_applicability": {
            "resolution_time": (
                "after frozen P export and before reading any trajectory, APE, or RPE"
            ),
            "active_rule": "accepted_learned_born_lineage_count > 0",
            "zero_action": "NOT_APPLICABLE",
            "active_action": (
                "derive D by deleting every observation of every learned-born P ID"
            ),
            "required_audit": "PASS_EXACT_WHOLE_LINEAGE_DROP",
            "audit_failure": "BLOCK_D_AND_MARK_H3_INELIGIBLE_CONTRACT_FAILURE",
            "interpretation": (
                "Direct backend exposure effect on the learned-conditioned carrier; "
                "not removal of the complete learned frontend."
            ),
        },
        "development_diagnostics": {
            "classical_results": "RETAIN_MANDATORY_WITHOUT_CAUSAL_LANGUAGE",
            "a03_actual_v3": "ZERO_ACTION_KLT_FALLBACK",
            "ntnu_exact_drop": "PASS_EXACT_WHOLE_LINEAGE_DROP",
            "confirmatory_denominator": False,
        },
        "entrypoints": {
            "P_legacy": file_record(P_GUARD, root=ROOT),
            "M": file_record(M_GUARD, root=ROOT),
        },
        "evidence": [
            file_record(path, root=ROOT)
            for path in (
                V3_LOCK,
                V4_LOCK,
                IDENTIFIABILITY,
                DECISION,
                DROP_AUDIT,
                ZERO_ACTION_AUDIT,
                P05_CONTRACT,
                P05_ATTESTATION,
                DROP_AUDITOR,
                ZERO_ACTION_AUDITOR,
                P05_CHECKER,
                P05_ATTESTER,
            )
        ],
        "p05_backend_contract_hash": p05_contract["contract_hash"],
        "outcome_boundary": "P04_FRONTEND_CONTRACT_ONLY_NO_VINS_APE_RPE_TRAJECTORY",
        "forbidden_outcomes_accessed": [],
        "next_stage": "P06_GUARDED_FINAL_SELECTION_THEN_FINAL_METHOD_LOCK",
    }
    payload["contract_hash"] = payload_hash(payload)
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
    print(f"P04_NATIVEQ_V3_ROUTE_CONTRACT PASS hash={payload['contract_hash']}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
