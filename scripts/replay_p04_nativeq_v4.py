#!/usr/bin/env python3
"""Replay a normalized P04 v4 stream into a deterministic JSON bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.p04_nativeq_arm_replayer_v4 import replay_master_events



def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def replay_file(input_path: Path, output_path: Path) -> dict[str, object]:
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite replay bundle: {output_path}")
    records = []
    with input_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid normalized JSONL at line {line_number}") from exc
    bundle = replay_master_events(records)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(bundle.to_json() + "\n", encoding="utf-8")
    return {
        "schema_version": "isj-p04-replay-artifact-v1",
        "input_path": display_path(input_path),
        "input_sha256": sha256(input_path),
        "output_path": display_path(output_path),
        "output_sha256": sha256(output_path),
        "event_count": len(records),
        "contract_hash": bundle.contract_hash,
        "normalized_stream_hash": bundle.normalized_stream_hash,
        "bundle_hash": bundle.bundle_hash,
        "source_attribution_status": bundle.source_attribution_status,
        "arm_summaries": [summary.as_dict() for summary in bundle.summaries],
        "outcome_boundary": "normalized_frontend_records_only_no_VINS_APE_RPE",
        "learned_outcome_read": False,
        "trajectory_outcome_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    summary = replay_file(args.input, args.output)
    if args.summary:
        args.summary.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
