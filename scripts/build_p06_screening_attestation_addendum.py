#!/usr/bin/env python3
"""Attest the five AQUALOC runs that were already active under runner v1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
SCREENING = BUNDLE / "p06/screening_runs/aqualoc_archaeology"
RUNNER_V1 = BUNDLE / "p06/screening_runner_hashes_v1.sha256"
RUNNER_V2 = BUNDLE / "p06/screening_runner_hashes_v2.sha256"
OUTPUT = BUNDLE / "p06/screening_attestations_v2_addendum.jsonl"
SEQUENCES = ("A01", "A04", "A07", "A08", "A10")
RUNNER_PATH = "scripts/run_p06_aqualoc_screening.py"
BUILDER_PATH = "scripts/build_p06_screening_attestation_addendum.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hashes(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split(None, 1)
        result[relative.strip()] = digest
    return result


def file_record(path: Path) -> dict[str, object]:
    return {
        "path": path.resolve().relative_to(ROOT).as_posix(),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def main() -> int:
    if OUTPUT.exists():
        raise FileExistsError(f"attestation addendum already exists: {OUTPUT}")
    v1 = hashes(RUNNER_V1)
    v2 = hashes(RUNNER_V2)
    rows: list[dict[str, object]] = []
    for sequence in SEQUENCES:
        run_dir = SCREENING / sequence
        metrics = run_dir / "metrics.csv"
        audit_path = run_dir / "screening_run.json"
        if not metrics.is_file() or not audit_path.is_file():
            raise FileNotFoundError(f"run has not completed: {sequence}")
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        if audit.get("status") != "PASS" or audit.get("contract_pass") is not True:
            raise ValueError(f"run audit is not PASS: {sequence}")
        rows.append(
            {
                "schema_version": "isj-p06-screening-attestation-v2",
                "dataset_family": "aqualoc_archaeology",
                "sequence": sequence,
                "provenance_mode": "EXECUTION_AUDIT_V1",
                "outcome_boundary": "KLT_AND_IMAGE_QUALITY_ONLY_NO_LEARNED_OR_VINS_OUTCOME",
                "metrics": file_record(metrics),
                "screening_run_audit": file_record(audit_path),
                "execution_runner": {
                    "path": RUNNER_PATH,
                    "sha256": v1[RUNNER_PATH],
                    "source_manifest": RUNNER_V1.relative_to(ROOT).as_posix(),
                },
                "attestation_runner": {
                    "path": RUNNER_PATH,
                    "sha256": v2[RUNNER_PATH],
                    "size_bytes": (ROOT / RUNNER_PATH).stat().st_size,
                },
                "attestation_builder": {
                    "path": BUILDER_PATH,
                    "sha256": sha256(ROOT / BUILDER_PATH),
                    "size_bytes": (ROOT / BUILDER_PATH).stat().st_size,
                },
                "audit_code_paths": [
                    record.get("path") for record in audit.get("code", [])
                ],
                "learned_outcome_read": False,
                "trajectory_outcome_read": False,
                "note": "Metrics and audit were emitted by the already-running v1 process; no post-hoc audit rewrite was performed.",
            }
        )
    OUTPUT.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    print(f"P06_SCREENING_ATTESTATION_ADDENDUM rows={len(rows)} output={OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
