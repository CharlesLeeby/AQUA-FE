#!/usr/bin/env python3
"""Audit P07 exports while treating the AFRL replay manifest as metadata only."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    from scripts import audit_p07_frontend_export_v3 as v3
    from scripts import build_p07_preoutcome_governance_v1 as governance
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as v3  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore


AuditViolation = v3.AuditViolation
MANIFEST_KEYS = {
    "run_dir",
    "short_bag",
    "play_bag",
    "feature_bag",
    "vins_config",
    "vins_csv",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            raise AuditViolation(f"invalid AFRL replay manifest line: {line!r}")
        key, value = line.split("=", 1)
        if key in values:
            raise AuditViolation(f"duplicate AFRL replay manifest key: {key}")
        values[key] = value
    if set(values) != MANIFEST_KEYS:
        raise AuditViolation(
            f"AFRL replay manifest keys differ: {sorted(set(values) ^ MANIFEST_KEYS)}"
        )
    return values


def validate_metadata_manifest(run_dir: Path) -> dict[str, object]:
    manifest_path = run_dir / "replay_manifest.txt"
    if not manifest_path.is_file():
        raise AuditViolation(f"missing AFRL replay metadata manifest: {manifest_path}")
    values = read_manifest(manifest_path)
    expected_root = str(v3.lexical_absolute(run_dir))
    if values["run_dir"] != expected_root:
        raise AuditViolation("AFRL replay manifest run_dir mismatch")

    expected = {
        "short_bag": run_dir / "cave_gennie_short.bag",
        "feature_bag": run_dir / "features.bag",
        "vins_config": run_dir / "vins_afrl_cave_external.yaml",
        "vins_csv": run_dir / "vins_output/vio.csv",
    }
    if values["play_bag"] != values["feature_bag"]:
        raise AuditViolation("AFRL RUN_VINS=0 manifest play_bag is not the feature bag")
    for key, path in expected.items():
        if values[key] != str(v3.lexical_absolute(path)):
            raise AuditViolation(f"AFRL replay manifest {key} mismatch")
    for key in ("short_bag", "feature_bag", "vins_config"):
        if not expected[key].is_file():
            raise AuditViolation(f"AFRL replay metadata input missing: {expected[key]}")
    if expected["vins_csv"].exists():
        raise AuditViolation("AFRL replay manifest points to an existing trajectory outcome")
    vins_output = run_dir / "vins_output"
    if not vins_output.is_dir() or any(path.is_file() for path in vins_output.rglob("*")):
        raise AuditViolation("AFRL RUN_VINS=0 output directory is missing or non-empty")
    if (run_dir / "vins.log").exists() or (run_dir / "vins_output.log").exists():
        raise AuditViolation("AFRL RUN_VINS=0 directory contains a VINS log")
    return {
        "path": v3.display_path(manifest_path),
        "sha256": sha256(manifest_path),
        "size_bytes": manifest_path.stat().st_size,
        "classification": "RUN_CONFIGURATION_METADATA_NOT_TRAJECTORY_OUTCOME",
        "vins_csv_absent": True,
        "vins_output_empty": True,
    }


def build_audit(
    *, index: int, command_log: Path, attestation: Path
) -> dict[str, object]:
    row = v3.queue_row(index)
    if row["dataset_family"] != "afrl":
        payload = v3.build_audit(
            index=index, command_log=command_log, attestation=attestation
        )
        payload["schema_version"] = "isj-p07-frontend-export-audit-v4"
        payload["afrl_replay_manifest"] = None
        return payload
    if not row["command"].startswith("RUN_VINS=0 "):
        raise AuditViolation("AFRL replay-manifest exception requires frozen RUN_VINS=0")

    original = v3.forbidden_outcomes
    validated: list[dict[str, object]] = []

    def metadata_aware_forbidden(run_dirs: list[Path]) -> list[str]:
        forbidden = original(run_dirs)
        manifest_paths = {
            v3.display_path(run_dir / "replay_manifest.txt")
            for run_dir in run_dirs
            if (run_dir / "replay_manifest.txt").is_file()
        }
        observed = {path for path in forbidden if path.endswith("/replay_manifest.txt")}
        if observed != manifest_paths:
            raise AuditViolation("AFRL replay manifest forbidden-set mismatch")
        for run_dir in run_dirs:
            if (run_dir / "replay_manifest.txt").is_file():
                validated.append(validate_metadata_manifest(run_dir))
        return [path for path in forbidden if path not in manifest_paths]

    v3.forbidden_outcomes = metadata_aware_forbidden
    try:
        payload = v3.build_audit(
            index=index, command_log=command_log, attestation=attestation
        )
    finally:
        v3.forbidden_outcomes = original
    if not validated:
        raise AuditViolation("AFRL export did not provide a validated replay manifest")
    payload["schema_version"] = "isj-p07-frontend-export-audit-v4"
    payload["checks"]["afrl_replay_manifest_metadata_only"] = True
    payload["afrl_replay_manifest"] = validated
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-index", type=int, required=True)
    parser.add_argument("--command-log", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    payload = build_audit(
        index=args.queue_index,
        command_log=args.command_log,
        attestation=args.attestation,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"P07_FRONTEND_EXPORT_AUDIT_V4_PASS queue_index={args.queue_index} "
        f"arm={payload['arm']} frames={payload['feature_bag']['feature_frames']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
