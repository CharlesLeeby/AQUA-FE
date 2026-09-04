#!/usr/bin/env python3
"""Run one or more full AQUALOC P06 KLT/image-only screening sequences."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
ELIGIBILITY = BUNDLE / "data_eligibility_manifest.csv"
CAPACITY = BUNDLE / "p02/candidate_capacity_audit.csv"
CHECKSUMS = BUNDLE / "p02/input_reference_checksums.csv"
DEFAULT_OUTPUT = BUNDLE / "p06/screening_runs"
CONFIG = ROOT / "uw_frontend/configs/klt_frontend.yaml"
REQUIRED_METRICS = (
    "grid_coverage",
    "dropout_ratio",
    "flat_region_ratio",
    "degradation_score",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sequence", nargs="+", help="A01..A10 or H01..H07")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    eligibility = read_csv(ELIGIBILITY)
    capacity = read_csv(CAPACITY)
    checksums = read_csv(CHECKSUMS)
    status = 0
    for sequence in args.sequence:
        result = run_sequence(
            sequence.upper(),
            Path(args.output_root),
            eligibility,
            capacity,
            checksums,
            force=bool(args.force),
            dry_run=bool(args.dry_run),
        )
        print(
            f"P06_AQUALOC_{result['status']} sequence={sequence.upper()} "
            f"rows={result.get('row_count', 0)} output={result['run_dir']}"
        )
        if result["status"] not in {"PASS", "DRY_RUN"}:
            status = 1
    return status


def run_sequence(
    sequence: str,
    output_root: Path,
    eligibility_rows: list[dict[str, str]],
    capacity_rows: list[dict[str, str]],
    checksum_rows: list[dict[str, str]],
    *,
    force: bool,
    dry_run: bool,
) -> dict[str, object]:
    manifest = unique_row(eligibility_rows, sequence)
    family = manifest["dataset_family"]
    if family not in {"aqualoc_archaeology", "aqualoc_harbor"}:
        raise ValueError(f"{sequence} is not an AQUALOC sequence")
    capacity = unique_row(capacity_rows, sequence)
    if capacity["low_normal_sequence_capacity_status"] != "CAPACITY_CANDIDATE":
        raise ValueError(f"{sequence} has no P06 candidate capacity")

    raw_path = ROOT / manifest["raw_input_path"]
    if not raw_path.is_file():
        raise FileNotFoundError(raw_path)
    number = int(sequence[1:])
    prefix = (
        f"images_sequence_{number}"
        if family == "aqualoc_archaeology"
        else f"harbor_images_sequence_{number:02d}"
    )
    run_dir = output_root / family / sequence
    metrics_path = run_dir / "metrics.csv"
    audit_path = run_dir / "screening_run.json"
    command_path = run_dir / "command.txt"
    command = [
        "python3",
        "-m",
        "uw_frontend.evaluation.run_frontend_eval",
        "--input",
        str(raw_path),
        "--image-prefix",
        prefix,
        "--output-csv",
        str(metrics_path),
        "--method",
        "klt",
        "--config",
        str(CONFIG),
        "--preprocess",
        "adaptive_clahe",
        "--every-n",
        "1",
        "--start-index",
        "0",
    ]
    base = {
        "schema_version": "isj-p06-screening-run-v1",
        "protocol_version": "isj-window-selection-v2",
        "dataset_family": family,
        "sequence": sequence,
        "split_role": manifest["role"],
        "run_dir": relative(run_dir),
        "metrics_path": relative(metrics_path),
        "command": shlex.join(command),
        "raw_input": {
            "path": manifest["raw_input_path"],
            "registered_sha256": registered_digest(
                checksum_rows,
                family,
                sequence,
                manifest["raw_input_path"],
            ),
            "size_bytes": raw_path.stat().st_size,
        },
        "code": [
            file_record(CONFIG),
            file_record(ROOT / "uw_frontend/evaluation/run_frontend_eval.py"),
            file_record(ROOT / "uw_frontend/tracking/klt_tracker.py"),
            file_record(ROOT / "uw_frontend/quality/image_quality.py"),
            file_record(ROOT / "scripts/run_p06_aqualoc_screening.py"),
            file_record(ROOT / "scripts/p06_window_selection_v2.py"),
        ],
        "outcome_boundary": "KLT_AND_IMAGE_QUALITY_ONLY_NO_LEARNED_OR_VINS_OUTCOME",
    }
    if dry_run:
        return {**base, "status": "DRY_RUN", "row_count": 0}

    run_dir.mkdir(parents=True, exist_ok=True)
    command_path.write_text(shlex.join(command) + "\n", encoding="utf-8")
    if force:
        metrics_path.unlink(missing_ok=True)
        audit_path.unlink(missing_ok=True)
    if not metrics_path.is_file() or metrics_path.stat().st_size == 0:
        completed = subprocess.run(command, cwd=ROOT, check=False)
        if completed.returncode != 0:
            result = {
                **base,
                "status": "FAILED",
                "returncode": completed.returncode,
                "generated_at_utc": now_utc(),
            }
            audit_path.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            return result

    audit = audit_metrics(metrics_path)
    result = {
        **base,
        **audit,
        "status": "PASS" if audit["contract_pass"] else "FAIL",
        "metrics_sha256": sha256_file(metrics_path),
        "generated_at_utc": now_utc(),
    }
    audit_path.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def audit_metrics(path: Path) -> dict[str, object]:
    rows = read_csv(path)
    if not rows:
        return {"contract_pass": False, "row_count": 0, "issues": ["empty_metrics"]}
    fields = set(rows[0])
    missing = sorted(set(REQUIRED_METRICS) - fields)
    issues = [f"missing_column:{field}" for field in missing]
    learned_nonzero = 0
    non_klt_mode = 0
    invalid_required = 0
    for row in rows:
        mode = str(row.get("tracker_mode", "klt")).strip().lower()
        if mode not in {"", "klt", "n/a"}:
            non_klt_mode += 1
        for field in REQUIRED_METRICS:
            try:
                value = float(row[field])
            except (KeyError, TypeError, ValueError):
                invalid_required += 1
                continue
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                invalid_required += 1
        for field, value in row.items():
            name = field.lower()
            if not name.endswith("_tracks"):
                continue
            if not any(token in name for token in ("xfeat", "superpoint", "loftr", "learned")):
                continue
            try:
                learned_nonzero += int(float(value or 0) != 0.0)
            except ValueError:
                learned_nonzero += 1
    if non_klt_mode:
        issues.append(f"non_klt_rows:{non_klt_mode}")
    if learned_nonzero:
        issues.append(f"learned_nonzero_cells:{learned_nonzero}")
    if invalid_required:
        issues.append(f"invalid_required_values:{invalid_required}")
    return {
        "contract_pass": not issues,
        "row_count": len(rows),
        "first_frame_index": rows[0]["frame_index"],
        "last_frame_index": rows[-1]["frame_index"],
        "issues": issues,
    }


def unique_row(rows: list[dict[str, str]], sequence: str) -> dict[str, str]:
    matches = [row for row in rows if row.get("sequence") == sequence]
    if len(matches) != 1:
        raise ValueError(f"expected one manifest row for {sequence}, found {len(matches)}")
    return matches[0]


def registered_digest(
    rows: list[dict[str, str]],
    family: str,
    sequence: str,
    path: str,
) -> str:
    matches = [
        row
        for row in rows
        if row.get("dataset_family") == family
        and row.get("sequence") == sequence
        and row.get("path") == path
        and row.get("artifact_role") == "raw_input"
    ]
    if len(matches) != 1 or matches[0].get("status") != "PASS":
        raise ValueError(f"missing registered input digest for {family}/{sequence}")
    return matches[0]["digest"]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def file_record(path: Path) -> dict[str, object]:
    return {
        "path": relative(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
