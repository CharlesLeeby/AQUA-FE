#!/usr/bin/env python3
"""P06 closeout v2 with provenance attestations and full manifest checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

try:
    from scripts import validate_p06_screening_closeout as base
except ModuleNotFoundError:
    import validate_p06_screening_closeout as base


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
P06 = BUNDLE / "p06"
ATTESTATION_FILES = (
    P06 / "screening_attestations_v2.jsonl",
    P06 / "screening_attestations_v2_addendum.jsonl",
)
CALIBRATION_CORRECTION = P06 / "afrl_calibration_correction_v1.json"
ATTESTATION_ADDENDUM_HASHES = P06 / "screening_attestation_addendum_hashes_v1.sha256"
CURRENT_MANIFESTS = (
    P06 / "b1_screening_code_hashes_v2.sha256",
    P06 / "screening_runner_hashes_v2.sha256",
    P06 / "screening_runner_v2_evidence_addendum.sha256",
    P06 / "final_artifact_validator_v1.sha256",
    P06 / "screening_attestation_hashes_v2.sha256",
    P06 / "reference_support_gate_v1.sha256",
    P06 / "reference_support_gate_v1_addendum.sha256",
    P06 / "screening_runner_hashes_v3.sha256",
    P06 / "afrl_calibration_correction_v1.sha256",
    P06 / "final_selection_governance_hashes_v1.sha256",
)
RUNNER_V1 = P06 / "screening_runner_hashes_v1.sha256"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def strict_hash_manifest(path: Path) -> tuple[dict[str, str], list[str]]:
    issues: list[str] = []
    entries: dict[str, str] = {}
    if not path.is_file():
        return entries, [f"hash_manifest_missing:{path.relative_to(ROOT)}"]
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2 or not HEX64.fullmatch(parts[0]):
            issues.append(f"hash_manifest_malformed:{path.name}:line{line_number}")
            continue
        digest, relative = parts
        if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            issues.append(f"hash_manifest_path_invalid:{path.name}:line{line_number}")
            continue
        if relative in entries:
            issues.append(f"hash_manifest_duplicate:{path.name}:{relative}")
            continue
        entries[relative] = digest
    return entries, issues


def validate_current_manifests() -> tuple[dict[str, str], list[str]]:
    union: dict[str, str] = {}
    issues: list[str] = []
    manifests = list(CURRENT_MANIFESTS)
    if ATTESTATION_ADDENDUM_HASHES.is_file():
        manifests.append(ATTESTATION_ADDENDUM_HASHES)
    for manifest in manifests:
        entries, parse_issues = strict_hash_manifest(manifest)
        issues.extend(parse_issues)
        for relative, digest in entries.items():
            current = union.get(relative)
            if current is not None and current != digest:
                issues.append(f"hash_manifest_conflict:{relative}")
                continue
            union[relative] = digest
            target = ROOT / relative
            if not target.is_file():
                issues.append(f"hash_target_missing:{relative}")
            elif sha256(target) != digest:
                issues.append(f"hash_target_mismatch:{relative}")
    return union, sorted(set(issues))


def resolve_registered_code_issues(
    issues: list[str], current_hashes: dict[str, str]
) -> list[str]:
    """Drop base-validator registration issues satisfied by a v2/v3 manifest."""

    prefix = "code_not_registered:"
    return [
        issue
        for issue in issues
        if not (
            issue.startswith(prefix)
            and issue[len(prefix) :] in current_hashes
        )
    ]


def read_attestations() -> tuple[dict[tuple[str, str], dict[str, Any]], list[str]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    issues: list[str] = []
    for path in ATTESTATION_FILES:
        if not path.is_file():
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                issues.append(f"attestation_json_invalid:{path.name}:line{line_number}")
                continue
            key = (str(row.get("dataset_family", "")), str(row.get("sequence", "")))
            if not all(key) or key in rows:
                issues.append(f"attestation_identity_invalid_or_duplicate:{key}")
                continue
            rows[key] = row
    return rows, issues


def validate_attestation(
    family: str,
    sequence: str,
    row: dict[str, Any],
    current_hashes: dict[str, str],
    runner_v1: dict[str, str],
) -> list[str]:
    issues: list[str] = []
    if row.get("schema_version") != "isj-p06-screening-attestation-v2":
        issues.append("attestation_schema_mismatch")
    if row.get("outcome_boundary") != base.EXPECTED_BOUNDARY:
        issues.append("attestation_outcome_boundary_mismatch")
    if row.get("learned_outcome_read") is not False:
        issues.append("attestation_learned_outcome_flag")
    if row.get("trajectory_outcome_read") is not False:
        issues.append("attestation_trajectory_outcome_flag")
    run_dir, pointer_issues = base.resolve_screening_dir(family, sequence)
    issues.extend(pointer_issues)
    for key, target in (
        ("metrics", run_dir / "metrics.csv"),
        ("screening_run_audit", run_dir / "screening_run.json"),
    ):
        record = row.get(key)
        if not isinstance(record, dict) or not target.is_file():
            issues.append(f"attestation_{key}_missing")
            continue
        relative = target.resolve().relative_to(ROOT).as_posix()
        if record.get("path") != relative:
            issues.append(f"attestation_{key}_path_mismatch")
        if record.get("sha256") != sha256(target):
            issues.append(f"attestation_{key}_hash_mismatch")
        if record.get("size_bytes") != target.stat().st_size:
            issues.append(f"attestation_{key}_size_mismatch")
    execution = row.get("execution_runner")
    if not isinstance(execution, dict):
        issues.append("attestation_execution_runner_missing")
    else:
        path = str(execution.get("path", ""))
        if runner_v1.get(path) != execution.get("sha256"):
            issues.append("attestation_execution_runner_v1_mismatch")
    attester = row.get("attestation_runner")
    if not isinstance(attester, dict):
        issues.append("attestation_current_runner_missing")
    else:
        path = str(attester.get("path", ""))
        digest = str(attester.get("sha256", ""))
        if current_hashes.get(path) != digest:
            issues.append("attestation_current_runner_manifest_mismatch")
        target = ROOT / path
        if not target.is_file() or sha256(target) != digest:
            issues.append("attestation_current_runner_content_mismatch")
    builder = row.get("attestation_builder")
    if builder is not None:
        if not isinstance(builder, dict):
            issues.append("attestation_builder_invalid")
        else:
            path = str(builder.get("path", ""))
            digest = str(builder.get("sha256", ""))
            if current_hashes.get(path) != digest:
                issues.append("attestation_builder_manifest_mismatch")
            target = ROOT / path
            if not target.is_file() or sha256(target) != digest:
                issues.append("attestation_builder_content_mismatch")
            if target.is_file() and builder.get("size_bytes") != target.stat().st_size:
                issues.append("attestation_builder_size_mismatch")
    return sorted(set(issues))


def pointer_identity_issues(family: str, sequence: str) -> list[str]:
    canonical = base.SCREENING / family / sequence
    pointer_path = canonical / "current_attempt.json"
    if not pointer_path.is_file():
        return []
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    run_dir, issues = base.resolve_screening_dir(family, sequence)
    if issues:
        return list(issues)
    audit_path = run_dir / "screening_run.json"
    if not audit_path.is_file():
        return ["pointer_active_audit_missing"]
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    expected = {
        "attempt_id": pointer.get("attempt_id"),
        "run_dir": pointer.get("run_dir"),
        "canonical_run_dir": canonical.resolve().relative_to(ROOT).as_posix(),
        "metrics_path": pointer.get("metrics_path"),
        "process_log_path": pointer.get("process_log_path"),
    }
    result = [
        f"pointer_audit_identity_mismatch:{key}"
        for key, value in expected.items()
        if audit.get(key) != value
    ]
    command_path = run_dir / "command.txt"
    if not command_path.is_file() or command_path.read_text(encoding="utf-8") != f"{audit.get('command', '')}\n":
        result.append("pointer_audit_command_mismatch")
    return sorted(set(result))


def validate_reference_exclusion(family: str, sequence: str) -> list[str]:
    path = base.SCREENING / family / sequence / "reference_exclusion.json"
    if not path.is_file():
        return ["reference_exclusion_missing"]
    try:
        decision = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ["reference_exclusion_json_invalid"]
    issues: list[str] = []
    expected = {
        "schema_version": "isj-p06-reference-sequence-exclusion-v1",
        "status": "STOPPED_REFERENCE_INELIGIBLE",
        "dataset_family": family,
        "sequence": sequence,
        "outcome_boundary": base.EXPECTED_BOUNDARY,
        "reference_support_pass_windows": 0,
    }
    for key, value in expected.items():
        if decision.get(key) != value:
            issues.append(f"reference_exclusion_field_mismatch:{key}")
    if decision.get("learned_outcome_read") is not False:
        issues.append("reference_exclusion_learned_outcome_flag")
    if decision.get("trajectory_outcome_read") is not False:
        issues.append("reference_exclusion_trajectory_outcome_flag")
    if decision.get("scientific_screening_result_produced") is not False:
        issues.append("reference_exclusion_scientific_result_flag")
    support_path = P06 / "reference_window_support_audit_v2.csv"
    if decision.get("reference_support_sha256") != sha256(support_path):
        issues.append("reference_exclusion_support_hash_mismatch")
    support_rows = [
        row
        for row in base.read_csv(support_path)
        if row.get("dataset_family") == family and row.get("sequence") == sequence
    ]
    if len(support_rows) != decision.get("gross_fixed_windows"):
        issues.append("reference_exclusion_window_count_mismatch")
    if any(row.get("reference_support_pass") != "false" for row in support_rows):
        issues.append("reference_exclusion_has_supported_window")
    for key in ("partial_metrics", "runner_audit"):
        record = decision.get(key)
        if not isinstance(record, dict):
            issues.append(f"reference_exclusion_{key}_missing")
            continue
        target = ROOT / str(record.get("path", ""))
        if not target.is_file() or record.get("sha256") != sha256(target):
            issues.append(f"reference_exclusion_{key}_hash_mismatch")
    return sorted(set(issues))


def validate_afrl_calibration_contract(family: str, sequence: str) -> list[str]:
    if family != "afrl" or not CALIBRATION_CORRECTION.is_file():
        return []
    run_dir, pointer_issues = base.resolve_screening_dir(family, sequence)
    if pointer_issues:
        return []
    audit_path = run_dir / "screening_run.json"
    if not audit_path.is_file():
        return []
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if audit.get("status") != "PASS":
        return []
    correction = json.loads(CALIBRATION_CORRECTION.read_text(encoding="utf-8"))
    expected = correction.get("sequences", {}).get(sequence)
    if not isinstance(expected, dict):
        return ["calibration_correction_sequence_missing"]
    contract = audit.get("calibration_contract")
    if not isinstance(contract, dict):
        return ["calibration_contract_missing"]
    issues: list[str] = []
    if audit.get("runner_version") != "isj-p06-ros-screening-v3-calibration-corrected":
        issues.append("calibration_runner_version_mismatch")
    if contract.get("schema_version") != "isj-p06-afrl-calibration-contract-v1":
        issues.append("calibration_contract_schema_mismatch")
    if contract.get("status") != "PASS":
        issues.append("calibration_contract_not_pass")
    if contract.get("outcome_boundary") != base.EXPECTED_BOUNDARY:
        issues.append("calibration_contract_boundary_mismatch")
    if contract.get("learned_outcome_read") is not False:
        issues.append("calibration_contract_learned_outcome_flag")
    if contract.get("trajectory_outcome_read") is not False:
        issues.append("calibration_contract_trajectory_outcome_flag")
    correction_record = contract.get("correction_manifest")
    if not isinstance(correction_record, dict):
        issues.append("calibration_correction_record_missing")
    else:
        if correction_record.get("path") != CALIBRATION_CORRECTION.relative_to(ROOT).as_posix():
            issues.append("calibration_correction_path_mismatch")
        if correction_record.get("sha256") != sha256(CALIBRATION_CORRECTION):
            issues.append("calibration_correction_hash_mismatch")
    selected_path = str(expected.get("selected_calibration_path", ""))
    if contract.get("selected_calibration_path") != selected_path:
        issues.append("selected_calibration_path_mismatch")
    selected = ROOT / selected_path
    if (
        not selected.is_file()
        or contract.get("selected_calibration_sha256") != sha256(selected)
        or expected.get("selected_calibration_sha256") != sha256(selected)
    ):
        issues.append("selected_calibration_hash_mismatch")
    camera_info = contract.get("camera_info")
    expected_info = expected.get("camera_info")
    if not isinstance(camera_info, dict) or not isinstance(expected_info, dict):
        issues.append("calibration_camera_info_missing")
    else:
        if camera_info.get("matches_correction") is not True:
            issues.append("calibration_camera_info_not_matched")
        for key in ("topic", "width", "height", "K", "D"):
            if camera_info.get(key) != expected_info.get(key):
                issues.append(f"calibration_camera_info_mismatch:{key}")
    return sorted(set(issues))


def build_report(require_final: bool) -> dict[str, Any]:
    report = base.build_report(require_final=require_final)
    current_hashes, manifest_issues = validate_current_manifests()
    runner_v1, runner_v1_issues = strict_hash_manifest(RUNNER_V1)
    attestations, attestation_parse_issues = read_attestations()
    global_issues = list(report.get("global_issues", []))
    global_issues.extend(manifest_issues)
    global_issues.extend(runner_v1_issues)
    global_issues.extend(attestation_parse_issues)
    if ATTESTATION_FILES[1].is_file() and not ATTESTATION_ADDENDUM_HASHES.is_file():
        global_issues.append("attestation_addendum_hash_manifest_missing")
    sequence_issues = {
        sequence: resolve_registered_code_issues(list(issues), current_hashes)
        for sequence, issues in report.get("sequence_issues", {}).items()
    }
    specs = {(row["dataset_family"], row["sequence"]): row for row in base.expected_sequences()}
    for key, attestation in attestations.items():
        if key not in specs:
            global_issues.append(f"attestation_sequence_not_expected:{key[0]}/{key[1]}")
            continue
        family, sequence = key
        issues = validate_attestation(
            family, sequence, attestation, current_hashes, runner_v1
        )
        if issues:
            sequence_issues.setdefault(sequence, []).extend(issues)
        else:
            sequence_issues[sequence] = [
                issue
                for issue in sequence_issues.get(sequence, [])
                if issue != "required_code_not_recorded:scripts/run_p06_aqualoc_screening.py"
                and issue != "required_code_not_recorded:scripts/run_p06_ros_screening.py"
            ]
    for family, sequence in specs:
        sequence_issues.setdefault(sequence, []).extend(
            pointer_identity_issues(family, sequence)
        )
        sequence_issues.setdefault(sequence, []).extend(
            validate_afrl_calibration_contract(family, sequence)
        )
    reference_excluded: list[str] = []
    for family, sequence in specs:
        exclusion_path = base.SCREENING / family / sequence / "reference_exclusion.json"
        if not exclusion_path.is_file():
            continue
        exclusion_issues = validate_reference_exclusion(family, sequence)
        if exclusion_issues:
            sequence_issues.setdefault(sequence, []).extend(exclusion_issues)
        else:
            reference_excluded.append(sequence)
            sequence_issues[sequence] = []
    sequence_issues = {
        sequence: sorted(set(issues)) for sequence, issues in sequence_issues.items()
    }
    incomplete = [sequence for sequence, issues in sequence_issues.items() if issues]
    final_issues = list(report.get("final_manifest_issues", []))
    screening_pass_sequences = [
        sequence
        for _, sequence in specs
        if sequence not in reference_excluded and not sequence_issues.get(sequence, [])
    ]
    screening_pass_count = len(screening_pass_sequences)
    terminal_count = screening_pass_count + len(reference_excluded)
    if global_issues:
        status = "REVISE"
    elif incomplete:
        status = "IN_PROGRESS" if terminal_count < report.get("required_sequence_count", 0) else "REVISE"
    elif require_final and final_issues:
        status = "REVISE"
    else:
        status = "PASS"
    return {
        **report,
        "schema_version": "isj-p06-screening-closeout-v2",
        "status": status,
        "global_issues": sorted(set(global_issues)),
        "sequence_issues": sequence_issues,
        "final_manifest_issues": final_issues,
        "provenance_attestation_count": len(attestations),
        "fully_validated_current_hash_count": len(current_hashes),
        "screening_pass_sequence_count": screening_pass_count,
        "reference_excluded_sequences": sorted(reference_excluded),
        "reference_excluded_sequence_count": len(reference_excluded),
        "terminal_sequence_count": terminal_count,
        "completed_sequence_count": terminal_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-final", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    report = build_report(bool(args.require_final))
    rendered = json.dumps(report, sort_keys=True, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    return 0 if report["status"] == "PASS" else (2 if report["status"] == "IN_PROGRESS" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
