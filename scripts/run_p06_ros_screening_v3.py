#!/usr/bin/env python3
"""Run P06 ROS screening with the versioned AFRL calibration correction."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import rosbag

try:
    from scripts import run_p06_ros_screening as v2
except ModuleNotFoundError:
    import run_p06_ros_screening as v2


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
CORRECTION = BUNDLE / "p06/afrl_calibration_correction_v1.json"
RUNNER_VERSION = "isj-p06-ros-screening-v3-calibration-corrected"
EXPECTED_BOUNDARY = "KLT_AND_IMAGE_QUALITY_ONLY_NO_LEARNED_OR_VINS_OUTCOME"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, object]:
    return {
        "path": path.resolve().relative_to(ROOT).as_posix(),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def load_correction() -> dict[str, Any]:
    correction = json.loads(CORRECTION.read_text(encoding="utf-8"))
    if correction.get("schema_version") != "isj-p06-afrl-calibration-correction-v1":
        raise ValueError("unexpected AFRL calibration correction schema")
    if correction.get("outcome_boundary") != EXPECTED_BOUNDARY:
        raise ValueError("AFRL calibration correction outcome boundary mismatch")
    if correction.get("learned_outcome_read") is not False:
        raise ValueError("AFRL calibration correction learned outcome flag mismatch")
    if correction.get("trajectory_outcome_read") is not False:
        raise ValueError("AFRL calibration correction trajectory outcome flag mismatch")
    for key in ("source_manifest", "source_builder"):
        record = correction.get(key)
        if not isinstance(record, dict):
            raise ValueError(f"missing correction {key} record")
        target = ROOT / str(record.get("path", ""))
        if not target.is_file() or sha256_file(target) != record.get("sha256"):
            raise ValueError(f"correction {key} hash mismatch")
    for sequence, entry in correction.get("sequences", {}).items():
        calibration = ROOT / str(entry.get("selected_calibration_path", ""))
        if not calibration.is_file():
            raise FileNotFoundError(f"missing corrected calibration for {sequence}")
        if sha256_file(calibration) != entry.get("selected_calibration_sha256"):
            raise ValueError(f"corrected calibration hash mismatch: {sequence}")
    return correction


def apply_correction_to_rows(
    rows: list[dict[str, str]], correction: dict[str, Any]
) -> list[dict[str, str]]:
    updated: list[dict[str, str]] = []
    entries = correction["sequences"]
    for source in rows:
        row = dict(source)
        sequence = row.get("sequence", "")
        if row.get("dataset_family") == "afrl" and sequence in entries:
            entry = entries[sequence]
            paths = [value for value in row.get("calibration_paths", "").split(";") if value]
            stale = str(entry["supersedes_calibration_path"])
            if not paths or paths[0] != stale:
                raise ValueError(f"unexpected frozen calibration path: {sequence}")
            paths[0] = str(entry["selected_calibration_path"])
            row["calibration_paths"] = ";".join(paths)
        updated.append(row)
    return updated


def camera_info_contract(
    raw_bag: Path, entry: dict[str, Any]
) -> dict[str, object]:
    expected = entry["camera_info"]
    actual_message = None
    with rosbag.Bag(str(raw_bag)) as bag:
        for _, message, _ in bag.read_messages(topics=[str(expected["topic"])]):
            actual_message = message
            break
    if actual_message is None:
        raise ValueError(f"camera info topic missing: {expected['topic']}")
    actual = {
        "K": [float(value) for value in actual_message.K],
        "D": [float(value) for value in actual_message.D],
        "width": int(actual_message.width),
        "height": int(actual_message.height),
        "topic": str(expected["topic"]),
    }
    for field in ("K", "D"):
        expected_values = [float(value) for value in expected[field]]
        actual_values = actual[field]
        if len(expected_values) != len(actual_values) or any(
            abs(left - right) > 1e-8
            for left, right in zip(expected_values, actual_values)
        ):
            raise ValueError(f"camera info {field} mismatch")
    for field in ("width", "height"):
        if int(actual[field]) != int(expected[field]):
            raise ValueError(f"camera info {field} mismatch")
    canonical = json.dumps(actual, sort_keys=True, separators=(",", ":"))
    return {
        **actual,
        "canonical_sha256": hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        "matches_correction": True,
    }


def postprocess_audit(
    result: dict[str, object],
    correction: dict[str, Any],
    camera_info: dict[str, object],
) -> dict[str, object]:
    sequence = str(result["sequence"])
    entry = correction["sequences"][sequence]
    contract = {
        "schema_version": "isj-p06-afrl-calibration-contract-v1",
        "status": "PASS",
        "correction_manifest": file_record(CORRECTION),
        "source_manifest": correction["source_manifest"],
        "supersedes_calibration_path": entry["supersedes_calibration_path"],
        "selected_calibration_path": entry["selected_calibration_path"],
        "selected_calibration_sha256": entry["selected_calibration_sha256"],
        "camera_info": camera_info,
        "outcome_boundary": EXPECTED_BOUNDARY,
        "learned_outcome_read": False,
        "trajectory_outcome_read": False,
    }
    enriched = dict(result)
    enriched["runner_version"] = RUNNER_VERSION
    enriched["calibration_contract"] = contract
    code = [dict(record) for record in enriched.get("code", [])]
    wrapper_record = file_record(Path(__file__))
    if not any(record.get("path") == wrapper_record["path"] for record in code):
        code.append(wrapper_record)
    enriched["code"] = code
    return enriched


def refresh_pointer(result: dict[str, object], audit_path: Path) -> None:
    attempt_id = str(result.get("attempt_id", ""))
    if result.get("status") != "PASS" or not attempt_id.startswith("attempt"):
        return
    canonical = ROOT / str(result["canonical_run_dir"])
    pointer_path = canonical / "current_attempt.json"
    if not pointer_path.is_file():
        raise FileNotFoundError("v2 runner did not create the AFRL attempt pointer")
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["screening_run_sha256"] = sha256_file(audit_path)
    pointer["runner_version"] = RUNNER_VERSION
    pointer["calibration_correction_manifest_sha256"] = sha256_file(CORRECTION)
    pointer["updated_at_utc"] = v2.now_utc()
    temporary = pointer_path.with_name(f".{pointer_path.name}.{attempt_id}.v3.tmp")
    temporary.write_text(json.dumps(pointer, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, pointer_path)


def run_sequence(
    sequence: str,
    output_root: Path,
    work_root: Path,
    *,
    force: bool,
    keep_work_bags: bool,
    dry_run: bool,
    attempt_id: str = "",
) -> dict[str, object]:
    correction = load_correction()
    if sequence not in correction["sequences"]:
        raise ValueError(f"missing calibration correction entry: {sequence}")
    source_row = v2.unique_row(v2.read_csv(v2.ELIGIBILITY), sequence)
    raw_bag = ROOT / source_row["raw_input_path"]
    info = camera_info_contract(raw_bag, correction["sequences"][sequence])
    original_read_csv = v2.read_csv

    def corrected_read_csv(path: Path) -> list[dict[str, str]]:
        rows = original_read_csv(path)
        if Path(path).resolve() == v2.ELIGIBILITY.resolve():
            return apply_correction_to_rows(rows, correction)
        return rows

    v2.read_csv = corrected_read_csv
    try:
        result = v2.run_sequence(
            sequence,
            output_root,
            work_root,
            force=force,
            keep_work_bags=keep_work_bags,
            dry_run=dry_run,
            attempt_id=attempt_id,
        )
    finally:
        v2.read_csv = original_read_csv
    enriched = postprocess_audit(result, correction, info)
    if dry_run:
        return enriched
    audit_path = ROOT / str(enriched["run_dir"]) / "screening_run.json"
    audit_path.write_text(json.dumps(enriched, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    refresh_pointer(enriched, audit_path)
    return enriched


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "sequence", choices=("cave_gennie", "bus_outside", "cemetery")
    )
    parser.add_argument("--output-root", default=str(v2.DEFAULT_OUTPUT))
    parser.add_argument("--work-root", default=str(v2.DEFAULT_WORK))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--keep-work-bags", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--attempt-id", default="")
    args = parser.parse_args()
    result = run_sequence(
        args.sequence,
        Path(args.output_root),
        Path(args.work_root),
        force=bool(args.force),
        keep_work_bags=bool(args.keep_work_bags),
        dry_run=bool(args.dry_run),
        attempt_id=str(args.attempt_id),
    )
    print(
        f"P06_ROS_V3_{result['status']} sequence={args.sequence} "
        f"rows={result.get('row_count', 0)} output={result['run_dir']}"
    )
    return 0 if result["status"] in {"PASS", "DRY_RUN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
