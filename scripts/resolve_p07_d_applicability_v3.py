#!/usr/bin/env python3
"""Resolve P07 D while accepting the AFRL-aware v4 frontend audit schema."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    from scripts import audit_p07_frontend_export_v3 as frontend_audit
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import resolve_p07_d_applicability_v2 as v2
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as frontend_audit  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import resolve_p07_d_applicability_v2 as v2  # type: ignore


ResolutionViolation = v2.ResolutionViolation
APPLICABILITY = v2.APPLICABILITY
RESOLUTION_ROOT = v2.RESOLUTION_ROOT
LOCK_ROOT = v2.LOCK_ROOT
matching_applicability_rows = v2.matching_applicability_rows
output_paths = v2.output_paths
queue_rows = v2.queue_rows
latest_registry_rows = v2.latest_registry_rows
slug = v2.slug


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolution_lock_path(window_id: str) -> Path:
    return LOCK_ROOT / f"{slug(window_id)}_v3.json"


def resolution_lock_hash(payload: dict[str, object]) -> str:
    clone = dict(payload)
    clone.pop("resolution_lock_hash", None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def p_audit_path(p_row: dict[str, str]) -> Path:
    attempt = (
        governance.P07
        / "frontend_attempts"
        / f"queue_{int(p_row['queue_index']):03d}_{p_row['tag']}"
    )
    for name in ("audit_v4.json", "audit_v3.json"):
        path = attempt / name
        if path.is_file():
            return path
    raise ResolutionViolation(f"missing P v4/v3 audit under: {attempt}")


def load_p_audit(window_id: str, p_row: dict[str, str]) -> tuple[Path, dict[str, object]]:
    path = p_audit_path(p_row)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version")
        not in {
            "isj-p07-frontend-export-audit-v4",
            "isj-p07-frontend-export-audit-v3",
            "isj-p07-a01-frontend-export-audit-v3",
        }
        or payload.get("status") != "PASS"
        or payload.get("window_id") != window_id
        or payload.get("arm") != governance.P_ARM
        or not isinstance(payload.get("learned_lineages"), dict)
        or payload.get("held_out_trajectory_outcome_read") is not False
    ):
        raise ResolutionViolation("P v4/v3 audit identity, status, or boundary mismatch")
    if payload.get("dataset_family") == "afrl" and (
        payload.get("schema_version") != "isj-p07-frontend-export-audit-v4"
        or payload.get("checks", {}).get("afrl_replay_manifest_metadata_only") is not True
    ):
        raise ResolutionViolation("AFRL P audit lacks the frozen metadata-only v4 check")
    return path, payload


def load_resolution_lock(window_id: str) -> dict[str, object]:
    path = resolution_lock_path(window_id)
    if not path.is_file():
        raise ResolutionViolation(f"missing D v3 resolution lock: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version") != "isj-p07-d-resolution-lock-v3"
        or payload.get("status") != "FROZEN_READY_TO_RESOLVE_D"
        or payload.get("window_id") != window_id
        or payload.get("resolution_lock_hash") != resolution_lock_hash(payload)
    ):
        raise ResolutionViolation("D v3 lock schema, identity, status, or hash mismatch")
    for record in payload["artifacts"]:
        artifact = governance.ROOT / str(record["path"])
        if (
            not artifact.is_file()
            or artifact.stat().st_size != int(record["size_bytes"])
            or sha256(artifact) != record["sha256"]
        ):
            raise ResolutionViolation(f"locked D v3 artifact drift: {artifact}")
    for snapshot in payload["mutable_stream_prefix_snapshots"]:
        stream = governance.ROOT / str(snapshot["path"])
        content = stream.read_bytes()
        size = int(snapshot["size_bytes"])
        if len(content) < size or hashlib.sha256(content[:size]).hexdigest() != snapshot["sha256"]:
            raise ResolutionViolation(f"append-only D v3 stream prefix drift: {stream}")
    return payload


def install_v3_contract() -> None:
    v2.p_audit_path = p_audit_path
    v2.load_p_audit = load_p_audit
    v2.resolution_lock_path = resolution_lock_path
    v2.resolution_lock_hash = resolution_lock_hash
    v2.load_resolution_lock = load_resolution_lock


def append_resolution(window_id: str) -> dict[str, object]:
    install_v3_contract()
    return v2.append_resolution(window_id)


def preflight(window_id: str) -> dict[str, object]:
    install_v3_contract()
    return v2.preflight(window_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window-id", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    if args.preflight_only:
        print(json.dumps(preflight(args.window_id), indent=2, sort_keys=True))
        return 0
    result = append_resolution(args.window_id)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
