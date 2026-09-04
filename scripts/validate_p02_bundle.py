#!/usr/bin/env python3
"""Validate and optionally freeze the P02 governance bundle."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
P02 = BUNDLE / "p02"
HEX64 = re.compile(r"[0-9a-f]{64}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-freeze-hashes", action="store_true")
    args = parser.parse_args()

    history = _read_csv(BUNDLE / "history_exclusion_manifest.csv")
    eligibility = _read_csv(BUNDLE / "data_eligibility_manifest.csv")
    references = _read_csv(BUNDLE / "reference_audit.csv")
    checksums = _read_csv(P02 / "input_reference_checksums.csv")
    capacity = _read_csv(P02 / "candidate_capacity_audit.csv")
    scores = _read_csv(P02 / "development_score_audit.csv")

    _validate_history(history)
    primary = _validate_eligibility(eligibility)
    _validate_references(references, primary)
    _validate_checksums(checksums, references, primary)
    capacity_summary = _validate_capacity(capacity)
    score_summary = _validate_development_scores(scores)
    _validate_code_hashes()
    ledger_events = _validate_ledger()
    _validate_documents()
    _validate_stage_boundary()

    summary = (
        "P02_BUNDLE_OK "
        f"history_rows={len(history)} eligibility_rows={len(eligibility)} "
        f"primary_sequences={len(primary)} reference_rows={len(references)} "
        f"checksum_rows={len(checksums)} checksum_pass={sum(r['status'] == 'PASS' for r in checksums)} "
        f"capacity_slots={capacity_summary['slots']} capacity_sequences={capacity_summary['sequences']} "
        f"capacity_domains={capacity_summary['domains']} primary_low={score_summary['primary_low']} "
        f"primary_normal={score_summary['primary_normal']} ledger_events={ledger_events}"
    )
    print(summary)

    if args.write_freeze_hashes:
        _write_freeze_hashes()
        (P02 / "p02_validation_report.txt").write_text(summary + "\n", encoding="utf-8")
        print(f"wrote {P02 / 'p02_freeze_hashes.sha256'}")
        print(f"wrote {P02 / 'p02_validation_report.txt'}")
    return 0


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        _require(reader.fieldnames is not None and len(reader.fieldnames) == len(set(reader.fieldnames)), f"bad CSV header: {path}")
        rows = list(reader)
    _require(all(None not in row for row in rows), f"ragged CSV row: {path}")
    return rows


def _validate_history(rows: list[dict[str, str]]) -> None:
    required = {
        "dataset_family", "sequence", "start", "end", "prior_artifact_count",
        "prior_learned_seen", "prior_vins_seen", "prior_parameter_use", "allowed_role",
        "evidence_paths", "decision_reason",
    }
    _require(rows and required <= set(rows[0]), "history schema is incomplete")
    identities: set[tuple[str, ...]] = set()
    for row in rows:
        key = (row["dataset_family"], row["sequence"], row["start"], row["end"], row.get("window_unit", ""))
        _require(key not in identities, f"duplicate history identity: {key}")
        identities.add(key)
        _require(int(row["prior_artifact_count"]) >= 1, f"empty history evidence count: {key}")
        _require(row["allowed_role"] == "DEVELOPMENT_ONLY", f"non-development history row: {key}")
        _require(bool(row["evidence_paths"]), f"missing history evidence path: {key}")
        _require("/home/ma/AQUA-FE_WS/" not in row["evidence_paths"], f"absolute history evidence path: {key}")
        for field in ("prior_learned_seen", "prior_vins_seen", "prior_parameter_use"):
            _require(row[field] in {"true", "false"}, f"bad boolean {field}: {key}")


def _validate_eligibility(rows: list[dict[str, str]]) -> set[tuple[str, str]]:
    _require(rows and all(row["manifest_schema"] == "isj-data-eligibility-v1" for row in rows), "eligibility schema mismatch")
    keys = [(row["dataset_family"], row["sequence"]) for row in rows]
    _require(len(keys) == len(set(keys)), "duplicate eligibility identity")
    primary: set[tuple[str, str]] = set()
    for row in rows:
        _require("/home/ma/AQUA-FE_WS/" not in row["evidence_paths"], f"absolute eligibility evidence: {keys}")
        if row["eligibility"] != "ELIGIBLE_WITH_REFERENCE_CAVEAT":
            continue
        key = (row["dataset_family"], row["sequence"])
        primary.add(key)
        _require(row["raw_exists"] == "true", f"missing primary raw input: {key}")
        _require(row["raw_integrity"] == "SIZE_MATCH", f"primary raw size not verified: {key}")
        _require(bool(row["reference_path"]), f"missing primary reference: {key}")
        _require(float(row["nominal_reference_rate_hz"]) >= 1.0, f"reference below primary rate: {key}")
        _require(all(row[field] for field in ("calibration_paths", "license_status", "decision_reason")), f"incomplete primary metadata: {key}")
    _require(len(primary) >= 6, "fewer than six primary candidate sequences")
    return primary


def _validate_references(rows: list[dict[str, str]], primary: set[tuple[str, str]]) -> None:
    _require(rows and all(row["audit_schema"] == "isj-reference-audit-v1" for row in rows), "reference schema mismatch")
    keys = {(row["dataset_family"], row["sequence"]) for row in rows}
    _require(primary <= keys, "primary eligibility/reference mismatch")
    for row in rows:
        key = (row["dataset_family"], row["sequence"])
        _require("/home/ma/AQUA-FE_WS/" not in row["evidence_paths"], f"absolute reference evidence: {key}")
        if key not in primary:
            continue
        _require(row["reference_exists"] == "true", f"missing primary reference: {key}")
        _require(_is_hex(row["reference_sha256"]), f"bad reference digest: {key}")
        _require(int(row["reference_unique_count"]) >= 30, f"insufficient reference rows: {key}")
        _require(int(row["reference_raw_count"]) >= int(row["reference_unique_count"]), f"bad reference counts: {key}")
        nominal = float(row["nominal_reference_rate_hz"])
        evaluation = float(row["evaluation_rate_hz"])
        _require(evaluation in {1.0, 2.0, 5.0, 10.0} and evaluation <= nominal, f"bad evaluation rate: {key}")
        _require(math.isclose(float(row["max_reference_gap_s"]), 2.5 / nominal, rel_tol=0.0, abs_tol=1e-8), f"bad reference gap: {key}")
        estimate = float(row["nominal_estimate_rate_hz"])
        _require(math.isclose(float(row["max_estimate_interp_gap_s"]), 2.5 / estimate, rel_tol=0.0, abs_tol=1e-8), f"bad estimate gap: {key}")
        _require(row["calibration_status"] == "PASS_ALL_PRESENT", f"calibration failure: {key}")


def _validate_checksums(
    rows: list[dict[str, str]],
    references: list[dict[str, str]],
    primary: set[tuple[str, str]],
) -> None:
    identities: set[tuple[str, str]] = set()
    by_path: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        _require(row["checksum_schema"] == "isj-input-reference-checksum-v1", "checksum schema mismatch")
        identity = (row["artifact_role"], row["path"])
        _require(identity not in identities, f"duplicate checksum identity: {identity}")
        identities.add(identity)
        by_path[identity] = row
        _require(row["algorithm"] == "SHA-256" and _is_hex(row["digest"]), f"bad checksum: {identity}")
        _require(row["status"] == "PASS", f"non-PASS checksum: {identity}")
        _require(int(row["size_bytes"]) >= 0, f"bad checksum size: {identity}")
        path = ROOT / row["path"]
        _require(path.exists(), f"checksum path missing: {identity}")
        if row["artifact_role"] != "raw_input":
            _require(_sha256_file(path) == row["digest"], f"content checksum mismatch: {identity}")
    for row in references:
        key = (row["dataset_family"], row["sequence"])
        if key not in primary:
            continue
        reference = by_path.get(("reference", row["reference_path"]))
        raw = by_path.get(("raw_input", row["raw_input_path"]))
        _require(reference is not None and reference["digest"] == row["reference_sha256"], f"reference checksum crosslink failure: {key}")
        _require(raw is not None and raw["local_size_verified"] == "true", f"raw checksum crosslink failure: {key}")


def _validate_capacity(rows: list[dict[str, str]]) -> dict[str, int]:
    eligible = [row for row in rows if row["eligibility"] == "ELIGIBLE_WITH_REFERENCE_CAVEAT"]
    for row in eligible:
        gross = int(row["gross_nonoverlap_windows"])
        excluded = int(row["history_overlap_windows"])
        available = int(row["available_candidate_windows"])
        cap = int(row["max_per_sequence_cap"])
        _require(0 <= excluded <= gross, f"history exclusion exceeds capacity: {row['sequence']}")
        _require(available == gross - excluded, f"bad available capacity: {row['sequence']}")
        _require(cap == min(4, available), f"bad sequence cap: {row['sequence']}")
    live = [row for row in eligible if int(row["available_candidate_windows"]) > 0]
    summary = {
        "slots": sum(int(row["max_per_sequence_cap"]) for row in eligible),
        "sequences": len(live),
        "domains": len({row["data_domain"] for row in live}),
    }
    _require(summary["slots"] >= 20, "fewer than 20 capped candidate slots")
    _require(summary["sequences"] >= 6, "fewer than six capacity sequences")
    _require(summary["domains"] >= 3, "fewer than three capacity domains")
    return summary


def _validate_development_scores(rows: list[dict[str, str]]) -> dict[str, int]:
    registered = {row["fixture_id"]: row for row in rows}
    _require(registered["afrl_cemetery_fr_005_410"]["metrics_path"].endswith("metrics_r2.csv"), "AFRL partial was not excluded")
    _require(registered["uvvid_cannon_000_179"]["metrics_path"].endswith("metrics_r2.csv"), "UVVID partial was not excluded")
    partials = {
        P02 / "development_screening/afrl_cemetery_fr_005_410/metrics.csv": 189,
        P02 / "development_screening/uvvid_cannon_000_179/metrics.csv": 42,
    }
    for path, expected in partials.items():
        _require(len(_read_csv(path)) == expected, f"unexpected partial row count: {path}")
        _require(all(row["metrics_path"] != path.relative_to(ROOT).as_posix() for row in rows), f"partial registered: {path}")
    primary = [row for row in rows if row["fixture_role"] == "primary"]
    for row in rows:
        metrics = _read_csv(ROOT / row["metrics_path"])
        _require(len(metrics) == int(row["row_count"]), f"fixture row-count mismatch: {row['fixture_id']}")
        required = {"grid_coverage", "dropout_ratio", "flat_region_ratio", "degradation_score"}
        _require(metrics and required <= set(metrics[0]), f"fixture metric schema mismatch: {row['fixture_id']}")
        for metric in metrics:
            _require(str(metric.get("tracker_mode", "klt")).lower() in {"", "klt", "n/a"}, f"non-KLT fixture: {row['fixture_id']}")
            for field in ("xfeat_tracks", "superpoint_lightglue_tracks", "loftr_tracks"):
                _require(float(metric.get(field) or 0) == 0.0, f"learned fixture metric: {row['fixture_id']}:{field}")
    counts = Counter(row["absolute_stratum"] for row in primary)
    _require(counts["low"] >= 1 and counts["normal"] >= 1, "development thresholds do not separate primary fixtures")
    return {"primary_low": counts["low"], "primary_normal": counts["normal"]}


def _validate_code_hashes() -> None:
    path = P02 / "b1_screening_code_hashes.sha256"
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    _require(lines, "empty B1 hash manifest")
    for line in lines:
        digest, relative = line.split("  ", 1)
        _require(_is_hex(digest), f"bad B1 digest: {relative}")
        _require(_sha256_file(ROOT / relative) == digest, f"B1 hash mismatch: {relative}")


def _validate_ledger() -> int:
    events = []
    with (BUNDLE / "execution_ledger.jsonl").open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise AssertionError(f"bad ledger JSON line {line_number}") from exc
    ids = [event["event_id"] for event in events]
    _require(len(ids) == len(set(ids)), "duplicate ledger event ID")
    return len(events)


def _validate_documents() -> None:
    protocol = (BUNDLE / "window_selection_protocol.md").read_text(encoding="utf-8")
    for token in (
        "isj-window-selection-v1", "MULTI_SEQUENCE_CANDIDATE", "tau_low = 0.17",
        "tau_normal = 0.10", "sequence_Q80", "sequence_Q20", "Hyndman-Fan type-7",
        "P06 passes", "learned/P/VINS output",
    ):
        _require(token in protocol, f"window protocol token missing: {token}")
    selector_digest = _sha256_file(ROOT / "scripts/p02_window_selection.py")
    _require(selector_digest in protocol, "selector digest missing from window protocol")

    evaluator = (BUNDLE / "evaluator_protocol_v1.md").read_text(encoding="utf-8")
    for token in ("AQUALOC archaeology", "AQUALOC harbor", "fjord_1-fjord_6", "AFRL stereo VI", "ReAqROVIO", "0.333333333 s"):
        _require(token in evaluator, f"evaluator candidate token missing: {token}")


def _validate_stage_boundary() -> None:
    forbidden = (
        BUNDLE / "dataset_manifest.csv",
        BUNDLE / "window_selection_audit.csv",
        BUNDLE / "dataset_checksum_manifest.txt",
        BUNDLE / "arm_order.csv",
    )
    _require(not any(path.exists() for path in forbidden), "P06-owned artifact exists during P02")


def _write_freeze_hashes() -> None:
    paths = (
        BUNDLE / "history_exclusion_manifest.csv",
        BUNDLE / "data_eligibility_manifest.csv",
        BUNDLE / "reference_audit.csv",
        BUNDLE / "window_selection_protocol.md",
        BUNDLE / "evaluator_protocol_v1.md",
        BUNDLE / "README.md",
        P02 / "input_reference_checksums.csv",
        P02 / "candidate_capacity_audit.csv",
        P02 / "candidate_capacity_decision.md",
        P02 / "development_score_audit.csv",
        P02 / "b1_screening_code_hashes.sha256",
        ROOT / "scripts/build_p02_audit.py",
        ROOT / "scripts/p02_window_selection.py",
        ROOT / "scripts/validate_p02_bundle.py",
        ROOT / "scripts/tests/test_p02_window_selection.py",
    )
    lines = [f"{_sha256_file(path)}  {path.relative_to(ROOT).as_posix()}" for path in paths]
    (P02 / "p02_freeze_hashes.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_hex(value: str) -> bool:
    return bool(HEX64.fullmatch(value))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
