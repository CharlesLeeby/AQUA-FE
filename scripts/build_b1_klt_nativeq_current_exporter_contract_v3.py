#!/usr/bin/env python3
"""Freeze the strict-keyset and sealed-environment additive B1 v3 contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

try:
    from scripts import build_b1_klt_nativeq_current_exporter_contract_v2 as v2
    from scripts import check_b1_klt_nativeq_current_exporter_contract_v2 as common
    from scripts import check_b1_klt_nativeq_current_exporter_contract_v3 as checker
except ImportError:
    import build_b1_klt_nativeq_current_exporter_contract_v2 as v2  # type: ignore
    import check_b1_klt_nativeq_current_exporter_contract_v2 as common  # type: ignore
    import check_b1_klt_nativeq_current_exporter_contract_v3 as checker  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / (
    "papers/ieee_sensors_journal_experiments/"
    "backend_quality_contract_b1_current_exporter_v3.json"
)


def build_payload() -> dict[str, object]:
    payload = v2.build_payload()
    payload["schema_version"] = "aqua-fe-b1-klt-nativeq-current-exporter-contract-v3"
    payload["status"] = "FROZEN_POST_STOP_B1_CURRENT_EXPORTER_CONTRACT_V3"
    payload["scope"] = "B1_KLT_NATIVEQ_A02_4500_6300_STRICT_ENV_COMPATIBILITY_ONLY"
    records = payload.get("records")
    if not isinstance(records, dict):
        raise v2.BuildError("V2_RECORDS_INVALID")
    records["contract_builder"] = v2.record(Path(__file__).resolve())
    records["contract_checker"] = v2.record(
        ROOT / "scripts/check_b1_klt_nativeq_current_exporter_contract_v3.py"
    )
    records["guard_wrapper"] = v2.record(
        ROOT / "scripts/run_a02_b1_klt_nativeq_current_exporter_guarded_v3.sh"
    )
    if frozenset(records) != checker.REQUIRED_RECORD_KEYS:
        raise v2.BuildError("V3_REQUIRED_RECORD_KEYSET_MISMATCH")
    ldd = payload.get("vins_ldd_core")
    if not isinstance(ldd, dict) or frozenset(ldd) != checker.REQUIRED_LDD_KEYS:
        raise v2.BuildError("V3_REQUIRED_LDD_KEYSET_MISMATCH")

    payload["algorithm_settings"] = checker.expected_algorithm_settings()
    payload["execution_governance"] = checker.expected_execution_governance()
    payload["contract_hash"] = common.payload_hash(payload)
    return payload


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    payload = build_payload()
    v2.write_exclusive(args.output, payload)
    print(f"B1_CURRENT_EXPORTER_CONTRACT_V3_FROZEN hash={payload['contract_hash']}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
