#!/usr/bin/env python3
"""Record post-hoc provenance for P06 metrics audits regenerated after execution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
SCREENING = BUNDLE / "p06/screening_runs"
RUNNER_V1 = BUNDLE / "p06/screening_runner_hashes_v1.sha256"
OUTPUT = BUNDLE / "p06/screening_attestations_v2.jsonl"

COMPLETED = (
    ("aqualoc_archaeology", "A02"),
    ("aqualoc_archaeology", "A03"),
    ("aqualoc_archaeology", "A09"),
    ("aqualoc_harbor", "H01"),
    ("aqualoc_harbor", "H02"),
    ("aqualoc_harbor", "H03"),
    ("aqualoc_harbor", "H04"),
    ("aqualoc_harbor", "H05"),
    ("aqualoc_harbor", "H06"),
    ("ntnu", "fjord_6"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_hashes(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            parts = line.strip().split(None, 1)
            if len(parts) == 2:
                result[parts[1].lstrip("* ")] = parts[0]
    return result


def file_record(path: Path, digest: str | None = None) -> dict[str, object]:
    return {
        "path": path.resolve().relative_to(ROOT).as_posix(),
        "sha256": digest or sha256(path),
        "size_bytes": path.stat().st_size,
    }


def main() -> int:
    v1_hashes = parse_hashes(RUNNER_V1)
    rows: list[dict[str, object]] = []
    for family, sequence in COMPLETED:
        run_dir = SCREENING / family / sequence
        audit_path = run_dir / "screening_run.json"
        metrics_path = run_dir / "metrics.csv"
        if not audit_path.is_file() or not metrics_path.is_file():
            raise FileNotFoundError(f"missing completed run: {run_dir}")
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        runner_path = (
            "scripts/run_p06_aqualoc_screening.py"
            if family.startswith("aqualoc_")
            else "scripts/run_p06_ros_screening.py"
        )
        runner = ROOT / runner_path
        record: dict[str, object] = {
            "schema_version": "isj-p06-screening-attestation-v2",
            "dataset_family": family,
            "sequence": sequence,
            "provenance_mode": "POST_HOC_METRICS_REAUDIT",
            "outcome_boundary": "KLT_AND_IMAGE_QUALITY_ONLY_NO_LEARNED_OR_VINS_OUTCOME",
            "metrics": file_record(metrics_path),
            "screening_run_audit": file_record(audit_path),
            "execution_runner": {
                "path": runner_path,
                "sha256": v1_hashes[runner_path],
                "source_manifest": "papers/ieee_sensors_journal_experiments/p06/screening_runner_hashes_v1.sha256",
            },
            "attestation_runner": file_record(runner),
            "audit_code_paths": [item.get("path") for item in audit.get("code", [])],
            "learned_outcome_read": False,
            "trajectory_outcome_read": False,
            "note": "Metrics were executed before the current self-recording/attempt governance wrapper was re-audited.",
        }
        if sequence == "fjord_6":
            record["deleted_temporary_adapter_artifact"] = {
                "path": "/mnt/data/AQUA-FE_WS/p06_screening_work/ntnu/fjord_6/features.bag",
                "sha256": "1f28e886a10ea4d52763405115b217b9a3d8990f10b015b5342a9fc94ff9f2d1",
                "size_bytes": 338613007,
                "disposition": "deleted_after_recorded_hash",
            }
        rows.append(record)
    OUTPUT.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    print(f"P06_SCREENING_ATTESTATIONS_V2 rows={len(rows)} output={OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
