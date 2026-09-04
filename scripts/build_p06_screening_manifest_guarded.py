#!/usr/bin/env python3
"""Run the frozen P06 quota builder only after a same-snapshot closeout PASS."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from scripts import build_p06_screening_manifest as builder
    from scripts import validate_p06_final_artifacts_v2 as final_validator
    from scripts import validate_p06_screening_closeout_v2 as closeout
except ModuleNotFoundError:
    import build_p06_screening_manifest as builder
    import validate_p06_final_artifacts_v2 as final_validator
    import validate_p06_screening_closeout_v2 as closeout


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
DATASET_MANIFEST = BUNDLE / "dataset_manifest.csv"
WINDOW_AUDIT = BUNDLE / "window_selection_audit.csv"
REFERENCE_SUPPORT = BUNDLE / "p06/reference_window_support_audit_v2.csv"
CORRECTED_CAPACITY = BUNDLE / "p06/candidate_capacity_reference_support_v2.csv"


def stable_relative_rows(
    rows: list[dict[str, str]], rate: float
) -> list[tuple[float, dict[str, str]]]:
    """Order duplicate timestamps by frame identity without reading scores."""

    if not rows:
        return []
    if "timestamp" in rows[0]:
        stamps = [float(row["timestamp"]) for row in rows]
        if any(not math.isfinite(value) for value in stamps):
            raise ValueError("non-finite screening timestamp")
        origin = min(stamps)
        ordered = sorted(
            enumerate(rows),
            key=lambda item: (
                float(item[1]["timestamp"]),
                int(float(item[1]["frame_index"])),
                item[0],
            ),
        )
        return [(float(row["timestamp"]) - origin, row) for _, row in ordered]
    indices = [int(float(row["frame_index"])) for row in rows]
    origin = min(indices)
    ordered = sorted(enumerate(rows), key=lambda item: (int(float(item[1]["frame_index"])), item[0]))
    return [((int(float(row["frame_index"])) - origin) / rate, row) for _, row in ordered]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reference_support_index() -> dict[tuple[str, str, int], dict[str, str]]:
    result: dict[tuple[str, str, int], dict[str, str]] = {}
    for row in builder.read_csv(REFERENCE_SUPPORT):
        key = (
            row["dataset_family"],
            row["sequence"],
            int(row["window_index"]),
        )
        if key in result:
            raise ValueError(f"duplicate reference-support identity: {key}")
        result[key] = row
    return result


def corrected_capacity_rows(
    original_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    correction = {
        (row["dataset_family"], row["sequence"]): row
        for row in builder.read_csv(CORRECTED_CAPACITY)
    }
    rows: list[dict[str, str]] = []
    for source in original_rows:
        row = dict(source)
        key = (row["dataset_family"], row["sequence"])
        fixed = correction.get(key)
        if fixed is None:
            rows.append(row)
            continue
        row["available_candidate_windows"] = fixed["corrected_available_windows"]
        row["max_per_sequence_cap"] = fixed["corrected_max_per_sequence_cap"]
        if fixed["capacity_decision"] == "EXCLUDE_SEQUENCE_REFERENCE_INELIGIBLE":
            row["low_normal_sequence_capacity_status"] = (
                "REFERENCE_INELIGIBLE_EXCLUDED_BEFORE_SCORE_SELECTION"
            )
        rows.append(row)
    return rows


def reference_aware_build_sequence_windows(
    spec: dict[str, str],
    rows: list[dict[str, str]],
    history_rows: list[dict[str, str]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    builder.core._assert_klt_only(rows)
    rate = builder.nominal_rate(spec["dataset_family"])
    timed = stable_relative_rows(rows, rate)
    if not timed:
        raise ValueError(f"empty metrics for {spec['sequence']}")
    full_window_count = int(
        math.floor(
            (timed[-1][0] + 1.0 / rate) / builder.core.WINDOW_DURATION_S
        )
    )
    groups: dict[int, list[dict[str, str]]] = defaultdict(list)
    for stamp, row in timed:
        window_index = int(math.floor(stamp / builder.core.WINDOW_DURATION_S))
        if 0 <= window_index < full_window_count:
            groups[window_index].append(row)
    excluded = builder.history_excluded_indices(
        spec["dataset_family"], spec["sequence"], full_window_count, history_rows
    )
    support = reference_support_index()
    windows: list[dict[str, object]] = []
    eligible: list[dict[str, object]] = []
    reference_failed = 0
    reference_history_overlap = 0
    for window_index in range(full_window_count):
        members = groups.get(window_index, [])
        start = window_index * builder.core.WINDOW_DURATION_S
        support_row = support.get(
            (spec["dataset_family"], spec["sequence"], window_index)
        )
        if support_row is None:
            raise ValueError(
                f"missing reference support: {spec['dataset_family']}/{spec['sequence']}/{window_index}"
            )
        support_pass = support_row["reference_support_pass"] == "true"
        if not support_pass:
            reference_failed += 1
            if window_index in excluded:
                reference_history_overlap += 1
        base_row: dict[str, object] = {
            "protocol_version": "isj-window-selection-v2",
            "quota_protocol": "isj-p06-global-quota-v1",
            "dataset_family": spec["dataset_family"],
            "data_domain": spec["data_domain"],
            "sequence": spec["sequence"],
            "window_index": window_index,
            "window_id": (
                f"{spec['dataset_family']}:{spec['sequence']}:{window_index:04d}"
            ),
            "window_start_s": start,
            "window_end_s": start + builder.core.WINDOW_DURATION_S,
            "input_frame_count": len(members),
            "history_excluded": str(window_index in excluded).lower(),
            "history_exclusion_reason": (
                "exact_prior_window_overlap" if window_index in excluded else ""
            ),
            "reference_support_pass": str(support_pass).lower(),
            "reference_support_reason": support_row["reference_support_reason"],
            "reference_supported_grid_count": support_row["supported_grid_count"],
            "reference_coverage": support_row["coverage"],
            "texture_stratum": (
                "history_excluded"
                if window_index in excluded
                else (
                    "reference_support_failed"
                    if not support_pass
                    else "insufficient_frames"
                )
            ),
            "selected_by_sequence_rule": "false",
            "selected_final": "false",
        }
        if len(members) >= builder.core.MIN_INPUT_FRAMES and support_pass:
            components = builder.core.score_metric_rows(members)
            base_row.update(components.__dict__)
            if window_index not in excluded:
                eligible.append(base_row)
        windows.append(base_row)
    if eligible:
        scores = [float(row["score"]) for row in eligible]
        q20 = builder.core.linear_quantile(scores, builder.core.NORMAL_PERCENTILE)
        q80 = builder.core.linear_quantile(scores, builder.core.LOW_PERCENTILE)
        labels = builder.core.classify_scores(scores)
        for row, label in zip(eligible, labels):
            row["texture_stratum"] = label
            row["sequence_q20"] = q20
            row["sequence_q80"] = q80
        selected = builder.core.select_within_sequence(eligible)
        selected_map = {int(row["window_index"]): row for row in selected}
        for row in windows:
            selected_row = selected_map.get(int(row["window_index"]))
            if selected_row is not None:
                row.update(selected_row)
                row["selected_by_sequence_rule"] = str(
                    bool(selected_row["selected_by_sequence_rule"])
                ).lower()
    available = sum(
        row["history_excluded"] == "false"
        and row["reference_support_pass"] == "true"
        and int(row["input_frame_count"]) >= builder.core.MIN_INPUT_FRAMES
        for row in windows
    )
    return windows, {
        "dataset_family": spec["dataset_family"],
        "data_domain": spec["data_domain"],
        "sequence": spec["sequence"],
        "metrics_rows": len(rows),
        "gross_windows_actual": full_window_count,
        "gross_windows_registered": int(spec["gross_nonoverlap_windows"]),
        "history_excluded_actual": len(excluded),
        "history_excluded_registered": int(spec["history_overlap_windows"]),
        "reference_failed_actual": reference_failed,
        "reference_history_overlap_actual": reference_history_overlap,
        "available_windows_actual": available,
        "available_windows_registered_corrected": int(
            spec["available_candidate_windows"]
        ),
    }


def input_snapshot(report: dict[str, Any]) -> dict[str, str]:
    paths: set[Path] = {
        closeout.base.CAPACITY,
        closeout.base.ELIGIBILITY,
        closeout.base.CHECKSUMS,
        closeout.base.CODE_HASHES,
        closeout.base.RUNNER_HASHES,
        builder.HISTORY,
        REFERENCE_SUPPORT,
        CORRECTED_CAPACITY,
        BUNDLE / "p06/reference_support_gate_v1.sha256",
        BUNDLE / "p06/reference_support_gate_v1_addendum.sha256",
        closeout.CALIBRATION_CORRECTION,
        *closeout.CURRENT_MANIFESTS,
        *closeout.ATTESTATION_FILES,
    }
    if closeout.ATTESTATION_ADDENDUM_HASHES.is_file():
        paths.add(closeout.ATTESTATION_ADDENDUM_HASHES)
    reference_excluded = set(report.get("reference_excluded_sequences", []))
    for spec in closeout.base.expected_sequences():
        if spec["sequence"] in reference_excluded:
            canonical = (
                closeout.base.SCREENING
                / spec["dataset_family"]
                / spec["sequence"]
            )
            paths.add(canonical / "reference_exclusion.json")
            continue
        run_dir, pointer_issues = closeout.base.resolve_screening_dir(
            spec["dataset_family"], spec["sequence"]
        )
        if pointer_issues:
            raise ValueError(f"invalid screening pointer: {spec['sequence']}:{pointer_issues}")
        paths.add(run_dir / "metrics.csv")
        paths.add(run_dir / "screening_run.json")
        pointer = closeout.base.SCREENING / spec["dataset_family"] / spec["sequence"] / "current_attempt.json"
        if pointer.is_file():
            paths.add(pointer)
    if report.get("status") != "PASS":
        raise ValueError("screening closeout is not PASS")
    return {
        path.resolve().relative_to(ROOT).as_posix(): sha256(path)
        for path in sorted(paths)
        if path.is_file()
    }


def main() -> int:
    if DATASET_MANIFEST.exists() or WINDOW_AUDIT.exists():
        print("P06_GUARDED_BUILD_REFUSED existing final selection artifacts")
        return 1
    preflight = closeout.build_report(require_final=False)
    if preflight["status"] != "PASS":
        print(
            "P06_GUARDED_BUILD_IN_PROGRESS "
            f"completed={preflight['completed_sequence_count']} "
            f"required={preflight['required_sequence_count']}"
        )
        return 2
    before = input_snapshot(preflight)
    builder.relative_rows = stable_relative_rows
    builder.build_sequence_windows = reference_aware_build_sequence_windows
    original_read_csv = builder.read_csv

    def read_csv_with_corrected_capacity(path: Path) -> list[dict[str, str]]:
        rows = original_read_csv(path)
        if path.resolve() == builder.CAPACITY.resolve():
            return corrected_capacity_rows(rows)
        return rows

    builder.read_csv = read_csv_with_corrected_capacity
    result = builder.main()
    if builder.PROGRESS.is_file():
        progress = json.loads(builder.PROGRESS.read_text(encoding="utf-8"))
        progress.update(
            {
                "registered_sequence_count": preflight["required_sequence_count"],
                "reference_eligible_sequence_count": (
                    preflight["required_sequence_count"]
                    - preflight.get("reference_excluded_sequence_count", 0)
                ),
                "reference_excluded_sequences": preflight.get(
                    "reference_excluded_sequences", []
                ),
                "reference_support_audit": {
                    "path": REFERENCE_SUPPORT.relative_to(ROOT).as_posix(),
                    "sha256": sha256(REFERENCE_SUPPORT),
                },
                "corrected_capacity": {
                    "path": CORRECTED_CAPACITY.relative_to(ROOT).as_posix(),
                    "sha256": sha256(CORRECTED_CAPACITY),
                },
                "input_snapshot": before,
            }
        )
        builder.PROGRESS.write_text(
            json.dumps(progress, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    after = input_snapshot(closeout.build_report(require_final=False))
    if before != after:
        print("P06_GUARDED_BUILD_REVISE input snapshot changed during selection")
        return 1
    if result != 0:
        return result
    final = final_validator.build_report()
    print(
        f"P06_GUARDED_BUILD_{final['status']} "
        f"selected={final.get('selected_window_count', 0)} "
        f"issues={len(final.get('issues', []))}"
    )
    return 0 if final["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
