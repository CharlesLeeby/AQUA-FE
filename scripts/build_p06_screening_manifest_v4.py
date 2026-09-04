#!/usr/bin/env python3
"""Apply the frozen full-reference gate before the v3 sequence cap."""

from __future__ import annotations

import csv
import json
import math
import os
from collections import Counter, defaultdict
from pathlib import Path

try:
    from scripts import build_p06_screening_manifest as quota
    from scripts import build_p06_screening_manifest_v3 as v3
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p06_screening_manifest as quota  # type: ignore
    import build_p06_screening_manifest_v3 as v3  # type: ignore


ROOT = v3.ROOT
BUNDLE = v3.BUNDLE
P06 = v3.P06
REFERENCE_SUPPORT = P06 / "reference_window_support_audit_v2.csv"
ATTEMPT02_AUDIT = BUNDLE / "window_selection_audit_v3.csv"
ATTEMPT02_MANIFEST = BUNDLE / "dataset_manifest_v3.csv"
ATTEMPT02_PROGRESS = P06 / "screening_progress_v3.json"
ATTEMPT02_VALIDATION = P06 / "final_artifact_validation_v3.json"
PROTOCOL = P06 / "final_reference_gate_repair_v4.md"
OUTPUT_AUDIT = BUNDLE / "window_selection_audit_v4.csv"
OUTPUT_MANIFEST = BUNDLE / "dataset_manifest_v4.csv"
OUTPUT_PROGRESS = P06 / "screening_progress_v4.json"

PROTOCOL_VERSION = "isj-window-selection-v4-full-reference"
QUOTA_VERSION = "isj-p06-global-quota-v3-full-reference"
EXPECTED_HASHES = {
    REFERENCE_SUPPORT: "9a81acea50be6890d29cd533a1566e4e3b783393961e640f8e99131bdd069a0b",
    ATTEMPT02_AUDIT: "f668bd34119c2920d9b82c84f73e72478ead9d5132ecad23abc8516569a84430",
    ATTEMPT02_MANIFEST: "4c52267a8b96e4c5eb9d8cd8577dd813e49f7798b8d360fc96c2ea13aa719f7b",
    ATTEMPT02_PROGRESS: "fb2c54ca76f16aaa168ef96a09966f2f1fe4f2134f30a4e4e54330a9882ecec1",
    ATTEMPT02_VALIDATION: "d97bc230d646b873b2628cff9c739845788a703cd5ee11c8d9b230f8d9132e84",
}


def support_index() -> dict[tuple[str, str, int], dict[str, str]]:
    _fields, rows = v3.read_csv(REFERENCE_SUPPORT)
    result: dict[tuple[str, str, int], dict[str, str]] = {}
    for row in rows:
        key = (row["dataset_family"], row["sequence"], int(row["window_index"]))
        if key in result:
            raise ValueError(f"duplicate reference support key: {key}")
        result[key] = row
    return result


def validate_inputs() -> dict[tuple[str, str, int], dict[str, str]]:
    for path, expected in EXPECTED_HASHES.items():
        if not path.is_file() or v3.sha256(path) != expected:
            raise ValueError(f"v4 input hash mismatch: {path}")
    if not PROTOCOL.is_file():
        raise FileNotFoundError(PROTOCOL)
    attempt02 = json.loads(ATTEMPT02_PROGRESS.read_text(encoding="utf-8"))
    validation = json.loads(ATTEMPT02_VALIDATION.read_text(encoding="utf-8"))
    if (
        attempt02.get("status") != "PASS"
        or validation.get("status") != "REVISE"
        or len(validation.get("issues", [])) != 8
        or attempt02.get("learned_outcome_read") is not False
        or attempt02.get("trajectory_outcome_read") is not False
    ):
        raise ValueError("attempt02 is not the frozen reference-incomplete state")
    return support_index()


def fully_supported(record: dict[str, str]) -> bool:
    return (
        int(record["supported_grid_count"]) == int(record["grid_count"])
        and math.isclose(float(record["coverage"]), 1.0, rel_tol=0.0, abs_tol=1e-12)
    )


def reclassify_and_gate() -> list[dict[str, object]]:
    support = validate_inputs()
    _fields, source_rows, _attempt01 = v3.validate_inputs()
    rows = v3.reclassify(source_rows)
    for row in rows:
        row["protocol_version_v3"] = row["protocol_version"]
        row["selected_by_sequence_rule_v3"] = row["selected_by_sequence_rule"]
        row["protocol_version"] = PROTOCOL_VERSION
        row["quota_protocol"] = QUOTA_VERSION
        key = (
            str(row["dataset_family"]),
            str(row["sequence"]),
            int(row["window_index"]),
        )
        record = support.get(key)
        if record is None:
            raise ValueError(f"missing frozen reference support row: {key}")
        row["full_reference_support"] = str(fully_supported(record)).lower()
        row["reference_grid_count"] = record["grid_count"]
        row["reference_supported_grid_count"] = record["supported_grid_count"]
        row["reference_full_coverage"] = record["coverage"]
        row["selected_by_sequence_rule"] = "false"
        row["selected_final"] = "false"

    by_sequence: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        if (
            row["full_reference_support"] == "true"
            and row["texture_stratum"] in {"low", "normal"}
        ):
            by_sequence[(str(row["dataset_family"]), str(row["sequence"]))].append(row)
    selected_ids: set[str] = set()
    for values in by_sequence.values():
        low = sorted(
            (row for row in values if row["texture_stratum"] == "low"),
            key=lambda row: (-float(row["score"]), float(row["window_start_s"])),
        )
        normal = sorted(
            (row for row in values if row["texture_stratum"] == "normal"),
            key=lambda row: (float(row["score"]), float(row["window_start_s"])),
        )
        selected_ids.update(str(row["window_id"]) for row in low[:2] + normal[:2])
    for row in rows:
        row["selected_by_sequence_rule"] = str(
            str(row["window_id"]) in selected_ids
        ).lower()
    return rows


def build_selection() -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    rows = reclassify_and_gate()
    low_candidates = v3.candidates(rows, "low")
    normal_candidates = v3.candidates(rows, "normal")
    pair = quota.choose_joint_pair(
        quota.build_variants(low_candidates), quota.build_variants(normal_candidates)
    )
    if pair is None or not quota.final_checks(pair[0], pair[1]):
        raise ValueError("frozen v4 full-reference selection is infeasible")
    selected_ids = {
        candidate.window_id for variant in pair for candidate in variant.candidates
    }
    for row in rows:
        row["selected_final"] = str(str(row["window_id"]) in selected_ids).lower()
    selected = [row for row in rows if row["selected_final"] == "true"]
    if any(row["full_reference_support"] != "true" for row in selected):
        raise ValueError("v4 selected a reference-incomplete window")
    strata = Counter(str(row["texture_stratum"]) for row in selected)
    tiers = Counter(str(row["selection_tier"]) for row in selected)
    progress: dict[str, object] = {
        "schema_version": "isj-p06-screening-progress-v4",
        "status": "PASS",
        "protocol_version": PROTOCOL_VERSION,
        "quota_protocol": QUOTA_VERSION,
        "repair_trigger": "ATTEMPT02_FINAL_REFERENCE_GRID_INCOMPLETE",
        "attempt02": {
            "window_selection_audit": v3.file_record(ATTEMPT02_AUDIT),
            "dataset_manifest": v3.file_record(ATTEMPT02_MANIFEST),
            "screening_progress": v3.file_record(ATTEMPT02_PROGRESS),
            "final_validation": v3.file_record(ATTEMPT02_VALIDATION),
            "status": "REVISE_FINAL_REFERENCE_SUPPORT",
        },
        "reference_support_audit": v3.file_record(REFERENCE_SUPPORT),
        "protocol_addendum": v3.file_record(PROTOCOL),
        "gross_window_count": len(rows),
        "sequence_capped_low_count": len(low_candidates),
        "sequence_capped_normal_count": len(normal_candidates),
        "selected_low_count": strata["low"],
        "selected_normal_count": strata["normal"],
        "selected_sequence_count": len({str(row["sequence"]) for row in selected}),
        "selected_domain_count": len({str(row["data_domain"]) for row in selected}),
        "selected_low_sequence_count": len(
            {str(row["sequence"]) for row in selected if row["texture_stratum"] == "low"}
        ),
        "selected_normal_sequence_count": len(
            {str(row["sequence"]) for row in selected if row["texture_stratum"] == "normal"}
        ),
        "selected_low_domain_count": len(
            {str(row["data_domain"]) for row in selected if row["texture_stratum"] == "low"}
        ),
        "selected_normal_domain_count": len(
            {str(row["data_domain"]) for row in selected if row["texture_stratum"] == "normal"}
        ),
        "selected_tier_counts": dict(sorted(tiers.items())),
        "selected_window_ids": sorted(selected_ids),
        "all_selected_full_reference_support": True,
        "outcome_boundary": v3.OUTCOME_BOUNDARY,
        "learned_outcome_read": False,
        "trajectory_outcome_read": False,
    }
    return rows, selected, progress


MANIFEST_FIELDS = v3.MANIFEST_FIELDS + [
    "reference_grid_count",
    "reference_supported_grid_count",
    "reference_full_coverage",
]


def manifest_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    base = v3.manifest_rows(rows)
    by_id = {str(row["window_id"]): row for row in rows}
    output: list[dict[str, object]] = []
    for row in base:
        source = by_id[str(row["window_id"])]
        value = dict(row)
        value["protocol_version"] = PROTOCOL_VERSION
        value["quota_protocol"] = QUOTA_VERSION
        value["split_role"] = (
            "SEQUENCE_HELD_OUT_CONFIRMATORY_AFTER_OUTCOME_BLIND_REPAIRS"
        )
        for key in (
            "reference_grid_count",
            "reference_supported_grid_count",
            "reference_full_coverage",
        ):
            value[key] = source[key]
        output.append(value)
    return output


def write_outputs(
    rows: list[dict[str, object]],
    selected: list[dict[str, object]],
    progress: dict[str, object],
) -> None:
    outputs = (OUTPUT_AUDIT, OUTPUT_MANIFEST, OUTPUT_PROGRESS)
    existing = [str(path) for path in outputs if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite v4 outputs: {existing}")
    temporary = {
        path: path.with_name(f"{path.name}.partial.{os.getpid()}") for path in outputs
    }
    v3.write_csv(temporary[OUTPUT_AUDIT], v3.audit_fields(rows), rows)
    v3.write_csv(temporary[OUTPUT_MANIFEST], MANIFEST_FIELDS, manifest_rows(selected))
    payload = dict(progress)
    payload["window_selection_audit"] = v3.file_record(temporary[OUTPUT_AUDIT])
    payload["window_selection_audit"]["path"] = v3.relative(OUTPUT_AUDIT)
    payload["dataset_manifest"] = v3.file_record(temporary[OUTPUT_MANIFEST])
    payload["dataset_manifest"]["path"] = v3.relative(OUTPUT_MANIFEST)
    temporary[OUTPUT_PROGRESS].write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    for path in outputs:
        os.replace(temporary[path], path)


def main() -> int:
    rows, selected, progress = build_selection()
    write_outputs(rows, selected, progress)
    print(
        "P06_SCREENING_V4_PASS "
        f"low={progress['selected_low_count']} normal={progress['selected_normal_count']} "
        f"sequences={progress['selected_sequence_count']} "
        f"domains={progress['selected_domain_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
