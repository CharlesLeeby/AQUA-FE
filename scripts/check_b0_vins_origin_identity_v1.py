#!/usr/bin/env python3
"""Fail closed unless the frozen VINS-origin B0 consumer identity is present."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.build_nativeq_backend_contract import payload_hash, sha256, validate_semantics
    from scripts.check_nativeq_backend_contract import write_decision
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    from build_nativeq_backend_contract import payload_hash, sha256, validate_semantics  # type: ignore
    from check_nativeq_backend_contract import write_decision  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = (
    ROOT / "papers/ieee_sensors_journal_experiments/backend_quality_contract_v1.json"
)
DEFAULT_VINS_WORKSPACE = Path("/home/ma/SLAM/VINS-Fusion-origin")
DEFAULT_BACKEND_ROOT = DEFAULT_VINS_WORKSPACE / "src/VINS-Fusion-master"
DEFAULT_BINARY = DEFAULT_VINS_WORKSPACE / "devel/lib/vins/vins_node"


def evaluate_b0_identity(
    *,
    contract_path: Path,
    vins_workspace: Path,
    backend_root: Path,
    binary: Path,
    binary_authority_path: Path | None = None,
) -> dict[str, object]:
    reasons: list[str] = []
    contract: dict[str, object] = {}
    try:
        value = json.loads(contract_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("contract is not a JSON object")
        contract = value
    except Exception as exc:
        reasons.append(f"CONTRACT_UNREADABLE:{type(exc).__name__}:{exc}")
    if contract:
        if contract.get("schema_version") != "aqua-fe-backend-quality-consumer-contract-v1":
            reasons.append("CONTRACT_SCHEMA_MISMATCH")
        if contract.get("status") != "FROZEN_DEVELOPMENT_CONSUMER_CONTRACT":
            reasons.append("CONTRACT_STATUS_MISMATCH")
        if payload_hash(contract) != contract.get("contract_hash"):
            reasons.append("CONTRACT_HASH_MISMATCH")
        expected_root = Path(str(contract.get("consumer_root", "")))
        if vins_workspace.resolve() != DEFAULT_VINS_WORKSPACE.resolve():
            reasons.append("VINS_WORKSPACE_MISMATCH")
        if backend_root.resolve() != expected_root.resolve():
            reasons.append("BACKEND_ROOT_MISMATCH")
        try:
            validate_semantics(backend_root)
        except Exception as exc:
            reasons.append(f"CONSUMER_SEMANTICS_MISMATCH:{type(exc).__name__}:{exc}")
        records = contract.get("consumer_files")
        if not isinstance(records, list):
            reasons.append("CONSUMER_FILE_RECORDS_MISSING")
        else:
            for record in records:
                if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                    reasons.append("CONSUMER_FILE_RECORD_INVALID")
                    continue
                path = backend_root / str(record["path"])
                if not path.is_file():
                    reasons.append(f"CONSUMER_FILE_MISSING:{path}")
                elif sha256(path) != record.get("sha256"):
                    reasons.append(f"CONSUMER_FILE_SHA256_MISMATCH:{path}")
        binary_record = contract.get("consumer_binary")
        if not isinstance(binary_record, dict):
            reasons.append("CONSUMER_BINARY_RECORD_MISSING")
        else:
            expected_binary = Path(str(binary_record.get("path", "")))
            authority_path = binary_authority_path or binary
            if authority_path.resolve() != expected_binary.resolve():
                reasons.append("CONSUMER_BINARY_PATH_MISMATCH")
            if not binary.is_file():
                reasons.append(f"CONSUMER_BINARY_MISSING:{binary}")
            elif sha256(binary) != binary_record.get("sha256"):
                reasons.append("CONSUMER_BINARY_SHA256_MISMATCH")
    return {
        "schema_version": "aqua-fe-b0-vins-origin-identity-decision-v1",
        "contract_pass": not reasons,
        "action": "ALLOW_B0_NATIVE" if not reasons else "REJECT_B0_NATIVE",
        "result_label": "B0_NATIVE_VINS_ORIGIN_V1" if not reasons else "B0_IDENTITY_REJECTED",
        "counts_as_b0": not reasons,
        "contract_path": str(contract_path),
        "contract_hash": contract.get("contract_hash"),
        "vins_workspace": str(vins_workspace),
        "backend_root": str(backend_root),
        "binary": str(binary),
        "binary_authority_path": str(binary_authority_path or binary),
        "reasons": reasons,
        "outcome_boundary": "EXECUTION_IDENTITY_ONLY_NO_FRONTEND_OR_TRAJECTORY_OUTCOME",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--vins-workspace", type=Path, default=DEFAULT_VINS_WORKSPACE)
    parser.add_argument("--backend-root", type=Path, default=DEFAULT_BACKEND_ROOT)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument(
        "--binary-authority-path", type=Path, default=DEFAULT_BINARY
    )
    parser.add_argument("--decision-json", type=Path, required=True)
    args = parser.parse_args()
    decision = evaluate_b0_identity(
        contract_path=args.contract,
        vins_workspace=args.vins_workspace,
        backend_root=args.backend_root,
        binary=args.binary,
        binary_authority_path=args.binary_authority_path,
    )
    write_decision(args.decision_json, decision)
    print(
        f"B0_VINS_ORIGIN_IDENTITY action={decision['action']} "
        f"reasons={len(decision['reasons'])} decision={args.decision_json}"
    )
    return 0 if decision["contract_pass"] else 42


if __name__ == "__main__":
    raise SystemExit(main())
