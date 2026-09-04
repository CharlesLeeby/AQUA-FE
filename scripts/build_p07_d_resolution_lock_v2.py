#!/usr/bin/env python3
"""Freeze one P07 D-applicability decision before appending its terminal row."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

try:
    from scripts import audit_p07_frontend_export_v3 as auditor
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import resolve_p07_d_applicability_v2 as resolver
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as auditor  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import resolve_p07_d_applicability_v2 as resolver  # type: ignore


LOCK_ROOT = governance.P07 / "d_resolution_locks"


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
        "path": auditor.display_path(path),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def prefix_snapshot(path: Path) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "path": auditor.display_path(path),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def lock_hash(payload: dict[str, object]) -> str:
    clone = dict(payload)
    clone.pop("resolution_lock_hash", None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def lock_path(window_id: str) -> Path:
    return LOCK_ROOT / f"{resolver.slug(window_id)}_v2.json"


def build_lock(window_id: str) -> dict[str, object]:
    output = lock_path(window_id)
    if output.exists():
        raise FileExistsError(output)
    rows = resolver.queue_rows(window_id)
    latest = resolver.latest_registry_rows(rows)
    p_row = next(row for row in rows if row["arm"] == governance.P_ARM)
    b1_row = next(row for row in rows if row["arm"] == governance.B1)
    p_audit_path, p_audit = resolver.load_p_audit(window_id, p_row)
    lineage_count = int(
        p_audit["learned_lineages"]["accepted_learned_born_lineage_count"]
    )
    p_bag = governance.ROOT / str(p_audit["feature_bag"]["path"])
    b1_bag = governance.ROOT / b1_row["expected_feature_bag"]
    if not p_bag.is_file() or not b1_bag.is_file():
        raise FileNotFoundError("D resolution requires frozen P and B1 bags")
    if lineage_count == 0 and sha256(p_bag) != sha256(b1_bag):
        raise ValueError("zero-action P is not byte-identical to frozen B1")

    manifest = auditor.manifest_row(window_id)
    applicability_rows = governance.read_csv(resolver.APPLICABILITY)
    matching = resolver.matching_applicability_rows(applicability_rows, manifest)
    pending = [row for row in matching if row["resolution"] == "PENDING_APPLICABILITY"]
    terminal = [row for row in matching if row["resolution"] != "PENDING_APPLICABILITY"]
    if len(pending) != 1 or terminal:
        raise ValueError(f"D applicability is not one pending/no terminal: {matching}")
    resolution_output, derivation_dir = resolver.output_paths(window_id, lineage_count)
    if resolution_output.exists() or (derivation_dir is not None and derivation_dir.exists()):
        raise FileExistsError("D resolution output or derivation collision")

    artifacts = [
        governance.EXPORT_QUEUE,
        governance.ALLOCATION_CSV,
        governance.QUEUE_LOCK,
        governance.METHOD_LOCK,
        governance.D_QUEUE,
        p_audit_path,
        p_bag,
        b1_bag,
        governance.ROOT / "scripts/resolve_p07_d_applicability_v2.py",
        governance.ROOT / "scripts/build_p07_d_resolution_lock_v2.py",
        governance.ROOT / "scripts/filter_feature_bag_by_channel.py",
        governance.ROOT / "scripts/audit_whole_lineage_exact_drop_v1.py",
        governance.ROOT / "scripts/attest_nativeq_feature_bag.py",
        governance.BUNDLE / "backend_quality_contract_v1.json",
    ]
    payload: dict[str, object] = {
        "schema_version": "isj-p07-d-resolution-lock-v2",
        "status": "FROZEN_READY_TO_RESOLVE_D",
        "frozen_at": now(),
        "window_id": window_id,
        "dataset_family": manifest["dataset_family"],
        "sequence": manifest["sequence"],
        "lineage_contract": {
            "accepted_learned_born_lineage_count": lineage_count,
            "birth_rule": "first ID occurrence has is_learned=1 or source_code in {10,20,30}",
            "late_marker_policy": "FAIL_CLOSED",
        },
        "decision": (
            "NOT_APPLICABLE_REQUIRE_BYTE_IDENTICAL_B1"
            if lineage_count == 0
            else "APPLICABLE_DERIVE_EXACT_WHOLE_LINEAGE_DROP"
        ),
        "parent_p": {
            "run_id": latest[governance.P_ARM]["run_id"],
            "registry_event_id": latest[governance.P_ARM]["registry_event_id"],
            "audit": auditor.display_path(p_audit_path),
            "feature_bag": auditor.display_path(p_bag),
            "feature_bag_sha256": sha256(p_bag),
        },
        "b1": {
            "run_id": latest[governance.B1]["run_id"],
            "registry_event_id": latest[governance.B1]["registry_event_id"],
            "feature_bag": auditor.display_path(b1_bag),
            "feature_bag_sha256": sha256(b1_bag),
        },
        "expected_resolution_output": auditor.display_path(resolution_output),
        "expected_derivation_dir": (
            auditor.display_path(derivation_dir) if derivation_dir is not None else None
        ),
        "artifacts": [file_record(path) for path in dict.fromkeys(artifacts)],
        "mutable_stream_prefix_snapshots": [
            prefix_snapshot(resolver.APPLICABILITY),
            prefix_snapshot(governance.BUNDLE / "run_registry.csv"),
        ],
        "outcome_boundary": "FRONTEND_ONLY_NO_VINS_APE_RPE_TRAJECTORY",
        "trajectory_outcome_read": False,
    }
    payload["resolution_lock_hash"] = lock_hash(payload)
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
        "P07_D_RESOLUTION_LOCK_V2_PASS "
        f"window={args.window_id} decision={payload['decision']} "
        f"hash={payload['resolution_lock_hash']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
