#!/usr/bin/env python3
"""Fail-closed, outcome-blind validator for the P06 screening closeout.

The frozen screening runners deliberately record a broad metrics schema because
the same exporter is used elsewhere.  This validator is a separate governance
layer: it checks the complete sequence denominator, registered input identity,
metric integrity, and that every learned/trajectory field is inactive before a
P06 manifest can be treated as a basis for P07.

It never starts ROS/VINS, reads trajectory output, or changes an existing
artifact unless ``--output`` is explicitly supplied for the JSON report.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
CAPACITY = BUNDLE / "p02/candidate_capacity_audit.csv"
ELIGIBILITY = BUNDLE / "data_eligibility_manifest.csv"
CHECKSUMS = BUNDLE / "p02/input_reference_checksums.csv"
SCREENING = BUNDLE / "p06/screening_runs"
DATASET_MANIFEST = BUNDLE / "dataset_manifest.csv"
WINDOW_AUDIT = BUNDLE / "window_selection_audit.csv"
PROGRESS = BUNDLE / "p06/screening_progress.json"
CODE_HASHES = BUNDLE / "p06/b1_screening_code_hashes_v2.sha256"
RUNNER_HASHES = BUNDLE / "p06/screening_runner_hashes_v2.sha256"

EXPECTED_BOUNDARY = "KLT_AND_IMAGE_QUALITY_ONLY_NO_LEARNED_OR_VINS_OUTCOME"
REQUIRED_METRICS = (
    "grid_coverage",
    "dropout_ratio",
    "flat_region_ratio",
    "degradation_score",
)
LEARNED_TOKENS = (
    "learned",
    "loftr",
    "xfeat",
    "superpoint",
    "lightglue",
    "semidense",
    "sidecar",
)
OUTCOME_TOKENS = (
    "ape",
    "rpe",
    "trajectory",
    "solver_failure",
    "solver_risk",
    "vins_estimator",
    "pose_rmse",
)
INACTIVE_TEXT = {
    "",
    "0",
    "0.0",
    "0.00",
    "false",
    "f",
    "n/a",
    "na",
    "nan",
    "none",
    "null",
    "disabled",
    "inactive",
    "not_run",
    "not_applicable",
    "policy_inactive",
}
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inactive_value(value: Any) -> bool:
    """Return whether a learned/sidecar value expresses an inactive path."""

    text = str(value).strip().lower()
    if text in INACTIVE_TEXT:
        return True
    try:
        number = float(text)
    except (TypeError, ValueError):
        return False
    return math.isnan(number) or (math.isfinite(number) and abs(number) <= 1e-12)


def histogram_is_inactive(value: Any) -> bool:
    """Audit source histograms without rejecting the active classical KLT/GFTT."""

    text = str(value).strip().lower()
    if text in INACTIVE_TEXT:
        return True
    for item in text.split(";"):
        if not item:
            continue
        name, separator, count = item.partition(":")
        if not any(token in name for token in LEARNED_TOKENS):
            continue
        if not separator:
            return False
        if not inactive_value(count):
            return False
    return True


def metric_rows_contract(rows: list[dict[str, str]]) -> list[str]:
    """Validate one screening CSV without interpreting any scientific outcome."""

    issues: list[str] = []
    if not rows:
        return ["empty_metrics"]
    fields = set(rows[0])
    for field in REQUIRED_METRICS:
        if field not in fields:
            issues.append(f"missing_column:{field}")

    frame_values: list[int] = []
    timestamps: list[float] = []
    names: list[str] = []
    for row_number, row in enumerate(rows, 2):
        try:
            frame = int(float(row.get("frame_index", "")))
        except (TypeError, ValueError):
            issues.append(f"invalid_frame_index:row{row_number}")
        else:
            frame_values.append(frame)
        if row.get("timestamp", "") not in {"", "n/a", "nan"}:
            try:
                timestamp = float(row["timestamp"])
            except (TypeError, ValueError):
                issues.append(f"invalid_timestamp:row{row_number}")
            else:
                if not math.isfinite(timestamp):
                    issues.append(f"nonfinite_timestamp:row{row_number}")
                timestamps.append(timestamp)
        if row.get("frame_name", ""):
            names.append(row["frame_name"])
        for field in REQUIRED_METRICS:
            if field not in row:
                continue
            try:
                value = float(row[field])
            except (TypeError, ValueError):
                issues.append(f"invalid_metric:{field}:row{row_number}")
                continue
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                issues.append(f"metric_out_of_range:{field}:row{row_number}")

        for field, value in row.items():
            lower = field.lower()
            if any(token in lower for token in OUTCOME_TOKENS):
                issues.append(f"outcome_column:{field}")
            if any(token in lower for token in LEARNED_TOKENS):
                if "histogram" in lower:
                    if not histogram_is_inactive(value):
                        issues.append(f"learned_nonzero:{field}:row{row_number}")
                elif not inactive_value(value):
                    issues.append(f"learned_nonzero:{field}:row{row_number}")
        for field in ("tracker_source_histogram", "export_source_histogram"):
            if field in row and not histogram_is_inactive(row[field]):
                issues.append(f"learned_histogram_nonzero:{field}:row{row_number}")
        mode = str(row.get("tracker_mode", "klt")).strip().lower()
        if mode not in {"", "klt", "n/a"}:
            issues.append(f"non_klt_tracker:{mode}:row{row_number}")

    if len(frame_values) == len(rows):
        if len(set(frame_values)) != len(frame_values):
            issues.append("duplicate_frame_index")
        if frame_values != sorted(frame_values):
            issues.append("non_monotonic_frame_index")
        if frame_values and frame_values != list(range(frame_values[0], frame_values[-1] + 1)):
            issues.append("frame_index_gap")
    if timestamps and timestamps != sorted(timestamps):
        issues.append("non_monotonic_timestamp")
    if names and len(set(names)) != len(names):
        issues.append("duplicate_frame_name")
    return sorted(set(issues))


def parse_hash_manifest(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, relative = parts
        if HEX64.fullmatch(digest):
            result[relative.strip().lstrip("* ")] = digest
    return result


def expected_sequences() -> list[dict[str, str]]:
    rows = read_csv(CAPACITY)
    return [
        row
        for row in rows
        if row.get("low_normal_sequence_capacity_status") == "CAPACITY_CANDIDATE"
    ]


def index_rows(rows: Iterable[dict[str, str]], key: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        value = row.get(key, "")
        if value:
            result[value] = row
    return result


def resolve_screening_dir(family: str, sequence: str) -> tuple[Path, list[str]]:
    """Resolve an AFRL replacement only through its frozen current pointer."""

    canonical = SCREENING / family / sequence
    if family != "afrl":
        return canonical, []
    pointer_path = canonical / "current_attempt.json"
    attempt_dirs = (
        [
            child
            for child in canonical.iterdir()
            if child.is_dir() and re.fullmatch(r"attempt[0-9]{2}", child.name)
        ]
        if canonical.is_dir()
        else []
    )
    if not pointer_path.is_file():
        if attempt_dirs:
            return canonical, ["current_attempt_pointer_missing"]
        return canonical, []
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return canonical, ["invalid_current_attempt_pointer"]
    issues: list[str] = []
    if pointer.get("schema_version") != "isj-p06-current-attempt-v1":
        issues.append("current_attempt_schema_mismatch")
    if pointer.get("dataset_family") != family or pointer.get("sequence") != sequence:
        issues.append("current_attempt_identity_mismatch")
    if pointer.get("status") != "PASS":
        issues.append("current_attempt_not_pass")
    attempt_id = pointer.get("attempt_id")
    if not isinstance(attempt_id, str) or not re.fullmatch(r"attempt[0-9]{2}", attempt_id):
        issues.append("current_attempt_id_invalid")
    value = pointer.get("run_dir")
    if not isinstance(value, str) or not value:
        return canonical, issues + ["current_attempt_run_dir_missing"]
    target = (ROOT / value).resolve()
    canonical_resolved = canonical.resolve()
    if target != canonical_resolved and canonical_resolved not in target.parents:
        issues.append("current_attempt_outside_canonical_dir")
        return canonical, issues
    if not (target / "screening_run.json").is_file():
        issues.append("current_attempt_screening_run_missing")
    if not (target / "metrics.csv").is_file():
        issues.append("current_attempt_metrics_missing")
    if isinstance(attempt_id, str) and target.name != attempt_id:
        issues.append("current_attempt_directory_mismatch")
    metrics = target / "metrics.csv"
    audit = target / "screening_run.json"
    process_log = target / "process.log"
    if pointer.get("metrics_path") != relative(metrics):
        issues.append("current_attempt_metrics_path_mismatch")
    if pointer.get("screening_run_path") != relative(audit):
        issues.append("current_attempt_audit_path_mismatch")
    if pointer.get("process_log_path") != relative(process_log):
        issues.append("current_attempt_process_log_path_mismatch")
    if metrics.is_file() and pointer.get("metrics_sha256") != sha256_file(metrics):
        issues.append("current_attempt_metrics_hash_mismatch")
    if audit.is_file() and pointer.get("screening_run_sha256") != sha256_file(audit):
        issues.append("current_attempt_audit_hash_mismatch")
    if not process_log.is_file():
        issues.append("current_attempt_process_log_missing")
    elif pointer.get("process_log_sha256") != sha256_file(process_log):
        issues.append("current_attempt_process_log_hash_mismatch")
    return target, issues


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def validate_run(
    spec: dict[str, str],
    eligibility: dict[str, dict[str, str]],
    checksums: dict[str, dict[str, str]],
    code_hashes: dict[str, str],
    runner_hashes: dict[str, str],
) -> list[str]:
    family = spec["dataset_family"]
    sequence = spec["sequence"]
    run_dir, pointer_issues = resolve_screening_dir(family, sequence)
    audit_path = run_dir / "screening_run.json"
    metrics_path = run_dir / "metrics.csv"
    issues: list[str] = list(pointer_issues)
    if not audit_path.is_file() or not metrics_path.is_file():
        return sorted(set(issues + ["missing_run_artifact"]))
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["invalid_screening_run_json"]
    expected = eligibility.get(sequence)
    if expected is None:
        issues.append("missing_eligibility_row")
    for key, value in (
        ("schema_version", "isj-p06-screening-run-v1"),
        ("protocol_version", "isj-window-selection-v2"),
        ("status", "PASS"),
        ("outcome_boundary", EXPECTED_BOUNDARY),
    ):
        if audit.get(key) != value:
            issues.append(f"audit_{key}_mismatch")
    if audit.get("contract_pass") is not True:
        issues.append("contract_pass_not_true")
    if audit.get("issues") != []:
        issues.append("runner_issues_not_empty")
    try:
        rows = read_csv(metrics_path)
    except (OSError, csv.Error):
        return issues + ["invalid_metrics_csv"]
    issues.extend(metric_rows_contract(rows))
    if audit.get("row_count") != len(rows):
        issues.append("row_count_mismatch")
    recorded_hash = audit.get("metrics_sha256")
    if not isinstance(recorded_hash, str) or sha256_file(metrics_path) != recorded_hash:
        issues.append("metrics_sha256_mismatch")
    if audit.get("first_frame_index") != (rows[0].get("frame_index") if rows else None):
        issues.append("first_frame_index_mismatch")
    if audit.get("last_frame_index") != (rows[-1].get("frame_index") if rows else None):
        issues.append("last_frame_index_mismatch")
    if expected is not None:
        if audit.get("dataset_family") != family or audit.get("sequence") != sequence:
            issues.append("audit_sequence_identity_mismatch")
        raw = audit.get("raw_input") or {}
        raw_path = expected.get("raw_input_path", "")
        if raw.get("path") != raw_path:
            issues.append("raw_input_path_mismatch")
        registered = checksums.get(raw_path)
        if registered is None or registered.get("artifact_role") != "raw_input":
            issues.append("raw_input_checksum_not_registered")
        elif raw.get("registered_sha256") != registered.get("digest"):
            issues.append("raw_input_registered_digest_mismatch")
        try:
            if int(raw.get("size_bytes", -1)) != int(expected.get("raw_size_bytes", -2)):
                issues.append("raw_input_size_mismatch")
        except (TypeError, ValueError):
            issues.append("raw_input_size_invalid")
        if not (ROOT / raw_path).is_file():
            issues.append("raw_input_missing")
    code_records = audit.get("code", [])
    if not isinstance(code_records, list) or not code_records:
        issues.append("code_records_missing")
        code_records = []
    required_code_paths = {
        "scripts/run_p06_aqualoc_screening.py"
        if family.startswith("aqualoc_")
        else "scripts/run_p06_ros_screening.py"
    }
    if family == "afrl":
        required_code_paths.add("scripts/run_p06_afrl_direct_screening.py")
    recorded_code_paths: set[str] = set()
    for record in code_records:
        if not isinstance(record, dict):
            issues.append("invalid_code_record")
            continue
        path = str(record.get("path", ""))
        path_parts = Path(path).parts
        if not path or Path(path).is_absolute() or ".." in path_parts:
            issues.append(f"code_path_invalid:{path}")
            continue
        if path in recorded_code_paths:
            issues.append(f"code_path_duplicate:{path}")
            continue
        recorded_code_paths.add(path)
        target = ROOT / path
        if path not in code_hashes and path not in runner_hashes:
            issues.append(f"code_not_registered:{path}")
            continue
        if not target.is_file():
            issues.append(f"code_missing:{path}")
            continue
        digest = sha256_file(target)
        if digest != record.get("sha256"):
            issues.append(f"code_hash_mismatch:{path}")
        frozen = code_hashes.get(path) or runner_hashes.get(path)
        if frozen is not None and digest != frozen:
            issues.append(f"code_frozen_hash_mismatch:{path}")
    for path in sorted(required_code_paths - recorded_code_paths):
        issues.append(f"required_code_not_recorded:{path}")
    return sorted(set(issues))


def validate_manifest() -> list[str]:
    issues: list[str] = []
    if not DATASET_MANIFEST.is_file() or not WINDOW_AUDIT.is_file():
        return ["missing_final_manifest"]
    try:
        selected = read_csv(DATASET_MANIFEST)
        audit = read_csv(WINDOW_AUDIT)
    except (OSError, csv.Error):
        return ["invalid_final_manifest_csv"]
    if len(selected) != 20:
        issues.append(f"selected_window_count:{len(selected)}")
    ids = [row.get("window_id", "") for row in selected]
    if len(set(ids)) != len(ids) or any(not value for value in ids):
        issues.append("selected_window_id_not_unique")
    strata = {str(row.get("texture_stratum", "")) for row in selected}
    if sum(row.get("texture_stratum") == "low" for row in selected) != 10:
        issues.append("selected_low_count")
    if sum(row.get("texture_stratum") == "normal" for row in selected) != 10:
        issues.append("selected_normal_count")
    by_id = {row.get("window_id"): row for row in audit}
    if len(by_id) != len(audit):
        issues.append("window_audit_id_not_unique")
    for row in selected:
        window_id = row.get("window_id", "")
        source = by_id.get(window_id)
        if source is None:
            issues.append(f"selected_not_in_audit:{window_id}")
            continue
        if source.get("selected_final", "").lower() != "true":
            issues.append(f"audit_selection_flag_missing:{window_id}")
        if source.get("history_excluded", "").lower() != "false":
            issues.append(f"history_excluded_selected:{window_id}")
        try:
            if int(float(row.get("input_frame_count", "0"))) < 200:
                issues.append(f"short_selected_window:{window_id}")
        except (TypeError, ValueError):
            issues.append(f"invalid_selected_frame_count:{window_id}")
    for stratum in ("low", "normal"):
        rows = [row for row in selected if row.get("texture_stratum") == stratum]
        sequences = {row.get("sequence") for row in rows}
        domains = {row.get("data_domain") for row in rows}
        if len(sequences) < 6:
            issues.append(f"{stratum}_sequence_diversity")
        if len(domains) < 2:
            issues.append(f"{stratum}_domain_diversity")
        counts: dict[str, int] = {}
        for row in rows:
            counts[row.get("sequence", "")] = counts.get(row.get("sequence", ""), 0) + 1
        if max(counts.values(), default=0) > 2:
            issues.append(f"{stratum}_sequence_cap")
    all_counts: dict[str, int] = {}
    for row in selected:
        all_counts[row.get("sequence", "")] = all_counts.get(row.get("sequence", ""), 0) + 1
    if max(all_counts.values(), default=0) > 4:
        issues.append("overall_sequence_cap")
    if len({row.get("data_domain") for row in selected}) < 3:
        issues.append("overall_domain_diversity")
    return sorted(set(issues))


def build_report(require_final: bool) -> dict[str, Any]:
    specs = expected_sequences()
    global_issues: list[str] = []
    if len(specs) != 18:
        global_issues.append(f"expected_capacity_sequence_count:18:actual:{len(specs)}")
    eligibility_rows = index_rows(read_csv(ELIGIBILITY), "sequence")
    checksums = index_rows(read_csv(CHECKSUMS), "path")
    code_hashes = parse_hash_manifest(CODE_HASHES)
    runner_hashes = parse_hash_manifest(RUNNER_HASHES)
    sequence_results: dict[str, list[str]] = {}
    for spec in specs:
        sequence_results[spec["sequence"]] = validate_run(
            spec, eligibility_rows, checksums, code_hashes, runner_hashes
        )
    missing = [sequence for sequence, issues in sequence_results.items() if issues]
    final_issues = validate_manifest() if require_final else []
    if global_issues or missing:
        status = "IN_PROGRESS"
    elif final_issues:
        status = "REVISE" if require_final else "IN_PROGRESS"
    else:
        status = "PASS"
    return {
        "schema_version": "isj-p06-screening-closeout-v1",
        "protocol_version": "isj-window-selection-v2",
        "status": status,
        "required_sequence_count": len(specs),
        "completed_sequence_count": len(specs) - len(missing),
        "global_issues": global_issues,
        "sequence_issues": sequence_results,
        "final_manifest_issues": final_issues,
        "outcome_boundary": EXPECTED_BOUNDARY,
        "learned_outcome_read": False,
        "trajectory_outcome_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-final",
        action="store_true",
        help="require and validate the 20-window final manifest",
    )
    parser.add_argument("--output", help="write the JSON report to this path")
    args = parser.parse_args()
    report = build_report(bool(args.require_final))
    rendered = json.dumps(report, sort_keys=True, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    return 0 if report["status"] == "PASS" else (2 if report["status"] == "IN_PROGRESS" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
