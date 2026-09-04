#!/usr/bin/env python3
"""Freeze a D-resolution lock that accepts v4 P frontend audits."""

from __future__ import annotations

import argparse
import json
import os

try:
    from scripts import build_p07_d_resolution_lock_v2 as v2
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import resolve_p07_d_applicability_v3 as resolver
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_d_resolution_lock_v2 as v2  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import resolve_p07_d_applicability_v3 as resolver  # type: ignore


def lock_path(window_id: str):
    return resolver.resolution_lock_path(window_id)


def build_lock(window_id: str) -> dict[str, object]:
    resolver.install_v3_contract()
    original_resolver = v2.resolver
    original_lock_path = v2.lock_path
    v2.resolver = resolver
    v2.lock_path = lock_path
    try:
        payload = v2.build_lock(window_id)
    finally:
        v2.resolver = original_resolver
        v2.lock_path = original_lock_path
    payload["schema_version"] = "isj-p07-d-resolution-lock-v3"
    payload["audit_compatibility_correction"] = {
        "accepted_p_audit_schemas": [
            "isj-p07-frontend-export-audit-v4",
            "isj-p07-frontend-export-audit-v3",
            "isj-p07-a01-frontend-export-audit-v3",
        ],
        "lineage_or_drop_contract_changed": False,
        "trajectory_outcome_read": False,
    }
    extra = [
        v2.file_record(governance.ROOT / "scripts/resolve_p07_d_applicability_v3.py"),
        v2.file_record(governance.ROOT / "scripts/build_p07_d_resolution_lock_v3.py"),
        v2.file_record(governance.ROOT / "scripts/tests/test_p07_d_resolution_v3.py"),
    ]
    by_path = {str(record["path"]): record for record in [*payload["artifacts"], *extra]}
    payload["artifacts"] = list(by_path.values())
    payload["resolution_lock_hash"] = resolver.resolution_lock_hash(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window-id", required=True)
    args = parser.parse_args()
    payload = build_lock(args.window_id)
    output = lock_path(args.window_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f"{output.name}.partial.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, output)
    print(
        "P07_D_RESOLUTION_LOCK_V3_PASS "
        f"window={args.window_id} decision={payload['decision']} "
        f"hash={payload['resolution_lock_hash']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
