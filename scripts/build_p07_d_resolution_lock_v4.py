#!/usr/bin/env python3
"""Freeze a P07 D lock with queue-55 A04 replacement-audit support."""

from __future__ import annotations

import argparse
import json
import os

try:
    from scripts import build_p07_d_resolution_lock_v2 as v2_builder
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import resolve_p07_d_applicability_v4 as resolver
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_d_resolution_lock_v2 as v2_builder  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import resolve_p07_d_applicability_v4 as resolver  # type: ignore


def lock_path(window_id: str):
    return resolver.resolution_lock_path(window_id)


def _replacement_evidence_if_used(
    p_row: dict[str, str],
) -> dict[str, object] | None:
    try:
        resolver._canonical_p_audit_path(p_row)
        return None
    except resolver.ResolutionViolation as exc:
        if p_row.get("window_id") != resolver.SPECIAL_WINDOW_ID:
            raise exc
    return resolver.load_replacement_evidence(p_row)


def _record_map(records: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(record["path"]): record for record in records}


def build_lock(window_id: str) -> dict[str, object]:
    original_resolver = v2_builder.resolver
    original_lock_path = v2_builder.lock_path
    v2_builder.resolver = resolver
    v2_builder.lock_path = lock_path
    try:
        payload = v2_builder.build_lock(window_id)
    finally:
        v2_builder.resolver = original_resolver
        v2_builder.lock_path = original_lock_path

    p_row = next(
        row for row in resolver.queue_rows(window_id) if row["arm"] == governance.P_ARM
    )
    replacement = _replacement_evidence_if_used(p_row)
    parent_contract_paths = [
        governance.ROOT / "scripts/resolve_p07_d_applicability_v2.py",
        governance.ROOT / "scripts/build_p07_d_resolution_lock_v2.py",
        governance.ROOT / "scripts/resolve_p07_d_applicability_v3.py",
        governance.ROOT / "scripts/build_p07_d_resolution_lock_v3.py",
        governance.ROOT / "scripts/tests/test_p07_d_resolution_v3.py",
    ]
    v4_paths = [
        governance.ROOT / "scripts/resolve_p07_d_applicability_v4.py",
        governance.ROOT / "scripts/build_p07_d_resolution_lock_v4.py",
        governance.ROOT / "scripts/tests/test_p07_d_resolution_v4.py",
    ]
    parent_records = [v2_builder.file_record(path) for path in parent_contract_paths]
    extra_records = [*parent_records, *[v2_builder.file_record(path) for path in v4_paths]]

    replacement_summary: dict[str, object]
    if replacement is None:
        replacement_summary = {
            "applied": False,
            "special_window_id": resolver.SPECIAL_WINDOW_ID,
            "canonical_v3_audit_used": True,
            "physical_frontend_rerun": False,
            "lineage_or_drop_contract_changed": False,
            "trajectory_outcome_read": False,
        }
    else:
        closeout_path = replacement["closeout_path"]
        audit_path = replacement["audit_path"]
        recovery_lock_path = replacement["recovery_lock_path"]
        assert hasattr(closeout_path, "is_file")
        assert hasattr(audit_path, "is_file")
        assert hasattr(recovery_lock_path, "is_file")
        evidence_records = [
            v2_builder.file_record(closeout_path),  # type: ignore[arg-type]
            v2_builder.file_record(audit_path),  # type: ignore[arg-type]
            v2_builder.file_record(recovery_lock_path),  # type: ignore[arg-type]
        ]
        extra_records.extend(evidence_records)
        closeout = replacement["closeout"]
        assert isinstance(closeout, dict)
        replacement_summary = {
            "applied": True,
            "special_window_id": resolver.SPECIAL_WINDOW_ID,
            "original_queue_index": resolver.SPECIAL_QUEUE_INDEX,
            "original_run_id": replacement["original_run_id"],
            "replacement_run_id": replacement["replacement_run_id"],
            "replacement_tag": replacement["replacement_tag"],
            "recovery_lock": evidence_records[2],
            "recovery_closeout": evidence_records[0],
            "replacement_audit": evidence_records[1],
            "physical_frontend_rerun": closeout["physical_frontend_rerun"],
            "lineage_or_drop_contract_changed": False,
            "trajectory_outcome_read": False,
        }

    payload["schema_version"] = "isj-p07-d-resolution-lock-v4"
    payload["audit_compatibility_correction"] = {
        "accepted_p_audit_schemas": [
            resolver.REPLACEMENT_AUDIT_SCHEMA,
            "isj-p07-frontend-export-audit-v3",
            "isj-p07-a01-frontend-export-audit-v3",
        ],
        "canonical_audit_policy": "V3_FOR_ALL_WINDOWS_EXCEPT_STRICT_Q55_A04_REPLACEMENT_FALLBACK",
        "lineage_or_drop_contract_changed": False,
        "trajectory_outcome_read": False,
    }
    payload["parent_resolution_contracts"] = {
        "v2_atomic_applicability_and_zero_action_identity": parent_records[:2],
        "v3_frontend_audit_schema_compatibility": parent_records[2:],
    }
    payload["layout_replacement_compatibility"] = replacement_summary
    by_path = _record_map([*payload["artifacts"], *extra_records])
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
        "P07_D_RESOLUTION_LOCK_V4_PASS "
        f"window={args.window_id} decision={payload['decision']} "
        f"hash={payload['resolution_lock_hash']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
