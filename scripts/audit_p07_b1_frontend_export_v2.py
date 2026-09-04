#!/usr/bin/env python3
"""V2 B1 auditor correcting workspace-symlink display normalization only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts import audit_p07_b1_frontend_export_v1 as v1


def parse_guard_path_without_resolving_workspace_symlink(command_log: Path) -> Path:
    import re

    text = command_log.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(r"\bdecision=([^\s]+_decision\.json)", text)
    unique = list(dict.fromkeys(matches))
    if len(unique) != 1:
        raise ValueError(f"expected one guard decision in command log, found {unique}")
    path = Path(unique[0])
    if not path.is_absolute():
        path = v1.governance.ROOT / path
    return path.absolute()


def build_audit_v2(*, index: int, command_log: Path, attestation: Path) -> dict[str, object]:
    original = v1.parse_guard_path
    v1.parse_guard_path = parse_guard_path_without_resolving_workspace_symlink
    try:
        payload = v1.build_audit(
            index=index,
            command_log=command_log,
            attestation=attestation,
        )
    finally:
        v1.parse_guard_path = original
    payload["schema_version"] = "isj-p07-b1-frontend-export-audit-v2"
    payload["auditor_correction"] = (
        "Preserve the workspace-visible /home/ma/AQUA-FE_WS/logs path instead "
        "of resolving its /mnt/data symlink before relative display. No data, "
        "contract, threshold, or scientific check changed."
    )
    payload["supersedes_failed_auditor"] = "audit_p07_b1_frontend_export_v1.py"
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
    payload = build_audit_v2(
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
        f"P07_B1_FRONTEND_EXPORT_AUDIT_V2_PASS queue_index={args.queue_index} "
        f"frames={payload['feature_bag']['feature_frames']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
