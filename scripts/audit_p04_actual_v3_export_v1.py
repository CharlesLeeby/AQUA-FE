#!/usr/bin/env python3
"""Audit an actual-v3 export-only arbitration attempt without VINS outcomes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from collections import Counter
from pathlib import Path

import rosbag


SCHEMA_VERSION = "aqua-fe-p04-actual-v3-export-audit-v1"
FEATURE_TOPIC = "/feature_tracker/feature"
OUTCOME_BOUNDARY = "FRONTEND_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY"
LEARNED_SOURCE_CODES = frozenset({10, 20, 30})


class AuditViolation(ValueError):
    """Raised when the attempt violates the frozen export-only contract."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_key_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw or "=" not in raw:
            raise AuditViolation(f"invalid arbitration summary line {line_number}")
        key, value = raw.split("=", 1)
        if not key or key in values:
            raise AuditViolation(f"duplicate/empty arbitration key on line {line_number}")
        values[key] = value
    return values


def read_metrics(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise AuditViolation(f"invalid metrics header: {path}")
        rows = list(reader)
    if not rows or any(None in row for row in rows):
        raise AuditViolation(f"empty or ragged metrics: {path}")
    return rows


def metric_sum(rows: list[dict[str, str]], key: str) -> int:
    total = 0
    for row_number, row in enumerate(rows, 2):
        try:
            value = float(row.get(key, ""))
        except ValueError as exc:
            raise AuditViolation(f"invalid {key} on metrics row {row_number}") from exc
        if not math.isfinite(value) or not value.is_integer() or value < 0:
            raise AuditViolation(f"non-count {key} on metrics row {row_number}")
        total += int(value)
    return total


def audit_bag(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise AuditViolation(f"missing feature bag: {path}")
    feature_frames = 0
    observations = 0
    source_codes: Counter[int] = Counter()
    learned_flags: Counter[int] = Counter()
    feature_stamps: list[float] = []
    topic_counts: Counter[str] = Counter()
    with rosbag.Bag(str(path), "r") as bag:
        for topic, message, _record_stamp in bag.read_messages():
            topic_counts[topic] += 1
            if topic != FEATURE_TOPIC:
                continue
            feature_frames += 1
            count = len(message.points)
            observations += count
            feature_stamps.append(float(message.header.stamp.to_sec()))
            channels = {channel.name: list(channel.values) for channel in message.channels}
            if len(channels) != len(message.channels):
                raise AuditViolation("duplicate feature channel")
            for name in ("id", "source_code", "is_learned", "quality", "sigma"):
                if name not in channels or len(channels[name]) != count:
                    raise AuditViolation(f"missing or mis-sized feature channel: {name}")
            ids = [int(round(value)) for value in channels["id"]]
            if len(ids) != len(set(ids)):
                raise AuditViolation("duplicate feature ID within a frame")
            source_codes.update(int(round(value)) for value in channels["source_code"])
            learned_flags.update(int(round(value)) for value in channels["is_learned"])
            if any(
                not math.isfinite(float(value))
                for name in ("quality", "sigma")
                for value in channels[name]
            ):
                raise AuditViolation("non-finite quality/sigma")
    if feature_frames == 0 or observations == 0:
        raise AuditViolation("feature bag is empty")
    if any(right <= left for left, right in zip(feature_stamps, feature_stamps[1:])):
        raise AuditViolation("feature timestamps are not strictly increasing")
    return {
        "path": str(path),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
        "feature_frames": feature_frames,
        "feature_observations": observations,
        "feature_span_s": feature_stamps[-1] - feature_stamps[0],
        "source_code_histogram": {
            str(key): source_codes[key] for key in sorted(source_codes)
        },
        "is_learned_histogram": {
            str(key): learned_flags[key] for key in sorted(learned_flags)
        },
        "topic_counts": {key: topic_counts[key] for key in sorted(topic_counts)},
    }


def forbidden_outcome_files(run_dirs: tuple[Path, ...]) -> list[str]:
    exact_names = {
        "vio.csv",
        "ape.csv",
        "rpe.csv",
        "trajectory.csv",
        "vins.log",
        "vins_output.log",
    }
    forbidden: list[str] = []
    for run_dir in run_dirs:
        for path in run_dir.rglob("*"):
            if path.is_file() and path.name.lower() in exact_names:
                forbidden.append(str(path))
    return sorted(forbidden)


def audit_attempt(
    *, probe_run: Path, final_run: Path, guard_decision: Path
) -> dict[str, object]:
    summary_path = final_run / "arbitration_summary.txt"
    probe_metrics_path = probe_run / "frontend_metrics.csv"
    final_metrics_path = final_run / "frontend_metrics.csv"
    for path in (guard_decision, summary_path, probe_metrics_path, final_metrics_path):
        if not path.is_file():
            raise AuditViolation(f"missing attempt artifact: {path}")

    guard = json.loads(guard_decision.read_text(encoding="utf-8"))
    if (
        guard.get("schema_version") != "aqua-fe-nativeq-backend-guard-decision-v1"
        or guard.get("contract_pass") is not True
        or guard.get("action") != "ALLOW_LEARNED"
        or guard.get("reasons") != []
    ):
        raise AuditViolation("native-q backend guard did not pass exactly")

    summary = parse_key_values(summary_path)
    required_summary = {
        "dataset_family": "aqualoc_archaeo",
        "profile": "klt_safe_fallback",
        "seedchain_profile": "lineage_early_seed_scan",
        "final_effective_seedchain_profile": "klt",
        "probe_xfeat_total": "0",
        "probe_xfeat_frames": "0",
        "oldcontract_signature": "0",
    }
    for key, expected in required_summary.items():
        if summary.get(key) != expected:
            raise AuditViolation(f"arbitration summary {key} != {expected}")
    if Path(summary.get("probe_run", "")).resolve() != probe_run.resolve():
        raise AuditViolation("arbitration summary probe path mismatch")
    if Path(summary.get("final_run", "")).resolve() != final_run.resolve():
        raise AuditViolation("arbitration summary final path mismatch")

    probe_rows = read_metrics(probe_metrics_path)
    final_rows = read_metrics(final_metrics_path)
    probe_bag = audit_bag(probe_run / "features.bag")
    final_bag = audit_bag(final_run / "features.bag")
    if len(probe_rows) != probe_bag["feature_frames"]:
        raise AuditViolation("probe metrics/bag frame count mismatch")
    if len(final_rows) != final_bag["feature_frames"]:
        raise AuditViolation("final metrics/bag frame count mismatch")
    if probe_bag["feature_frames"] != 450 or final_bag["feature_frames"] != 450:
        raise AuditViolation("A03 attempt does not contain the expected 450 feature frames")

    probe_exported_xfeat = metric_sum(probe_rows, "exported_xfeat_features")
    final_exported_xfeat = metric_sum(final_rows, "exported_xfeat_features")
    if probe_exported_xfeat != 0 or final_exported_xfeat != 0:
        raise AuditViolation("zero-action fallback contains published XFeat observations")
    if int(summary["probe_xfeat_total"]) != probe_exported_xfeat:
        raise AuditViolation("summary/metrics XFeat total mismatch")
    if probe_bag["sha256"] != final_bag["sha256"]:
        raise AuditViolation("zero-action probe and KLT fallback bags are not byte-identical")
    if any(int(code) in LEARNED_SOURCE_CODES for code in probe_bag["source_code_histogram"]):
        raise AuditViolation("zero-action bag contains a learned source code")
    if probe_bag["is_learned_histogram"] != {"0": probe_bag["feature_observations"]}:
        raise AuditViolation("zero-action bag contains learned-marked observations")

    forbidden = forbidden_outcome_files((probe_run, final_run))
    if forbidden:
        raise AuditViolation(f"trajectory outcome artifact found: {forbidden}")

    return {
        "schema_version": SCHEMA_VERSION,
        "contract_pass": True,
        "decision": "PASS_ACTUAL_V3_ZERO_ACTION_KLT_FALLBACK",
        "outcome_boundary": OUTCOME_BOUNDARY,
        "forbidden_outcomes_accessed": [],
        "checks": {
            "nativeq_backend_guard_exact_pass": True,
            "actual_v3_early_seed_arbitration_identity": True,
            "probe_and_final_feature_bags_byte_identical": True,
            "zero_published_learned_observations": True,
            "no_trajectory_outcome_artifacts": True,
        },
        "guard": {
            "path": str(guard_decision),
            "sha256": sha256(guard_decision),
            "backend_contract_hash": guard.get("contract_hash"),
        },
        "arbitration_summary": {
            "path": str(summary_path),
            "sha256": sha256(summary_path),
            "profile": summary["profile"],
            "oldcontract_fail_reasons": summary.get("oldcontract_fail_reasons"),
        },
        "probe": {
            **probe_bag,
            "metrics_path": str(probe_metrics_path),
            "metrics_sha256": sha256(probe_metrics_path),
            "learned_candidate_count_sum": metric_sum(
                probe_rows, "learned_candidate_count"
            ),
            "learned_confirmed_count_sum": metric_sum(
                probe_rows, "learned_confirmed_count"
            ),
            "exported_xfeat_observations": probe_exported_xfeat,
        },
        "final": {
            **final_bag,
            "metrics_path": str(final_metrics_path),
            "metrics_sha256": sha256(final_metrics_path),
            "exported_xfeat_observations": final_exported_xfeat,
        },
        "interpretation_boundary": (
            "Development zero-action parity diagnostic only; not a learned-positive, "
            "classical-control, trajectory, or confirmatory result."
        ),
    }


def write_json_no_clobber(path: Path, payload: dict[str, object]) -> None:
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
    parser.add_argument("--probe-run", type=Path, required=True)
    parser.add_argument("--final-run", type=Path, required=True)
    parser.add_argument("--guard-decision", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = audit_attempt(
        probe_run=args.probe_run,
        final_run=args.final_run,
        guard_decision=args.guard_decision,
    )
    write_json_no_clobber(args.output, payload)
    print(
        "P04_ACTUAL_V3_EXPORT_AUDIT PASS "
        f"decision={payload['decision']} output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
