#!/usr/bin/env python3
"""Validate the versioned P06 quota-repair manifest and reference support."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    from scripts import build_p06_screening_manifest_v3 as builder
    from scripts import validate_p06_final_artifacts as reference_validator
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p06_screening_manifest_v3 as builder  # type: ignore
    import validate_p06_final_artifacts as reference_validator  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
OUTPUT = BUNDLE / "p06/final_artifact_validation_v3.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        if not fields or len(fields) != len(set(fields)):
            raise ValueError(f"invalid CSV header: {path}")
        rows = list(reader)
    if any(None in row for row in rows):
        raise ValueError(f"ragged CSV: {path}")
    return rows


def render_csv(fields: list[str], rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def deterministic_rebuild() -> dict[str, object]:
    rows, selected, progress = builder.build_selection()
    audit_bytes = render_csv(builder.audit_fields(rows), rows)
    manifest_bytes = render_csv(
        builder.MANIFEST_FIELDS, builder.manifest_rows(selected)
    )
    observed_progress = json.loads(builder.OUTPUT_PROGRESS.read_text(encoding="utf-8"))
    expected_progress = dict(progress)
    expected_progress["window_selection_audit"] = {
        "path": builder.relative(builder.OUTPUT_AUDIT),
        "sha256": hash_bytes(audit_bytes),
        "size_bytes": len(audit_bytes),
    }
    expected_progress["dataset_manifest"] = {
        "path": builder.relative(builder.OUTPUT_MANIFEST),
        "sha256": hash_bytes(manifest_bytes),
        "size_bytes": len(manifest_bytes),
    }
    return {
        "pass": (
            hash_bytes(audit_bytes) == sha256(builder.OUTPUT_AUDIT)
            and hash_bytes(manifest_bytes) == sha256(builder.OUTPUT_MANIFEST)
            and expected_progress == observed_progress
        ),
        "expected_window_audit_sha256": hash_bytes(audit_bytes),
        "observed_window_audit_sha256": sha256(builder.OUTPUT_AUDIT),
        "expected_manifest_sha256": hash_bytes(manifest_bytes),
        "observed_manifest_sha256": sha256(builder.OUTPUT_MANIFEST),
        "expected_progress_equals_observed": expected_progress == observed_progress,
    }


def reference_support_report(selected: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[str]]:
    eligibility = reference_validator.index(
        reference_validator.read_csv(reference_validator.ELIGIBILITY)
    )
    references = reference_validator.index(
        reference_validator.read_csv(reference_validator.REFERENCES)
    )
    origins: dict[tuple[str, str], float] = {}
    stamps: dict[tuple[str, str], list[float]] = {}
    rows: list[dict[str, Any]] = []
    issues: list[str] = []
    for selected_row in selected:
        family = selected_row["dataset_family"]
        sequence = selected_row["sequence"]
        window_id = selected_row["window_id"]
        key = (family, sequence)
        eligibility_row = eligibility.get(key)
        reference_row = references.get(key)
        if eligibility_row is None or reference_row is None:
            issues.append(f"reference_registration_missing:{window_id}")
            continue
        if key not in origins:
            origins[key], _metrics = reference_validator.metrics_origin(family, sequence)
        if key not in stamps:
            stamps[key] = reference_validator.load_reference_stamps(
                family, sequence, ROOT / eligibility_row["reference_path"]
            )
        start = origins[key] + float(selected_row["window_start_s"])
        end = origins[key] + float(selected_row["window_end_s"])
        support = reference_validator.reference_support(
            stamps[key],
            start,
            end,
            float(reference_row["evaluation_rate_hz"]),
            float(reference_row["max_reference_gap_s"]),
        )
        result = {
            "window_id": window_id,
            "absolute_start_s": start,
            "absolute_end_s": end,
            **support,
        }
        rows.append(result)
        if not support.get("pass"):
            issues.append(f"reference_support_fail:{window_id}")
    return rows, issues


def build_report() -> dict[str, object]:
    issues: list[str] = []
    required = (
        builder.OUTPUT_AUDIT,
        builder.OUTPUT_MANIFEST,
        builder.OUTPUT_PROGRESS,
    )
    if any(not path.is_file() for path in required):
        return {
            "schema_version": "isj-p06-final-artifact-validation-v3",
            "status": "IN_PROGRESS",
            "issues": ["missing_v3_selection_artifacts"],
            "learned_outcome_read": False,
            "trajectory_outcome_read": False,
        }
    audit = read_csv(builder.OUTPUT_AUDIT)
    selected = read_csv(builder.OUTPUT_MANIFEST)
    progress = json.loads(builder.OUTPUT_PROGRESS.read_text(encoding="utf-8"))
    if len(audit) != 156:
        issues.append(f"window_audit_count:{len(audit)}")
    if len(selected) != 20:
        issues.append(f"selected_window_count:{len(selected)}")
    if progress.get("status") != "PASS":
        issues.append("screening_progress_not_pass")
    if progress.get("learned_outcome_read") is not False:
        issues.append("learned_outcome_boundary_violation")
    if progress.get("trajectory_outcome_read") is not False:
        issues.append("trajectory_outcome_boundary_violation")

    selected_ids = [row.get("window_id", "") for row in selected]
    if len(selected_ids) != len(set(selected_ids)) or any(not value for value in selected_ids):
        issues.append("duplicate_or_empty_selected_window_id")
    audit_by_id = {row["window_id"]: row for row in audit}
    if len(audit_by_id) != len(audit):
        issues.append("duplicate_window_audit_id")
    final_ids = {
        row["window_id"] for row in audit if row.get("selected_final") == "true"
    }
    if set(selected_ids) != final_ids:
        issues.append("manifest_audit_selection_mismatch")

    strata = Counter(row.get("texture_stratum", "") for row in selected)
    tiers = Counter(row.get("selection_tier", "") for row in selected)
    if strata != {"low": 10, "normal": 10}:
        issues.append(f"stratum_counts:{dict(strata)}")
    if tiers != {
        "ABSOLUTE_LOW": 4,
        "RELATIVE_Q80_FALLBACK": 6,
        "STRICT_NORMAL": 10,
    }:
        issues.append(f"tier_counts:{dict(tiers)}")

    per_sequence_stratum: Counter[tuple[str, str]] = Counter()
    for row in selected:
        window_id = row["window_id"]
        source = audit_by_id.get(window_id)
        if source is None:
            issues.append(f"selected_window_missing_from_audit:{window_id}")
            continue
        if source.get("history_excluded") != "false":
            issues.append(f"history_excluded_selected:{window_id}")
        if source.get("reference_support_pass") != "true":
            issues.append(f"reference_gate_selected:{window_id}")
        if int(float(row.get("input_frame_count", "0"))) < 200:
            issues.append(f"input_support_selected:{window_id}")
        score = float(row["score"])
        q20 = float(row["sequence_q20"])
        q80 = float(row["sequence_q80"])
        tier = row["selection_tier"]
        if tier == "ABSOLUTE_LOW" and not (score >= 0.17 and score >= q80):
            issues.append(f"absolute_low_rule:{window_id}")
        elif tier == "RELATIVE_Q80_FALLBACK" and not (
            0.10 < score < 0.17 and score >= q80
        ):
            issues.append(f"relative_low_rule:{window_id}")
        elif tier == "STRICT_NORMAL" and not (score <= 0.10 and score <= q20):
            issues.append(f"strict_normal_rule:{window_id}")
        per_sequence_stratum[(row["sequence"], row["texture_stratum"])] += 1
    if max(per_sequence_stratum.values(), default=0) > 2:
        issues.append("per_sequence_stratum_cap_exceeded")

    for stratum in ("low", "normal"):
        subset = [row for row in selected if row["texture_stratum"] == stratum]
        if len({row["sequence"] for row in subset}) < 6:
            issues.append(f"sequence_diversity:{stratum}")
        if len({row["data_domain"] for row in subset}) < 2:
            issues.append(f"domain_diversity:{stratum}")
    if len({row["data_domain"] for row in selected}) < 3:
        issues.append("joint_domain_diversity")

    deterministic = deterministic_rebuild()
    if deterministic["pass"] is not True:
        issues.append("deterministic_rebuild_mismatch")
    support_rows, support_issues = reference_support_report(selected)
    issues.extend(support_issues)
    return {
        "schema_version": "isj-p06-final-artifact-validation-v3",
        "status": "PASS" if not issues else "REVISE",
        "protocol_version": builder.PROTOCOL_VERSION,
        "selected_window_count": len(selected),
        "stratum_counts": dict(sorted(strata.items())),
        "tier_counts": dict(sorted(tiers.items())),
        "selected_sequence_count": len({row["sequence"] for row in selected}),
        "selected_domain_count": len({row["data_domain"] for row in selected}),
        "deterministic_rebuild": deterministic,
        "selected_reference_support": support_rows,
        "artifacts": {
            "window_selection_audit": {
                "path": builder.relative(builder.OUTPUT_AUDIT),
                "sha256": sha256(builder.OUTPUT_AUDIT),
            },
            "dataset_manifest": {
                "path": builder.relative(builder.OUTPUT_MANIFEST),
                "sha256": sha256(builder.OUTPUT_MANIFEST),
            },
            "screening_progress": {
                "path": builder.relative(builder.OUTPUT_PROGRESS),
                "sha256": sha256(builder.OUTPUT_PROGRESS),
            },
        },
        "issues": sorted(set(issues)),
        "outcome_boundary": builder.OUTCOME_BOUNDARY,
        "learned_outcome_read": False,
        "trajectory_outcome_read": False,
    }


def write_no_clobber(path: Path, payload: dict[str, object]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    report = build_report()
    write_no_clobber(args.output, report)
    print(
        f"P06_FINAL_ARTIFACTS_V3_{report['status']} "
        f"selected={report.get('selected_window_count', 0)} "
        f"issues={len(report.get('issues', []))}"
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
