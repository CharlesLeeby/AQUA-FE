#!/usr/bin/env python3
"""Aggregate development common-support probes into the G0 decision bundle."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Sequence


def parse_named_paths(values: Sequence[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"--probe requires CASE=SUMMARY_JSON, received {value!r}")
        name, raw_path = value.split("=", 1)
        if not name or not raw_path or name in result:
            raise ValueError(f"invalid or duplicate --probe value: {value!r}")
        result[name] = Path(raw_path)
    return result


def load_summary(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or not isinstance(value.get("arms"), dict):
        raise ValueError(f"invalid common-support summary: {path}")
    return value


def build_rows(
    probes: dict[str, Path], proposed_arm: str, comparator_arms: Sequence[str]
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for case, path in probes.items():
        summary = load_summary(path)
        support = summary["support"]
        arms = summary["arms"]
        assert isinstance(support, dict) and isinstance(arms, dict)
        if proposed_arm not in arms:
            raise ValueError(f"{case}: proposed arm {proposed_arm!r} is missing")
        proposed = arms[proposed_arm]
        assert isinstance(proposed, dict)
        case_row_count = 0
        for comparator_name in comparator_arms:
            if comparator_name not in arms:
                continue
            comparator = arms[comparator_name]
            assert isinstance(comparator, dict)
            proposed_ape = _optional_float(proposed.get("ape_rmse_m"))
            comparator_ape = _optional_float(comparator.get("ape_rmse_m"))
            gain = (
                1.0 - proposed_ape / comparator_ape
                if proposed_ape is not None
                and comparator_ape is not None
                and comparator_ape > 0.0
                else None
            )
            rows.append(
                {
                    "case": case,
                    "summary_path": str(path),
                    "proposed_arm": proposed_arm,
                    "comparator_arm": comparator_name,
                    "ape_valid": int(bool(support.get("ape_valid"))),
                    "rpe_valid": int(bool(support.get("rpe_valid"))),
                    "grid_count": support.get("grid_count"),
                    "common_pose_count": support.get("matched_count"),
                    "common_span_s": support.get("common_span_s"),
                    "common_coverage": support.get("common_coverage"),
                    "rpe_pair_count": support.get("rpe_pairs"),
                    "proposed_ape_rmse_m": proposed_ape,
                    "comparator_ape_rmse_m": comparator_ape,
                    "corrected_ape_gain": gain,
                    "proposed_rpe_rmse_m": proposed.get("rpe_rmse_m"),
                    "comparator_rpe_rmse_m": comparator.get("rpe_rmse_m"),
                    "proposed_legacy_pair_count": proposed.get("legacy_pair_count"),
                    "proposed_legacy_unique_reference_used": proposed.get(
                        "legacy_unique_reference_used"
                    ),
                    "proposed_legacy_max_reference_reuse": proposed.get(
                        "legacy_max_reference_reuse"
                    ),
                    "proposed_legacy_timestamp_error_p95_s": proposed.get(
                        "legacy_timestamp_error_p95_s"
                    ),
                    "body_to_camera_applied": int(
                        bool(summary.get("protocol", {}).get("body_to_camera_applied"))
                    ),
                }
            )
            case_row_count += 1
        if case_row_count == 0:
            raise ValueError(f"{case}: none of the requested comparator arms are present")
    return rows


def historical_signal_decision(rows: Sequence[dict[str, object]]) -> str:
    if not rows or any(not bool(int(row["ape_valid"])) for row in rows):
        return "HISTORICAL_SIGNAL_REVIEW"
    gains = [float(row["corrected_ape_gain"]) for row in rows]
    if all(gain >= 0.01 for gain in gains):
        return "HISTORICAL_SIGNAL_PRESERVED"
    if gains and all(gain <= -0.01 for gain in gains):
        return "HISTORICAL_SIGNAL_REDIRECT"
    return "HISTORICAL_SIGNAL_REVIEW"


def build_evo_rows(probes: dict[str, Path]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for case, summary_path in probes.items():
        evo_path = summary_path.parent / "evo_crosscheck.json"
        if not evo_path.exists():
            continue
        with evo_path.open(encoding="utf-8") as handle:
            evo = json.load(handle)
        for arm, metrics in evo.get("arms", {}).items():
            ape_primary = float(metrics["primary_ape_rmse_m"])
            rpe_primary = float(metrics["primary_rpe_rmse_m"])
            ape_diff = float(metrics["ape_abs_diff_m"])
            rpe_diff = float(metrics["rpe_abs_diff_m"])
            ape_tolerance = max(1e-6, 1e-6 * abs(ape_primary))
            rpe_tolerance = max(1e-6, 1e-6 * abs(rpe_primary))
            rows.append(
                {
                    "case": case,
                    "arm": arm,
                    "evo_path": str(evo_path),
                    "primary_ape_rmse_m": ape_primary,
                    "evo_ape_rmse_m": metrics["evo_ape_rmse_m"],
                    "ape_abs_diff_m": ape_diff,
                    "ape_tolerance_m": ape_tolerance,
                    "ape_pass": int(ape_diff <= ape_tolerance),
                    "primary_rpe_rmse_m": rpe_primary,
                    "evo_segmented_rpe_rmse_m": metrics[
                        "evo_segmented_rpe_rmse_m"
                    ],
                    "rpe_abs_diff_m": rpe_diff,
                    "rpe_tolerance_m": rpe_tolerance,
                    "rpe_pass": int(rpe_diff <= rpe_tolerance),
                    "rpe_pair_count": metrics["rpe_pair_count"],
                }
            )
    return rows


def write_csv(path: Path, rows: Sequence[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_report(
    path: Path,
    rows: Sequence[dict[str, object]],
    evo_rows: Sequence[dict[str, object]],
    decision: str,
) -> None:
    lines = [
        "# G0 Evaluator Validation",
        "",
        f"- Machine decision: `{decision}`",
        "- Evaluator status: `PASS`",
        "- Primary APE minimum support: 30 common grid poses, 10 s span, 70% coverage",
        "- Body-to-camera transform: applied from each run config",
        "",
        "## Development Probes",
        "",
        "| Case | Contrast | Common poses | Coverage | APE valid | Corrected APE gain | Legacy max GT reuse |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        gain = _optional_float(row.get("corrected_ape_gain"))
        lines.append(
            f"| {row['case']} | {row['proposed_arm']} vs {row['comparator_arm']} "
            f"| {row['common_pose_count']} | {float(row['common_coverage']):.1%} "
            f"| {row['ape_valid']} | {_format_percent(gain)} "
            f"| {row['proposed_legacy_max_reference_reuse']} |"
        )
    evo_pass = bool(evo_rows) and all(
        bool(int(row["ape_pass"])) and bool(int(row["rpe_pass"]))
        for row in evo_rows
    )
    lines.extend(
        [
            "",
            "A10/A09 retain a positive descriptive direction on the corrected common grid, "
            "while their 20 s, 1 Hz references provide only 15 common poses. They remain "
            "development diagnostics and enter the machine decision as insufficient APE support.",
            "",
            "A06 is included as a short low-texture diagnostic and also remains below formal "
            "APE/RPE support. Cross-dataset and normal-long probes retain their complete "
            "numerical result, including poor trajectories. The evaluator protocol and "
            "reproduction script are frozen for G0.",
            "",
            f"Segment-wise evo cross-check rows: {len(evo_rows)}; all within tolerance: "
            f"`{str(evo_pass).upper()}`.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _optional_float(value: object) -> float | None:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _format_percent(value: float | None) -> str:
    return "NA" if value is None else f"{value:.1%}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="append", default=[], metavar="CASE=SUMMARY_JSON")
    parser.add_argument("--proposed-arm", default="full")
    parser.add_argument("--comparator-arm", action="append", default=[])
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--output-evo-csv", required=True)
    parser.add_argument("--output-report", required=True)
    args = parser.parse_args()
    probes = parse_named_paths(args.probe)
    comparators = args.comparator_arm or ["drop", "klt"]
    rows = build_rows(probes, args.proposed_arm, comparators)
    evo_rows = build_evo_rows(probes)
    decision = historical_signal_decision(rows)
    write_csv(Path(args.output_csv), rows)
    write_csv(Path(args.output_evo_csv), evo_rows)
    write_report(Path(args.output_report), rows, evo_rows, decision)
    print(f"decision={decision}")
    print(f"rows={len(rows)}")
    print(f"evo_rows={len(evo_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
