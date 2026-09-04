#!/usr/bin/env python3
"""Freeze additive B0/B1 execution adapters over the final scientific lock."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

try:
    from scripts.build_nativeq_backend_contract import file_record
    from scripts.build_p06_final_freeze_v1 import final_method_hash
    from scripts.check_b0_vins_origin_identity_v1 import (
        DEFAULT_BACKEND_ROOT,
        DEFAULT_BINARY,
        DEFAULT_CONTRACT,
        DEFAULT_VINS_WORKSPACE,
        evaluate_b0_identity,
    )
    from scripts.check_b1_klt_nativeq_contract_v1 import evaluate_b1
    from scripts.check_nativeq_backend_contract import DEFAULT_CONFIG, DEFAULT_EXPORTER
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    from build_nativeq_backend_contract import file_record  # type: ignore
    from build_p06_final_freeze_v1 import final_method_hash  # type: ignore
    from check_b0_vins_origin_identity_v1 import (  # type: ignore
        DEFAULT_BACKEND_ROOT,
        DEFAULT_BINARY,
        DEFAULT_CONTRACT,
        DEFAULT_VINS_WORKSPACE,
        evaluate_b0_identity,
    )
    from check_b1_klt_nativeq_contract_v1 import evaluate_b1  # type: ignore
    from check_nativeq_backend_contract import DEFAULT_CONFIG, DEFAULT_EXPORTER  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
P07 = BUNDLE / "p07"
DEFAULT_OUTPUT = P07 / "execution_adapter_lock_v1.json"
FINAL_METHOD = BUNDLE / "method_lock.json"
FINAL_PROTOCOL = BUNDLE / "protocol_v1_nativeq_v3.md"

B0 = "B0_native_vins_origin_v1"
B1 = "B1_klt_nativeq_v3"
P_ARM = "P_legacy_nativeq_xfeat_seedchain_v3"
M_ARM = "M_xfeat_pairwise_nativeq_v1"
D_ARM = "D_legacy_exact_lineage_drop_v3"

ARTIFACTS = (
    FINAL_METHOD,
    FINAL_PROTOCOL,
    BUNDLE / "arm_order.csv",
    BUNDLE / "dataset_manifest_v4.csv",
    BUNDLE / "environment_manifest_nativeq_v5_final.txt",
    ROOT / "scripts/check_b0_vins_origin_identity_v1.py",
    ROOT / "scripts/check_b1_klt_nativeq_contract_v1.py",
    ROOT / "scripts/run_isj_b0_native_vins_guarded_v1.sh",
    ROOT / "scripts/run_isj_b1_klt_nativeq_guarded_v1.sh",
    ROOT / "scripts/run_isj_nativeq_contract_guarded_v4.sh",
    ROOT / "scripts/run_p05_modern_xfeat_baseline_guarded_v2.sh",
    ROOT / "scripts/audit_whole_lineage_exact_drop_v1.py",
    ROOT / "scripts/run_ntnu_vins_eval.sh",
    ROOT / "scripts/run_aqualoc_archaeo_vins_eval.sh",
    ROOT / "scripts/run_aqualoc_real_vins_eval.sh",
    ROOT / "scripts/run_afrl_cave_vins_eval.sh",
    ROOT / "scripts/build_p07_execution_adapter_lock_v1.py",
    ROOT / "scripts/tests/test_p07_b0_b1_execution_guards.py",
    ROOT / "scripts/tests/test_p07_execution_adapter_lock_v1.py",
)


def adapter_hash(payload: dict[str, object]) -> str:
    clone = dict(payload)
    clone.pop("adapter_lock_hash", None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_payload() -> dict[str, object]:
    method = json.loads(FINAL_METHOD.read_text(encoding="utf-8"))
    if (
        method.get("status") != "FROZEN_FOR_P07_CONFIRMATORY_EXECUTION"
        or final_method_hash(method) != method.get("method_lock_hash")
    ):
        raise ValueError("final method lock mismatch")
    if method.get("arms", {}).get("required_every_window") != [B0, B1, P_ARM, M_ARM]:
        raise ValueError("final required arm set mismatch")
    b0 = evaluate_b0_identity(
        contract_path=DEFAULT_CONTRACT,
        vins_workspace=DEFAULT_VINS_WORKSPACE,
        backend_root=DEFAULT_BACKEND_ROOT,
        binary=DEFAULT_BINARY,
    )
    b1 = evaluate_b1(
        contract_path=DEFAULT_CONTRACT,
        backend_root=DEFAULT_BACKEND_ROOT,
        binary=DEFAULT_BINARY,
        exporter=DEFAULT_EXPORTER,
        frontend_config=DEFAULT_CONFIG,
    )
    if b0["contract_pass"] is not True or b1["contract_pass"] is not True:
        raise ValueError(f"B0/B1 identity rejection: {b0['reasons']} {b1['reasons']}")
    payload: dict[str, object] = {
        "schema_version": "isj-p07-execution-adapter-lock-v1",
        "status": "FROZEN_FOR_FRONTEND_EXPORT_QUEUE",
        "scientific_identity_change": "NONE_ADDITIVE_EXECUTION_PROVENANCE_ONLY",
        "final_method_lock_hash": method["method_lock_hash"],
        "entrypoints": {
            B0: "scripts/run_isj_b0_native_vins_guarded_v1.sh",
            B1: "scripts/run_isj_b1_klt_nativeq_guarded_v1.sh",
            P_ARM: "scripts/run_isj_nativeq_contract_guarded_v4.sh",
            M_ARM: "scripts/run_p05_modern_xfeat_baseline_guarded_v2.sh",
            D_ARM: "scripts/audit_whole_lineage_exact_drop_v1.py",
        },
        "standard_family_api": {
            "ntnu": "FAMILY DATASET START_S DURATION_S EVERY_N",
            "aqualoc_archaeology": "FAMILY SEQUENCE START_FRAME END_FRAME EVERY_N",
            "aqualoc_harbor": "FAMILY SEQUENCE START_FRAME END_FRAME EVERY_N",
            "afrl": "FAMILY DATASET START_S DURATION_S EVERY_N",
        },
        "window_conversion": {
            "aqualoc_archaeology": "frame=round(relative_seconds*20)",
            "aqualoc_harbor": "frame=round(relative_seconds*20)",
            "ntnu": "start_seconds=relative_window_start; duration_seconds=45",
            "afrl": "start_seconds=relative_window_start; duration_seconds=45",
        },
        "guard_decisions": {
            B0: {
                "schema": b0["schema_version"],
                "action": b0["action"],
                "contract_hash": b0["contract_hash"],
            },
            B1: {
                "schema": b1["schema_version"],
                "action": b1["action"],
                "contract_hash": b1["contract_hash"],
            },
        },
        "execution_boundary": {
            "B0": "native VINS-origin path; no external feature export",
            "B1": "fresh KLT export or hash-attested reuse under native-q",
            "P_M": "existing final guarded entrypoints unchanged",
            "mismatch": "reject arm; no mislabeled fallback result",
        },
        "artifacts": [file_record(path, root=ROOT) for path in ARTIFACTS],
        "outcome_boundary": "EXECUTION_ADAPTER_ONLY_NO_HELD_OUT_FRONTEND_OR_TRAJECTORY_OUTCOME",
        "held_out_learned_outcome_read": False,
        "held_out_trajectory_outcome_read": False,
        "next_stage": "P07_FRONTEND_EXPORT_QUEUE_FREEZE",
    }
    payload["adapter_lock_hash"] = adapter_hash(payload)
    return payload


def write_no_clobber(path: Path, payload: dict[str, object]) -> None:
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
    write_no_clobber(args.output, payload)
    print(f"P07_EXECUTION_ADAPTER_LOCK PASS hash={payload['adapter_lock_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
