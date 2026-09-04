#!/usr/bin/env python3
"""Build the versioned outcome-blind P06 quota-repair selection."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

try:
    from scripts import build_p06_screening_manifest as quota
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p06_screening_manifest as quota  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
P06 = BUNDLE / "p06"
INPUT_AUDIT = BUNDLE / "window_selection_audit.csv"
INPUT_MANIFEST = BUNDLE / "dataset_manifest.csv"
INPUT_PROGRESS = P06 / "screening_progress.json"
PROTOCOL = P06 / "window_selection_quota_repair_v3.md"
OUTPUT_AUDIT = BUNDLE / "window_selection_audit_v3.csv"
OUTPUT_MANIFEST = BUNDLE / "dataset_manifest_v3.csv"
OUTPUT_PROGRESS = P06 / "screening_progress_v3.json"

PROTOCOL_VERSION = "isj-window-selection-v3-quota-repair"
QUOTA_VERSION = "isj-p06-global-quota-v2-outcome-blind-repair"
OUTCOME_BOUNDARY = "KLT_AND_IMAGE_QUALITY_ONLY_NO_LEARNED_OR_VINS_OUTCOME"
TAU_LOW = 0.17
TAU_NORMAL = 0.10
EXPECTED_INPUT_HASHES = {
    INPUT_AUDIT: "1b1192de5602562a8f868c612f27bcc02ca568cd735c2b7da1e6e6e833d093c1",
    INPUT_MANIFEST: "298aa36bf063ee80aec529dba87b3f92535cdf5384f85cbfbc294a18736b7b20",
    INPUT_PROGRESS: "6af8deabce62d5f5bc2afbe1d58538c3ee16a4030ad2796f088dfc8275955569",
}
FORBIDDEN_INPUT_COLUMN_TOKENS = (
    "learned",
    "xfeat",
    "loftr",
    "superpoint",
    "trajectory",
    "ape",
    "rpe",
    "vins",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def file_record(path: Path) -> dict[str, object]:
    return {
        "path": relative(path),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        if not fields or len(fields) != len(set(fields)):
            raise ValueError(f"invalid CSV header: {path}")
        rows = list(reader)
    if any(None in row for row in rows):
        raise ValueError(f"ragged CSV: {path}")
    return fields, rows


def validate_inputs() -> tuple[list[str], list[dict[str, str]], dict[str, object]]:
    for path, expected in EXPECTED_INPUT_HASHES.items():
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f"attempt01 input hash mismatch: {path}")
    if not PROTOCOL.is_file():
        raise FileNotFoundError(PROTOCOL)
    fields, rows = read_csv(INPUT_AUDIT)
    for field in fields:
        lowered = field.lower()
        if any(token in lowered for token in FORBIDDEN_INPUT_COLUMN_TOKENS):
            raise ValueError(f"forbidden outcome-bearing input column: {field}")
    progress = json.loads(INPUT_PROGRESS.read_text(encoding="utf-8"))
    if (
        progress.get("status") != "REVISE"
        or progress.get("selected_low_count") != 0
        or progress.get("selected_normal_count") != 0
        or progress.get("sequence_capped_low_count") != 4
        or progress.get("sequence_capped_normal_count") != 13
        or progress.get("outcome_boundary") != OUTCOME_BOUNDARY
    ):
        raise ValueError("attempt01 is not the frozen quota-infeasible REVISE state")
    if len(rows) != int(progress.get("gross_window_count", -1)):
        raise ValueError("attempt01 audit/progress row count mismatch")
    return fields, rows, progress


def _eligible(row: dict[str, str]) -> bool:
    return (
        row.get("history_excluded") == "false"
        and row.get("reference_support_pass") == "true"
        and bool(row.get("score"))
        and bool(row.get("sequence_q20"))
        and bool(row.get("sequence_q80"))
    )


def reclassify(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for original in rows:
        row: dict[str, object] = dict(original)
        row["protocol_version_v2"] = original.get("protocol_version", "")
        row["texture_stratum_v2"] = original.get("texture_stratum", "")
        row["selected_by_sequence_rule_v2"] = original.get(
            "selected_by_sequence_rule", "false"
        )
        row["protocol_version"] = PROTOCOL_VERSION
        row["quota_protocol"] = QUOTA_VERSION
        row["selected_by_sequence_rule"] = "false"
        row["selected_final"] = "false"
        row["selection_tier"] = ""
        if not _eligible(original):
            output.append(row)
            continue
        score = float(original["score"])
        q20 = float(original["sequence_q20"])
        q80 = float(original["sequence_q80"])
        if score <= TAU_NORMAL and score <= q20:
            row["texture_stratum"] = "normal"
            row["selection_tier"] = "STRICT_NORMAL"
        elif score > TAU_NORMAL and score >= q80:
            row["texture_stratum"] = "low"
            row["selection_tier"] = (
                "ABSOLUTE_LOW" if score >= TAU_LOW else "RELATIVE_Q80_FALLBACK"
            )
        else:
            row["texture_stratum"] = "unclassified"
        output.append(row)

    by_sequence: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in output:
        if _eligible({key: str(value) for key, value in row.items()}):
            by_sequence[(str(row["dataset_family"]), str(row["sequence"]))].append(row)
    selected_ids: set[str] = set()
    for sequence_rows in by_sequence.values():
        low = sorted(
            (row for row in sequence_rows if row["texture_stratum"] == "low"),
            key=lambda row: (-float(row["score"]), float(row["window_start_s"])),
        )
        normal = sorted(
            (row for row in sequence_rows if row["texture_stratum"] == "normal"),
            key=lambda row: (float(row["score"]), float(row["window_start_s"])),
        )
        selected_ids.update(str(row["window_id"]) for row in low[:2] + normal[:2])
    for row in output:
        row["selected_by_sequence_rule"] = str(
            str(row["window_id"]) in selected_ids
        ).lower()
    return output


def candidates(rows: list[dict[str, object]], stratum: str) -> list[quota.Candidate]:
    selected = [
        row
        for row in rows
        if row.get("texture_stratum") == stratum
        and row.get("selected_by_sequence_rule") == "true"
    ]
    selected.sort(
        key=lambda row: (
            -float(row["score"]) if stratum == "low" else float(row["score"]),
            str(row["dataset_family"]),
            str(row["sequence"]),
            float(row["window_start_s"]),
        )
    )
    return [
        quota.Candidate(
            window_id=str(row["window_id"]),
            dataset_family=str(row["dataset_family"]),
            data_domain=str(row["data_domain"]),
            sequence=str(row["sequence"]),
            window_index=int(row["window_index"]),
            window_start_s=float(row["window_start_s"]),
            score=float(row["score"]),
            stratum=stratum,
            global_rank=rank,
        )
        for rank, row in enumerate(selected, 1)
    ]


def build_selection() -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    _fields, source_rows, attempt01 = validate_inputs()
    rows = reclassify(source_rows)
    low_candidates = candidates(rows, "low")
    normal_candidates = candidates(rows, "normal")
    low_variants = quota.build_variants(low_candidates)
    normal_variants = quota.build_variants(normal_candidates)
    pair = quota.choose_joint_pair(low_variants, normal_variants)
    if pair is None or not quota.final_checks(pair[0], pair[1]):
        raise ValueError("frozen v3 quota repair is infeasible")
    low_ids = {candidate.window_id for candidate in pair[0].candidates}
    normal_ids = {candidate.window_id for candidate in pair[1].candidates}
    if low_ids & normal_ids:
        raise ValueError("low and normal selections overlap")
    selected_ids = low_ids | normal_ids
    for row in rows:
        row["selected_final"] = str(str(row["window_id"]) in selected_ids).lower()
    selected_rows = [row for row in rows if row["selected_final"] == "true"]
    tier_counts = Counter(str(row["selection_tier"]) for row in selected_rows)
    progress: dict[str, object] = {
        "schema_version": "isj-p06-screening-progress-v3",
        "status": "PASS",
        "protocol_version": PROTOCOL_VERSION,
        "quota_protocol": QUOTA_VERSION,
        "repair_trigger": "ATTEMPT01_STRICT_LOW_QUOTA_INFEASIBLE",
        "attempt01": {
            "window_selection_audit": file_record(INPUT_AUDIT),
            "dataset_manifest": file_record(INPUT_MANIFEST),
            "screening_progress": file_record(INPUT_PROGRESS),
            "status": attempt01["status"],
            "sequence_capped_low_count": attempt01["sequence_capped_low_count"],
            "sequence_capped_normal_count": attempt01[
                "sequence_capped_normal_count"
            ],
        },
        "protocol_addendum": file_record(PROTOCOL),
        "gross_window_count": len(rows),
        "sequence_capped_low_count": len(low_candidates),
        "sequence_capped_normal_count": len(normal_candidates),
        "selected_low_count": len(low_ids),
        "selected_normal_count": len(normal_ids),
        "selected_sequence_count": len(
            {str(row["sequence"]) for row in selected_rows}
        ),
        "selected_domain_count": len(
            {str(row["data_domain"]) for row in selected_rows}
        ),
        "selected_low_sequence_count": len(
            {str(row["sequence"]) for row in selected_rows if row["texture_stratum"] == "low"}
        ),
        "selected_normal_sequence_count": len(
            {str(row["sequence"]) for row in selected_rows if row["texture_stratum"] == "normal"}
        ),
        "selected_low_domain_count": len(
            {str(row["data_domain"]) for row in selected_rows if row["texture_stratum"] == "low"}
        ),
        "selected_normal_domain_count": len(
            {str(row["data_domain"]) for row in selected_rows if row["texture_stratum"] == "normal"}
        ),
        "selected_tier_counts": dict(sorted(tier_counts.items())),
        "selected_window_ids": sorted(selected_ids),
        "outcome_boundary": OUTCOME_BOUNDARY,
        "learned_outcome_read": False,
        "trajectory_outcome_read": False,
    }
    return rows, selected_rows, progress


def write_csv(path: Path, fields: Iterable[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def audit_fields(rows: list[dict[str, object]]) -> list[str]:
    return sorted({key for row in rows for key in row})


MANIFEST_FIELDS = [
    "protocol_version",
    "quota_protocol",
    "dataset_family",
    "data_domain",
    "sequence",
    "window_id",
    "window_index",
    "window_start_s",
    "window_end_s",
    "texture_stratum",
    "selection_tier",
    "score",
    "sequence_q20",
    "sequence_q80",
    "input_frame_count",
    "split_role",
    "outcome_boundary",
]


def manifest_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for row in sorted(
        rows,
        key=lambda item: (
            str(item["texture_stratum"]),
            str(item["dataset_family"]),
            str(item["sequence"]),
            float(item["window_start_s"]),
        ),
    ):
        output.append(
            {
                **{key: row.get(key, "") for key in MANIFEST_FIELDS},
                "split_role": "SEQUENCE_HELD_OUT_CONFIRMATORY_AFTER_KLT_ONLY_REPAIR",
                "outcome_boundary": "SELECTED_WITH_KLT_AND_IMAGE_QUALITY_ONLY",
            }
        )
    return output


def write_outputs(
    rows: list[dict[str, object]],
    selected: list[dict[str, object]],
    progress: dict[str, object],
) -> None:
    outputs = (OUTPUT_AUDIT, OUTPUT_MANIFEST, OUTPUT_PROGRESS)
    existing = [str(path) for path in outputs if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite v3 selection outputs: {existing}")
    temporary = {
        path: path.with_name(f"{path.name}.partial.{os.getpid()}") for path in outputs
    }
    for path in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
    write_csv(temporary[OUTPUT_AUDIT], audit_fields(rows), rows)
    write_csv(temporary[OUTPUT_MANIFEST], MANIFEST_FIELDS, manifest_rows(selected))
    progress = dict(progress)
    progress["window_selection_audit"] = file_record(temporary[OUTPUT_AUDIT])
    progress["window_selection_audit"]["path"] = relative(OUTPUT_AUDIT)
    progress["dataset_manifest"] = file_record(temporary[OUTPUT_MANIFEST])
    progress["dataset_manifest"]["path"] = relative(OUTPUT_MANIFEST)
    temporary[OUTPUT_PROGRESS].write_text(
        json.dumps(progress, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    for path in outputs:
        os.replace(temporary[path], path)


def main() -> int:
    rows, selected, progress = build_selection()
    write_outputs(rows, selected, progress)
    print(
        "P06_SCREENING_V3_PASS "
        f"low={progress['selected_low_count']} normal={progress['selected_normal_count']} "
        f"sequences={progress['selected_sequence_count']} "
        f"domains={progress['selected_domain_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
