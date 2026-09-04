#!/usr/bin/env python3
"""Fail closed unless B1 KLT export and native-q consumption match the lock."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from scripts.check_nativeq_backend_contract import (
        DEFAULT_BACKEND_ROOT,
        DEFAULT_BINARY,
        DEFAULT_CONFIG,
        DEFAULT_CONTRACT,
        DEFAULT_EXPORTER,
        evaluate_contract,
        runtime_contract,
        write_decision,
    )
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    from check_nativeq_backend_contract import (  # type: ignore
        DEFAULT_BACKEND_ROOT,
        DEFAULT_BINARY,
        DEFAULT_CONFIG,
        DEFAULT_CONTRACT,
        DEFAULT_EXPORTER,
        evaluate_contract,
        runtime_contract,
        write_decision,
    )


def frozen_runtime() -> dict[str, object]:
    return runtime_contract(
        mode="vins_safe",
        floor=0.80,
        alpha=0.65,
        raw_quality=False,
        constant_quality=False,
        scales={"learned": 1.0, "sp_lg": 1.0, "xfeat": 1.0, "loftr": 1.0},
        constants={"learned": None, "sp_lg": None, "xfeat": None, "loftr": None},
    )


def evaluate_b1(
    *,
    contract_path: Path,
    backend_root: Path,
    binary: Path,
    exporter: Path,
    frontend_config: Path,
    feature_bag: Path | None = None,
    bag_attestation: Path | None = None,
) -> dict[str, object]:
    decision = evaluate_contract(
        contract_path=contract_path,
        backend_root=backend_root,
        binary=binary,
        exporter=exporter,
        frontend_config=frontend_config,
        runtime=frozen_runtime(),
        feature_bag=feature_bag,
        bag_attestation=bag_attestation,
    )
    passed = bool(decision["contract_pass"])
    return {
        **decision,
        "schema_version": "aqua-fe-b1-klt-nativeq-guard-decision-v1",
        "action": "ALLOW_B1_KLT_NATIVEQ" if passed else "REJECT_B1_KLT_NATIVEQ",
        "result_label": "B1_KLT_NATIVEQ_V3" if passed else "B1_CONTRACT_REJECTED",
        "counts_as_b1": passed,
        "counts_as_proposed_result": False,
        "outcome_boundary": "B1_EXECUTION_CONTRACT_ONLY_NO_TRAJECTORY_OUTCOME",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--backend-root", type=Path, default=DEFAULT_BACKEND_ROOT)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--exporter", type=Path, default=DEFAULT_EXPORTER)
    parser.add_argument("--frontend-config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--feature-bag", type=Path)
    parser.add_argument("--bag-attestation", type=Path)
    parser.add_argument("--decision-json", type=Path, required=True)
    args = parser.parse_args()
    decision = evaluate_b1(
        contract_path=args.contract,
        backend_root=args.backend_root,
        binary=args.binary,
        exporter=args.exporter,
        frontend_config=args.frontend_config,
        feature_bag=args.feature_bag,
        bag_attestation=args.bag_attestation,
    )
    write_decision(args.decision_json, decision)
    print(
        f"B1_KLT_NATIVEQ_GUARD action={decision['action']} "
        f"reasons={len(decision['reasons'])} decision={args.decision_json}"
    )
    return 0 if decision["contract_pass"] else 42


if __name__ == "__main__":
    raise SystemExit(main())
