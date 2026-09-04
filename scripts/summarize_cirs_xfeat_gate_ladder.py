#!/usr/bin/env python3
"""Summarize CIRS XFeat seed gate-ladder export-only runs."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


RUN_RE = re.compile(
    r"external_hybrid_xfeat_every1_jun24_ladder_"
    r"(?P<stage>.+)_s(?P<start>[0-9.]+)_d(?P<duration>[0-9.]+)$"
)


def _num(row: dict[str, str], key: str) -> float:
    try:
        return float(row.get(key) or 0.0)
    except ValueError:
        return 0.0


def _sum(rows: list[dict[str, str]], key: str) -> float:
    return sum(_num(r, key) for r in rows)


def _max(rows: list[dict[str, str]], key: str) -> float:
    return max((_num(r, key) for r in rows), default=0.0)


def _mean_positive(rows: list[dict[str, str]], key: str) -> float:
    vals = [_num(r, key) for r in rows if _num(r, key) > 0]
    return sum(vals) / len(vals) if vals else 0.0


def _dominant_reason(rows: list[dict[str, str]], key: str) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        value = (row.get(key) or "").strip()
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    if not counts:
        return ""
    return max(counts.items(), key=lambda item: (item[1], item[0]))[0]


def summarize_run(run_dir: Path) -> dict[str, str] | None:
    match = RUN_RE.match(run_dir.name)
    if not match:
        return None
    metrics_path = run_dir / "frontend_metrics.csv"
    if not metrics_path.exists():
        return None
    with metrics_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None

    learned_candidate = _sum(rows, "learned_candidate_count")
    learned_confirmed = _sum(rows, "learned_confirmed_count")
    pre_gate_non_loftr = _sum(rows, "pre_gate_non_loftr_total")
    pre_gate_non_loftr_basic = _sum(rows, "pre_gate_non_loftr_basic_ok")
    exported_xfeat = _sum(rows, "exported_xfeat_features")
    exported_learned = _sum(rows, "exported_learned_features")
    xfeat_frames = sum(1 for r in rows if _num(r, "exported_xfeat_features") > 0)
    confirmed_frames = sum(1 for r in rows if _num(r, "learned_confirmed_count") > 0)
    candidate_frames = sum(1 for r in rows if _num(r, "learned_candidate_count") > 0)

    confirm_rate = learned_confirmed / learned_candidate if learned_candidate > 0 else 0.0
    basic_rate = pre_gate_non_loftr_basic / pre_gate_non_loftr if pre_gate_non_loftr > 0 else 0.0
    export_rate = exported_xfeat / pre_gate_non_loftr_basic if pre_gate_non_loftr_basic > 0 else 0.0

    info = match.groupdict()
    return {
        "stage": info["stage"],
        "start": info["start"],
        "duration": info["duration"],
        "run_dir": str(run_dir),
        "frames": str(len(rows)),
        "candidate_frames": str(candidate_frames),
        "confirmed_frames": str(confirmed_frames),
        "xfeat_export_frames": str(xfeat_frames),
        "learned_candidate_sum": f"{learned_candidate:.0f}",
        "learned_confirmed_sum": f"{learned_confirmed:.0f}",
        "pre_gate_non_loftr_total": f"{pre_gate_non_loftr:.0f}",
        "pre_gate_non_loftr_basic_ok": f"{pre_gate_non_loftr_basic:.0f}",
        "exported_xfeat_sum": f"{exported_xfeat:.0f}",
        "exported_learned_sum": f"{exported_learned:.0f}",
        "confirm_per_candidate": f"{confirm_rate:.6f}",
        "basic_ok_per_pre_gate": f"{basic_rate:.6f}",
        "export_per_basic_ok": f"{export_rate:.6f}",
        "max_exported_xfeat_per_frame": f"{_max(rows, 'exported_xfeat_features'):.0f}",
        "mean_positive_exported_xfeat": f"{_mean_positive(rows, 'exported_xfeat_features'):.3f}",
        "dominant_gate_reason": _dominant_reason(rows, "learned_export_gate_reason"),
        "dominant_geometry_reason": _dominant_reason(rows, "learned_export_geometry_reason"),
        "dominant_benefit_reason": _dominant_reason(rows, "learned_export_benefit_reason"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--logs-root", type=Path, default=Path("logs/cirs_caves_vins"))
    parser.add_argument("--output-csv", type=Path, required=True)
    args = parser.parse_args()

    summaries = []
    for run_dir in sorted(args.logs_root.glob("external_hybrid_xfeat_every1_jun24_ladder_*")):
        if run_dir.is_dir():
            row = summarize_run(run_dir)
            if row is not None:
                summaries.append(row)

    fieldnames = [
        "start",
        "duration",
        "stage",
        "frames",
        "candidate_frames",
        "confirmed_frames",
        "xfeat_export_frames",
        "learned_candidate_sum",
        "learned_confirmed_sum",
        "pre_gate_non_loftr_total",
        "pre_gate_non_loftr_basic_ok",
        "exported_xfeat_sum",
        "exported_learned_sum",
        "confirm_per_candidate",
        "basic_ok_per_pre_gate",
        "export_per_basic_ok",
        "max_exported_xfeat_per_frame",
        "mean_positive_exported_xfeat",
        "dominant_gate_reason",
        "dominant_geometry_reason",
        "dominant_benefit_reason",
        "run_dir",
    ]
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summaries)
    print(f"wrote {len(summaries)} rows to {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
